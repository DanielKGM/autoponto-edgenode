from contextlib import asynccontextmanager
import asyncio
import logging

from fastapi import Depends, FastAPI, Header, HTTPException, Request

from app.attendance_consumer import consumir_eventos_presenca
from app.config import EDGE_SHARED_AUTH, LOG_LEVEL
from app.db import inicializar_banco
from app.interscity import PublicadorInterscity
from app.mqtt import criar_listener_mqtt
from app.redis_store import enfileirar_frame, fila_frames_cheia
from app.repository import (
    buscar_aula_atual_por_dispositivo,
    buscar_uuid_dispositivo_por_codigo,
    calcular_contexto_do_dispositivo,
    reconstruir_cache_redis,
)

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)
logger = logging.getLogger("edge-app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    inicializar_banco()

    reconstruir_cache_redis()
    stop_event = asyncio.Event()

    publicador_interscity = PublicadorInterscity()
    publicador_interscity.iniciar()
    mqtt_client = criar_listener_mqtt(publicador_interscity.enfileirar)
    mqtt_client.loop_start()
    tasks = [
        asyncio.create_task(consumir_eventos_presenca(stop_event, mqtt_client)),
    ]
    logger.info("edge-app started")
    try:
        yield
    finally:
        stop_event.set()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        mqtt_client.loop_stop()
        mqtt_client.disconnect()
        publicador_interscity.parar()


app = FastAPI(title="edge-app", lifespan=lifespan)


def validar_autenticacao(x_auth: str = Header(default="")) -> None:
    if not x_auth:
        raise HTTPException(status_code=401, detail="missing X-Auth")
    if x_auth != EDGE_SHARED_AUTH:
        raise HTTPException(status_code=401, detail="invalid X-Auth")


@app.get("/health")
def saude():
    return {"ok": True}


@app.get("/context")
def obter_contexto(
    x_device_id: str = Header(default=""),
    _: None = Depends(validar_autenticacao),
):
    if not x_device_id:
        raise HTTPException(status_code=400, detail="missing X-Device-Id")

    contexto = calcular_contexto_do_dispositivo(x_device_id)
    logger.info(
        "context device=%s sala=%s aula=%s msRemaining=%s msForNext=%s",
        x_device_id,
        contexto.sala_id,
        contexto.aula_id,
        contexto.ms_remaining,
        contexto.ms_for_next,
    )
    return contexto.para_payload()


@app.post("/frame")
async def receber_frame(
    request: Request,
    x_device_id: str = Header(default=""),
    _: None = Depends(validar_autenticacao),
):
    if not x_device_id:
        raise HTTPException(status_code=400, detail="missing X-Device-Id")

    tipo_conteudo = request.headers.get("content-type", "")
    if tipo_conteudo != "image/jpeg":
        raise HTTPException(status_code=415, detail="expected image/jpeg")

    dispositivo_uuid = buscar_uuid_dispositivo_por_codigo(x_device_id)
    if not dispositivo_uuid:
        logger.info("frame ignored device=%s reason=unknown_device", x_device_id)
        return {"ok": False, "reason": "unknown_device"}

    aula = buscar_aula_atual_por_dispositivo(x_device_id)
    if not aula:
        logger.info("frame ignored device=%s reason=no_current_aula", x_device_id)
        return {"ok": False, "reason": "no_current_aula"}

    if fila_frames_cheia():
        logger.warning("frame rejected device=%s reason=queue_full", x_device_id)
        raise HTTPException(status_code=503, detail="frame queue full")

    corpo = await request.body()
    if not corpo:
        raise HTTPException(status_code=400, detail="empty body")

    tamanho_fila = enfileirar_frame(
        dispositivo_uuid,
        x_device_id,
        aula.sala_id,
        aula.id,
        corpo,
    )
    logger.info(
        "frame accepted device=%s sala=%s aula=%s bytes=%d queue_len=%d",
        x_device_id,
        aula.sala_id,
        aula.id,
        len(corpo),
        tamanho_fila,
    )
    return {"ok": True, "queue_len": tamanho_fila}
