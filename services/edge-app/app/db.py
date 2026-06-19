from collections.abc import Iterator
from contextlib import contextmanager
import sqlite3

from app.config import SQLITE_PATH


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS salas (
  id TEXT PRIMARY KEY,
  nome TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS dispositivos (
  id TEXT PRIMARY KEY,
  sala_id TEXT NOT NULL,
  ativo INTEGER NOT NULL DEFAULT 1,
  status TEXT,
  interscity_uuid TEXT,
  FOREIGN KEY (sala_id) REFERENCES salas(id)
);

CREATE TABLE IF NOT EXISTS aulas (
  id TEXT PRIMARY KEY,
  nome TEXT NOT NULL,
  sala_id TEXT NOT NULL,
  inicio TEXT NOT NULL,
  fim TEXT NOT NULL,
  status TEXT,
  FOREIGN KEY (sala_id) REFERENCES salas(id)
);

CREATE TABLE IF NOT EXISTS alunos (
  id TEXT PRIMARY KEY,
  matricula TEXT NOT NULL,
  nome TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS matriculas_aula (
  aula_id TEXT NOT NULL,
  aluno_id TEXT NOT NULL,
  PRIMARY KEY (aula_id, aluno_id),
  FOREIGN KEY (aula_id) REFERENCES aulas(id) ON DELETE CASCADE,
  FOREIGN KEY (aluno_id) REFERENCES alunos(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS embeddings_faciais (
  id TEXT PRIMARY KEY,
  aluno_id TEXT NOT NULL,
  vetor BLOB NOT NULL,
  FOREIGN KEY (aluno_id) REFERENCES alunos(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS eventos_presenca (
  id TEXT PRIMARY KEY,
  aluno_id TEXT NOT NULL,
  aula_id TEXT NOT NULL,
  dispositivo_id TEXT NOT NULL,
  reconhecido_em TEXT NOT NULL,
  score REAL NOT NULL,
  sync_status TEXT NOT NULL DEFAULT 'pending',
  UNIQUE(aluno_id, aula_id)
);

CREATE TABLE IF NOT EXISTS sync_state (
  entity TEXT PRIMARY KEY,
  cursor TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_aulas_sala_tempo ON aulas(sala_id, inicio, fim);
CREATE INDEX IF NOT EXISTS idx_embeddings_aluno ON embeddings_faciais(aluno_id);
CREATE INDEX IF NOT EXISTS idx_eventos_presenca_sync ON eventos_presenca(sync_status);
CREATE UNIQUE INDEX IF NOT EXISTS idx_eventos_presenca_aluno_aula
  ON eventos_presenca(aluno_id, aula_id);
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
        _ensure_column(conn, "dispositivos", "interscity_uuid", "TEXT")


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
