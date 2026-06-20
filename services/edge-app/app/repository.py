from datetime import datetime
from zoneinfo import ZoneInfo
import uuid

import msgpack
from sqlalchemy import or_, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.config import ZONE_INFO
from app.db import SessionLocal, session_scope
from app.db_models import Aluno, Aula as DbAula, Dispositivo, EmbeddingFacial
from app.db_models import EventoPresenca, MatriculaAula
from app.models import Aula, DeviceContext
from app.redis_store import replace_runtime_cache

TZ = ZoneInfo(ZONE_INFO)
INACTIVE_AULA_STATUSES = ("FECHADA", "CANCELADA")


def parse_dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=TZ)
    return parsed.astimezone(TZ)


def get_sala_id_for_device(dispositivo_id: str) -> str | None:
    with SessionLocal() as session:
        return session.scalar(
            select(Dispositivo.sala_id).where(
                Dispositivo.id == dispositivo_id,
                Dispositivo.ativo.is_(True),
            )
        )


def get_device_interscity_uuid(dispositivo_id: str) -> str | None:
    with SessionLocal() as session:
        interscity_uuid = session.scalar(
            select(Dispositivo.interscity_uuid).where(Dispositivo.id == dispositivo_id)
        )
        return interscity_uuid or None


def _aula_from_model(aula: DbAula) -> Aula:
    return Aula(
        id=aula.id,
        nome=aula.nome,
        sala_id=aula.sala_id,
        inicio=parse_dt(aula.inicio),
        fim=parse_dt(aula.fim),
        status=aula.status,
    )


def _aulas_for_sala(sala_id: str) -> list[Aula]:
    with SessionLocal() as session:
        rows = session.scalars(
            select(DbAula)
            .where(
                DbAula.sala_id == sala_id,
                or_(
                    DbAula.status.is_(None),
                    DbAula.status.not_in(INACTIVE_AULA_STATUSES),
                ),
            )
            .order_by(DbAula.inicio)
        ).all()
    aulas = [_aula_from_model(row) for row in rows]
    return sorted(aulas, key=lambda aula: aula.inicio)


def _current_and_next_aula(
    sala_id: str, now: datetime
) -> tuple[Aula | None, Aula | None]:
    next_aula = None
    for aula in _aulas_for_sala(sala_id):
        if aula.inicio <= now < aula.fim:
            return aula, None
        if now < aula.inicio and next_aula is None:
            next_aula = aula
    return None, next_aula


def get_current_aula_for_device(dispositivo_id: str) -> Aula | None:
    sala_id = get_sala_id_for_device(dispositivo_id)
    if not sala_id:
        return None

    current, _ = _current_and_next_aula(sala_id, datetime.now(TZ))
    return current


def compute_context_for_device(dispositivo_id: str) -> DeviceContext:
    sala_id = get_sala_id_for_device(dispositivo_id)
    if not sala_id:
        return DeviceContext(aula_nome="", ms_remaining=0, ms_for_next=0)

    now = datetime.now(TZ)
    current, next_aula = _current_and_next_aula(sala_id, now)
    if current:
        return DeviceContext(
            aula_nome=current.nome,
            ms_remaining=max(int((current.fim - now).total_seconds() * 1000), 0),
            ms_for_next=0,
            aula_id=current.id,
            sala_id=sala_id,
        )
    if next_aula:
        return DeviceContext(
            aula_nome=next_aula.nome,
            ms_remaining=0,
            ms_for_next=max(int((next_aula.inicio - now).total_seconds() * 1000), 0),
            aula_id=next_aula.id,
            sala_id=sala_id,
        )

    return DeviceContext(aula_nome="", ms_remaining=0, ms_for_next=0, sala_id=sala_id)


def save_attendance_event(event: dict) -> dict:
    event_id = event.get("eventId") or str(uuid.uuid4())
    with session_scope() as session:
        stmt = (
            sqlite_insert(EventoPresenca)
            .values(
                id=event_id,
                aluno_id=event["alunoId"],
                aula_id=event["aulaId"],
                dispositivo_id=event["dispositivoId"],
                reconhecido_em=event["recognizedAt"],
                score=float(event["score"]),
                sync_status="pending",
            )
            .on_conflict_do_nothing(index_elements=["aluno_id", "aula_id"])
        )
        result = session.execute(stmt)
        is_new = result.rowcount == 1

        row = session.execute(
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
                EventoPresenca.aluno_id == event["alunoId"],
                EventoPresenca.aula_id == event["aulaId"],
            )
        ).mappings().one_or_none()

    if row is None:
        raise RuntimeError("attendance event was not stored")

    return {
        "id": row["id"],
        "aluno_id": row["aluno_id"],
        "aluno_nome": row["aluno_nome"] or row["aluno_id"],
        "aula_id": row["aula_id"],
        "dispositivo_id": row["dispositivo_id"],
        "reconhecido_em": row["reconhecido_em"],
        "score": row["score"],
        "is_new": is_new,
    }


def rebuild_runtime_cache() -> None:
    with SessionLocal() as session:
        matricula_rows = session.execute(
            select(MatriculaAula.aula_id, MatriculaAula.aluno_id)
        ).all()
        embedding_rows = session.execute(
            select(EmbeddingFacial.id, EmbeddingFacial.aluno_id, EmbeddingFacial.vetor)
        ).all()

    aula_alunos: dict[str, list[str]] = {}
    for aula_id, aluno_id in matricula_rows:
        aula_alunos.setdefault(aula_id, []).append(aluno_id)

    embeddings = {
        embedding_id: msgpack.packb(
            {
                "alunoId": aluno_id,
                "embedding": vetor,
            },
            use_bin_type=True,
        )
        for embedding_id, aluno_id, vetor in embedding_rows
    }
    replace_runtime_cache(aula_alunos, embeddings)
