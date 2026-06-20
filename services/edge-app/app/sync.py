import argparse
import asyncio
import base64
import logging

import msgpack
from sqlalchemy import delete, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.config import AUTOPONTO_API_TOKEN, AUTOPONTO_API_URL, NODE_ID
from app.db import SessionLocal, escopo_sessao, inicializar_banco
from app.db_models import Aluno, Aula, Dispositivo, EmbeddingFacial
from app.db_models import EventoPresenca, MatriculaTurma, Sala, SyncState
from app.repository import reconstruir_cache_redis

logger = logging.getLogger(__name__)

ENTIDADES_SINCRONIZADAS = (
    "salas",
    "dispositivos",
    "aulas",
    "alunos",
    "matriculas_turma",
    "embeddings_faciais",
)
ENTIDADES_CACHE_RECONHECIMENTO = (
    "dispositivos",
    "aulas",
    "matriculas_turma",
    "embeddings_faciais",
)
MODELOS_DO_CACHE_REPLICADO = (
    EmbeddingFacial,
    MatriculaTurma,
    Aula,
    Dispositivo,
    Aluno,
    Sala,
)


def _cabecalhos_autenticacao() -> dict[str, str]:
    cabecalhos = {"X-Node-Id": NODE_ID}
    if AUTOPONTO_API_TOKEN:
        cabecalhos["Authorization"] = f"NodeToken {AUTOPONTO_API_TOKEN}"
    return cabecalhos


def _validar_resposta_http(resposta, operacao: str) -> None:
    try:
        resposta.raise_for_status()
    except Exception:
        corpo = getattr(resposta, "text", "")
        if len(corpo) > 1000:
            corpo = f"{corpo[:1000]}..."
        logger.warning(
            "sync %s failed status=%s body=%s",
            operacao,
            getattr(resposta, "status_code", "unknown"),
            corpo,
        )
        raise


def _vetor_embedding_para_blob(valor) -> bytes:
    if isinstance(valor, str):
        return base64.b64decode(valor)
    if isinstance(valor, list):
        return msgpack.packb(
            {"dtype": "float32", "shape": [1, len(valor)], "data": valor},
            use_bin_type=True,
        )
    raise ValueError("payload de embedding sem suporte")


def _valor_booleano_ativo(valor) -> bool:
    if isinstance(valor, str):
        return valor.strip().lower() not in ("0", "false", "no", "off", "")
    return bool(valor)


def _salvar_muitos_com_upsert(
    sessao: Session,
    modelo,
    registros: list[dict],
    colunas: list[str],
    colunas_conflito: list[str] | None = None,
) -> None:
    if not registros:
        return

    colunas_conflito = colunas_conflito or [colunas[0]]
    comando = sqlite_insert(modelo).values(registros)
    valores_atualizacao = {
        coluna: getattr(comando.excluded, coluna)
        for coluna in colunas
        if coluna not in colunas_conflito
    }
    if valores_atualizacao:
        comando = comando.on_conflict_do_update(
            index_elements=colunas_conflito,
            set_=valores_atualizacao,
        )
    else:
        comando = comando.on_conflict_do_nothing(index_elements=colunas_conflito)
    sessao.execute(comando)


def _limpar_cache_replicado(sessao: Session) -> None:
    for modelo in MODELOS_DO_CACHE_REPLICADO:
        sessao.execute(delete(modelo))
    sessao.execute(delete(SyncState))


def _aplicar_exclusoes(sessao: Session, removidos: dict) -> None:
    for modelo, entidade in (
        (EmbeddingFacial, "embeddings_faciais"),
        (MatriculaTurma, "matriculas_turma"),
        (Aula, "aulas"),
        (Dispositivo, "dispositivos"),
        (Aluno, "alunos"),
        (Sala, "salas"),
    ):
        ids_removidos = removidos.get(entidade, [])
        if ids_removidos:
            sessao.execute(delete(modelo).where(modelo.id.in_(ids_removidos)))


def _salvar_cursores(sessao: Session, cursores: dict) -> None:
    registros = [
        {"entity": entidade, "cursor": str(cursor)}
        for entidade, cursor in cursores.items()
        if entidade in ENTIDADES_SINCRONIZADAS
    ]
    _salvar_muitos_com_upsert(sessao, SyncState, registros, ["entity", "cursor"])


