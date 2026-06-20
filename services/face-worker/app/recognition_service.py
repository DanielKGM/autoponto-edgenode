import logging
import os
import time

from app.storage import Armazenamento
from app.vision_engine import VisionEngine

logger = logging.getLogger(__name__)

LIMIAR_RECONHECIMENTO_FACIAL = float(os.getenv("FACE_MATCH_THRESHOLD", "0.363"))


class ServicoReconhecimento:
    def __init__(self, armazenamento: Armazenamento):
        self.armazenamento = armazenamento
        self.visao = VisionEngine()

    def reconhecer(self, frame_bytes: bytes, aula_id: str) -> dict:
        inicio = time.perf_counter()

        imagem = self.visao.decodificar_jpeg(frame_bytes)
        if imagem is None:
            return {
                "ok": False,
                "reason": "decode_failed",
            }

        rosto = self.visao.detectar_melhor_rosto(imagem)
        if rosto is None:
            return {
                "ok": False,
                "reason": "no_face",
            }

        embedding = self.visao.extrair_embedding(imagem, rosto)
        if embedding is None:
            return {
                "ok": False,
                "reason": "embedding_failed",
            }

        embeddings_conhecidos = self.armazenamento.carregar_embeddings_da_aula(aula_id)

        melhor_aluno = None
        melhor_embedding_id = None
        melhor_score = -1.0

        for embedding_id, aluno_id, embedding_conhecido in embeddings_conhecidos:
            score = self.visao.comparar(embedding, embedding_conhecido)
            if score > melhor_score:
                melhor_score = score
                melhor_aluno = aluno_id
                melhor_embedding_id = embedding_id

        tempo_ms = round((time.perf_counter() - inicio) * 1000, 2)

        if melhor_aluno is None or melhor_score < LIMIAR_RECONHECIMENTO_FACIAL:
            logger.info(
                "recognition miss best_aluno=%s best_embedding_id=%s score=%.4f threshold=%.4f elapsed_ms=%s",
                melhor_aluno,
                melhor_embedding_id,
                melhor_score,
                LIMIAR_RECONHECIMENTO_FACIAL,
                tempo_ms,
            )
            return {
                "ok": False,
                "reason": "not_recognized",
                "alunoId": melhor_aluno,
                "embeddingId": melhor_embedding_id,
                "score": melhor_score,
                "elapsedMs": tempo_ms,
            }

        logger.info(
            "recognition hit aluno=%s embedding_id=%s score=%.4f elapsed_ms=%s",
            melhor_aluno,
            melhor_embedding_id,
            melhor_score,
            tempo_ms,
        )
        return {
            "ok": True,
            "alunoId": melhor_aluno,
            "embeddingId": melhor_embedding_id,
            "score": melhor_score,
            "elapsedMs": tempo_ms,
        }
