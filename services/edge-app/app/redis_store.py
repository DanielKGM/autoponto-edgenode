from datetime import datetime, timezone
import json
import msgpack
import redis

from app.config import MAX_FRAME_QUEUE, REDIS_HOST, REDIS_PORT
from app.models import FrameQueueItem

QUEUE_FRAMES = "queue:frames"
QUEUE_ATTENDANCE_EVENTS = "queue:eventos_presenca"
FACE_EMBEDDINGS = "face:embeddings"
DISPOSITIVO_STATUS_PREFIX = "dispositivo:"
DISPOSITIVO_STATUS_SUFFIX = ":status"


def get_redis(decode_responses: bool = False) -> redis.Redis:
    return redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        decode_responses=decode_responses,
    )


def queue_length() -> int:
    return int(get_redis().llen(QUEUE_FRAMES))


def is_frame_queue_full() -> bool:
    return queue_length() >= MAX_FRAME_QUEUE


def enqueue_frame(
    dispositivo_id: str,
    sala_id: str,
    aula_id: str,
    frame_bytes: bytes,
) -> int:
    item = FrameQueueItem(
        dispositivo_id=dispositivo_id,
        sala_id=sala_id,
        aula_id=aula_id,
        received_at=datetime.now(timezone.utc),
        frame=frame_bytes,
    )
    client = get_redis()
    client.rpush(QUEUE_FRAMES, msgpack.packb(item.to_queue_payload(), use_bin_type=True))
    return queue_length()


def save_device_status(dispositivo_id: str, state: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    data = {
        "dispositivoId": dispositivo_id,
        "status": state.strip().lower(),
        "reportadoEm": now,
    }
    client = get_redis(decode_responses=True)
    client.set(
        f"{DISPOSITIVO_STATUS_PREFIX}{dispositivo_id}{DISPOSITIVO_STATUS_SUFFIX}",
        json.dumps(data),
    )
    client.hset("dispositivos:last_seen", dispositivo_id, now)


def iter_device_statuses() -> list[dict]:
    statuses = []
    client = get_redis(decode_responses=True)
    for key in client.scan_iter(
        f"{DISPOSITIVO_STATUS_PREFIX}*{DISPOSITIVO_STATUS_SUFFIX}"
    ):
        raw = client.get(key)
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue

        dispositivo_id = data.get("dispositivoId")
        status = data.get("status")
        reportado_em = data.get("reportadoEm")
        if dispositivo_id and status and reportado_em:
            statuses.append(
                {
                    "dispositivo_id": dispositivo_id,
                    "status": status,
                    "reportado_em": reportado_em,
                }
            )

    return statuses


def replace_runtime_cache(aula_alunos: dict[str, list[str]], embeddings: dict[str, bytes]) -> None:
    client = get_redis()
    pipe = client.pipeline()
    for key in client.scan_iter("aula:*:alunos"):
        pipe.delete(key)
    pipe.delete(FACE_EMBEDDINGS)

    for aula_id, aluno_ids in aula_alunos.items():
        key = f"aula:{aula_id}:alunos"
        if aluno_ids:
            pipe.sadd(key, *aluno_ids)

    if embeddings:
        pipe.hset(FACE_EMBEDDINGS, mapping=embeddings)

    pipe.execute()
