from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import msgpack
import numpy as np
import redis


ROOT = Path(__file__).resolve().parents[1]
EDGE_APP_PATH = ROOT / "services" / "edge-app"
DEFAULT_SQLITE_PATH = ROOT / "data" / "edge" / "edge.db"
DEFAULT_EMBEDDINGS_DIR = ROOT / "embeddings_mock"
EMBEDDING_GLOB = "*_normal.npy"

LOCALE_ID = "LABESE"
DEVICE_ID = "9084CED6CDC0"
LESSON_ID = "ambiental"
LESSON_NAME = "AMBIENTAL"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed local mock data for edge development.")
    parser.add_argument("--sqlite-path", default=str(DEFAULT_SQLITE_PATH))
    parser.add_argument("--embeddings-dir", default=str(DEFAULT_EMBEDDINGS_DIR))
    parser.add_argument("--redis-host", default="localhost")
    parser.add_argument("--redis-port", type=int, default=6379)
    parser.add_argument("--zone-info", default="America/Fortaleza")
    parser.add_argument("--lesson-date", default="")
    parser.add_argument("--skip-redis", action="store_true")
    return parser.parse_args()


def load_schema() -> str:
    edge_app_path = str(EDGE_APP_PATH)
    if edge_app_path in sys.path:
        sys.path.remove(edge_app_path)
    sys.path.insert(0, edge_app_path)
    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]

    from app.db import SCHEMA

    return SCHEMA


def connect(sqlite_path: Path) -> sqlite3.Connection:
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    if sqlite_path.exists() and not os.access(sqlite_path, os.W_OK):
        raise PermissionError(
            f"SQLite file is not writable: {sqlite_path}. "
            "Fix ownership with: sudo chown -R $USER:$USER data/edge"
        )
    if not os.access(sqlite_path.parent, os.W_OK):
        raise PermissionError(
            f"SQLite directory is not writable: {sqlite_path.parent}. "
            "Fix ownership with: sudo chown -R $USER:$USER data/edge"
        )

    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(load_schema())
    return conn


def encode_embedding(embedding: np.ndarray) -> bytes:
    embedding = np.asarray(embedding, dtype=np.float32)
    return msgpack.packb(
        {
            "dtype": "float32",
            "shape": list(embedding.shape),
            "data": embedding.tobytes(),
        },
        use_bin_type=True,
    )


def format_student_name(student_id: str) -> str:
    return " ".join(part.capitalize() for part in student_id.split("_"))


def lesson_window(zone_info: str, lesson_date: str) -> tuple[str, str]:
    tz = ZoneInfo(zone_info)
    if lesson_date:
        base_date = datetime.fromisoformat(lesson_date).date()
    else:
        base_date = datetime.now(tz).date()

    starts_at = datetime.combine(base_date, time(8, 20), tzinfo=tz)
    ends_at = datetime.combine(base_date, time(10, 10), tzinfo=tz)
    return starts_at.isoformat(), ends_at.isoformat()


def iter_students(embeddings_dir: Path) -> list[Path]:
    return sorted(path for path in embeddings_dir.iterdir() if path.is_dir())


