from fastapi import FastAPI, Header, HTTPException, Request, Depends
from app.auth import validate_auth
from app.providers import get_locale_id_for_device, get_schedule_for_locale
from app.context_logic import compute_context
from app.redis_queue import enqueue_frame

app = FastAPI(title="edge-api")


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/context")
def get_context(
    x_device_id: str = Header(default=""),
    _: None = Depends(validate_auth),
):
    print("x_device_id =", repr(x_device_id))

    locale_id = get_locale_id_for_device(x_device_id)
    print("locale_id =", repr(locale_id))

    if not locale_id:
        return {
            "lesson_name": "",
            "msRemaining": 0,
            "msForNext": 0,
        }

    schedule = get_schedule_for_locale(locale_id)
    print("schedule =", schedule)

    context = compute_context(schedule)
    print("context =", context)

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

    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="empty body")

    locale_id = get_locale_id_for_device(x_device_id)
    enqueue_frame(x_device_id, locale_id, body)

    return {
        "ok": True,
    }