import sys
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))


@pytest.fixture(autouse=True)
def sqlite_test_db(tmp_path, monkeypatch):
    from app import db
    from app import sync

    db.configure_database(tmp_path / "edge-test.db")
    db.init_db()
    monkeypatch.setattr(sync, "rebuild_runtime_cache", lambda: None)
    yield
    db.engine.dispose()
