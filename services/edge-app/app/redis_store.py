from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import uuid

import msgpack
import redis

from app.config import (
    MAX_EVENTOS_PRESENCA_REDIS,
    MAX_FRAME_QUEUE,
    REDIS_HOST,
    REDIS_PORT,
    ZONE_INFO,
)

QUEUE_FRAMES = "queue:frames"
QUEUE_ATTENDANCE_EVENTS = "queue:eventos_presenca"

SNAPSHOT_DATA = "snapshot:data"
SNAPSHOT_SYNCED_AT = "snapshot:synced_at"
FACE_EMBEDDINGS = "face:embeddings"
DISPOSITIVOS_POR_CODIGO = "dispositivos:por_codigo"
ALUNOS_POR_ID = "alunos:por_id"
AULA_ALUNOS_PREFIX = "aula:"
AULA_ALUNOS_SUFFIX = ":alunos"
SALA_AULAS_PREFIX = "sala:"
SALA_AULAS_SUFFIX = ":aulas"

PRESENCA_EVENTOS = "presenca:eventos"
PRESENCA_POR_ALUNO_AULA = "presenca:por_aluno_aula"
PRESENCA_PENDENTES = "presenca:pendentes"
PRESENCA_SINCRONIZADAS = "presenca:sincronizadas"

FUSO_HORARIO = ZoneInfo(ZONE_INFO)
STATUS_AULA_INATIVA = ("FECHADA", "CANCELADA")


SALVAR_EVENTO_PRESENCA_LUA = """
local existente = redis.call('HGET', KEYS[2], ARGV[1])
if existente then
  return {existente, 0}
end
redis.call('HSET', KEYS[1], ARGV[2], ARGV[3])
redis.call('HSET', KEYS[2], ARGV[1], ARGV[2])
redis.call('ZADD', KEYS[3], ARGV[4], ARGV[2])
return {ARGV[2], 1}
"""


def obter_redis(decode_responses: bool = False) -> redis.Redis:
    return redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        decode_responses=decode_responses,
    )


def _empacotar(valor) -> bytes:
    return msgpack.packb(valor, use_bin_type=True)


def _desempacotar(valor: bytes | None):
    if valor is None:
        return None
    return msgpack.unpackb(valor, raw=False)


def _texto(valor) -> str | None:
    if valor is None:
        return None
    if isinstance(valor, bytes):
        return valor.decode("utf-8")
    return str(valor)


def converter_data_hora(valor: str) -> datetime:
    data_hora = datetime.fromisoformat(valor.replace("Z", "+00:00"))
    if data_hora.tzinfo is None:
        return data_hora.replace(tzinfo=FUSO_HORARIO)
    return data_hora.astimezone(FUSO_HORARIO)


def snapshot_redis_valido() -> bool:
    return _texto(obter_redis().get(SNAPSHOT_DATA)) == datetime.now(
        FUSO_HORARIO
    ).date().isoformat()


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
    cliente.rpush(QUEUE_FRAMES, _empacotar(item))
    return int(cliente.llen(QUEUE_FRAMES))


def _chave_aula_alunos(aula_id: str) -> str:
    return f"{AULA_ALUNOS_PREFIX}{aula_id}{AULA_ALUNOS_SUFFIX}"


def _chave_sala_aulas(sala_id: str) -> str:
    return f"{SALA_AULAS_PREFIX}{sala_id}{SALA_AULAS_SUFFIX}"


def _validar_mapa(nome: str, valor) -> dict:
    if not isinstance(valor, dict):
        raise ValueError(f"cache_redis.{nome} deve ser um objeto")
    return valor


def _registro_embedding_para_redis(registro: dict) -> bytes:
    aluno_id = registro.get("alunoId")
    embedding = registro.get("embedding")
    if not aluno_id or embedding is None:
        raise ValueError("embedding facial deve incluir alunoId e embedding")
    if not isinstance(embedding, list):
        raise ValueError("embedding facial deve ser uma lista numerica")
    return _empacotar({"alunoId": aluno_id, "embedding": embedding})


