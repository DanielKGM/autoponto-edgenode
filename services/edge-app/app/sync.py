import asyncio
import argparse
import base64
import logging

import msgpack
from sqlalchemy import delete, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.config import (
    AUTOPONTO_API_TOKEN,
    AUTOPONTO_API_URL,
    NODE_ID,
    SYNC_INTERVAL_SECONDS,
)
from app.db import SessionLocal, init_db, session_scope
from app.db_models import Aluno, Aula, Dispositivo, EmbeddingFacial, MatriculaAula
from app.db_models import EventoPresenca, Sala, SyncState
from app.repository import rebuild_runtime_cache

logger = logging.getLogger(__name__)

SYNC_ENTITIES = (
    "salas",
    "dispositivos",
    "aulas",
    "alunos",
    "matriculas_aula",
    "embeddings_faciais",
)
RUNTIME_CACHE_ENTITIES = ("aulas", "alunos", "matriculas_aula", "embeddings_faciais")


def _headers() -> dict[str, str]:
    headers = {"X-Node-Id": NODE_ID}
    if AUTOPONTO_API_TOKEN:
        headers["Authorization"] = f"NodeToken {AUTOPONTO_API_TOKEN}"
    return headers


def _raise_for_status(response, operation: str) -> None:
    try:
        response.raise_for_status()
    except Exception:
        body = getattr(response, "text", "")
        if len(body) > 1000:
            body = f"{body[:1000]}..."
        logger.warning(
            "sync %s failed status=%s body=%s",
            operation,
            getattr(response, "status_code", "unknown"),
            body,
        )
        raise


def _embedding_blob(value) -> bytes:
    if isinstance(value, str):
        return base64.b64decode(value)
    if isinstance(value, list):
        return msgpack.packb(
            {"dtype": "float32", "shape": [1, len(value)], "data": value},
            use_bin_type=True,
        )
    raise ValueError("unsupported embedding payload")


