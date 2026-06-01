import importlib
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


def load_edge_app(tmp_path: Path, monkeypatch):
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
    repository = importlib.import_module("app.repository")
    db.init_db()
    return db, repository


def seed_context(db, starts_at: datetime, ends_at: datetime) -> None:
    with db.transaction() as conn:
        conn.execute("INSERT INTO locales (id, name) VALUES ('room-1', 'Sala 1')")
        conn.execute(
            "INSERT INTO devices (id, locale_id, active) VALUES ('dev-1', 'room-1', 1)"
        )
        conn.execute(
            """
            INSERT INTO lessons (id, name, locale_id, starts_at, ends_at)
            VALUES ('lesson-1', 'Estrutura de Dados', 'room-1', ?, ?)
            """,
            (starts_at.isoformat(), ends_at.isoformat()),
        )


def test_context_returns_current_lesson(tmp_path, monkeypatch):
    db, repository = load_edge_app(tmp_path, monkeypatch)
    now = datetime.now(ZoneInfo("America/Fortaleza"))
    seed_context(db, now - timedelta(minutes=5), now + timedelta(minutes=10))

    context = repository.compute_context_for_device("dev-1")

    assert context.lesson_name == "Estrutura de Dados"
    assert context.lesson_id == "lesson-1"
    assert context.ms_remaining > 0
    assert context.ms_for_next == 0


def test_context_returns_no_lesson_for_unknown_device(tmp_path, monkeypatch):
    db, repository = load_edge_app(tmp_path, monkeypatch)
    now = datetime.now(ZoneInfo("America/Fortaleza"))
    seed_context(db, now - timedelta(minutes=5), now + timedelta(minutes=10))

    context = repository.compute_context_for_device("missing")

    assert context.lesson_name == ""
    assert context.ms_remaining == 0
    assert context.ms_for_next == 0
