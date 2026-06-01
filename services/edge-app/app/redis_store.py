from datetime import datetime, timezone
import json
import msgpack
import redis

from app.config import MAX_FRAME_QUEUE, REDIS_HOST, REDIS_PORT
from app.models import FrameQueueItem

QUEUE_FRAMES = "queue:frames"
QUEUE_ATTENDANCE_EVENTS = "queue:attendance_events"
FACE_EMBEDDINGS = "face:embeddings"


def get_redis(decode_responses: bool = False) -> redis.Redis:
    return redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        decode_responses=decode_responses,
    )


def queue_length() -> int:
    return int(get_redis().llen(QUEUE_FRAMES))


def is_frame_queue_full() -> bool:
    return queue_length() >= MAX_FRAME_QUEUE


def enqueue_frame(
    device_id: str,
    locale_id: str,
    lesson_id: str,
    frame_bytes: bytes,
) -> int:
    item = FrameQueueItem(
        device_id=device_id,
        locale_id=locale_id,
        lesson_id=lesson_id,
        received_at=datetime.now(timezone.utc),
        frame=frame_bytes,
    )
    client = get_redis()
    client.rpush(QUEUE_FRAMES, msgpack.packb(item.to_queue_payload(), use_bin_type=True))
    return queue_length()


def save_device_status(device_id: str, state: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    data = {
        "deviceId": device_id,
        "state": state,
        "receivedAt": now,
    }
    client = get_redis(decode_responses=True)
    client.set(f"device:{device_id}:status", json.dumps(data))
    client.hset("devices:last_seen", device_id, now)


def replace_runtime_cache(lesson_students: dict[str, list[str]], embeddings: dict[str, bytes]) -> None:
    client = get_redis()
    pipe = client.pipeline()
    for key in client.scan_iter("lesson:*:students"):
        pipe.delete(key)
    pipe.delete(FACE_EMBEDDINGS)

    for lesson_id, student_ids in lesson_students.items():
        key = f"lesson:{lesson_id}:students"
        if student_ids:
            pipe.sadd(key, *student_ids)

    if embeddings:
        pipe.hset(FACE_EMBEDDINGS, mapping=embeddings)

    pipe.execute()