def _active_flag(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() not in ("0", "false", "no", "off", "")
    return bool(value)


def _upsert_many(
    session: Session,
    model,
    rows: list[dict],
    columns: list[str],
    conflict_columns: list[str] | None = None,
) -> None:
    if not rows:
        return

    conflict_columns = conflict_columns or [columns[0]]
    stmt = sqlite_insert(model).values(rows)
    set_values = {
        col: getattr(stmt.excluded, col)
        for col in columns
        if col not in conflict_columns
    }
    if set_values:
        stmt = stmt.on_conflict_do_update(
            index_elements=conflict_columns,
            set_=set_values,
        )
    else:
        stmt = stmt.on_conflict_do_nothing(index_elements=conflict_columns)
    session.execute(stmt)


def _insert_matriculas(session: Session, rows: list[dict]) -> None:
    if not rows:
        return
    stmt = (
        sqlite_insert(MatriculaAula)
        .values(rows)
        .on_conflict_do_nothing(index_elements=["aula_id", "aluno_id"])
    )
    session.execute(stmt)


def _apply_deletions(session: Session, deleted: dict) -> None:
    for item in deleted.get("matriculas_aula", []):
        session.execute(
            delete(MatriculaAula).where(
                MatriculaAula.aula_id == item["aula_id"],
                MatriculaAula.aluno_id == item["aluno_id"],
            )
        )

    for model, entity in (
        (EmbeddingFacial, "embeddings_faciais"),
        (Aula, "aulas"),
        (Dispositivo, "dispositivos"),
        (Aluno, "alunos"),
        (Sala, "salas"),
    ):
        ids = deleted.get(entity, [])
        if ids:
            session.execute(delete(model).where(model.id.in_(ids)))


def _save_cursors(session: Session, cursors: dict) -> None:
    rows = [
        {"entity": entity, "cursor": str(cursor)}
        for entity, cursor in cursors.items()
        if entity in SYNC_ENTITIES
    ]
    _upsert_many(session, SyncState, rows, ["entity", "cursor"])


def apply_pull_payload(payload: dict) -> None:
    data = payload.get("data", payload)
    deleted = payload.get("deleted", {})
    should_rebuild_cache = any(data.get(entity) for entity in RUNTIME_CACHE_ENTITIES)
    should_rebuild_cache = should_rebuild_cache or any(
        deleted.get(entity) for entity in RUNTIME_CACHE_ENTITIES
    )

    upserts: tuple[tuple[object, list[dict], list[str]], ...] = (
        (
            Sala,
            [{"id": item["id"], "nome": item["nome"]} for item in data.get("salas", [])],
            ["id", "nome"],
        ),
        (
            Dispositivo,
            [
                {
                    "id": item["id"],
                    "sala_id": item["sala_id"],
                    "ativo": _active_flag(item.get("ativo", True)),
                    "status": item.get("status"),
                    "interscity_uuid": item.get("interscity_uuid"),
                }
                for item in data.get("dispositivos", [])
            ],
            ["id", "sala_id", "ativo", "status", "interscity_uuid"],
        ),
        (
            Aula,
            [
                {
                    "id": item["id"],
                    "nome": item["nome"],
                    "sala_id": item["sala_id"],
                    "inicio": item["inicio"],
                    "fim": item["fim"],
                    "status": item.get("status"),
                }
                for item in data.get("aulas", [])
            ],
            ["id", "nome", "sala_id", "inicio", "fim", "status"],
        ),
        (
            Aluno,
            [
                {
                    "id": item["id"],
                    "matricula": item.get("matricula") or item["id"],
                    "nome": item["nome"],
                }
                for item in data.get("alunos", [])
            ],
            ["id", "matricula", "nome"],
        ),
    )

    with session_scope() as session:
        for model, rows, columns in upserts:
            _upsert_many(session, model, rows, columns)

        _insert_matriculas(
            session,
            [
                {"aula_id": item["aula_id"], "aluno_id": item["aluno_id"]}
                for item in data.get("matriculas_aula", [])
            ],
        )

        _upsert_many(
            session,
            EmbeddingFacial,
            [
                {
                    "id": item["id"],
                    "aluno_id": item["aluno_id"],
                    "vetor": _embedding_blob(item["vetor"]),
                }
                for item in data.get("embeddings_faciais", [])
            ],
            ["id", "aluno_id", "vetor"],
        )

        _apply_deletions(session, deleted)
        _save_cursors(session, payload.get("cursors", {}))

    if should_rebuild_cache:
        rebuild_runtime_cache()


def _current_cursors(force_full: bool = False) -> dict[str, str]:
    if force_full:
        return {}
    with SessionLocal() as session:
        rows = session.execute(select(SyncState.entity, SyncState.cursor)).all()
        return {
            entity: cursor
            for entity, cursor in rows
            if entity in SYNC_ENTITIES
        }


def _pending_attendance() -> list[dict]:
    with SessionLocal() as session:
        rows = session.execute(
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
        ).mappings().all()
        return [dict(row) for row in rows]


def _mark_synced(ids: list[str]) -> None:
    if not ids:
        return
    with session_scope() as session:
        session.execute(
            update(EventoPresenca)
            .where(EventoPresenca.id.in_(ids))
            .values(sync_status="synced")
        )


async def sync_once(force_full: bool = False) -> None:
    if not AUTOPONTO_API_URL:
        return

    import httpx

    async with httpx.AsyncClient(timeout=20) as client:
        pull = await client.get(
            f"{AUTOPONTO_API_URL}/edge/pull",
            headers=_headers(),
            params={
                "node_id": NODE_ID,
                "cursors": msgpack.packb(_current_cursors(force_full)).hex(),
            },
        )
        _raise_for_status(pull, "pull")
        apply_pull_payload(pull.json())

        pending = _pending_attendance()
        if pending:
            push = await client.post(
                f"{AUTOPONTO_API_URL}/edge/attendance",
                headers=_headers(),
                json={"node_id": NODE_ID, "eventos": pending},
            )
            _raise_for_status(push, "attendance push")
            synced_ids = push.json().get(
                "synced_ids",
                [event["id"] for event in pending],
            )
            _mark_synced(synced_ids)


async def run_sync_loop(stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        try:
            await sync_once()
        except Exception as exc:
            logger.warning("sync failed: %s", exc)

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=SYNC_INTERVAL_SECONDS)
        except asyncio.TimeoutError:
            pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one AutoPonto sync cycle.")
    parser.add_argument(
        "--full",
        action="store_true",
        help="send empty cursors and ask the API for a full pull",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )
    init_db()
    asyncio.run(sync_once(force_full=args.full))


if __name__ == "__main__":
    main()
