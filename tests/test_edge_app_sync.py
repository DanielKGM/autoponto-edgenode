import importlib
import sys
from pathlib import Path


def load_edge_modules(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "edge.db"))
    monkeypatch.setenv("ZONE_INFO", "America/Fortaleza")
    monkeypatch.setenv("REDIS_HOST", "localhost")
    monkeypatch.setenv("REDIS_PORT", "6379")

    service_path = str(Path(__file__).resolve().parents[1] / "services" / "edge-app")
    if service_path in sys.path:
        sys.path.remove(service_path)
    sys.path.insert(0, service_path)

    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]

    db = importlib.import_module("app.db")
    sync = importlib.import_module("app.sync")
    db.init_db()
    monkeypatch.setattr(sync, "rebuild_runtime_cache", lambda: None)
    return db, sync


def test_sync_applies_new_model_and_deletions(tmp_path, monkeypatch):
    db, sync = load_edge_modules(tmp_path, monkeypatch)

    sync.apply_pull_payload(
        {
            "data": {
                "locales": [{"id": "room-1", "name": "Sala 1"}],
                "devices": [{"id": "dev-1", "locale_id": "room-1", "active": True}],
                "lessons": [
                    {
                        "id": "lesson-1",
                        "name": "Algoritmos",
                        "locale_id": "room-1",
                        "starts_at": "2026-01-01T08:00:00-03:00",
                        "ends_at": "2026-01-01T10:00:00-03:00",
                    }
                ],
                "students": [
                    {
                        "id": "student-1",
                        "registration": "20260001",
                        "name": "Ana",
                        "active": True,
                    }
                ],
                "enrollments": [{"lesson_id": "lesson-1", "student_id": "student-1"}],
                "face_embeddings": [
                    {"id": "emb-1", "student_id": "student-1", "embedding": [0.1, 0.2]},
                    {"id": "emb-2", "student_id": "student-1", "embedding": [0.3, 0.4]},
                ],
            },
            "cursors": {"students": "cursor-1"},
        }
    )

    with db.connect() as conn:
        student = conn.execute("SELECT registration FROM students WHERE id = 'student-1'").fetchone()
        enrollments = conn.execute("SELECT COUNT(*) AS total FROM enrollments").fetchone()
        embeddings = conn.execute("SELECT COUNT(*) AS total FROM face_embeddings").fetchone()
        cursor = conn.execute("SELECT cursor FROM sync_state WHERE entity = 'students'").fetchone()

    assert student["registration"] == "20260001"
    assert enrollments["total"] == 1
    assert embeddings["total"] == 2
    assert cursor["cursor"] == "cursor-1"

    sync.apply_pull_payload(
        {
            "deleted": {
                "enrollments": [{"lesson_id": "lesson-1", "student_id": "student-1"}],
                "face_embeddings": ["emb-1"],
            }
        }
    )

    with db.connect() as conn:
        enrollments = conn.execute("SELECT COUNT(*) AS total FROM enrollments").fetchone()
        embeddings = conn.execute("SELECT COUNT(*) AS total FROM face_embeddings").fetchone()

    assert enrollments["total"] == 0
    assert embeddings["total"] == 1
