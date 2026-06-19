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
ATTENDANCE_QUEUE_KEY = "queue:eventos_presenca"
EMBEDDINGS_KEY = "face:embeddings"


class Storage:
    def __init__(self):
        self.redis = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            decode_responses=False,
            socket_connect_timeout=5,
            socket_timeout=10,
            health_check_interval=30,
        )

    def pop_frame_blocking(self) -> dict | None:
        item = self.redis.blpop(QUEUE_KEY, timeout=5)
        if item is None:
            return None
        _, item_raw = item
        return msgpack.unpackb(item_raw, raw=False)

    def load_embeddings_for_aula(
        self, aula_id: str
    ) -> list[tuple[str, str, np.ndarray]]:
        aluno_ids = self.redis.smembers(f"aula:{aula_id}:alunos")
        if not aluno_ids:
            logger.info("no eligible alunos for aula=%s", aula_id)
            return []

        eligible = {aluno_id.decode("utf-8") for aluno_id in aluno_ids}
        raw = self.redis.hgetall(EMBEDDINGS_KEY)

        result = []
        for embedding_id, emb_blob in raw.items():
            if not emb_blob:
                continue
            if isinstance(embedding_id, bytes):
                embedding_id = embedding_id.decode("utf-8")
            aluno_id, embedding = self._decode_embedding_record(emb_blob)
            if aluno_id in eligible:
                result.append((embedding_id, aluno_id, embedding))

        logger.info(
            "loaded %d eligible embeddings for aula=%s", len(result), aula_id
        )
        return result

    def enqueue_attendance_event(
        self,
        dispositivo_id: str,
        aula_id: str,
        aluno_id: str,
        score: float,
    ) -> None:
        payload = {
            "eventId": str(uuid4()),
            "dispositivoId": dispositivo_id,
            "aulaId": aula_id,
            "alunoId": aluno_id,
            "score": score,
            "recognizedAt": datetime.now(timezone.utc).isoformat(),
        }
        self.redis.rpush(
            ATTENDANCE_QUEUE_KEY, msgpack.packb(payload, use_bin_type=True)
        )

    def _decode_embedding_record(self, blob: bytes) -> tuple[str, np.ndarray]:
        record = msgpack.unpackb(blob, raw=False)
        embedding_payload = msgpack.unpackb(record["embedding"], raw=False)
        data = embedding_payload["data"]
        if isinstance(data, list):
            embedding = np.asarray(data, dtype=np.float32)
        else:
            embedding = np.frombuffer(data, dtype=np.float32)
        return record["alunoId"], embedding.reshape(embedding_payload["shape"])
