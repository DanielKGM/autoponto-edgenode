from datetime import datetime, timezone
import json
import logging
from socket import timeout as SocketTimeout
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.config import INTERSCITY_API_URL, RESOURCE_ADAPTOR_PATH
from app.repository import get_device_interscity_uuid

logger = logging.getLogger(__name__)

LOG_CAPABILITIES = ("rssi", "heap_min", "lesson", "remainingms", "nextms")
REQUEST_TIMEOUT_SECONDS = 5


def is_configured() -> bool:
    return bool(INTERSCITY_API_URL and RESOURCE_ADAPTOR_PATH)


def resource_data_url(resource_uuid: str) -> str:
    base = INTERSCITY_API_URL.rstrip("/")
    path = RESOURCE_ADAPTOR_PATH.strip("/")
    return f"{base}/{path}/{resource_uuid}/data"


def interscity_timestamp(value: str | None = None) -> str:
    if value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            parsed = datetime.now(timezone.utc)
    else:
        parsed = datetime.now(timezone.utc)

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    return parsed.astimezone(timezone.utc).replace(tzinfo=None).isoformat(
        timespec="milliseconds"
    )


def build_resource_payload(capabilities: dict, timestamp: str | None = None) -> dict:
    ts = interscity_timestamp(timestamp)
    data = {
        name: [{"value": value, "timestamp": ts}]
        for name, value in capabilities.items()
        if value is not None
    }
    return {"data": data}


def publish_resource_data(
    resource_uuid: str | None,
    capabilities: dict,
    timestamp: str | None = None,
) -> bool:
    if not resource_uuid or not is_configured():
        return False

    payload = build_resource_payload(capabilities, timestamp)
    if not payload["data"]:
        return False

    request = Request(
        resource_data_url(resource_uuid),
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )

    response = None
    try:
        response = urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS)
        return True
    except (TimeoutError, SocketTimeout, HTTPError, URLError, OSError) as exc:
        logger.warning("interscity publish failed resource=%s error=%s", resource_uuid, exc)
        return False
    finally:
        if response and hasattr(response, "close"):
            response.close()


def publish_device_status(
    dispositivo_id: str,
    status: str,
    timestamp: str | None = None,
) -> bool:
    interscity_uuid = get_device_interscity_uuid(dispositivo_id)
    return publish_resource_data(
        interscity_uuid,
        {"status": status.strip().lower()},
        timestamp,
    )


def log_capabilities(payload: dict) -> dict:
    context = payload.get("context") if isinstance(payload.get("context"), dict) else {}
    values = {
        "rssi": payload.get("rssi"),
        "heap_min": payload.get("heap_min"),
        "lesson": payload.get("lesson", context.get("lesson")),
        "remainingms": payload.get(
            "remainingms",
            payload.get("remaining_ms", context.get("remaining_ms")),
        ),
        "nextms": payload.get("nextms", payload.get("next_ms", context.get("next_ms"))),
    }
    return {
        name: values[name]
        for name in LOG_CAPABILITIES
        if values.get(name) is not None
    }


def publish_device_log(
    dispositivo_id: str,
    payload: dict,
    timestamp: str | None = None,
) -> bool:
    interscity_uuid = get_device_interscity_uuid(dispositivo_id)
    return publish_resource_data(
        interscity_uuid,
        log_capabilities(payload),
        timestamp,
    )
