import importlib
import msgpack
import sys
from pathlib import Path


def load_redis_store(monkeypatch):
    monkeypatch.setenv("REDIS_HOST", "localhost")
    monkeypatch.setenv("REDIS_PORT", "6379")
    monkeypatch.setenv("MAX_FRAME_QUEUE", "100")

    service_path = str(Path(__file__).resolve().parents[1] / "services" / "edge-app")
    if service_path in sys.path:
        sys.path.remove(service_path)
    sys.path.insert(0, service_path)

    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]

    return importlib.import_module("app.redis_store")


class FakeRedis:
    def __init__(self):
        self.items = []

    def rpush(self, key, value):
        self.items.append((key, value))

    def llen(self, key):
        return len(self.items)


def test_frame_queue_payload_uses_lesson_without_class(monkeypatch):
    redis_store = load_redis_store(monkeypatch)
    fake = FakeRedis()
    monkeypatch.setattr(redis_store, "get_redis", lambda decode_responses=False: fake)

    queue_len = redis_store.enqueue_frame("dev-1", "room-1", "lesson-1", b"jpeg")

    assert queue_len == 1
    _, raw = fake.items[0]
    payload = msgpack.unpackb(raw, raw=False)
    assert payload["lessonId"] == "lesson-1"
    assert "classId" not in payload
