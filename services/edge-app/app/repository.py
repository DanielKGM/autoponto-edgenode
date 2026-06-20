from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo
import uuid

import msgpack
from sqlalchemy import or_, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.config import ZONE_INFO
from app.db import SessionLocal, escopo_sessao
from app.db_models import Aluno, Aula, Dispositivo, EmbeddingFacial
from app.db_models import EventoPresenca, MatriculaTurma
from app.models import ContextoDispositivo
from app.redis_store import obter_aulas_por_sala, obter_dispositivo_por_codigo
from app.redis_store import substituir_cache_redis

FUSO_HORARIO = ZoneInfo(ZONE_INFO)
STATUS_AULA_INATIVA = ("FECHADA", "CANCELADA")


@dataclass(frozen=True)
class AulaAtual:
    id: str
    nome: str
    turma_id: str
    sala_id: str
    inicio: datetime
    fim: datetime
    status: str | None = None


def converter_data_hora(valor: str) -> datetime:
    data_hora = datetime.fromisoformat(valor.replace("Z", "+00:00"))
    if data_hora.tzinfo is None:
        return data_hora.replace(tzinfo=FUSO_HORARIO)
    return data_hora.astimezone(FUSO_HORARIO)


def buscar_dispositivo_ativo_por_codigo(dispositivo_codigo: str) -> dict | None:
    return obter_dispositivo_por_codigo(dispositivo_codigo)


def buscar_sala_id_por_dispositivo(dispositivo_codigo: str) -> str | None:
    dispositivo = buscar_dispositivo_ativo_por_codigo(dispositivo_codigo)
    return dispositivo["sala_id"] if dispositivo else None


def buscar_uuid_dispositivo_por_codigo(dispositivo_codigo: str) -> str | None:
    dispositivo = buscar_dispositivo_ativo_por_codigo(dispositivo_codigo)
    return dispositivo["dispositivo_id"] if dispositivo else None


def _aula_do_cache(dados: dict) -> AulaAtual:
    return AulaAtual(
        id=dados["id"],
        nome=dados["nome"],
        turma_id=dados["turma_id"],
        sala_id=dados["sala_id"],
        inicio=converter_data_hora(dados["inicio"]),
        fim=converter_data_hora(dados["fim"]),
        status=dados.get("status"),
    )


def _aulas_da_sala(sala_id: str) -> list[AulaAtual]:
    aulas = [_aula_do_cache(linha) for linha in obter_aulas_por_sala(sala_id)]
    return sorted(aulas, key=lambda aula: aula.inicio)


def _aula_atual_e_proxima(
    sala_id: str, agora: datetime
) -> tuple[AulaAtual | None, AulaAtual | None]:
    proxima_aula = None
    for aula in _aulas_da_sala(sala_id):
        if aula.inicio <= agora < aula.fim:
            return aula, None
        if agora < aula.inicio and proxima_aula is None:
            proxima_aula = aula
    return None, proxima_aula


def buscar_aula_atual_por_dispositivo(dispositivo_codigo: str) -> AulaAtual | None:
    sala_id = buscar_sala_id_por_dispositivo(dispositivo_codigo)
    if not sala_id:
        return None

    aula_atual, _ = _aula_atual_e_proxima(sala_id, datetime.now(FUSO_HORARIO))
    return aula_atual


def calcular_contexto_do_dispositivo(dispositivo_codigo: str) -> ContextoDispositivo:
    sala_id = buscar_sala_id_por_dispositivo(dispositivo_codigo)
    if not sala_id:
        return ContextoDispositivo(aula_nome="", ms_remaining=0, ms_for_next=0)

    agora = datetime.now(FUSO_HORARIO)
    aula_atual, proxima_aula = _aula_atual_e_proxima(sala_id, agora)
    if aula_atual:
        return ContextoDispositivo(
            aula_nome=aula_atual.nome,
            ms_remaining=max(int((aula_atual.fim - agora).total_seconds() * 1000), 0),
            ms_for_next=0,
            aula_id=aula_atual.id,
            sala_id=sala_id,
        )
    if proxima_aula:
        return ContextoDispositivo(
            aula_nome=proxima_aula.nome,
            ms_remaining=0,
            ms_for_next=max(
                int((proxima_aula.inicio - agora).total_seconds() * 1000), 0
            ),
            aula_id=proxima_aula.id,
            sala_id=sala_id,
        )

    return ContextoDispositivo(
        aula_nome="", ms_remaining=0, ms_for_next=0, sala_id=sala_id
    )


