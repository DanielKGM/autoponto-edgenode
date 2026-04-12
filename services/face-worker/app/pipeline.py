import os
from vision import VisionPipeline
from embeddings_store import load_all_embeddings

FACE_MATCH_THRESHOLD = float(os.getenv("FACE_MATCH_THRESHOLD", "0.363"))


class RecognitionService:
    def __init__(self):
        self.vision = VisionPipeline()

    def recognize(self, frame_bytes: bytes) -> dict:
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

        known = load_all_embeddings()

        best_student = None
        best_score = -1.0

        for student_id, known_emb in known.items():
            score = self.vision.compare(embedding, known_emb)
            if score > best_score:
                best_score = score
                best_student = student_id

        if best_student is None or best_score < FACE_MATCH_THRESHOLD:
            return {
                "ok": False,
                "reason": "not_recognized",
                "score": best_score,
            }

        return {
            "ok": True,
            "studentId": best_student,
            "score": best_score,
        }