import json
import os
import redis
from datetime import datetime, timezone
from pathlib import Path

REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
TEMPFRAMES_DIR = os.getenv("TEMPFRAMES_DIR", "/edge-data/tempframes")
MAX_FRAME_QUEUE = int(os.getenv("MAX_FRAME_QUEUE", "100"))

QUEUE_KEY = "queue:frames"


def get_redis() -> redis.Redis:
    return redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        decode_responses=True,
    )


def get_queue_length() -> int:
    client = get_redis()
    return int(client.llen(QUEUE_KEY))


def is_queue_full() -> bool:
    return get_queue_length() >= MAX_FRAME_QUEUE


def save_frame_to_disk(device_id: str, frame_bytes: bytes) -> tuple[str, str]:
    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y%m%dT%H%M%S%fZ")
    filename = f"{device_id}_{stamp}.jpg"

    base_dir = Path(TEMPFRAMES_DIR)
    base_dir.mkdir(parents=True, exist_ok=True)

    full_path = base_dir / filename
    full_path.write_bytes(frame_bytes)

    return str(full_path), now.isoformat()


def enqueue_frame(device_id: str, locale_id: str | None, frame_bytes: bytes) -> dict:
    frame_path, received_at = save_frame_to_disk(device_id, frame_bytes)

    payload = {
        "deviceId": device_id,
        "localeId": locale_id,
        "size": len(frame_bytes),
        "receivedAt": received_at,
        "framePath": frame_path,
    }

    client = get_redis()
    client.rpush(QUEUE_KEY, json.dumps(payload))

    return payload