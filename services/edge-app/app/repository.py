from datetime import datetime
from zoneinfo import ZoneInfo
import uuid

import msgpack

from app.config import ZONE_INFO
from app.db import connect, transaction
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
    with connect() as conn:
        row = conn.execute(
            "SELECT sala_id FROM dispositivos WHERE id = ? AND ativo = 1",
            (dispositivo_id,),
        ).fetchone()
        return row["sala_id"] if row else None


def get_device_interscity_uuid(dispositivo_id: str) -> str | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT interscity_uuid FROM dispositivos WHERE id = ?",
            (dispositivo_id,),
        ).fetchone()
        if not row:
            return None
        return row["interscity_uuid"] or None


def _aula_from_row(row) -> Aula:
    return Aula(
        id=row["id"],
        nome=row["nome"],
        sala_id=row["sala_id"],
        inicio=parse_dt(row["inicio"]),
        fim=parse_dt(row["fim"]),
        status=row["status"],
    )


def _aulas_for_sala(sala_id: str) -> list[Aula]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT id, nome, sala_id, inicio, fim, status
            FROM aulas
            WHERE sala_id = ?
              AND (status IS NULL OR status NOT IN (?, ?))
            """,
            (sala_id, *INACTIVE_AULA_STATUSES),
        ).fetchall()
    aulas = [_aula_from_row(row) for row in rows]
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
    with transaction() as conn:
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO eventos_presenca
            (id, aluno_id, aula_id, dispositivo_id, reconhecido_em, score, sync_status)
            VALUES (?, ?, ?, ?, ?, ?, 'pending')
            """,
            (
                event_id,
                event["alunoId"],
                event["aulaId"],
                event["dispositivoId"],
                event["recognizedAt"],
                float(event["score"]),
            ),
        )
        is_new = cursor.rowcount == 1
        row = conn.execute(
            """
            SELECT
              eventos_presenca.id,
              eventos_presenca.aluno_id,
              eventos_presenca.aula_id,
              eventos_presenca.dispositivo_id,
              eventos_presenca.reconhecido_em,
              eventos_presenca.score,
              COALESCE(alunos.nome, eventos_presenca.aluno_id) AS aluno_nome
            FROM eventos_presenca
            LEFT JOIN alunos ON alunos.id = eventos_presenca.aluno_id
            WHERE eventos_presenca.aluno_id = ?
              AND eventos_presenca.aula_id = ?
            """,
            (event["alunoId"], event["aulaId"]),
        ).fetchone()

    if row is None:
        raise RuntimeError("attendance event was not stored")

    return {
        "id": row["id"],
        "aluno_id": row["aluno_id"],
        "aluno_nome": row["aluno_nome"],
        "aula_id": row["aula_id"],
        "dispositivo_id": row["dispositivo_id"],
        "reconhecido_em": row["reconhecido_em"],
        "score": row["score"],
        "is_new": is_new,
    }


def rebuild_runtime_cache() -> None:
    with connect() as conn:
        matricula_rows = conn.execute(
            "SELECT aula_id, aluno_id FROM matriculas_aula"
        ).fetchall()
        embedding_rows = conn.execute(
            """
            SELECT id, aluno_id, vetor
            FROM embeddings_faciais
            """
        ).fetchall()

    aula_alunos: dict[str, list[str]] = {}
    for row in matricula_rows:
        aula_alunos.setdefault(row["aula_id"], []).append(row["aluno_id"])

    embeddings = {
        row["id"]: msgpack.packb(
            {
                "alunoId": row["aluno_id"],
                "embedding": row["vetor"],
            },
            use_bin_type=True,
        )
        for row in embedding_rows
    }
    replace_runtime_cache(aula_alunos, embeddings)
