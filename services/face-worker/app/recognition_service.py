import logging
import os
import time

from app.storage import Storage
from app.vision_engine import VisionEngine

logger = logging.getLogger(__name__)

FACE_MATCH_THRESHOLD = float(os.getenv("FACE_MATCH_THRESHOLD", "0.363"))


class RecognitionService:
    def __init__(self, storage: Storage):
        self.storage = storage
        self.vision = VisionEngine()

    def recognize(self, frame_bytes: bytes) -> dict:
        t0 = time.perf_counter()

        image = self.vision.decode_jpeg(frame_bytes)
        if image is None:
            return {
                "ok": False,
                "reason": "decode_failed",
            }

        face = self.vision.detect_best_face(image)
        if face is None:
            return {
                "ok": False,
                "reason": "no_face",
            }

        embedding = self.vision.extract_embedding(image, face)
        if embedding is None:
            return {
                "ok": False,
                "reason": "embedding_failed",
            }

        known = self.storage.load_all_embeddings()

        best_student = None
        best_score = -1.0

        for student_id, known_emb in known.items():
            score = self.vision.compare(embedding, known_emb)
            if score > best_score:
                best_score = score
                best_student = student_id

        elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)

        if best_student is None or best_score < FACE_MATCH_THRESHOLD:
            logger.info(
                "recognition miss score=%.4f threshold=%.4f elapsed_ms=%s",
                best_score,
                FACE_MATCH_THRESHOLD,
                elapsed_ms,
            )
            return {
                "ok": False,
                "reason": "not_recognized",
                "score": best_score,
                "elapsedMs": elapsed_ms,
            }

        logger.info(
            "recognition hit student=%s score=%.4f elapsed_ms=%s",
            best_student,
            best_score,
            elapsed_ms,
        )
        return {
            "ok": True,
            "studentId": best_student,
            "score": best_score,
            "elapsedMs": elapsed_ms,
        }
