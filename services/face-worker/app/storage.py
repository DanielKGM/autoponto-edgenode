import logging
import os
from datetime import datetime, timezone
from uuid import uuid4

import msgpack
import numpy as np
import redis

logger = logging.getLogger(__name__)

REDIS_HOST = os.getenv("REDIS_HOST")
REDIS_PORT = int(os.getenv("REDIS_PORT"))

QUEUE_KEY = "queue:frames"
ATTENDANCE_QUEUE_KEY = "queue:attendance_events"
EMBEDDINGS_KEY = "face:embeddings"


class Storage:
    def __init__(self):
        self.redis = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            decode_responses=False,
        )

    def pop_frame_blocking(self) -> dict:
        _, item_raw = self.redis.blpop(QUEUE_KEY, timeout=0)
        return msgpack.unpackb(item_raw, raw=False)

    def load_embeddings_for_lesson(self, lesson_id: str) -> list[tuple[str, str, np.ndarray]]:
        student_ids = self.redis.smembers(f"lesson:{lesson_id}:students")
        if not student_ids:
            logger.info("no eligible students for lesson=%s", lesson_id)
            return []

        eligible = {student_id.decode("utf-8") for student_id in student_ids}
        raw = self.redis.hgetall(EMBEDDINGS_KEY)

        result = []
        for embedding_id, emb_blob in raw.items():
            if not emb_blob:
                continue
            if isinstance(embedding_id, bytes):
                embedding_id = embedding_id.decode("utf-8")
            student_id, embedding = self._decode_embedding_record(emb_blob)
            if student_id in eligible:
                result.append((embedding_id, student_id, embedding))

        logger.info("loaded %d eligible embeddings for lesson=%s", len(result), lesson_id)
        return result

    def save_embedding(self, student_id: str, embedding: np.ndarray, embedding_id: str | None = None):
        payload = msgpack.packb(
            {
                "studentId": student_id,
                "embedding": self._encode_embedding(embedding),
            },
            use_bin_type=True,
        )
        self.redis.hset(EMBEDDINGS_KEY, embedding_id or student_id, payload)

    def enqueue_attendance_event(
        self,
        device_id: str,
        lesson_id: str,
        student_id: str,
        score: float,
    ) -> None:
        payload = {
            "eventId": str(uuid4()),
            "deviceId": device_id,
            "lessonId": lesson_id,
            "studentId": student_id,
            "score": score,
            "recognizedAt": datetime.now(timezone.utc).isoformat(),
        }
        self.redis.rpush(ATTENDANCE_QUEUE_KEY, msgpack.packb(payload, use_bin_type=True))

    def _decode_embedding(self, blob: bytes) -> np.ndarray:
        payload = msgpack.unpackb(blob, raw=False)
        if isinstance(payload.get("data"), list):
            return np.asarray(payload["data"], dtype=np.float32).reshape(payload["shape"])
        return np.frombuffer(payload["data"], dtype=np.float32).reshape(payload["shape"])

    def _decode_embedding_record(self, blob: bytes) -> tuple[str, np.ndarray]:
        payload = msgpack.unpackb(blob, raw=False)
        return payload["studentId"], self._decode_embedding(payload["embedding"])

    def _encode_embedding(self, embedding: np.ndarray) -> bytes:
        embedding = np.asarray(embedding, dtype=np.float32)
        return msgpack.packb(
            {
                "dtype": "float32",
                "shape": list(embedding.shape),
                "data": embedding.tobytes(),
            },
            use_bin_type=True,
        )
