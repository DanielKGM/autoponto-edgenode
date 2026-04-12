from queue_io import pop_frame_blocking
from mqtt_io import build_mqtt, publish_result
from pipeline import RecognitionService


def main():
    mqtt_client = build_mqtt()
    recognition = RecognitionService()

    print("waiting for frames...", flush=True)

    while True:
        item = pop_frame_blocking()

        if not item:
            continue

        device_id = item["deviceId"]
        frame_bytes = item["frame"]

        result = recognition.recognize(frame_bytes)

        if result["ok"]:
            payload = {
                "auth": True,
                "msg": result["studentId"] + result["score"],
            }
        else:
            payload = {
                "auth": False,
            }

        publish_result(mqtt_client, device_id, payload)


if __name__ == "__main__":
    main()
