import json
import logging
import os

import paho.mqtt.client as mqtt

logger = logging.getLogger(__name__)

MQTT_HOST = os.getenv("MQTT_HOST")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USER = os.getenv("MQTT_USER")
MQTT_PASS = os.getenv("MQTT_PASS")


def build_mqtt_client():
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="face-worker")
    client.username_pw_set(MQTT_USER, MQTT_PASS)
    client.connect(MQTT_HOST, MQTT_PORT, 60)
    client.loop_start()
    logger.info("mqtt connected to %s:%s", MQTT_HOST, MQTT_PORT)
    return client


def publish_result(client: mqtt.Client, device_id: str, payload: dict):
    topic = f"cmd/{device_id}"
    client.publish(topic, json.dumps(payload), qos=1, retain=False)
    logger.info("published mqtt result to %s", topic)
