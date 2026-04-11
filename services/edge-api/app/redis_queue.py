import os
import json
import base64
import redis
from datetime import datetime, timezone

REDIS_HOST = os.getenv("REDIS_HOST")
REDIS_PORT = int(os.getenv("REDIS_PORT"))


def enqueue_frame(device_id: str, locale_id: str | None, frame_bytes: bytes) -> None:
    client = redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        decode_responses=True,
    )

    payload = {
        "deviceId": device_id,
        "size": len(frame_bytes),
        "receivedAt": datetime.now(timezone.utc).isoformat(),
        "jpegBase64": base64.b64encode(frame_bytes).decode("ascii"),
    }

    client.rpush("queue:frames", json.dumps(payload))