from datetime import datetime
from zoneinfo import ZoneInfo
import uuid

import msgpack

from app.config import ZONE_INFO
from app.db import connect, transaction
from app.models import DeviceContext, Lesson
from app.redis_store import replace_runtime_cache

TZ = ZoneInfo(ZONE_INFO)


def parse_dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=TZ)
    return parsed.astimezone(TZ)


def get_locale_id_for_device(device_id: str) -> str | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT locale_id FROM devices WHERE id = ? AND active = 1",
            (device_id,),
        ).fetchone()
        return row["locale_id"] if row else None


def _lesson_from_row(row) -> Lesson:
    return Lesson(
        id=row["id"],
        name=row["name"],
        locale_id=row["locale_id"],
        starts_at=parse_dt(row["starts_at"]),
        ends_at=parse_dt(row["ends_at"]),
    )


def _lessons_for_locale(locale_id: str) -> list[Lesson]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT id, name, locale_id, starts_at, ends_at
            FROM lessons WHERE locale_id = ?
            """,
            (locale_id,),
        ).fetchall()
    lessons = [_lesson_from_row(row) for row in rows]
    return sorted(lessons, key=lambda lesson: lesson.starts_at)


def _current_and_next_lesson(
    locale_id: str, now: datetime
) -> tuple[Lesson | None, Lesson | None]:
    next_lesson = None
    for lesson in _lessons_for_locale(locale_id):
        if lesson.starts_at <= now < lesson.ends_at:
            return lesson, None
        if now < lesson.starts_at and next_lesson is None:
            next_lesson = lesson
    return None, next_lesson


def get_current_lesson_for_device(device_id: str) -> Lesson | None:
    locale_id = get_locale_id_for_device(device_id)
    if not locale_id:
        return None

    current, _ = _current_and_next_lesson(locale_id, datetime.now(TZ))
    return current


def compute_context_for_device(device_id: str) -> DeviceContext:
    locale_id = get_locale_id_for_device(device_id)
    if not locale_id:
        return DeviceContext(lesson_name="", ms_remaining=0, ms_for_next=0)

    now = datetime.now(TZ)
    current, next_lesson = _current_and_next_lesson(locale_id, now)
    if current:
        return DeviceContext(
            lesson_name=current.name,
            ms_remaining=max(int((current.ends_at - now).total_seconds() * 1000), 0),
            ms_for_next=0,
            lesson_id=current.id,
            locale_id=locale_id,
        )
    if next_lesson:
        return DeviceContext(
            lesson_name=next_lesson.name,
            ms_remaining=0,
            ms_for_next=max(int((next_lesson.starts_at - now).total_seconds() * 1000), 0),
            lesson_id=next_lesson.id,
            locale_id=locale_id,
        )

    return DeviceContext(
        lesson_name="", ms_remaining=0, ms_for_next=0, locale_id=locale_id
    )


def save_attendance_event(event: dict) -> dict:
    event_id = event.get("eventId") or str(uuid.uuid4())
    with transaction() as conn:
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO attendance_events
            (id, student_id, lesson_id, device_id, recognized_at, score, sync_status)
            VALUES (?, ?, ?, ?, ?, ?, 'pending')
            """,
            (
                event_id,
                event["studentId"],
                event["lessonId"],
                event["deviceId"],
                event["recognizedAt"],
                float(event["score"]),
            ),
        )
        is_new = cursor.rowcount == 1
        row = conn.execute(
            """
            SELECT
              attendance_events.id,
              attendance_events.student_id,
              attendance_events.lesson_id,
              attendance_events.device_id,
              attendance_events.recognized_at,
              attendance_events.score,
              COALESCE(students.name, attendance_events.student_id) AS student_name
            FROM attendance_events
            LEFT JOIN students ON students.id = attendance_events.student_id
            WHERE attendance_events.student_id = ?
              AND attendance_events.lesson_id = ?
            """,
            (event["studentId"], event["lessonId"]),
        ).fetchone()

    if row is None:
        raise RuntimeError("attendance event was not stored")

    return {
        "id": row["id"],
        "student_id": row["student_id"],
        "student_name": row["student_name"],
        "lesson_id": row["lesson_id"],
        "device_id": row["device_id"],
        "recognized_at": row["recognized_at"],
        "score": row["score"],
        "is_new": is_new,
    }


def rebuild_runtime_cache() -> None:
    with connect() as conn:
        enrollment_rows = conn.execute(
            "SELECT lesson_id, student_id FROM enrollments"
        ).fetchall()
        embedding_rows = conn.execute("""
            SELECT face_embeddings.id, face_embeddings.student_id, face_embeddings.embedding
            FROM face_embeddings
            JOIN students ON students.id = face_embeddings.student_id
            WHERE students.active = 1
            """).fetchall()

    lesson_students: dict[str, list[str]] = {}
    for row in enrollment_rows:
        lesson_students.setdefault(row["lesson_id"], []).append(row["student_id"])

    embeddings = {
        row["id"]: msgpack.packb(
            {
                "studentId": row["student_id"],
                "embedding": row["embedding"],
            },
            use_bin_type=True,
        )
        for row in embedding_rows
    }
    replace_runtime_cache(lesson_students, embeddings)
