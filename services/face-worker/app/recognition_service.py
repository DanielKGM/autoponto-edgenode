import logging
import os
import time

from app.storage import ArmazenamentoRedis
from app.vision_engine import VisionEngine
from tcc_evidencias import registrar_tempo

logger = logging.getLogger(__name__)

LIMIAR_RECONHECIMENTO_FACIAL = float(os.getenv("FACE_MATCH_THRESHOLD", "0.363"))


class ServicoReconhecimento:
    def __init__(self, armazenamento: ArmazenamentoRedis):
        self.armazenamento = armazenamento
        self.visao = VisionEngine()

    def reconhecer(self, frame_bytes: bytes, aula_id: str) -> dict:
        inicio = time.perf_counter()

        imagem = self.visao.decodificar_jpeg(frame_bytes)
        if imagem is None:
            registrar_tempo(
                "reconhecimento_total_ms",
                (time.perf_counter() - inicio) * 1000,
                "face-worker",
                status="falha",
                detalhes={"aula_id": aula_id, "reason": "decode_failed"},
            )
            return {
                "ok": False,
                "reason": "decode_failed",
            }

        inicio_deteccao = time.perf_counter()
        rosto = self.visao.detectar_melhor_rosto(imagem)
        registrar_tempo(
            "deteccao_facial_ms",
            (time.perf_counter() - inicio_deteccao) * 1000,
            "face-worker",
            status="sucesso" if rosto is not None else "falha",
            detalhes={
                "aula_id": aula_id,
                "reason": "ok" if rosto is not None else "no_face",
            },
        )
        if rosto is None:
            registrar_tempo(
                "reconhecimento_total_ms",
                (time.perf_counter() - inicio) * 1000,
                "face-worker",
                status="falha",
                detalhes={"aula_id": aula_id, "reason": "no_face"},
            )
            return {
                "ok": False,
                "reason": "no_face",
            }

        inicio_embedding = time.perf_counter()
        embedding = self.visao.extrair_embedding(imagem, rosto)
        registrar_tempo(
            "embedding_extracao_ms",
            (time.perf_counter() - inicio_embedding) * 1000,
            "face-worker",
            status="sucesso" if embedding is not None else "falha",
            detalhes={
                "aula_id": aula_id,
                "reason": "ok" if embedding is not None else "embedding_failed",
            },
        )
        if embedding is None:
            registrar_tempo(
                "reconhecimento_total_ms",
                (time.perf_counter() - inicio) * 1000,
                "face-worker",
                status="falha",
                detalhes={"aula_id": aula_id, "reason": "embedding_failed"},
            )
            return {
                "ok": False,
                "reason": "embedding_failed",
            }

        inicio_comparacao = time.perf_counter()
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

        tempo_comparacao_ms = round(
            (time.perf_counter() - inicio_comparacao) * 1000,
            2,
        )
        tempo_ms = round((time.perf_counter() - inicio) * 1000, 2)

        if melhor_aluno is None or melhor_score < LIMIAR_RECONHECIMENTO_FACIAL:
            registrar_tempo(
                "embedding_comparacao_ms",
                tempo_comparacao_ms,
                "face-worker",
                detalhes={
                    "aula_id": aula_id,
                    "embeddings": len(embeddings_conhecidos),
                    "reason": "not_recognized",
                    "score": melhor_score,
                },
            )
            registrar_tempo(
                "reconhecimento_total_ms",
                tempo_ms,
                "face-worker",
                status="falha",
                detalhes={
                    "aula_id": aula_id,
                    "reason": "not_recognized",
                    "score": melhor_score,
                },
            )
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

        registrar_tempo(
            "embedding_comparacao_ms",
            tempo_comparacao_ms,
            "face-worker",
            detalhes={
                "aula_id": aula_id,
                "embeddings": len(embeddings_conhecidos),
                "reason": "recognized",
                "score": melhor_score,
            },
        )
        registrar_tempo(
            "reconhecimento_total_ms",
            tempo_ms,
            "face-worker",
            detalhes={
                "aula_id": aula_id,
                "reason": "recognized",
                "score": melhor_score,
            },
        )
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
