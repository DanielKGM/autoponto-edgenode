import os
import msgpack
import redis

QUEUE_KEY = "queue:frames"

REDIS_HOST = os.getenv("REDIS_HOST")
REDIS_PORT = int(os.getenv("REDIS_PORT"))


def get_redis() -> redis.Redis:
    return redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        decode_responses=False,
    )


def pop_frame_blocking() -> dict:
    r = get_redis()
    _, item_raw = r.blpop(QUEUE_KEY, timeout=0)
    return msgpack.unpackb(item_raw, raw=False)