def substituir_snapshot_redis(
    cache_redis: dict,
    snapshot_data: str,
    synced_at: str,
) -> None:
    dispositivos = _validar_mapa(
        "dispositivos_por_codigo",
        cache_redis.get("dispositivos_por_codigo", {}),
    )
    aulas_por_sala = _validar_mapa(
        "aulas_por_sala",
        cache_redis.get("aulas_por_sala", {}),
    )
    alunos_por_aula = _validar_mapa(
        "alunos_por_aula",
        cache_redis.get("alunos_por_aula", {}),
    )
    alunos_por_id = _validar_mapa(
        "alunos_por_id",
        cache_redis.get("alunos_por_id", {}),
    )
    embeddings = _validar_mapa(
        "embeddings_faciais",
        cache_redis.get("embeddings_faciais", {}),
    )

    cliente = obter_redis()
    chaves_antigas = [
        DISPOSITIVOS_POR_CODIGO,
        ALUNOS_POR_ID,
        FACE_EMBEDDINGS,
        SNAPSHOT_DATA,
        SNAPSHOT_SYNCED_AT,
    ]
    for padrao in (
        f"{AULA_ALUNOS_PREFIX}*{AULA_ALUNOS_SUFFIX}",
        f"{SALA_AULAS_PREFIX}*{SALA_AULAS_SUFFIX}",
        "dispositivo:*:status",
    ):
        chaves_antigas.extend(cliente.scan_iter(padrao))

    pipeline = cliente.pipeline(transaction=True)
    if chaves_antigas:
        pipeline.delete(*chaves_antigas)

    pipeline.set(SNAPSHOT_DATA, snapshot_data)
    pipeline.set(SNAPSHOT_SYNCED_AT, synced_at)

    if dispositivos:
        pipeline.hset(
            DISPOSITIVOS_POR_CODIGO,
            mapping={
                codigo: _empacotar(dispositivo)
                for codigo, dispositivo in dispositivos.items()
            },
        )

    if alunos_por_id:
        pipeline.hset(
            ALUNOS_POR_ID,
            mapping={
                aluno_id: _empacotar(
                    dados if isinstance(dados, dict) else {"nome": dados}
                )
                for aluno_id, dados in alunos_por_id.items()
            },
        )

    for sala_id, aulas in aulas_por_sala.items():
        pipeline.set(_chave_sala_aulas(sala_id), _empacotar(aulas))

    for aula_id, aluno_ids in alunos_por_aula.items():
        if aluno_ids:
            pipeline.sadd(_chave_aula_alunos(aula_id), *aluno_ids)

    if embeddings:
        pipeline.hset(
            FACE_EMBEDDINGS,
            mapping={
                embedding_id: _registro_embedding_para_redis(registro)
                for embedding_id, registro in embeddings.items()
            },
        )

    pipeline.execute()


def obter_dispositivo_por_codigo(dispositivo_codigo: str) -> dict | None:
    if not snapshot_redis_valido():
        return None
    dispositivo = _desempacotar(
        obter_redis().hget(DISPOSITIVOS_POR_CODIGO, dispositivo_codigo)
    )
    if not dispositivo or not dispositivo.get("ativo"):
        return None
    return dispositivo


def _evento_presenca(cliente, evento_id: str) -> dict | None:
    evento = _desempacotar(cliente.hget(PRESENCA_EVENTOS, evento_id))
    return evento if isinstance(evento, dict) else None


def _aula_atual_e_proxima(
    sala_id: str,
    agora: datetime,
) -> tuple[dict | None, dict | None]:
    proxima_aula = None
    if not snapshot_redis_valido():
        return None, None

    aulas = _desempacotar(obter_redis().get(_chave_sala_aulas(sala_id)))
    if not isinstance(aulas, list):
        return None, None

    for aula in sorted(aulas, key=lambda item: item["inicio"]):
        if aula.get("status") in STATUS_AULA_INATIVA:
            continue
        aula["inicio_data_hora"] = converter_data_hora(aula["inicio"])
        aula["fim_data_hora"] = converter_data_hora(aula["fim"])
        if aula["inicio_data_hora"] <= agora < aula["fim_data_hora"]:
            return aula, None
        if agora < aula["inicio_data_hora"] and proxima_aula is None:
            proxima_aula = aula
    return None, proxima_aula


def aula_atual_da_sala(sala_id: str) -> dict | None:
    aula_atual, _ = _aula_atual_e_proxima(sala_id, datetime.now(FUSO_HORARIO))
    return aula_atual


def calcular_contexto_dispositivo(dispositivo_codigo: str) -> dict:
    dispositivo = obter_dispositivo_por_codigo(dispositivo_codigo)
    if not dispositivo:
        return {"lesson_name": "", "msRemaining": 0, "msForNext": 0}

    sala_id = dispositivo["sala_id"]
    agora = datetime.now(FUSO_HORARIO)
    aula_atual, proxima_aula = _aula_atual_e_proxima(sala_id, agora)
    if aula_atual:
        return {
            "lesson_name": aula_atual["nome"],
            "msRemaining": max(
                int((aula_atual["fim_data_hora"] - agora).total_seconds() * 1000),
                0,
            ),
            "msForNext": 0,
        }
    if proxima_aula:
        return {
            "lesson_name": proxima_aula["nome"],
            "msRemaining": 0,
            "msForNext": max(
                int(
                    (proxima_aula["inicio_data_hora"] - agora).total_seconds() * 1000
                ),
                0,
            ),
        }

    return {"lesson_name": "", "msRemaining": 0, "msForNext": 0}


