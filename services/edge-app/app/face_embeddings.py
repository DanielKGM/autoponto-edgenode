import json
import logging

import numpy as np
from cryptography.fernet import Fernet, InvalidToken

from app.config import FACE_EMBEDDING_ENCRYPTION_KEY

logger = logging.getLogger(__name__)


def preparar_cache_redis_com_embeddings_descriptografados(
    cache_redis: dict,
    chave: str = FACE_EMBEDDING_ENCRYPTION_KEY,
) -> dict:
    fernet = _criar_fernet(chave)
    embeddings = cache_redis.get("embeddings_faciais", {})
    if not isinstance(embeddings, dict):
        raise ValueError("cache_redis.embeddings_faciais deve ser um objeto")

    processados = {}
    for embedding_id, registro in embeddings.items():
        try:
            processados[embedding_id] = _processar_registro_embedding(fernet, registro)
        except Exception as exc:
            logger.warning(
                "embedding facial invalido embedding_id=%s error=%s",
                embedding_id,
                exc,
            )
            raise

    cache_processado = dict(cache_redis)
    cache_processado["embeddings_faciais"] = processados
    return cache_processado


def _criar_fernet(chave: str) -> Fernet:
    if not chave:
        raise ValueError("FACE_EMBEDDING_ENCRYPTION_KEY ausente")
    try:
        return Fernet(chave.encode("ascii"))
    except Exception as exc:
        raise ValueError("FACE_EMBEDDING_ENCRYPTION_KEY invalida") from exc


def _processar_registro_embedding(fernet: Fernet, registro: dict) -> dict:
    if not isinstance(registro, dict):
        raise ValueError("embedding facial deve ser um objeto")

    aluno_id = registro.get("alunoId")
    if not isinstance(aluno_id, str) or not aluno_id.strip():
        raise ValueError("embedding facial deve incluir alunoId")

    ciphertext = registro.get("embedding_encrypted")
    if not isinstance(ciphertext, str) or not ciphertext.strip():
        raise ValueError("embedding facial deve incluir embedding_encrypted")

    return {
        "alunoId": aluno_id,
        "embedding": _descriptografar_embedding(fernet, ciphertext),
    }


def _descriptografar_embedding(fernet: Fernet, ciphertext: str) -> list[float]:
    try:
        raw = fernet.decrypt(ciphertext.encode("ascii"))
    except InvalidToken as exc:
        raise ValueError("embedding_encrypted invalido") from exc
    except UnicodeEncodeError as exc:
        raise ValueError("embedding_encrypted deve ser ascii") from exc

    try:
        valores = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("embedding descriptografado deve ser JSON valido") from exc

    return _normalizar_embedding(valores)


def _normalizar_embedding(valores) -> list[float]:
    if not isinstance(valores, list):
        raise ValueError("embedding descriptografado deve ser uma lista numerica")

    if len(valores) == 1 and isinstance(valores[0], list):
        valores = valores[0]
    elif any(isinstance(valor, list) for valor in valores):
        raise ValueError("embedding descriptografado deve ser lista plana")

    if not valores:
        raise ValueError("embedding descriptografado nao pode ser vazio")

    for valor in valores:
        if isinstance(valor, bool) or not isinstance(valor, (int, float)):
            raise ValueError("embedding descriptografado deve ser numerico")

    embedding = np.asarray(valores, dtype=np.float32)
    if not np.isfinite(embedding).all():
        raise ValueError("embedding descriptografado deve conter numeros finitos")
    return embedding.reshape(-1).tolist()
