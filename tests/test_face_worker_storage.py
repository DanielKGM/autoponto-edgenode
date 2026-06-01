import importlib
import msgpack
import sys
from pathlib import Path

import numpy as np


def load_storage_module(monkeypatch):
    monkeypatch.setenv("REDIS_HOST", "localhost")
    monkeypatch.setenv("REDIS_PORT", "6379")

    service_path = str(Path(__file__).resolve().parents[1] / "services" / "face-worker")
    if service_path in sys.path:
        sys.path.remove(service_path)
    sys.path.insert(0, service_path)

    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]

    return importlib.import_module("app.storage")


class FakeRedis:
    def smembers(self, key):
        assert key == "lesson:lesson-1:students"
        return {b"student-1"}

    def hgetall(self, key):
        assert key == "face:embeddings"
        return {
            b"emb-1": pack_record("student-1", [0.1, 0.2]),
            b"emb-2": pack_record("student-1", [0.3, 0.4]),
            b"emb-3": pack_record("student-2", [0.5, 0.6]),
        }


def pack_record(student_id: str, values: list[float]) -> bytes:
    embedding = np.asarray([values], dtype=np.float32)
    embedding_blob = msgpack.packb(
        {
            "dtype": "float32",
            "shape": list(embedding.shape),
            "data": embedding.tobytes(),
        },
        use_bin_type=True,
    )
    return msgpack.packb(
        {
            "studentId": student_id,
            "embedding": embedding_blob,
        },
        use_bin_type=True,
    )


def test_loads_multiple_embeddings_for_same_student(monkeypatch):
    storage_module = load_storage_module(monkeypatch)
    storage = storage_module.Storage.__new__(storage_module.Storage)
    storage.redis = FakeRedis()

    embeddings = storage.load_embeddings_for_lesson("lesson-1")

    assert [student_id for student_id, _ in embeddings] == ["student-1", "student-1"]
    assert len(embeddings) == 2
