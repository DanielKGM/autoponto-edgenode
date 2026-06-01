import asyncio
import logging

import msgpack

from app.redis_store import QUEUE_ATTENDANCE_EVENTS, get_redis
from app.repository import save_attendance_event

logger = logging.getLogger(__name__)


async def consume_attendance_events(stop_event: asyncio.Event) -> None:
    client = get_redis()
    while not stop_event.is_set():
        item = await asyncio.to_thread(client.blpop, QUEUE_ATTENDANCE_EVENTS, 1)
        if not item:
            continue

        _, raw = item
        event = msgpack.unpackb(raw, raw=False)
        event_id = save_attendance_event(event)
        logger.info(
            "attendance event stored id=%s device=%s student=%s lesson=%s",
            event_id,
            event.get("deviceId"),
            event.get("studentId"),
            event.get("lessonId"),
        )