def salvar_evento_presenca(evento: dict) -> dict:
    evento_id = evento.get("eventId") or str(uuid.uuid4())
    with escopo_sessao() as sessao:
        comando = (
            sqlite_insert(EventoPresenca)
            .values(
                id=evento_id,
                aluno_id=evento["alunoId"],
                aula_id=evento["aulaId"],
                dispositivo_id=evento["dispositivoId"],
                reconhecido_em=evento["recognizedAt"],
                score=float(evento["score"]),
                sync_status="pending",
            )
            .on_conflict_do_nothing(index_elements=["aluno_id", "aula_id"])
        )
        resultado = sessao.execute(comando)
        novo = resultado.rowcount == 1

        linha = (
            sessao.execute(
                select(
                    EventoPresenca.id,
                    EventoPresenca.aluno_id,
                    EventoPresenca.aula_id,
                    EventoPresenca.dispositivo_id,
                    EventoPresenca.reconhecido_em,
                    EventoPresenca.score,
                    Aluno.nome.label("aluno_nome"),
                )
                .outerjoin(Aluno, Aluno.id == EventoPresenca.aluno_id)
                .where(
                    EventoPresenca.aluno_id == evento["alunoId"],
                    EventoPresenca.aula_id == evento["aulaId"],
                )
            )
            .mappings()
            .one_or_none()
        )

    if linha is None:
        raise RuntimeError("evento de presenca nao foi armazenado")

    return {
        "id": linha["id"],
        "aluno_id": linha["aluno_id"],
        "aluno_nome": linha["aluno_nome"] or linha["aluno_id"],
        "aula_id": linha["aula_id"],
        "dispositivo_id": linha["dispositivo_id"],
        "dispositivo_codigo": evento.get("dispositivoCodigo"),
        "reconhecido_em": linha["reconhecido_em"],
        "score": linha["score"],
        "novo": novo,
    }


def reconstruir_cache_redis() -> None:
    with SessionLocal() as sessao:
        linhas_dispositivo = sessao.execute(
            select(
                Dispositivo.id,
                Dispositivo.codigo,
                Dispositivo.sala_id,
                Dispositivo.ativo,
                Dispositivo.interscity_uuid,
            )
        ).all()
        linhas_aula = sessao.scalars(
            select(Aula)
            .where(
                or_(
                    Aula.status.is_(None),
                    Aula.status.not_in(STATUS_AULA_INATIVA),
                )
            )
            .order_by(Aula.sala_id, Aula.inicio)
        ).all()
        linhas_matricula = sessao.execute(
            select(Aula.id, MatriculaTurma.aluno_id).join(
                MatriculaTurma,
                MatriculaTurma.turma_id == Aula.turma_id,
            )
        ).all()
        linhas_embedding = sessao.execute(
            select(EmbeddingFacial.id, EmbeddingFacial.aluno_id, EmbeddingFacial.vetor)
        ).all()

    dispositivos = {
        codigo: {
            "dispositivo_id": dispositivo_id,
            "dispositivo_codigo": codigo,
            "sala_id": sala_id,
            "ativo": bool(ativo),
            "interscity_uuid": interscity_uuid,
        }
        for dispositivo_id, codigo, sala_id, ativo, interscity_uuid in linhas_dispositivo
    }

    sala_aulas: dict[str, list[dict]] = {}
    for aula in linhas_aula:
        sala_aulas.setdefault(aula.sala_id, []).append(
            {
                "id": aula.id,
                "nome": aula.nome,
                "turma_id": aula.turma_id,
                "sala_id": aula.sala_id,
                "inicio": aula.inicio,
                "fim": aula.fim,
                "status": aula.status,
            }
        )

    embeddings = {
        embedding_id: msgpack.packb(
            {
                "alunoId": aluno_id,
                "embedding": vetor,
            },
            use_bin_type=True,
        )
        for embedding_id, aluno_id, vetor in linhas_embedding
    }

    aula_alunos: dict[str, list[str]] = {}
    for aula_id, aluno_id in linhas_matricula:
        aula_alunos.setdefault(aula_id, []).append(aluno_id)

    substituir_cache_redis(dispositivos, sala_aulas, aula_alunos, embeddings)
