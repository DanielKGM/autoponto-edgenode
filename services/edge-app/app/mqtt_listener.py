import json
import logging

import paho.mqtt.client as mqtt

from app.config import MQTT_HOST, MQTT_PASS, MQTT_PORT, MQTT_USER
from app.redis_store import save_device_status

logger = logging.getLogger(__name__)


def build_status_listener() -> mqtt.Client:
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="edge-app-status")
    client.username_pw_set(MQTT_USER, MQTT_PASS)

    def on_connect(client, userdata, flags, reason_code, properties=None):
        logger.info("mqtt status listener connected rc=%s", reason_code)
        client.subscribe("sts/+")

    def on_message(client, userdata, msg):
        parts = msg.topic.split("/")
        if len(parts) != 2 or parts[0] != "sts":
            return
        device_id = parts[1]
        state = msg.payload.decode("utf-8", errors="replace").strip()
        save_device_status(device_id, state)
        logger.info("device status device=%s state=%s", device_id, state)

    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(MQTT_HOST, MQTT_PORT, 60)
    return client


def publish_command(client: mqtt.Client, device_id: str, payload: dict) -> None:
    topic = f"cmd/{device_id}"
    client.publish(topic, json.dumps(payload, ensure_ascii=False), qos=1, retain=False)
    logger.info("published mqtt command to %s", topic)
