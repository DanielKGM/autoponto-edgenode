import json
import logging
from collections.abc import Callable

import paho.mqtt.client as mqtt

from app.config import MQTT_HOST, MQTT_PASS, MQTT_PORT, MQTT_USER
from app.metricas_avg_us import registrar_metricas_avg_us

logger = logging.getLogger(__name__)

LOG_CAPABILITY_KEYS = (
    "heap_free",
    "heap_min",
    "heap_max",
    "psram_free",
    "psram_min",
    "psram_max",
    "rssi",
    "post_max_ms",
)


def criar_listener_mqtt(
    enfileirar_publicacao_interscity: Callable[[str, dict, str | None], bool],
) -> mqtt.Client:
    cliente = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="edge-app")
    cliente.username_pw_set(MQTT_USER, MQTT_PASS)

    def on_connect(client, userdata, flags, reason_code, properties=None):
        logger.info("mqtt listener connected rc=%s", reason_code)
        client.subscribe("log/+")

    def on_message(client, userdata, msg):
        parts = msg.topic.split("/")
        if len(parts) != 2 or parts[0] != "log":
            return

        dispositivo_codigo = parts[1]
        payload = msg.payload.decode("utf-8", errors="replace").strip()
        try:
            dados = json.loads(payload)
        except json.JSONDecodeError:
            logger.warning(
                "log de dispositivo invalido dispositivo_codigo=%s payload=%s",
                dispositivo_codigo,
                payload,
            )
            return
        if not isinstance(dados, dict):
            logger.warning(
                "log de dispositivo sem objeto json dispositivo_codigo=%s payload=%s",
                dispositivo_codigo,
                payload,
            )
            return

        tipo = dados.get("kind")
        timestamp = dados.get("timestamp") or dados.get("reportadoEm")

        if tipo == "status":
            status = str(dados.get("status", "")).strip().lower()
            if not status:
                logger.warning(
                    "status de dispositivo invalido dispositivo_codigo=%s payload=%s",
                    dispositivo_codigo,
                    dados,
                )
                return
            enfileirar_publicacao_interscity(
                dispositivo_codigo,
                {"status": status},
                timestamp,
            )
            logger.info(
                "status de dispositivo recebido dispositivo_codigo=%s status=%s",
                dispositivo_codigo,
                status,
            )
            return

        if tipo == "pir":
            enfileirar_publicacao_interscity(
                dispositivo_codigo,
                {"presenca": dados.get("presenca", True)},
                timestamp,
            )
            logger.info(
                "presenca pir recebida dispositivo_codigo=%s", dispositivo_codigo
            )
            return

        if tipo == "metrics":
            idle = dados.get("idle")

            if isinstance(idle, bool) and idle:

                logger.info(
                    "metricas de dispositivo recusadas (idle) dispositivo_codigo=%s",
                    dispositivo_codigo,
                )

                return

            avg_us = dados.get("avg_us")
            if isinstance(avg_us, dict):
                registrar_metricas_avg_us(dispositivo_codigo, avg_us)
            enfileirar_publicacao_interscity(
                dispositivo_codigo,
                {chave: dados.get(chave) for chave in LOG_CAPABILITY_KEYS},
                timestamp,
            )
            logger.info(
                "metricas de dispositivo recebidas dispositivo_codigo=%s",
                dispositivo_codigo,
            )
            return

        logger.warning(
            "tipo de log desconhecido dispositivo_codigo=%s kind=%s",
            dispositivo_codigo,
            tipo,
        )

    cliente.on_connect = on_connect
    cliente.on_message = on_message
    cliente.connect(MQTT_HOST, MQTT_PORT, 60)
    return cliente


def publicar_comando(
    client: mqtt.Client,
    dispositivo_codigo: str,
    payload: dict,
) -> None:
    topic = f"cmd/{dispositivo_codigo}"
    client.publish(topic, json.dumps(payload, ensure_ascii=False), qos=1, retain=False)
    logger.info("published mqtt command to %s", topic)
