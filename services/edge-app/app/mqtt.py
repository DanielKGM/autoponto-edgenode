import json
import logging

import paho.mqtt.client as mqtt

from app.config import MQTT_HOST, MQTT_PASS, MQTT_PORT, MQTT_USER
from app.interscity import publish_device_capabilities
from app.redis_store import save_device_status

logger = logging.getLogger(__name__)

LOG_CAPABILITY_KEYS = (
    "heap_free",
    "psram_free",
    "now_ms",
    "rssi",
    "heap_min",
    "lesson",
    "remaining_ms",
    "next_ms",
)


def build_mqtt_listener() -> mqtt.Client:
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="edge-app")
    client.username_pw_set(MQTT_USER, MQTT_PASS)

    def on_connect(client, userdata, flags, reason_code, properties=None):
        logger.info("mqtt listener connected rc=%s", reason_code)
        client.subscribe("log/+")

    def on_message(client, userdata, msg):
        parts = msg.topic.split("/")
        if len(parts) != 2 or parts[0] != "log":
            return

        device_id = parts[1]
        payload = msg.payload.decode("utf-8", errors="replace").strip()
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            logger.warning("invalid device log device=%s payload=%s", device_id, payload)
            return

        kind = data.get("kind")
        timestamp = data.get("timestamp") or data.get("reportadoEm")

        if kind == "status":
            status = str(data.get("status", "")).strip().lower()
            if not status:
                logger.warning("invalid device status log device=%s payload=%s", device_id, data)
                return
            saved = save_device_status(device_id, status)
            publish_device_capabilities(
                device_id,
                {"status": saved["status"]},
                timestamp or saved["reportadoEm"],
            )
            logger.info("device status device=%s status=%s", device_id, saved["status"])
            return

        if kind == "pir":
            publish_device_capabilities(
                device_id,
                {"presenca": data.get("presenca", True)},
                timestamp,
            )
            logger.info("device pir presence device=%s", device_id)
            return

        if kind == "metrics":
            publish_device_capabilities(
                device_id,
                {key: data.get(key) for key in LOG_CAPABILITY_KEYS},
                timestamp,
            )
            logger.info("device metrics received device=%s", device_id)
            return

        logger.warning("unknown device log kind device=%s kind=%s", device_id, kind)

    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(MQTT_HOST, MQTT_PORT, 60)
    return client


def publish_command(client: mqtt.Client, device_id: str, payload: dict) -> None:
    topic = f"cmd/{device_id}"
    client.publish(topic, json.dumps(payload, ensure_ascii=False), qos=1, retain=False)
    logger.info("published mqtt command to %s", topic)
