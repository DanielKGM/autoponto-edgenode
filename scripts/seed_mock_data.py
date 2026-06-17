from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import msgpack
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
EDGE_APP_PATH = ROOT / "services" / "edge-app"

DEFAULT_SQLITE_PATH = ROOT / "data" / "db" / "db.sql"
DEFAULT_EMBEDDINGS_DIR = ROOT / "embeddings"

LOCALE_ID = "LABESE"
DEVICE_ID = "9084CED6CDC0"
LESSON_ID = "ambiental"
LESSON_NAME = "AMBIENTAL"
EMBEDDING_FILE = "front_normal.npy"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed local mock students and face embeddings.")
    parser.add_argument("--sqlite-path", default=str(DEFAULT_SQLITE_PATH))
    parser.add_argument("--embeddings-dir", default=str(DEFAULT_EMBEDDINGS_DIR))
    parser.add_argument("--redis-host", default="localhost")
    parser.add_argument("--redis-port", type=int, default=6379)
    parser.add_argument("--zone-info", default=os.getenv("ZONE_INFO", "America/Fortaleza"))
    parser.add_argument("--lesson-date", default="")
    parser.add_argument("--skip-redis", action="store_true")
    return parser.parse_args()


def load_edge_app(sqlite_path: Path, redis_host: str, redis_port: int):
    os.environ["SQLITE_PATH"] = str(sqlite_path)
    os.environ["REDIS_HOST"] = redis_host
    os.environ["REDIS_PORT"] = str(redis_port)

    edge_app_path = str(EDGE_APP_PATH)
    if edge_app_path not in sys.path:
        sys.path.insert(0, edge_app_path)

    for module_name in list(sys.modules):
        if module_name == "app" or module_name.startswith("app."):
            del sys.modules[module_name]

    from app.db import connect, init_db, transaction
    from app.repository import rebuild_runtime_cache

    return connect, init_db, transaction, rebuild_runtime_cache


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


def student_name(student_id: str) -> str:
    return " ".join(part.capitalize() for part in student_id.split("_"))


def lesson_window(zone_info: str, lesson_date: str = "") -> tuple[str, str]:
    tz = ZoneInfo(zone_info)
    base_date = (
        datetime.fromisoformat(lesson_date).date()
        if lesson_date
        else datetime.now(tz).date()
    )
    starts_at = datetime.combine(base_date, time.min, tzinfo=tz)
    ends_at = starts_at + timedelta(days=1)
    return starts_at.isoformat(), ends_at.isoformat()


def front_embedding_files(embeddings_dir: Path) -> list[Path]:
    return sorted(
        path
        for path in embeddings_dir.glob(f"*/{EMBEDDING_FILE}")
        if path.is_file()
    )


def seed_sqlite(
    sqlite_path: Path,
    embeddings_dir: Path,
    zone_info: str,
    lesson_date: str,
) -> dict[str, int]:
    connect, init_db, transaction, _ = load_edge_app(sqlite_path, "localhost", 6379)
    init_db()

    embedding_files = front_embedding_files(embeddings_dir)
    if not embedding_files:
        raise FileNotFoundError(f"no {EMBEDDING_FILE} files found in {embeddings_dir}")

    starts_at, ends_at = lesson_window(zone_info, lesson_date)
    student_ids = [path.parent.name for path in embedding_files]

    with transaction() as conn:
        previous_rows = conn.execute(
            "SELECT student_id FROM enrollments WHERE lesson_id = ?",
            (LESSON_ID,),
        ).fetchall()
        seeded_student_ids = sorted(
            {row["student_id"] for row in previous_rows} | set(student_ids)
        )

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

        for index, embedding_file in enumerate(embedding_files, start=1):
            student_id = embedding_file.parent.name
            conn.execute(
                """
                INSERT INTO students (id, registration, name, active)
                VALUES (?, ?, ?, 1)
                ON CONFLICT(id) DO UPDATE SET
                  registration = excluded.registration,
                  name = excluded.name,
                  active = excluded.active
                """,
                (student_id, f"MOCK{index:04d}", student_name(student_id)),
            )

        conn.execute("DELETE FROM enrollments WHERE lesson_id = ?", (LESSON_ID,))
        for student_id in student_ids:
            conn.execute(
                "INSERT OR IGNORE INTO enrollments (lesson_id, student_id) VALUES (?, ?)",
                (LESSON_ID, student_id),
            )

        for student_id in seeded_student_ids:
            conn.execute("DELETE FROM face_embeddings WHERE student_id = ?", (student_id,))

        for embedding_file in embedding_files:
            student_id = embedding_file.parent.name
            embedding_id = f"{student_id}:front_normal"
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

    with connect() as conn:
        total_embeddings = conn.execute(
            "SELECT COUNT(*) AS total FROM face_embeddings"
        ).fetchone()["total"]

    return {
        "students": len(student_ids),
        "embeddings": len(embedding_files),
        "db_embeddings": total_embeddings,
    }


def main() -> None:
    args = parse_args()
    sqlite_path = Path(args.sqlite_path).expanduser().resolve()
    embeddings_dir = Path(args.embeddings_dir).expanduser().resolve()

    stats = seed_sqlite(sqlite_path, embeddings_dir, args.zone_info, args.lesson_date)

    if not args.skip_redis:
        _, _, _, rebuild_runtime_cache = load_edge_app(
            sqlite_path,
            args.redis_host,
            args.redis_port,
        )
        rebuild_runtime_cache()

    print(
        "mock seed complete "
        f"sqlite={sqlite_path} "
        f"students={stats['students']} "
        f"front_embeddings={stats['embeddings']} "
        f"db_embeddings={stats['db_embeddings']} "
        f"redis={'skipped' if args.skip_redis else f'{args.redis_host}:{args.redis_port}'}"
    )


if __name__ == "__main__":
    main()
