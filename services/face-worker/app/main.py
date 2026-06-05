import logging
import os

from app.recognition_service import RecognitionService
from app.storage import Storage


def configure_logging():
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )


def process_frame(
    item: dict,
    storage: Storage,
    recognition: RecognitionService,
    logger,
) -> bool:
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
        return False

    logger.info(
        "frame received device=%s locale=%s lesson=%s bytes=%d receivedAt=%s",
        device_id,
        locale_id,
        lesson_id,
        len(frame_bytes),
        received_at,
    )

    result = recognition.recognize(frame_bytes, lesson_id)
    if not result["ok"]:
        logger.info(
            "recognition failed device=%s reason=%s score=%s %s",
            device_id,
            result["reason"],
            result.get("score"),
            result.get("embeddingId"),
        )
        return False

    storage.enqueue_attendance_event(
        device_id=device_id,
        lesson_id=lesson_id,
        student_id=result["studentId"],
        score=result["score"],
    )
    logger.info(
        "recognition success queued_attendance device=%s student=%s embedding_id=%s score=%.4f",
        device_id,
        result["studentId"],
        result.get("embeddingId"),
        result["score"],
    )
    return True


def main():
    configure_logging()
    logger = logging.getLogger("face-worker")

    storage = Storage()
    recognition = RecognitionService(storage)

    logger.info("waiting for frames...")

    while True:
        try:
            item = storage.pop_frame_blocking()
            if not item:
                continue

            process_frame(item, storage, recognition, logger)

        except Exception as exc:
            logger.exception("worker loop error: %s", exc)


if __name__ == "__main__":
    main()
