import json
import os
from pathlib import Path

import redis
import paho.mqtt.client as mqtt


REDIS_HOST = os.getenv("REDIS_HOST")
REDIS_PORT = int(os.getenv("REDIS_PORT"))

MQTT_HOST = os.getenv("MQTT_HOST")
MQTT_PORT = int(os.getenv("MQTT_PORT"))
MQTT_USER = os.getenv("MQTT_USER")
MQTT_PASS = os.getenv("MQTT_PASS")

QUEUE_KEY = "queue:frames"


def get_redis() -> redis.Redis:
    return redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        decode_responses=True,
    )


def build_mqtt():
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="face-worker")
    client.username_pw_set(MQTT_USER, MQTT_PASS)
    client.connect(MQTT_HOST, MQTT_PORT, 60)
    client.loop_start()
    return client

# mock
# TODO: real face recognition
def process_item(mqtt_client: mqtt.Client, item_raw: str):
    item = json.loads(item_raw)

    device_id = item["deviceId"]
    frame_path = item["framePath"]

    exists = Path(frame_path).exists()

    if exists:
        payload = {
            "auth": True,
            "msg": "Autenticado com sucesso!",
        }
    else:
        payload = {
            "auth": False,
            "msg": "Erro ao autenticar! Tente novamente.",
        }

    mqtt_client.publish(
        f"cmd/{device_id}",
        json.dumps(payload),
        qos=1,
        retain=False,
    )

    if exists:
        try:
            Path(frame_path).unlink()
        except Exception as exc:
            print(f"[face-worker] failed deleting {frame_path}: {exc}", flush=True)

    print(f"[face-worker] processed device={device_id} exists={exists}", flush=True)


def main():
    r = get_redis()
    mqtt_client = build_mqtt()

    print("[face-worker] waiting for frames...", flush=True)

    while True:
        item = r.blpop(QUEUE_KEY, timeout=0)
        if not item:
            continue

        _, item_raw = item
        process_item(mqtt_client, item_raw)


if __name__ == "__main__":
    main()