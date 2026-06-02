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
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

SQLITE_PATH = Path(os.getenv("SQLITE_PATH", "/data/bd.db"))
NODE_ID = os.getenv("NODE_ID", "edge-node")
MAIN_API_URL = os.getenv("MAIN_API_URL", "").rstrip("/")
MAIN_API_TOKEN = os.getenv("MAIN_API_TOKEN", "")
SYNC_INTERVAL_SECONDS = _int_env("SYNC_INTERVAL_SECONDS", 60)
