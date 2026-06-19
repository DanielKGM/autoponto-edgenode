import asyncio
import argparse
import base64
import logging

import msgpack

from app.config import (
    AUTOPONTO_API_TOKEN,
    AUTOPONTO_API_URL,
    NODE_ID,
    SYNC_INTERVAL_SECONDS,
)
from app.db import connect, init_db, transaction
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


def _upsert_many(conn, table: str, rows: list[dict], columns: list[str]) -> None:
    if not rows:
        return
    placeholders = ", ".join("?" for _ in columns)
    assignments = ", ".join(f"{col} = excluded.{col}" for col in columns[1:])
    sql = (
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders}) "
        f"ON CONFLICT({columns[0]}) DO UPDATE SET {assignments}"
    )
    conn.executemany(sql, [tuple(row[col] for col in columns) for row in rows])


def _apply_deletions(conn, deleted: dict) -> None:
    for item in deleted.get("matriculas_aula", []):
        conn.execute(
            "DELETE FROM matriculas_aula WHERE aula_id = ? AND aluno_id = ?",
            (item["aula_id"], item["aluno_id"]),
        )

    for table, entity in (
        ("embeddings_faciais", "embeddings_faciais"),
        ("aulas", "aulas"),
        ("dispositivos", "dispositivos"),
        ("alunos", "alunos"),
        ("salas", "salas"),
    ):
        ids = deleted.get(entity, [])
        if ids:
            conn.executemany(
                f"DELETE FROM {table} WHERE id = ?",
                [(item_id,) for item_id in ids],
            )


def _save_cursors(conn, cursors: dict) -> None:
    for entity, cursor in cursors.items():
        if entity not in SYNC_ENTITIES:
            continue
        conn.execute(
            """
            INSERT INTO sync_state (entity, cursor)
            VALUES (?, ?)
            ON CONFLICT(entity) DO UPDATE SET cursor = excluded.cursor
            """,
            (entity, str(cursor)),
        )


def apply_pull_payload(payload: dict) -> None:
    data = payload.get("data", payload)
    deleted = payload.get("deleted", {})
    should_rebuild_cache = any(data.get(entity) for entity in RUNTIME_CACHE_ENTITIES)
    should_rebuild_cache = should_rebuild_cache or any(
        deleted.get(entity) for entity in RUNTIME_CACHE_ENTITIES
    )

    upserts: tuple[tuple[str, list[dict], list[str]], ...] = (
        (
            "salas",
            [{"id": item["id"], "nome": item["nome"]} for item in data.get("salas", [])],
            ["id", "nome"],
        ),
        (
            "dispositivos",
            [
                {
                    "id": item["id"],
                    "sala_id": item["sala_id"],
                    "ativo": int(item.get("ativo", True)),
                    "status": item.get("status"),
                    "interscity_uuid": item.get("interscity_uuid"),
                }
                for item in data.get("dispositivos", [])
            ],
            ["id", "sala_id", "ativo", "status", "interscity_uuid"],
        ),
        (
            "aulas",
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
            "alunos",
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

    with transaction() as conn:
        for table, rows, columns in upserts:
            _upsert_many(conn, table, rows, columns)

        for item in data.get("matriculas_aula", []):
            conn.execute(
                "INSERT OR IGNORE INTO matriculas_aula (aula_id, aluno_id) VALUES (?, ?)",
                (item["aula_id"], item["aluno_id"]),
            )

        for item in data.get("embeddings_faciais", []):
            conn.execute(
                """
                INSERT INTO embeddings_faciais (id, aluno_id, vetor)
                VALUES (?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  aluno_id = excluded.aluno_id,
                  vetor = excluded.vetor
                """,
                (
                    item["id"],
                    item["aluno_id"],
                    _embedding_blob(item["vetor"]),
                ),
            )

        _apply_deletions(conn, deleted)
        _save_cursors(conn, payload.get("cursors", {}))

    if should_rebuild_cache:
        rebuild_runtime_cache()


def _current_cursors(force_full: bool = False) -> dict[str, str]:
    if force_full:
        return {}
    with connect() as conn:
        rows = conn.execute("SELECT entity, cursor FROM sync_state").fetchall()
        return {
            row["entity"]: row["cursor"]
            for row in rows
            if row["entity"] in SYNC_ENTITIES
        }


def _pending_attendance() -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT
              id,
              aluno_id,
              aula_id,
              dispositivo_id,
              reconhecido_em,
              score
            FROM eventos_presenca
            WHERE sync_status = 'pending'
            ORDER BY reconhecido_em
            LIMIT 100
            """
        ).fetchall()
        return [dict(row) for row in rows]


def _mark_synced(ids: list[str]) -> None:
    if not ids:
        return
    with transaction() as conn:
        conn.executemany(
            "UPDATE eventos_presenca SET sync_status = 'synced' WHERE id = ?",
            [(event_id,) for event_id in ids],
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
