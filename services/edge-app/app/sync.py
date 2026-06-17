import asyncio
import base64
import logging

import msgpack

from app.config import MAIN_API_TOKEN, MAIN_API_URL, NODE_ID, SYNC_INTERVAL_SECONDS
from app.db import connect, transaction
from app.redis_store import iter_device_statuses
from app.repository import rebuild_runtime_cache

logger = logging.getLogger(__name__)


def _headers() -> dict[str, str]:
    headers = {"X-Node-Id": NODE_ID}
    if MAIN_API_TOKEN:
        headers["Authorization"] = f"NodeToken {MAIN_API_TOKEN}"
    return headers


def _embedding_blob(value) -> bytes:
    if isinstance(value, str):
        return base64.b64decode(value)
    if isinstance(value, list):
        data = msgpack.packb(
            {"dtype": "float32", "shape": [1, len(value)], "data": value},
            use_bin_type=True,
        )
        return data
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


def _device_row(item: dict) -> dict:
    return {
        "id": item["id"],
        "locale_id": item["locale_id"],
        "active": int(item.get("active", True)),
        "status": item.get("status"),
    }


def _lesson_row(item: dict) -> dict:
    return {
        "id": item["id"],
        "name": item["name"],
        "locale_id": item["locale_id"],
        "starts_at": item["starts_at"],
        "ends_at": item["ends_at"],
        "status": item.get("status"),
    }


def _student_row(item: dict) -> dict:
    return {
        "id": item["id"],
        "registration": item.get("registration") or item["id"],
        "name": item["name"],
        "active": int(item.get("active", True)),
    }


def _delete_by_ids(conn, table: str, ids: list[str]) -> None:
    if not ids:
        return
    conn.executemany(
        f"DELETE FROM {table} WHERE id = ?",
        [(item_id,) for item_id in ids],
    )


def _apply_deletions(conn, deleted: dict) -> None:
    for item in deleted.get("enrollments", []):
        conn.execute(
            "DELETE FROM enrollments WHERE lesson_id = ? AND student_id = ?",
            (item["lesson_id"], item["student_id"]),
        )

    for table in ("face_embeddings", "lessons", "devices", "students", "locales"):
        _delete_by_ids(conn, table, deleted.get(table, []))


def _save_cursors(conn, cursors: dict) -> None:
    for entity, cursor in cursors.items():
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
    upserts = (
        ("locales", data.get("locales", []), ["id", "name"]),
        (
            "devices",
            [_device_row(item) for item in data.get("devices", [])],
            ["id", "locale_id", "active", "status"],
        ),
        (
            "lessons",
            [_lesson_row(item) for item in data.get("lessons", [])],
            ["id", "name", "locale_id", "starts_at", "ends_at", "status"],
        ),
        (
            "students",
            [_student_row(item) for item in data.get("students", [])],
            ["id", "registration", "name", "active"],
        ),
    )

    with transaction() as conn:
        for table, rows, columns in upserts:
            _upsert_many(conn, table, rows, columns)

        for item in data.get("enrollments", []):
            conn.execute(
                "INSERT OR IGNORE INTO enrollments (lesson_id, student_id) VALUES (?, ?)",
                (item["lesson_id"], item["student_id"]),
            )

        for item in data.get("face_embeddings", []):
            conn.execute(
                """
                INSERT INTO face_embeddings (id, student_id, embedding)
                VALUES (?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  student_id = excluded.student_id,
                  embedding = excluded.embedding
                """,
                (
                    item.get("id") or item["student_id"],
                    item["student_id"],
                    _embedding_blob(item["embedding"]),
                ),
            )

        _apply_deletions(conn, deleted)
        _save_cursors(conn, payload.get("cursors", {}))

    rebuild_runtime_cache()


def _current_cursors() -> dict[str, str]:
    with connect() as conn:
        rows = conn.execute("SELECT entity, cursor FROM sync_state").fetchall()
        return {row["entity"]: row["cursor"] for row in rows}


def _pending_attendance() -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT id, student_id, lesson_id, device_id, recognized_at, score
            FROM attendance_events
            WHERE sync_status = 'pending'
            ORDER BY recognized_at
            LIMIT 100
            """
        ).fetchall()
        return [dict(row) for row in rows]


def _mark_synced(ids: list[str]) -> None:
    if not ids:
        return
    with transaction() as conn:
        conn.executemany(
            "UPDATE attendance_events SET sync_status = 'synced' WHERE id = ?",
            [(event_id,) for event_id in ids],
        )


async def _push_device_statuses(client) -> None:
    statuses = iter_device_statuses()
    if not statuses:
        return

    response = await client.post(
        f"{MAIN_API_URL}/edge/devices/status",
        headers=_headers(),
        json={"node_id": NODE_ID, "devices": statuses},
    )
    response.raise_for_status()


async def sync_once() -> None:
    if not MAIN_API_URL:
        return

    import httpx

    async with httpx.AsyncClient(timeout=20) as client:
        pull = await client.get(
            f"{MAIN_API_URL}/edge/pull",
            headers=_headers(),
            params={
                "node_id": NODE_ID,
                "cursors": msgpack.packb(_current_cursors()).hex(),
            },
        )
        pull.raise_for_status()
        apply_pull_payload(pull.json())

        await _push_device_statuses(client)

        pending = _pending_attendance()
        if pending:
            push = await client.post(
                f"{MAIN_API_URL}/edge/attendance",
                headers=_headers(),
                json={"node_id": NODE_ID, "events": pending},
            )
            push.raise_for_status()
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