def aplicar_payload_sincronizacao(
    payload: dict, substituir_cache: bool = False
) -> None:
    dados = payload.get("data", payload)
    removidos = payload.get("deleted", {})
    deve_reconstruir_cache = substituir_cache or any(
        dados.get(entidade) for entidade in ENTIDADES_CACHE_RECONHECIMENTO
    )
    deve_reconstruir_cache = deve_reconstruir_cache or any(
        removidos.get(entidade) for entidade in ENTIDADES_CACHE_RECONHECIMENTO
    )

    upserts: tuple[tuple[object, list[dict], list[str]], ...] = (
        (
            Sala,
            [
                {"id": item["id"], "nome": item["nome"]}
                for item in dados.get("salas", [])
            ],
            ["id", "nome"],
        ),
        (
            Dispositivo,
            [
                {
                    "id": item["id"],
                    "codigo": item["codigo"],
                    "sala_id": item["sala_id"],
                    "ativo": _valor_booleano_ativo(item.get("ativo", True)),
                    "interscity_uuid": item.get("interscity_uuid") or None,
                }
                for item in dados.get("dispositivos", [])
            ],
            ["id", "codigo", "sala_id", "ativo", "interscity_uuid"],
        ),
        (
            Aula,
            [
                {
                    "id": item["id"],
                    "nome": item["nome"],
                    "turma_id": item["turma_id"],
                    "sala_id": item["sala_id"],
                    "inicio": item["inicio"],
                    "fim": item["fim"],
                    "status": item.get("status"),
                }
                for item in dados.get("aulas", [])
            ],
            ["id", "nome", "turma_id", "sala_id", "inicio", "fim", "status"],
        ),
        (
            Aluno,
            [
                {
                    "id": item["id"],
                    "matricula": item.get("matricula") or item["id"],
                    "nome": item["nome"],
                }
                for item in dados.get("alunos", [])
            ],
            ["id", "matricula", "nome"],
        ),
        (
            MatriculaTurma,
            [
                {
                    "id": item["id"],
                    "turma_id": item["turma_id"],
                    "aluno_id": item["aluno_id"],
                }
                for item in dados.get("matriculas_turma", [])
            ],
            ["id", "turma_id", "aluno_id"],
        ),
        (
            EmbeddingFacial,
            [
                {
                    "id": item["id"],
                    "aluno_id": item["aluno_id"],
                    "vetor": _vetor_embedding_para_blob(item["vetor"]),
                }
                for item in dados.get("embeddings_faciais", [])
            ],
            ["id", "aluno_id", "vetor"],
        ),
    )

    with escopo_sessao() as sessao:
        if substituir_cache:
            _limpar_cache_replicado(sessao)

        for modelo, registros, colunas in upserts:
            _salvar_muitos_com_upsert(sessao, modelo, registros, colunas)

        if not substituir_cache:
            _aplicar_exclusoes(sessao, removidos)
        _salvar_cursores(sessao, payload.get("cursors", {}))

    if deve_reconstruir_cache:
        reconstruir_cache_redis()


def _cursores_atuais() -> dict[str, str]:
    with SessionLocal() as sessao:
        linhas = sessao.execute(select(SyncState.entity, SyncState.cursor)).all()
        return {
            entidade: cursor
            for entidade, cursor in linhas
            if entidade in ENTIDADES_SINCRONIZADAS
        }


def _presencas_pendentes() -> list[dict]:
    with SessionLocal() as sessao:
        linhas = (
            sessao.execute(
                select(
                    EventoPresenca.id,
                    EventoPresenca.aluno_id,
                    EventoPresenca.aula_id,
                    EventoPresenca.dispositivo_id,
                    EventoPresenca.reconhecido_em,
                    EventoPresenca.score,
                )
                .where(EventoPresenca.sync_status == "pending")
                .order_by(EventoPresenca.reconhecido_em)
                .limit(100)
            )
            .mappings()
            .all()
        )
        return [dict(linha) for linha in linhas]


def _marcar_presencas_sincronizadas(ids: list[str]) -> None:
    if not ids:
        return
    with escopo_sessao() as sessao:
        sessao.execute(
            update(EventoPresenca)
            .where(EventoPresenca.id.in_(ids))
            .values(sync_status="synced")
        )


async def executar_sincronizacao(
    forcar_completa: bool = False,
    enviar_presencas: bool = True,
) -> None:
    if not AUTOPONTO_API_URL:
        return

    import httpx

    parametros = {"node_id": NODE_ID}
    substituir_cache = forcar_completa
    if forcar_completa:
        parametros["full"] = "true"
    else:
        cursores = _cursores_atuais()
        if set(cursores) == set(ENTIDADES_SINCRONIZADAS):
            parametros["cursors"] = msgpack.packb(cursores).hex()
        else:
            parametros["full"] = "true"
            substituir_cache = True

    async with httpx.AsyncClient(timeout=20) as cliente:
        resposta_pull = await cliente.get(
            f"{AUTOPONTO_API_URL}/edge/pull/",
            headers=_cabecalhos_autenticacao(),
            params=parametros,
        )
        _validar_resposta_http(resposta_pull, "pull")
        aplicar_payload_sincronizacao(
            resposta_pull.json(),
            substituir_cache=substituir_cache,
        )

        presencas = _presencas_pendentes()
        if enviar_presencas and presencas:
            resposta_presencas = await cliente.post(
                f"{AUTOPONTO_API_URL}/edge/attendance/",
                headers=_cabecalhos_autenticacao(),
                json={"node_id": NODE_ID, "eventos": presencas},
            )
            _validar_resposta_http(resposta_presencas, "attendance push")
            ids_sincronizados = resposta_presencas.json().get(
                "synced_ids",
                [presenca["id"] for presenca in presencas],
            )
            _marcar_presencas_sincronizadas(ids_sincronizados)


def main() -> None:
    parser = argparse.ArgumentParser(description="Executa uma sincronizacao AutoPonto.")
    parser.add_argument(
        "--completa",
        action="store_true",
        help="envia full=true e solicita um pull completo da API",
    )
    parser.add_argument(
        "--sem-presencas",
        action="store_true",
        help="nao envia presencas pendentes neste ciclo",
    )
    argumentos = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )
    inicializar_banco()
    asyncio.run(
        executar_sincronizacao(
            forcar_completa=argumentos.completa,
            enviar_presencas=not argumentos.sem_presencas,
        )
    )


if __name__ == "__main__":
    main()
