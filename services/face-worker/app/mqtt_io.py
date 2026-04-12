import json
import os
import paho.mqtt.client as mqtt

MQTT_HOST = os.getenv("MQTT_HOST")
MQTT_PORT = int(os.getenv("MQTT_PORT"))
MQTT_USER = os.getenv("MQTT_USER")
MQTT_PASS = os.getenv("MQTT_PASS")


def build_mqtt():
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="face-worker")
    client.username_pw_set(MQTT_USER, MQTT_PASS)
    client.connect(MQTT_HOST, MQTT_PORT, 60)
    client.loop_start()
    return client


def publish_result(client: mqtt.Client, device_id: str, payload: dict):
    client.publish(
        f"cmd/{device_id}",
        json.dumps(payload),
        qos=1,
        retain=False,
    )
