import logging
import os
from datetime import datetime, timezone
from uuid import uuid4

import msgpack
import numpy as np
import redis

logger = logging.getLogger(__name__)

REDIS_HOST = os.getenv("REDIS_HOST")
REDIS_PORT = int(os.getenv("REDIS_PORT"))

QUEUE_KEY = "queue:frames"
ATTENDANCE_QUEUE_KEY = "queue:eventos_presenca"
EMBEDDINGS_KEY = "face:embeddings"


class ArmazenamentoRedis:
    def __init__(self):
        self.redis = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            decode_responses=False,
            socket_connect_timeout=5,
            socket_timeout=10,
            health_check_interval=30,
        )

    def buscar_frame_bloqueante(self) -> dict | None:
        item = self.redis.blpop(QUEUE_KEY, timeout=5)
        if item is None:
            return None
        _, item_bruto = item
        return msgpack.unpackb(item_bruto, raw=False)

    def carregar_embeddings_da_aula(
        self, aula_id: str
    ) -> list[tuple[str, str, np.ndarray]]:
        aluno_ids = self.redis.smembers(f"aula:{aula_id}:alunos")
        if not aluno_ids:
            logger.info("no eligible alunos for aula=%s", aula_id)
            return []

        alunos_elegiveis = {aluno_id.decode("utf-8") for aluno_id in aluno_ids}
        registros_brutos = self.redis.hgetall(EMBEDDINGS_KEY)

        resultado = []
        for embedding_id, embedding_bruto in registros_brutos.items():
            if not embedding_bruto:
                continue
            if isinstance(embedding_id, bytes):
                embedding_id = embedding_id.decode("utf-8")
            aluno_id, embedding = self._decodificar_registro_embedding(embedding_bruto)
            if aluno_id in alunos_elegiveis:
                resultado.append((embedding_id, aluno_id, embedding))

        logger.info(
            "loaded %d eligible embeddings for aula=%s", len(resultado), aula_id
        )
        return resultado

    def enfileirar_evento_presenca(
        self,
        dispositivo_id: str,
        dispositivo_codigo: str | None,
        aula_id: str,
        aluno_id: str,
        score: float,
    ) -> None:
        payload = {
            "eventId": str(uuid4()),
            "dispositivoId": dispositivo_id,
            "aulaId": aula_id,
            "alunoId": aluno_id,
            "score": score,
            "recognizedAt": datetime.now(timezone.utc).isoformat(),
        }
        if dispositivo_codigo:
            payload["dispositivoCodigo"] = dispositivo_codigo
        self.redis.rpush(
            ATTENDANCE_QUEUE_KEY, msgpack.packb(payload, use_bin_type=True)
        )

    def _decodificar_registro_embedding(self, blob: bytes) -> tuple[str, np.ndarray]:
        registro = msgpack.unpackb(blob, raw=False)
        payload_embedding = msgpack.unpackb(registro["embedding"], raw=False)
        dados = payload_embedding["data"]
        if isinstance(dados, list):
            embedding = np.asarray(dados, dtype=np.float32)
        else:
            embedding = np.frombuffer(dados, dtype=np.float32)
        return registro["alunoId"], embedding.reshape(payload_embedding["shape"])
