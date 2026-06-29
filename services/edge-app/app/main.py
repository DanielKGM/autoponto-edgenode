from contextlib import asynccontextmanager
import asyncio
import logging
import time

from fastapi import Depends, FastAPI, Header, HTTPException, Request

from app.attendance_consumer import consumir_eventos_presenca
from app.config import EDGE_SHARED_AUTH, LOG_LEVEL
from app.interscity import PublicadorInterscity
from app.mqtt import criar_listener_mqtt
from app.redis_store import (
    aula_atual_da_sala,
    calcular_contexto_dispositivo,
    enfileirar_frame,
    fila_frames_cheia,
    obter_dispositivo_por_codigo,
    snapshot_redis_valido,
)
from tcc_evidencias import registrar_tempo

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)
logger = logging.getLogger("edge-app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not snapshot_redis_valido():
        logger.warning("snapshot redis ausente ou expirado")
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


@app.middleware("http")
async def registrar_metricas_http(request: Request, call_next):
    metricas = {
        ("/context", "GET"): "http_context_ms",
        ("/frame", "POST"): "http_frame_ms",
    }
    metrica = metricas.get((request.url.path, request.method))
    if not metrica:
        return await call_next(request)

    inicio = time.perf_counter()
    status_code = 500
    try:
        resposta = await call_next(request)
        status_code = resposta.status_code
        return resposta
    finally:
        registrar_tempo(
            metrica,
            (time.perf_counter() - inicio) * 1000,
            "edge-app",
            status="sucesso" if status_code < 400 else "falha",
            origem=request.headers.get("x-device-id", ""),
            detalhes={"metodo": request.method, "status_code": status_code},
        )


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
    if not snapshot_redis_valido():
        logger.info("context empty device=%s reason=snapshot_expired", x_device_id)
        return {"lesson_name": "", "msRemaining": 0, "msForNext": 0}

    contexto = calcular_contexto_dispositivo(x_device_id)
    logger.info(
        "context device=%s lesson=%s msRemaining=%s msForNext=%s",
        x_device_id,
        contexto["lesson_name"],
        contexto["msRemaining"],
        contexto["msForNext"],
    )
    return contexto


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
    if not snapshot_redis_valido():
        logger.info("frame ignored device=%s reason=snapshot_expired", x_device_id)
        return {"ok": False, "reason": "snapshot_expired"}

    dispositivo = obter_dispositivo_por_codigo(x_device_id)
    if not dispositivo:
        logger.info("frame ignored device=%s reason=unknown_device", x_device_id)
        return {"ok": False, "reason": "unknown_device"}

    aula = aula_atual_da_sala(dispositivo["sala_id"])
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
        dispositivo["dispositivo_id"],
        x_device_id,
        aula["sala_id"],
        aula["id"],
        corpo,
    )
    logger.info(
        "frame accepted device=%s sala=%s aula=%s bytes=%d queue_len=%d",
        x_device_id,
        aula["sala_id"],
        aula["id"],
        len(corpo),
        tamanho_fila,
    )
    return {"ok": True, "queue_len": tamanho_fila}
