import json
import logging

import paho.mqtt.client as mqtt

from app.config import MQTT_HOST, MQTT_PASS, MQTT_PORT, MQTT_USER
from app.interscity import publish_device_log, publish_device_status
from app.redis_store import save_device_status

logger = logging.getLogger(__name__)


def build_status_listener() -> mqtt.Client:
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="edge-app-status")
    client.username_pw_set(MQTT_USER, MQTT_PASS)

    def on_connect(client, userdata, flags, reason_code, properties=None):
        logger.info("mqtt status listener connected rc=%s", reason_code)
        client.subscribe("sts/+")
        client.subscribe("log/+")

    def on_message(client, userdata, msg):
        parts = msg.topic.split("/")
        if len(parts) != 2:
            return

        kind, device_id = parts
        payload = msg.payload.decode("utf-8", errors="replace").strip()

        if kind == "sts":
            data = save_device_status(device_id, payload)
            publish_device_status(device_id, data["status"], data["reportadoEm"])
            logger.info("device status device=%s status=%s", device_id, data["status"])
            return

        if kind == "log":
            try:
                data = json.loads(payload)
            except json.JSONDecodeError:
                logger.warning("invalid device log device=%s payload=%s", device_id, payload)
                return
            publish_device_log(device_id, data)
            logger.info("device log received device=%s", device_id)

    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(MQTT_HOST, MQTT_PORT, 60)
    return client


def publish_command(client: mqtt.Client, device_id: str, payload: dict) -> None:
    topic = f"cmd/{device_id}"
    client.publish(topic, json.dumps(payload, ensure_ascii=False), qos=1, retain=False)
    logger.info("published mqtt command to %s", topic)