def salvar_evento_presenca(evento: dict) -> dict:
    cliente = obter_redis()
    evento_id = evento.get("eventId") or str(uuid.uuid4())
    aluno_id = evento["alunoId"]
    aula_id = evento["aulaId"]
    aluno = _desempacotar(cliente.hget(ALUNOS_POR_ID, aluno_id)) or {}
    aluno_aula_chave = f"{aluno_id}:{aula_id}"
    score_presenca = converter_data_hora(evento["recognizedAt"]).timestamp()

    evento_redis = {
        "id": evento_id,
        "aluno_id": aluno_id,
        "aluno_nome": aluno.get("nome") or aluno_id,
        "aula_id": aula_id,
        "dispositivo_id": evento["dispositivoId"],
        "dispositivo_codigo": evento.get("dispositivoCodigo"),
        "reconhecido_em": evento["recognizedAt"],
        "score": float(evento["score"]),
        "_aluno_aula_chave": aluno_aula_chave,
        "_score": score_presenca,
    }

    resultado = cliente.eval(
        SALVAR_EVENTO_PRESENCA_LUA,
        3,
        PRESENCA_EVENTOS,
        PRESENCA_POR_ALUNO_AULA,
        PRESENCA_PENDENTES,
        aluno_aula_chave,
        evento_id,
        _empacotar(evento_redis),
        str(score_presenca),
    )
    evento_id_salvo = _texto(resultado[0])
    evento_salvo = _evento_presenca(cliente, evento_id_salvo)
    if evento_salvo is None:
        raise RuntimeError("evento de presenca nao foi armazenado")

    return {
        "id": evento_salvo["id"],
        "aluno_id": evento_salvo["aluno_id"],
        "aluno_nome": evento_salvo.get("aluno_nome") or evento_salvo["aluno_id"],
        "aula_id": evento_salvo["aula_id"],
        "dispositivo_id": evento_salvo["dispositivo_id"],
        "dispositivo_codigo": evento_salvo.get("dispositivo_codigo"),
        "reconhecido_em": evento_salvo["reconhecido_em"],
        "score": evento_salvo["score"],
        "novo": bool(int(resultado[1])),
    }


def obter_eventos_presenca_pendentes(
    ids: list[str] | None = None,
    limite: int = 100,
) -> list[dict]:
    cliente = obter_redis()
    if ids is None:
        ids_eventos = [
            _texto(valor)
            for valor in cliente.zrange(PRESENCA_PENDENTES, 0, limite - 1)
        ]
    else:
        ids_eventos = [
            evento_id
            for evento_id in ids
            if cliente.zscore(PRESENCA_PENDENTES, evento_id) is not None
        ]

    eventos = []
    for evento_id in ids_eventos:
        if not evento_id:
            continue
        evento = _evento_presenca(cliente, evento_id)
        if evento:
            eventos.append(evento)
    return eventos


def podar_eventos_presenca_sincronizados() -> None:
    if MAX_EVENTOS_PRESENCA_REDIS <= 0:
        return

    cliente = obter_redis()
    excedente = int(cliente.zcard(PRESENCA_SINCRONIZADAS)) - MAX_EVENTOS_PRESENCA_REDIS
    if excedente <= 0:
        return

    ids_remover = [
        _texto(evento_id)
        for evento_id in cliente.zrange(PRESENCA_SINCRONIZADAS, 0, excedente - 1)
    ]
    pipeline = cliente.pipeline(transaction=True)
    for evento_id in ids_remover:
        if not evento_id:
            continue
        evento = _evento_presenca(cliente, evento_id)
        if evento and evento.get("_aluno_aula_chave"):
            pipeline.hdel(PRESENCA_POR_ALUNO_AULA, evento["_aluno_aula_chave"])
        pipeline.hdel(PRESENCA_EVENTOS, evento_id)
        pipeline.zrem(PRESENCA_SINCRONIZADAS, evento_id)
    pipeline.execute()


def marcar_eventos_presenca_sincronizados(ids: list[str]) -> None:
    if not ids:
        return

    cliente = obter_redis()
    pipeline = cliente.pipeline(transaction=True)
    for evento_id in ids:
        evento = _evento_presenca(cliente, evento_id)
        pipeline.zrem(PRESENCA_PENDENTES, evento_id)
        if evento:
            pipeline.zadd(
                PRESENCA_SINCRONIZADAS,
                {evento_id: float(evento.get("_score", 0))},
            )
    pipeline.execute()
    podar_eventos_presenca_sincronizados()
