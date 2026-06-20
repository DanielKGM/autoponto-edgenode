from datetime import datetime, timezone
import msgpack
import redis

from app.config import MAX_FRAME_QUEUE, REDIS_HOST, REDIS_PORT

QUEUE_FRAMES = "queue:frames"
QUEUE_ATTENDANCE_EVENTS = "queue:eventos_presenca"
FACE_EMBEDDINGS = "face:embeddings"
DISPOSITIVOS_POR_CODIGO = "dispositivos:por_codigo"
AULA_ALUNOS_PREFIX = "aula:"
AULA_ALUNOS_SUFFIX = ":alunos"
SALA_AULAS_PREFIX = "sala:"
SALA_AULAS_SUFFIX = ":aulas"


def obter_redis(decode_responses: bool = False) -> redis.Redis:
    return redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        decode_responses=decode_responses,
    )


def fila_frames_cheia() -> bool:
    return int(obter_redis().llen(QUEUE_FRAMES)) >= MAX_FRAME_QUEUE


def enfileirar_frame(
    dispositivo_id: str,
    dispositivo_codigo: str,
    sala_id: str,
    aula_id: str,
    frame_bytes: bytes,
) -> int:
    item = {
        "dispositivoId": dispositivo_id,
        "dispositivoCodigo": dispositivo_codigo,
        "salaId": sala_id,
        "aulaId": aula_id,
        "receivedAt": datetime.now(timezone.utc).isoformat(),
        "frame": frame_bytes,
    }
    cliente = obter_redis()
    cliente.rpush(QUEUE_FRAMES, msgpack.packb(item, use_bin_type=True))
    return int(cliente.llen(QUEUE_FRAMES))


def _empacotar(valor) -> bytes:
    return msgpack.packb(valor, use_bin_type=True)


def _desempacotar(valor: bytes | None):
    if valor is None:
        return None
    return msgpack.unpackb(valor, raw=False)


def _chave_aula_alunos(aula_id: str) -> str:
    return f"{AULA_ALUNOS_PREFIX}{aula_id}{AULA_ALUNOS_SUFFIX}"


def _chave_sala_aulas(sala_id: str) -> str:
    return f"{SALA_AULAS_PREFIX}{sala_id}{SALA_AULAS_SUFFIX}"


def obter_dispositivo_por_codigo(dispositivo_codigo: str) -> dict | None:
    dispositivo = _desempacotar(
        obter_redis().hget(DISPOSITIVOS_POR_CODIGO, dispositivo_codigo)
    )
    if not dispositivo or not dispositivo.get("ativo"):
        return None
    return dispositivo


def obter_uuid_interscity_por_codigo(dispositivo_codigo: str) -> str | None:
    dispositivo = obter_dispositivo_por_codigo(dispositivo_codigo)
    if not dispositivo:
        return None
    return dispositivo.get("interscity_uuid") or None


def obter_aulas_por_sala(sala_id: str) -> list[dict]:
    aulas = _desempacotar(obter_redis().get(_chave_sala_aulas(sala_id)))
    return aulas if isinstance(aulas, list) else []


def substituir_cache_redis(
    dispositivos: dict[str, dict],
    sala_aulas: dict[str, list[dict]],
    aula_alunos: dict[str, list[str]],
    embeddings: dict[str, bytes],
) -> None:
    cliente = obter_redis()
    pipeline = cliente.pipeline()

    for padrao in (
        f"{AULA_ALUNOS_PREFIX}*{AULA_ALUNOS_SUFFIX}",
        f"{SALA_AULAS_PREFIX}*{SALA_AULAS_SUFFIX}",
        "dispositivo:*:status",
    ):
        for chave in cliente.scan_iter(padrao):
            pipeline.delete(chave)
    pipeline.delete(DISPOSITIVOS_POR_CODIGO)
    pipeline.delete("dispositivos:last_seen")
    pipeline.delete(FACE_EMBEDDINGS)

    if dispositivos:
        pipeline.hset(
            DISPOSITIVOS_POR_CODIGO,
            mapping={
                codigo: _empacotar(dispositivo)
                for codigo, dispositivo in dispositivos.items()
            },
        )

    for sala_id, aulas in sala_aulas.items():
        pipeline.set(_chave_sala_aulas(sala_id), _empacotar(aulas))

    for aula_id, aluno_ids in aula_alunos.items():
        chave = _chave_aula_alunos(aula_id)
        if aluno_ids:
            pipeline.sadd(chave, *aluno_ids)

    if embeddings:
        pipeline.hset(FACE_EMBEDDINGS, mapping=embeddings)

    pipeline.execute()
