import os
import pickle
import redis
import numpy as np

REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))

EMBEDDINGS_KEY = "face:embeddings"


def get_redis() -> redis.Redis:
    return redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        decode_responses=False,
    )


def load_all_embeddings() -> dict[str, np.ndarray]:
    r = get_redis()
    raw = r.hgetall(EMBEDDINGS_KEY)

    result = {}
    for student_id, emb_blob in raw.items():
        result[student_id.decode("utf-8")] = pickle.loads(emb_blob)

    return result


def save_embedding(student_id: str, embedding: np.ndarray):
    r = get_redis()
    r.hset(EMBEDDINGS_KEY, student_id, pickle.dumps(embedding))