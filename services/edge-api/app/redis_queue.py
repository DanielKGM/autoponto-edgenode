import os
from datetime import datetime, timezone

import msgpack
import redis

REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
MAX_FRAME_QUEUE = int(os.getenv("MAX_FRAME_QUEUE", "100"))

QUEUE_KEY = "queue:frames"


def get_redis() -> redis.Redis:
    return redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        decode_responses=False,
    )


def get_queue_length() -> int:
    client = get_redis()
    return int(client.llen(QUEUE_KEY))


def is_queue_full() -> bool:
    return get_queue_length() >= MAX_FRAME_QUEUE


def enqueue_frame(device_id: str, locale_id: str | None, frame_bytes: bytes) -> int:
    payload = {
        "deviceId": device_id,
        "localeId": locale_id,
        "receivedAt": datetime.now(timezone.utc).isoformat(),
        "frame": frame_bytes,
    }

    packed = msgpack.packb(payload, use_bin_type=True)

    client = get_redis()
    client.rpush(QUEUE_KEY, packed)

    return get_queue_length()