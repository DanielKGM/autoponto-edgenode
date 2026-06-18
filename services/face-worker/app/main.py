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
    dispositivo_id = item["dispositivoId"]
    sala_id = item.get("salaId")
    aula_id = item.get("aulaId")
    received_at = item.get("receivedAt")
    frame_bytes = item["frame"]

    if not aula_id:
        logger.info(
            "frame ignored dispositivo=%s reason=missing_aula aula=%s",
            dispositivo_id,
            aula_id,
        )
        return False

    logger.info(
        "frame received dispositivo=%s sala=%s aula=%s bytes=%d receivedAt=%s",
        dispositivo_id,
        sala_id,
        aula_id,
        len(frame_bytes),
        received_at,
    )

    result = recognition.recognize(frame_bytes, aula_id)
    if not result["ok"]:
        logger.info(
            "recognition failed dispositivo=%s reason=%s score=%s %s",
            dispositivo_id,
            result["reason"],
            result.get("score"),
            result.get("embeddingId"),
        )
        return False

    storage.enqueue_attendance_event(
        dispositivo_id=dispositivo_id,
        aula_id=aula_id,
        aluno_id=result["alunoId"],
        score=result["score"],
    )
    logger.info(
        "recognition success queued_attendance dispositivo=%s aluno=%s embedding_id=%s score=%.4f",
        dispositivo_id,
        result["alunoId"],
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
