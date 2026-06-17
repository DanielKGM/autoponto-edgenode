from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

import numpy as np


def load_seed_module():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "seed_mock_data.py"
    spec = importlib.util.spec_from_file_location("seed_mock_data", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def write_embedding(path: Path, values: list[float]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    np.save(path, np.asarray([values], dtype=np.float32))


def test_seed_imports_only_front_normal_embeddings(tmp_path):
    seed = load_seed_module()
    embeddings_dir = tmp_path / "embeddings"
    sqlite_path = tmp_path / "db.sql"

    write_embedding(embeddings_dir / "ana_silva" / "front_normal.npy", [0.1, 0.2])
    write_embedding(embeddings_dir / "ana_silva" / "left_normal.npy", [0.3, 0.4])
    write_embedding(embeddings_dir / "ana_silva" / "front_esp_like.npy", [0.5, 0.6])
    write_embedding(embeddings_dir / "bruno_lima" / "front_normal.npy", [0.7, 0.8])
    write_embedding(embeddings_dir / "bruno_lima" / "right_normal.npy", [0.9, 1.0])

    first = seed.seed_sqlite(
        sqlite_path,
        embeddings_dir,
        "America/Fortaleza",
        "2026-06-08",
    )
    second = seed.seed_sqlite(
        sqlite_path,
        embeddings_dir,
        "America/Fortaleza",
        "2026-06-08",
    )

    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row
    try:
        embedding_ids = {
            row["id"]
            for row in conn.execute("SELECT id FROM face_embeddings").fetchall()
        }
        enrollments = {
            row["student_id"]
            for row in conn.execute("SELECT student_id FROM enrollments").fetchall()
        }
        lesson = conn.execute(
            "SELECT starts_at, ends_at FROM lessons WHERE id = 'ambiental'"
        ).fetchone()
    finally:
        conn.close()

    assert first["students"] == 2
    assert first["embeddings"] == 2
    assert second["students"] == 2
    assert second["embeddings"] == 2
    assert embedding_ids == {"ana_silva:front_normal", "bruno_lima:front_normal"}
    assert enrollments == {"ana_silva", "bruno_lima"}
    assert lesson["starts_at"] == "2026-06-08T00:00:00-03:00"
    assert lesson["ends_at"] == "2026-06-09T00:00:00-03:00"
