from collections.abc import Iterator
from contextlib import contextmanager
import sqlite3

from app.config import SQLITE_PATH


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS locales (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS devices (
  id TEXT PRIMARY KEY,
  locale_id TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 1,
  status TEXT,
  FOREIGN KEY (locale_id) REFERENCES locales(id)
);

CREATE TABLE IF NOT EXISTS lessons (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  locale_id TEXT NOT NULL,
  starts_at TEXT NOT NULL,
  ends_at TEXT NOT NULL,
  status TEXT,
  FOREIGN KEY (locale_id) REFERENCES locales(id)
);

CREATE TABLE IF NOT EXISTS students (
  id TEXT PRIMARY KEY,
  registration TEXT NOT NULL,
  name TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS enrollments (
  lesson_id TEXT NOT NULL,
  student_id TEXT NOT NULL,
  PRIMARY KEY (lesson_id, student_id),
  FOREIGN KEY (lesson_id) REFERENCES lessons(id) ON DELETE CASCADE,
  FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS face_embeddings (
  id TEXT PRIMARY KEY,
  student_id TEXT NOT NULL,
  embedding BLOB NOT NULL,
  FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS attendance_events (
  id TEXT PRIMARY KEY,
  student_id TEXT NOT NULL,
  lesson_id TEXT NOT NULL,
  device_id TEXT NOT NULL,
  recognized_at TEXT NOT NULL,
  score REAL NOT NULL,
  sync_status TEXT NOT NULL DEFAULT 'pending',
  UNIQUE(student_id, lesson_id)
);

CREATE TABLE IF NOT EXISTS sync_state (
  entity TEXT PRIMARY KEY,
  cursor TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_lessons_locale_time ON lessons(locale_id, starts_at, ends_at);
CREATE INDEX IF NOT EXISTS idx_embeddings_student ON face_embeddings(student_id);
CREATE INDEX IF NOT EXISTS idx_attendance_sync ON attendance_events(sync_status);
CREATE UNIQUE INDEX IF NOT EXISTS idx_attendance_student_lesson
  ON attendance_events(student_id, lesson_id);
"""


def _ensure_column(
    conn: sqlite3.Connection,
    table: str,
    column: str,
    definition: str,
) -> None:
    columns = {
        row["name"]
        for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
    }
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def init_db() -> None:
    SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        conn.executescript(SCHEMA)
        _ensure_column(conn, "devices", "status", "TEXT")
        _ensure_column(conn, "lessons", "status", "TEXT")


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def transaction() -> Iterator[sqlite3.Connection]:
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
