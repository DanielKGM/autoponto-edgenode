from datetime import datetime, timezone
import json
import logging
from socket import timeout as SocketTimeout
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.config import INTERSCITY_API_URL, RESOURCE_ADAPTOR_PATH
from app.repository import get_device_interscity_uuid

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT_SECONDS = 5


def _timestamp(value: str | None) -> str:
    try:
        parsed = (
            datetime.fromisoformat(value.replace("Z", "+00:00"))
            if value
            else datetime.now(timezone.utc)
        )
    except ValueError:
        parsed = datetime.now(timezone.utc)

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    return (
        parsed.astimezone(timezone.utc)
        .replace(tzinfo=None)
        .isoformat(timespec="milliseconds")
    )


def publish_device_capabilities(
    dispositivo_id: str,
    capabilities: dict,
    timestamp: str | None = None,
) -> bool:
    resource_uuid = get_device_interscity_uuid(dispositivo_id)
    if not resource_uuid or not INTERSCITY_API_URL or not RESOURCE_ADAPTOR_PATH:
        return False

    values = {key: value for key, value in capabilities.items() if value is not None}
    if not values:
        return False

    ts = _timestamp(timestamp)
    url = (
        f"{INTERSCITY_API_URL.rstrip('/')}/"
        f"{RESOURCE_ADAPTOR_PATH.strip('/')}/{resource_uuid}/data"
    )
    payload = {
        "data": {
            key: [{"value": value, "timestamp": ts}]
            for key, value in values.items()
        }
    }
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )

    response = None
    try:
        response = urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS)
        return True
    except (TimeoutError, SocketTimeout, HTTPError, URLError, OSError) as exc:
        logger.warning(
            "interscity publish failed device=%s resource=%s error=%s",
            dispositivo_id,
            resource_uuid,
            exc,
        )
        return False
    finally:
        if response and hasattr(response, "close"):
            response.close()
