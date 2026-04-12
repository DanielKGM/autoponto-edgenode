from fastapi import FastAPI, Header, HTTPException, Request, Depends
from app.providers import get_locale_id_for_device, get_schedule_for_locale
from app.context_logic import compute_context
from app.redis_queue import enqueue_frame, is_queue_full
import os

app = FastAPI(title="edge-api")


EDGE_SHARED_AUTH = os.getenv("EDGE_SHARED_AUTH")


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
    locale_id = get_locale_id_for_device(x_device_id)
    if not locale_id:
        return {
            "lesson_name": "",
            "msRemaining": 0,
            "msForNext": 0,
        }

    schedule = get_schedule_for_locale(locale_id)
    context = compute_context(schedule)
    return context.to_payload()


@app.post("/frame")
async def post_frame(
    request: Request,
    x_device_id: str = Header(default=""),
    _: None = Depends(validate_auth),
):
    if not x_device_id:
        raise HTTPException(status_code=400, detail="missing X-Device-Id")

    if is_queue_full():
        raise HTTPException(
            status_code=503,
            detail="frame queue full",
        )

    content_type = request.headers.get("content-type", "")
    if content_type != "image/jpeg":
        raise HTTPException(status_code=415, detail="expected image/jpeg")

    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="empty body")

    locale_id = get_locale_id_for_device(x_device_id)
    queue_len = enqueue_frame(x_device_id, locale_id, body)

    return {
        "ok": True,
        "queue_len": queue_len,
    }
