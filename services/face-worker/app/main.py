import logging
import os
import traceback

from app.mqtt_client import build_mqtt_client, publish_result
from app.recognition_service import RecognitionService
from app.storage import Storage


def configure_logging():
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )


def main():
    configure_logging()
    logger = logging.getLogger("face-worker")

    storage = Storage()
    mqtt_client = build_mqtt_client()
    recognition = RecognitionService(storage)

    logger.info("waiting for frames...")

    while True:
        try:
            item = storage.pop_frame_blocking()
            if not item:
                continue

            device_id = item["deviceId"]
            locale_id = item.get("localeId")
            received_at = item.get("receivedAt")
            frame_bytes = item["frame"]

            logger.info(
                "frame received device=%s locale=%s bytes=%d receivedAt=%s",
                device_id,
                locale_id,
                len(frame_bytes),
                received_at,
            )

            result = recognition.recognize(frame_bytes)

            if result["ok"]:
                payload = {
                    "auth": True,
                    "msg": "Autenticado com sucesso!",
                }
                logger.info(
                    "recognition success device=%s student=%s score=%.4f",
                    device_id,
                    result["studentId"],
                    result["score"],
                )
            else:
                payload = {
                    "auth": False,
                }
                logger.info(
                    "recognition failed device=%s reason=%s score=%s",
                    device_id,
                    result["reason"],
                    result.get("score"),
                )

            publish_result(mqtt_client, device_id, payload)

        except Exception as exc:
            logger.error("worker loop error: %s", exc)
            logger.debug(traceback.format_exc())


if __name__ == "__main__":
    main()
