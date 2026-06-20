import asyncio
import logging

import msgpack

from app.mqtt import publicar_comando
from app.redis_store import QUEUE_ATTENDANCE_EVENTS, obter_redis
from app.repository import converter_data_hora, salvar_evento_presenca

logger = logging.getLogger(__name__)


def montar_mensagem_presenca(evento_salvo: dict) -> str:
    partes_nome = evento_salvo["aluno_nome"].split()
    aluno_nome = " ".join(partes_nome[:2]) or evento_salvo["aluno_nome"]
    reconhecido_em = converter_data_hora(evento_salvo["reconhecido_em"]).strftime(
        "%H:%M"
    )
    return f"{aluno_nome} - registrado {reconhecido_em}"


def processar_evento_presenca(evento: dict, mqtt_client) -> dict:
    evento_salvo = salvar_evento_presenca(evento)
    payload = {
        "auth": True,
        "msg": montar_mensagem_presenca(evento_salvo),
    }
    dispositivo_codigo = evento.get("dispositivoCodigo")
    if not dispositivo_codigo:
        logger.warning(
            "attendance event without dispositivoCodigo id=%s dispositivo=%s",
            evento_salvo["id"],
            evento.get("dispositivoId"),
        )
        return evento_salvo

    publicar_comando(mqtt_client, dispositivo_codigo, payload)
    logger.info(
        "attendance event stored id=%s dispositivo=%s codigo=%s aluno=%s aula=%s novo=%s",
        evento_salvo["id"],
        evento.get("dispositivoId"),
        dispositivo_codigo,
        evento_salvo["aluno_id"],
        evento_salvo["aula_id"],
        evento_salvo["novo"],
    )
    return evento_salvo


async def consumir_eventos_presenca(stop_event: asyncio.Event, mqtt_client) -> None:
    cliente = obter_redis()
    while not stop_event.is_set():
        item = await asyncio.to_thread(cliente.blpop, QUEUE_ATTENDANCE_EVENTS, 1)
        if item is None:
            continue

        try:
            _, bruto = item
            evento = msgpack.unpackb(bruto, raw=False)
            processar_evento_presenca(evento, mqtt_client)
        except Exception as exc:
            logger.exception("failed to consume attendance event: %s", exc)
