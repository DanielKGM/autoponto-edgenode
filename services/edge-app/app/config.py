from pathlib import Path
import os


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return int(value)


REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = _int_env("REDIS_PORT", 6379)
MQTT_HOST = os.getenv("MQTT_HOST", "mosquitto")
MQTT_PORT = _int_env("MQTT_PORT", 1883)
MQTT_USER = os.getenv("MQTT_USER", "service")
MQTT_PASS = os.getenv("MQTT_PASS", "replace")
EDGE_SHARED_AUTH = os.getenv("EDGE_SHARED_AUTH", "replace")
ZONE_INFO = os.getenv("ZONE_INFO", "America/Fortaleza")
MAX_FRAME_QUEUE = _int_env("MAX_FRAME_QUEUE", 100)
MAX_EVENTOS_PRESENCA_LOCAL = _int_env("MAX_EVENTOS_PRESENCA_LOCAL", 50000)
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
INTERSCITY_QUEUE_MAX = _int_env("INTERSCITY_QUEUE_MAX", 1000)
INTERSCITY_WORKERS = _int_env("INTERSCITY_WORKERS", 1)
INTERSCITY_TIMEOUT_SECONDS = _int_env("INTERSCITY_TIMEOUT_SECONDS", 5)

SQLITE_PATH = Path(os.getenv("SQLITE_PATH", "/data/db.sql"))
NODE_ID = os.getenv("NODE_ID", "edge-node")
AUTOPONTO_API_URL = os.getenv("AUTOPONTO_API_URL", "").rstrip("/")
AUTOPONTO_API_TOKEN = os.getenv("AUTOPONTO_API_TOKEN", "")
INTERSCITY_API_URL = os.getenv("INTERSCITY_API_URL", "").rstrip("/")
RESOURCE_ADAPTOR_PATH = os.getenv(
    "RESOURCE_ADAPTOR_PATH",
    "/adaptor/resources",
)
