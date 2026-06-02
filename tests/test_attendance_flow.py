from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EDGE_APP = ROOT / "services" / "edge-app"


def clear_app_modules() -> None:
    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]


def load_edge_app(tmp_path, monkeypatch):
    clear_app_modules()
    monkeypatch.syspath_prepend(str(EDGE_APP))
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "edge.db"))
    monkeypatch.setenv("ZONE_INFO", "America/Fortaleza")

    db = importlib.import_module("app.db")
    consumer = importlib.import_module("app.attendance_consumer")
    db.init_db()

    with db.transaction() as conn:
        conn.execute("INSERT INTO locales (id, name) VALUES ('LABESE', 'LABESE')")
        conn.execute(
            """
            INSERT INTO devices (id, locale_id, active)
            VALUES ('9084CED6CDC0', 'LABESE', 1)
            """
        )
        conn.execute(
            """
            INSERT INTO lessons (id, name, locale_id, starts_at, ends_at)
            VALUES (
              'ambiental',
              'AMBIENTAL',
              'LABESE',
              '2026-06-02T00:00:00-03:00',
              '2026-06-03T00:00:00-03:00'
            )
            """
        )
        conn.execute(
            """
            INSERT INTO students (id, registration, name, active)
            VALUES ('student-1', 'MOCK0001', 'Daniel Silva Santos', 1)
            """
        )

    return db, consumer


class FakeMqttClient:
    def __init__(self):
        self.published = []

    def publish(self, topic, payload, qos=0, retain=False):
        self.published.append(
            {
                "topic": topic,
                "payload": json.loads(payload),
                "qos": qos,
                "retain": retain,
            }
        )


def test_attendance_is_unique_and_mqtt_uses_first_recognition_time(tmp_path, monkeypatch):
    db, consumer = load_edge_app(tmp_path, monkeypatch)
    mqtt = FakeMqttClient()

    first = consumer.handle_attendance_event(
        {
            "eventId": "event-1",
            "deviceId": "9084CED6CDC0",
            "lessonId": "ambiental",
            "studentId": "student-1",
            "score": 0.72,
            "recognizedAt": "2026-06-02T11:42:00+00:00",
        },
        mqtt,
    )
    second = consumer.handle_attendance_event(
        {
            "eventId": "event-2",
            "deviceId": "9084CED6CDC0",
            "lessonId": "ambiental",
            "studentId": "student-1",
            "score": 0.91,
            "recognizedAt": "2026-06-02T12:10:00+00:00",
        },
        mqtt,
    )

    with db.connect() as conn:
        total = conn.execute("SELECT COUNT(*) AS total FROM attendance_events").fetchone()[
            "total"
        ]

    assert total == 1
    assert first["is_new"] is True
    assert second["is_new"] is False
    assert second["id"] == first["id"]
    assert second["recognized_at"] == "2026-06-02T11:42:00+00:00"

    assert [item["topic"] for item in mqtt.published] == [
        "cmd/9084CED6CDC0",
        "cmd/9084CED6CDC0",
    ]
    assert mqtt.published[0]["payload"]["msg"] == (
        "Daniel Silva - presença registrada às 08:42"
    )
    assert mqtt.published[1]["payload"]["msg"] == (
        "Daniel Silva - presença registrada às 08:42"
    )
    assert mqtt.published[0]["payload"]["alreadyRegistered"] is False
    assert mqtt.published[1]["payload"]["alreadyRegistered"] is True
