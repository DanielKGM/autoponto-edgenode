import asyncio
import base64
import logging

import msgpack

from app.config import MAIN_API_TOKEN, MAIN_API_URL, NODE_ID, SYNC_INTERVAL_SECONDS
from app.db import connect, transaction
from app.repository import rebuild_runtime_cache

logger = logging.getLogger(__name__)


def _headers() -> dict[str, str]:
    headers = {"X-Node-Id": NODE_ID}
    if MAIN_API_TOKEN:
        headers["Authorization"] = f"Bearer {MAIN_API_TOKEN}"
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


def apply_pull_payload(payload: dict) -> None:
    data = payload.get("data", payload)
    deleted = payload.get("deleted", {})
    devices = [
        {
            "id": item["id"],
            "locale_id": item["locale_id"],
            "active": int(item.get("active", True)),
        }
        for item in data.get("devices", [])
    ]
    lessons = [
        {
            "id": item["id"],
            "name": item["name"],
            "locale_id": item["locale_id"],
            "starts_at": item["starts_at"],
            "ends_at": item["ends_at"],
        }
        for item in data.get("lessons", [])
    ]
    students = [
        {
            "id": item["id"],
            "registration": item.get("registration") or item["id"],
            "name": item["name"],
            "active": int(item.get("active", True)),
        }
        for item in data.get("students", [])
    ]

    with transaction() as conn:
        _upsert_many(conn, "locales", data.get("locales", []), ["id", "name"])
        _upsert_many(conn, "devices", devices, ["id", "locale_id", "active"])
        _upsert_many(
            conn,
            "lessons",
            lessons,
            ["id", "name", "locale_id", "starts_at", "ends_at"],
        )
        _upsert_many(conn, "students", students, ["id", "registration", "name", "active"])

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

        for item in deleted.get("enrollments", []):
            conn.execute(
                "DELETE FROM enrollments WHERE lesson_id = ? AND student_id = ?",
                (item["lesson_id"], item["student_id"]),
            )
        for item_id in deleted.get("face_embeddings", []):
            conn.execute("DELETE FROM face_embeddings WHERE id = ?", (item_id,))
        for item_id in deleted.get("lessons", []):
            conn.execute("DELETE FROM lessons WHERE id = ?", (item_id,))
        for item_id in deleted.get("devices", []):
            conn.execute("DELETE FROM devices WHERE id = ?", (item_id,))
        for item_id in deleted.get("students", []):
            conn.execute("DELETE FROM students WHERE id = ?", (item_id,))
        for item_id in deleted.get("locales", []):
            conn.execute("DELETE FROM locales WHERE id = ?", (item_id,))

        for entity, cursor in payload.get("cursors", {}).items():
            conn.execute(
                """
                INSERT INTO sync_state (entity, cursor)
                VALUES (?, ?)
                ON CONFLICT(entity) DO UPDATE SET cursor = excluded.cursor
                """,
                (entity, str(cursor)),
            )

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


async def sync_once() -> None:
    if not MAIN_API_URL:
        return

    import httpx

    async with httpx.AsyncClient(timeout=20) as client:
        pull = await client.get(
            f"{MAIN_API_URL}/edge/pull",
            headers=_headers(),
            params={"node_id": NODE_ID, "cursors": msgpack.packb(_current_cursors()).hex()},
        )
        pull.raise_for_status()
        apply_pull_payload(pull.json())

        pending = _pending_attendance()
        if pending:
            push = await client.post(
                f"{MAIN_API_URL}/edge/attendance",
                headers=_headers(),
                json={"node_id": NODE_ID, "events": pending},
            )
            push.raise_for_status()
            synced_ids = push.json().get("synced_ids", [event["id"] for event in pending])
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
