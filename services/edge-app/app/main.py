from contextlib import asynccontextmanager
import asyncio
import logging

from fastapi import Depends, FastAPI, Header, HTTPException, Request

from app.attendance_consumer import consume_attendance_events
from app.config import EDGE_SHARED_AUTH, LOG_LEVEL
from app.db import init_db
from app.mqtt_listener import build_status_listener
from app.redis_store import enqueue_frame, is_frame_queue_full
from app.repository import (
    compute_context_for_device,
    get_current_lesson_for_device,
    rebuild_runtime_cache,
)
from app.sync import run_sync_loop

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)
logger = logging.getLogger("edge-app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    rebuild_runtime_cache()
    stop_event = asyncio.Event()
    mqtt_client = build_status_listener()
    mqtt_client.loop_start()
    tasks = [
        asyncio.create_task(consume_attendance_events(stop_event, mqtt_client)),
        asyncio.create_task(run_sync_loop(stop_event)),
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


app = FastAPI(title="edge-app", lifespan=lifespan)


def validate_auth(x_auth: str = Header(default="")) -> None:
    if not x_auth:
        raise HTTPException(status_code=401, detail="missing X-Auth")
    if x_auth != EDGE_SHARED_AUTH:
        raise HTTPException(status_code=401, detail="invalid X-Auth")


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/context")
def get_context(
    x_device_id: str = Header(default=""),
    _: None = Depends(validate_auth),
):
    if not x_device_id:
        raise HTTPException(status_code=400, detail="missing X-Device-Id")

    context = compute_context_for_device(x_device_id)
    logger.info(
        "context device=%s locale=%s lesson=%s msRemaining=%s msForNext=%s",
        x_device_id,
        context.locale_id,
        context.lesson_id,
        context.ms_remaining,
        context.ms_for_next,
    )
    return context.to_payload()


@app.post("/frame")
async def post_frame(
    request: Request,
    x_device_id: str = Header(default=""),
    _: None = Depends(validate_auth),
):
    if not x_device_id:
        raise HTTPException(status_code=400, detail="missing X-Device-Id")

    content_type = request.headers.get("content-type", "")
    if content_type != "image/jpeg":
        raise HTTPException(status_code=415, detail="expected image/jpeg")

    lesson = get_current_lesson_for_device(x_device_id)
    if not lesson:
        logger.info("frame ignored device=%s reason=no_current_lesson", x_device_id)
        return {"ok": False, "reason": "no_current_lesson"}

    if is_frame_queue_full():
        logger.warning("frame rejected device=%s reason=queue_full", x_device_id)
        raise HTTPException(status_code=503, detail="frame queue full")

    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="empty body")

    queue_len = enqueue_frame(
        x_device_id,
        lesson.locale_id,
        lesson.id,
        body,
    )
    logger.info(
        "frame accepted device=%s locale=%s lesson=%s bytes=%d queue_len=%d",
        x_device_id,
        lesson.locale_id,
        lesson.id,
        len(body),
        queue_len,
    )
    return {"ok": True, "queue_len": queue_len}
