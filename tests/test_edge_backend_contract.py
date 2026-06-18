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


def test_apply_pull_payload_stores_dispositivo_and_aula_status(monkeypatch, tmp_path):
    db, _, sync = load_edge_modules(monkeypatch, tmp_path)
    db.init_db()
    monkeypatch.setattr(sync, "rebuild_runtime_cache", lambda: None)

    sync.apply_pull_payload(
        {
            "data": {
                "salas": [{"id": "sala-1", "nome": "Sala 1"}],
                "dispositivos": [
                    {
                        "id": "disp-1",
                        "sala_id": "sala-1",
                        "ativo": True,
                        "status": "idle",
                    }
                ],
                "aulas": [
                    {
                        "id": "aula-1",
                        "nome": "Aula 1",
                        "sala_id": "sala-1",
                        "inicio": "2026-06-17T08:20:00-03:00",
                        "fim": "2026-06-17T10:10:00-03:00",
                        "status": "PLANEJADA",
                    }
                ],
            },
            "deleted": {},
            "cursors": {"dispositivos": "cursor-dispositivos"},
        }
    )

    with db.connect() as conn:
        device = conn.execute("SELECT status FROM dispositivos").fetchone()
        aula = conn.execute("SELECT status FROM aulas").fetchone()
        cursor = conn.execute(
            "SELECT cursor FROM sync_state WHERE entity = 'dispositivos'"
        ).fetchone()

    assert device["status"] == "idle"
    assert aula["status"] == "PLANEJADA"
    assert cursor["cursor"] == "cursor-dispositivos"


def test_iter_device_statuses_returns_backend_payload(monkeypatch, tmp_path):
    _, redis_store, _ = load_edge_modules(monkeypatch, tmp_path)

    class FakeRedis:
        def __init__(self):
            self.data = {
                "dispositivo:esp-1:status": json.dumps(
                    {
                        "dispositivoId": "esp-1",
                        "status": "working",
                        "reportadoEm": "2026-06-17T11:30:00+00:00",
                    }
                ),
                "dispositivo:bad:status": "{",
                "dispositivo:empty:status": "{}",
            }

        def scan_iter(self, pattern):
            return iter(self.data)

        def get(self, key):
            return self.data[key]

    monkeypatch.setattr(redis_store, "get_redis", lambda decode_responses=False: FakeRedis())

    assert redis_store.iter_device_statuses() == [
        {
            "dispositivo_id": "esp-1",
            "status": "working",
            "reportado_em": "2026-06-17T11:30:00+00:00",
        }
    ]


def test_push_device_statuses_posts_backend_contract(monkeypatch, tmp_path):
    _, _, sync = load_edge_modules(monkeypatch, tmp_path)
    status_payload = [
        {
            "dispositivo_id": "esp-1",
            "status": "idle",
            "reportado_em": "2026-06-17T11:30:00+00:00",
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
            {"node_id": "NO-CCET-01", "dispositivos": status_payload},
        )
    ]


def test_pending_attendance_uses_referencia_api_fields(monkeypatch, tmp_path):
    db, _, sync = load_edge_modules(monkeypatch, tmp_path)
    db.init_db()

    with db.transaction() as conn:
        conn.execute("INSERT INTO salas (id, nome) VALUES ('sala-1', 'Sala 1')")
        conn.execute(
            """
            INSERT INTO dispositivos (id, sala_id, ativo, status)
            VALUES ('disp-1', 'sala-1', 1, 'idle')
            """
        )
        conn.execute(
            """
            INSERT INTO aulas (id, nome, sala_id, inicio, fim, status)
            VALUES (
              'aula-1',
              'AMBIENTAL',
              'sala-1',
              '2026-06-17T08:20:00-03:00',
              '2026-06-17T10:10:00-03:00',
              'ABERTA'
            )
            """
        )
        conn.execute(
            """
            INSERT INTO alunos (id, matricula, nome, ativo)
            VALUES ('aluno-1', '20260001', 'Daniel Silva', 1)
            """
        )
        conn.execute(
            """
            INSERT INTO eventos_presenca
              (id, aluno_id, aula_id, dispositivo_id, reconhecido_em, score)
            VALUES (
              'evt-1',
              'aluno-1',
              'aula-1',
              'disp-1',
              '2026-06-17T08:42:00-03:00',
              0.72
            )
            """
        )

    assert sync._pending_attendance() == [
        {
            "id": "evt-1",
            "aluno_id": "aluno-1",
            "aula_id": "aula-1",
            "dispositivo_id": "disp-1",
            "reconhecido_em": "2026-06-17T08:42:00-03:00",
            "score": 0.72,
        }
    ]
