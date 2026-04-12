import json
import os
from datetime import datetime, timezone

import redis
import paho.mqtt.client as mqtt


REDIS_HOST = os.getenv("REDIS_HOST")
REDIS_PORT = int(os.getenv("REDIS_PORT"))

MQTT_HOST = os.getenv("MQTT_HOST")
MQTT_PORT = int(os.getenv("MQTT_PORT"))
MQTT_USER = os.getenv("MQTT_USER")
MQTT_PASS = os.getenv("MQTT_PASS")


def get_redis() -> redis.Redis:
    return redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        decode_responses=True,
    )


r = get_redis()


def on_connect(client, userdata, flags, reason_code, properties=None):
    print(f"[mqtt-listener] connected rc={reason_code}", flush=True)
    client.subscribe("sts/+")


def on_message(client, userdata, msg):
    topic = msg.topic
    payload = msg.payload.decode("utf-8", errors="replace").strip()

    parts = topic.split("/")
    if len(parts) != 2 or parts[0] != "sts":
        return

    device_id = parts[1]
    now = datetime.now(timezone.utc).isoformat()

    data = {
        "deviceId": device_id,
        "state": payload,
        "receivedAt": now,
    }

    r.set(f"device:{device_id}:status", json.dumps(data))
    r.hset(
        "devices:last_seen",
        device_id,
        now,
    )

    print(f"{device_id} -> {payload}", flush=True)


def main():
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="mqtt-listener")
    client.username_pw_set(MQTT_USER, MQTT_PASS)
    client.on_connect = on_connect
    client.on_message = on_message

    client.connect(MQTT_HOST, MQTT_PORT, 60)
    client.loop_forever()


if __name__ == "__main__":
    main()