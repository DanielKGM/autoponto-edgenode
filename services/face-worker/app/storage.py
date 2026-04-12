import logging
import os
import pickle

import msgpack
import numpy as np
import redis

logger = logging.getLogger(__name__)

REDIS_HOST = os.getenv("REDIS_HOST")
REDIS_PORT = int(os.getenv("REDIS_PORT"))

QUEUE_KEY = "queue:frames"
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

    def load_all_embeddings(self) -> dict[str, np.ndarray]:
        raw = self.redis.hgetall(EMBEDDINGS_KEY)

        result = {}
        for student_id, emb_blob in raw.items():
            result[student_id.decode("utf-8")] = pickle.loads(emb_blob)

        logger.info("loaded %d embeddings from redis", len(result))
        return result

    def save_embedding(self, student_id: str, embedding: np.ndarray):
        self.redis.hset(EMBEDDINGS_KEY, student_id, pickle.dumps(embedding))
