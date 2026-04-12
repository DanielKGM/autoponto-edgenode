import json
import os

import msgpack
import paho.mqtt.client as mqtt
import redis


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
        decode_responses=False,
    )


def build_mqtt():
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="face-worker")
    client.username_pw_set(MQTT_USER, MQTT_PASS)
    client.connect(MQTT_HOST, MQTT_PORT, 60)
    client.loop_start()
    return client


def unpack_item(item_raw: bytes) -> dict:
    return msgpack.unpackb(item_raw, raw=False)


# mock
# TODO: pipeline real de visão computacional
def process_item(mqtt_client: mqtt.Client, item_raw: bytes):
    item = unpack_item(item_raw)

    device_id = item["deviceId"]
    locale_id = item.get("localeId")
    frame_bytes = item["frame"]
    received_at = item.get("receivedAt")

    payload = {
        "auth": True,
        "msg": "Autenticado com sucesso!",
    }

    mqtt_client.publish(
        f"cmd/{device_id}",
        json.dumps(payload),
        qos=1,
        retain=False,
    )

    print(
        f"processed device={device_id} locale={locale_id}",
        flush=True,
    )


def main():
    r = get_redis()
    mqtt_client = build_mqtt()

    print("waiting for frames...", flush=True)

    while True:
        item = r.blpop(QUEUE_KEY, timeout=0)
        if not item:
            continue

        _, item_raw = item
        process_item(mqtt_client, item_raw)


if __name__ == "__main__":
    main()