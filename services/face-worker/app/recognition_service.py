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

    def recognize(self, frame_bytes: bytes, aula_id: str) -> dict:
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

        known = self.storage.load_embeddings_for_aula(aula_id)

        best_aluno = None
        best_embedding_id = None
        best_score = -1.0

        for embedding_id, aluno_id, known_emb in known:
            score = self.vision.compare(embedding, known_emb)
            if score > best_score:
                best_score = score
                best_aluno = aluno_id
                best_embedding_id = embedding_id

        elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)

        if best_aluno is None or best_score < FACE_MATCH_THRESHOLD:
            logger.info(
                "recognition miss best_aluno=%s best_embedding_id=%s score=%.4f threshold=%.4f elapsed_ms=%s",
                best_aluno,
                best_embedding_id,
                best_score,
                FACE_MATCH_THRESHOLD,
                elapsed_ms,
            )
            return {
                "ok": False,
                "reason": "not_recognized",
                "alunoId": best_aluno,
                "embeddingId": best_embedding_id,
                "score": best_score,
                "elapsedMs": elapsed_ms,
            }

        logger.info(
            "recognition hit aluno=%s embedding_id=%s score=%.4f elapsed_ms=%s",
            best_aluno,
            best_embedding_id,
            best_score,
            elapsed_ms,
        )
        return {
            "ok": True,
            "alunoId": best_aluno,
            "embeddingId": best_embedding_id,
            "score": best_score,
            "elapsedMs": elapsed_ms,
        }