def seed_sqlite(
    conn: sqlite3.Connection,
    embeddings_dir: Path,
    zone_info: str,
    lesson_date: str,
) -> dict[str, int]:
    starts_at, ends_at = lesson_window(zone_info, lesson_date)
    students = iter_students(embeddings_dir)
    imported_embeddings = 0

    with conn:
        conn.execute(
            """
            INSERT INTO locales (id, name)
            VALUES (?, ?)
            ON CONFLICT(id) DO UPDATE SET name = excluded.name
            """,
            (LOCALE_ID, LOCALE_ID),
        )
        conn.execute(
            """
            INSERT INTO devices (id, locale_id, active)
            VALUES (?, ?, 1)
            ON CONFLICT(id) DO UPDATE SET
              locale_id = excluded.locale_id,
              active = excluded.active
            """,
            (DEVICE_ID, LOCALE_ID),
        )
        conn.execute(
            """
            INSERT INTO lessons (id, name, locale_id, starts_at, ends_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              name = excluded.name,
              locale_id = excluded.locale_id,
              starts_at = excluded.starts_at,
              ends_at = excluded.ends_at
            """,
            (LESSON_ID, LESSON_NAME, LOCALE_ID, starts_at, ends_at),
        )

        for index, student_dir in enumerate(students, start=1):
            student_id = student_dir.name
            conn.execute(
                """
                INSERT INTO students (id, registration, name, active)
                VALUES (?, ?, ?, 1)
                ON CONFLICT(id) DO UPDATE SET
                  registration = excluded.registration,
                  name = excluded.name,
                  active = excluded.active
                """,
                (
                    student_id,
                    f"MOCK{index:04d}",
                    format_student_name(student_id),
                ),
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO enrollments (lesson_id, student_id)
                VALUES (?, ?)
                """,
                (LESSON_ID, student_id),
            )
            conn.execute(
                "DELETE FROM face_embeddings WHERE student_id = ?",
                (student_id,),
            )

            for embedding_file in sorted(student_dir.glob(EMBEDDING_GLOB)):
                embedding_id = f"{student_id}:{embedding_file.stem}"
                embedding = np.load(embedding_file)
                conn.execute(
                    """
                    INSERT INTO face_embeddings (id, student_id, embedding)
                    VALUES (?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                      student_id = excluded.student_id,
                      embedding = excluded.embedding
                    """,
                    (embedding_id, student_id, encode_embedding(embedding)),
                )
                imported_embeddings += 1

    return {
        "students": len(students),
        "embeddings": imported_embeddings,
    }


def rebuild_redis_cache(conn: sqlite3.Connection, client: redis.Redis) -> None:
    enrollment_rows = conn.execute(
        "SELECT lesson_id, student_id FROM enrollments"
    ).fetchall()
    embedding_rows = conn.execute(
        """
        SELECT face_embeddings.id, face_embeddings.student_id, face_embeddings.embedding
        FROM face_embeddings
        JOIN students ON students.id = face_embeddings.student_id
        WHERE students.active = 1
        """
    ).fetchall()

    lesson_students: dict[str, list[str]] = {}
    for row in enrollment_rows:
        lesson_students.setdefault(row["lesson_id"], []).append(row["student_id"])

    embedding_records = {
        row["id"]: msgpack.packb(
            {
                "studentId": row["student_id"],
                "embedding": row["embedding"],
            },
            use_bin_type=True,
        )
        for row in embedding_rows
    }

    pipe = client.pipeline()
    for key in client.scan_iter("lesson:*:students"):
        pipe.delete(key)
    pipe.delete("face:embeddings")

    for lesson_id, student_ids in lesson_students.items():
        if student_ids:
            pipe.sadd(f"lesson:{lesson_id}:students", *student_ids)
    if embedding_records:
        pipe.hset("face:embeddings", mapping=embedding_records)

    pipe.execute()


def main() -> None:
    args = parse_args()
    sqlite_path = Path(args.sqlite_path).expanduser().resolve()
    embeddings_dir = Path(args.embeddings_dir).expanduser().resolve()

    if not embeddings_dir.exists():
        raise FileNotFoundError(f"embeddings dir not found: {embeddings_dir}")

    conn = connect(sqlite_path)
    try:
        stats = seed_sqlite(conn, embeddings_dir, args.zone_info, args.lesson_date)
        if not args.skip_redis:
            client = redis.Redis(
                host=args.redis_host,
                port=args.redis_port,
                decode_responses=False,
            )
            rebuild_redis_cache(conn, client)
    finally:
        conn.close()

    print(
        "mock seed complete "
        f"sqlite={sqlite_path} "
        f"students={stats['students']} "
        f"embeddings={stats['embeddings']} "
        f"redis={'skipped' if args.skip_redis else f'{args.redis_host}:{args.redis_port}'}"
    )


if __name__ == "__main__":
    main()
