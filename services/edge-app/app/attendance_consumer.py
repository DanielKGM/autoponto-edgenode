import asyncio
import logging

import msgpack

from app.mqtt import publish_command
from app.redis_store import QUEUE_ATTENDANCE_EVENTS, get_redis
from app.repository import parse_dt, save_attendance_event

logger = logging.getLogger(__name__)


def first_two_names(name: str) -> str:
    parts = name.split()
    return " ".join(parts[:2]) or name


def format_attendance_message(stored_event: dict) -> str:
    aluno_nome = first_two_names(stored_event["aluno_nome"])
    reconhecido_em = parse_dt(stored_event["reconhecido_em"]).strftime("%H:%M")
    return f"{aluno_nome} - registrado {reconhecido_em}"


def handle_attendance_event(event: dict, mqtt_client) -> dict:
    stored = save_attendance_event(event)
    payload = {
        "auth": True,
        "msg": format_attendance_message(stored),
    }
    publish_command(mqtt_client, event["dispositivoId"], payload)
    logger.info(
        "attendance event stored id=%s dispositivo=%s aluno=%s aula=%s is_new=%s",
        stored["id"],
        event.get("dispositivoId"),
        stored["aluno_id"],
        stored["aula_id"],
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
