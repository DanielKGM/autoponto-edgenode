import asyncio
import logging

import msgpack

from app.mqtt_listener import publish_command
from app.redis_store import QUEUE_ATTENDANCE_EVENTS, get_redis
from app.repository import parse_dt, save_attendance_event

logger = logging.getLogger(__name__)


def first_two_names(name: str) -> str:
    parts = name.split()
    return " ".join(parts[:2]) or name


def format_attendance_message(stored_event: dict) -> str:
    student_name = first_two_names(stored_event["student_name"])
    recognized_at = parse_dt(stored_event["recognized_at"]).strftime("%H:%M")
    return f"{student_name} - registrado {recognized_at}"


def handle_attendance_event(event: dict, mqtt_client) -> dict:
    stored = save_attendance_event(event)
    payload = {
        "auth": True,
        "studentId": stored["student_id"],
        "msg": format_attendance_message(stored),
        "recognizedAt": stored["recognized_at"],
        "alreadyRegistered": not stored["is_new"],
    }
    publish_command(mqtt_client, event["deviceId"], payload)
    logger.info(
        "attendance event stored id=%s device=%s student=%s lesson=%s is_new=%s",
        stored["id"],
        event.get("deviceId"),
        stored["student_id"],
        stored["lesson_id"],
        stored["is_new"],
    )
    return stored


async def consume_attendance_events(stop_event: asyncio.Event, mqtt_client) -> None:
    client = get_redis()
    while not stop_event.is_set():
        item = await asyncio.to_thread(client.blpop, QUEUE_ATTENDANCE_EVENTS, 1)
        if not item:
            continue

        try:
            _, raw = item
            event = msgpack.unpackb(raw, raw=False)
            handle_attendance_event(event, mqtt_client)
        except Exception as exc:
            logger.exception("failed to consume attendance event: %s", exc)
