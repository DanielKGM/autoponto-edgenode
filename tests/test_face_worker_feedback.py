import importlib
import sys
from pathlib import Path


def load_face_worker():
    import os

    os.environ.setdefault("MQTT_HOST", "localhost")
    os.environ.setdefault("MQTT_PORT", "1883")
    os.environ.setdefault("MQTT_USER", "service")
    os.environ.setdefault("MQTT_PASS", "replace")
    os.environ.setdefault("REDIS_HOST", "localhost")
    os.environ.setdefault("REDIS_PORT", "6379")
    service_path = str(Path(__file__).resolve().parents[1] / "services" / "face-worker")
    if service_path in sys.path:
        sys.path.remove(service_path)
    sys.path.insert(0, service_path)

    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]

    return importlib.import_module("app.main")


class FakeStorage:
    def __init__(self, item):
        self.item = item
        self.enqueued = []
        self.calls = 0

    def pop_frame_blocking(self):
        self.calls += 1
        if self.calls > 1:
            raise KeyboardInterrupt()
        return self.item

    def enqueue_attendance_event(self, **kwargs):
        self.enqueued.append(kwargs)


class FakeRecognition:
    def __init__(self, result):
        self.result = result

    def recognize(self, frame_bytes, lesson_id):
        return self.result


def test_worker_does_not_publish_mqtt_on_failed_recognition(monkeypatch):
    main = load_face_worker()
    storage = FakeStorage(
        {
            "deviceId": "dev-1",
            "lessonId": "lesson-1",
            "frame": b"jpeg",
        }
    )
    published = []

    monkeypatch.setattr(main, "Storage", lambda: storage)
    monkeypatch.setattr(main, "RecognitionService", lambda storage: FakeRecognition({"ok": False, "reason": "no_face"}))
    monkeypatch.setattr(main, "build_mqtt_client", lambda: object())
    monkeypatch.setattr(main, "publish_result", lambda client, device_id, payload: published.append(payload))

    try:
        main.main()
    except KeyboardInterrupt:
        pass

    assert published == []
    assert storage.enqueued == []


def test_worker_publishes_positive_feedback_and_enqueues_attendance(monkeypatch):
    main = load_face_worker()
    storage = FakeStorage(
        {
            "deviceId": "dev-1",
            "lessonId": "lesson-1",
            "frame": b"jpeg",
        }
    )
    published = []

    monkeypatch.setattr(main, "Storage", lambda: storage)
    monkeypatch.setattr(
        main,
        "RecognitionService",
        lambda storage: FakeRecognition({"ok": True, "studentId": "student-1", "score": 0.9}),
    )
    monkeypatch.setattr(main, "build_mqtt_client", lambda: object())
    monkeypatch.setattr(main, "publish_result", lambda client, device_id, payload: published.append(payload))

    try:
        main.main()
    except KeyboardInterrupt:
        pass

    assert published == [{"auth": True, "studentId": "student-1", "msg": "student-1"}]
    assert storage.enqueued == [
        {
            "device_id": "dev-1",
            "lesson_id": "lesson-1",
            "student_id": "student-1",
            "score": 0.9,
        }
    ]
