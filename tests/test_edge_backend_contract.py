from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path


def load_edge_modules(monkeypatch, tmp_path):
    app_path = Path(__file__).resolve().parents[1] / "services" / "edge-app"
    monkeypatch.syspath_prepend(str(app_path))
    for module_name in list(sys.modules):
        if module_name == "app" or module_name.startswith("app."):
            sys.modules.pop(module_name)

    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "db.sql"))
    monkeypatch.setenv("MAIN_API_URL", "http://backend:8000/api")
    monkeypatch.setenv("MAIN_API_TOKEN", "node-token")
    monkeypatch.setenv("NODE_ID", "NO-CCET-01")

    from app import db, redis_store, sync

    return db, redis_store, sync


def test_sync_headers_use_node_token(monkeypatch, tmp_path):
    _, _, sync = load_edge_modules(monkeypatch, tmp_path)

    assert sync._headers()["Authorization"] == "NodeToken node-token"


def test_apply_pull_payload_stores_device_and_lesson_status(monkeypatch, tmp_path):
    db, _, sync = load_edge_modules(monkeypatch, tmp_path)
    db.init_db()
    monkeypatch.setattr(sync, "rebuild_runtime_cache", lambda: None)

    sync.apply_pull_payload(
        {
            "data": {
                "locales": [{"id": "LABESE", "name": "LABESE"}],
                "devices": [
                    {
                        "id": "9084CED6CDC0",
                        "locale_id": "LABESE",
                        "active": True,
                        "status": "idle",
                    }
                ],
                "lessons": [
                    {
                        "id": "ambiental",
                        "name": "AMBIENTAL",
                        "locale_id": "LABESE",
                        "starts_at": "2026-06-17T08:20:00-03:00",
                        "ends_at": "2026-06-17T10:10:00-03:00",
                        "status": "PLANEJADA",
                    }
                ],
            },
            "deleted": {},
            "cursors": {"devices": "cursor-devices"},
        }
    )

    with db.connect() as conn:
        device = conn.execute("SELECT status FROM devices").fetchone()
        lesson = conn.execute("SELECT status FROM lessons").fetchone()
        cursor = conn.execute(
            "SELECT cursor FROM sync_state WHERE entity = 'devices'"
        ).fetchone()

    assert device["status"] == "idle"
    assert lesson["status"] == "PLANEJADA"
    assert cursor["cursor"] == "cursor-devices"


def test_iter_device_statuses_returns_backend_payload(monkeypatch, tmp_path):
    _, redis_store, _ = load_edge_modules(monkeypatch, tmp_path)

    class FakeRedis:
        def __init__(self):
            self.data = {
                "device:esp-1:status": json.dumps(
                    {
                        "deviceId": "esp-1",
                        "state": "working",
                        "receivedAt": "2026-06-17T11:30:00+00:00",
                    }
                ),
                "device:bad:status": "{",
                "device:empty:status": "{}",
            }

        def scan_iter(self, pattern):
            return iter(self.data)

        def get(self, key):
            return self.data[key]

    monkeypatch.setattr(redis_store, "get_redis", lambda decode_responses=False: FakeRedis())

    assert redis_store.iter_device_statuses() == [
        {
            "device_id": "esp-1",
            "status": "working",
            "reported_at": "2026-06-17T11:30:00+00:00",
        }
    ]


def test_push_device_statuses_posts_backend_contract(monkeypatch, tmp_path):
    _, _, sync = load_edge_modules(monkeypatch, tmp_path)
    status_payload = [
        {
            "device_id": "esp-1",
            "status": "idle",
            "reported_at": "2026-06-17T11:30:00+00:00",
        }
    ]
    monkeypatch.setattr(sync, "iter_device_statuses", lambda: status_payload)

    class Response:
        def raise_for_status(self):
            return None

    class FakeClient:
        def __init__(self):
            self.calls = []

        async def post(self, url, headers, json):
            self.calls.append((url, headers, json))
            return Response()

    client = FakeClient()
    asyncio.run(sync._push_device_statuses(client))

    assert client.calls == [
        (
            "http://backend:8000/api/edge/devices/status",
            {"X-Node-Id": "NO-CCET-01", "Authorization": "NodeToken node-token"},
            {"node_id": "NO-CCET-01", "devices": status_payload},
        )
    ]
