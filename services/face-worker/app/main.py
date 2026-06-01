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
            lesson_id = item.get("lessonId")
            received_at = item.get("receivedAt")
            frame_bytes = item["frame"]

            if not lesson_id:
                logger.info(
                    "frame ignored device=%s reason=missing_lesson lesson=%s",
                    device_id,
                    lesson_id,
                )
                continue

            logger.info(
                "frame received device=%s locale=%s lesson=%s bytes=%d receivedAt=%s",
                device_id,
                locale_id,
                lesson_id,
                len(frame_bytes),
                received_at,
            )

            result = recognition.recognize(frame_bytes, lesson_id)

            if result["ok"]:
                payload = {
                    "auth": True,
                    "studentId": result["studentId"],
                    "msg": result["studentId"],
                }
                storage.enqueue_attendance_event(
                    device_id=device_id,
                    lesson_id=lesson_id,
                    student_id=result["studentId"],
                    score=result["score"],
                )
                publish_result(mqtt_client, device_id, payload)
                logger.info(
                    "recognition success device=%s student=%s score=%.4f",
                    device_id,
                    result["studentId"],
                    result["score"],
                )
            else:
                logger.info(
                    "recognition failed without mqtt feedback device=%s reason=%s score=%s",
                    device_id,
                    result["reason"],
                    result.get("score"),
                )

        except Exception as exc:
            logger.error("worker loop error: %s", exc)
            logger.debug(traceback.format_exc())


if __name__ == "__main__":
    main()
