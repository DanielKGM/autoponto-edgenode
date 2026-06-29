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
MAX_EVENTOS_PRESENCA_REDIS = _int_env("MAX_EVENTOS_PRESENCA_REDIS", 50000)
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
METRICAS_AVG_US_PATH = os.getenv(
    "METRICAS_AVG_US_PATH",
    "/data/logs/metricas_avg_us.txt",
)
METRICAS_AVG_US_AMOSTRAS_PATH = os.getenv(
    "METRICAS_AVG_US_AMOSTRAS_PATH",
    "/data/logs/metricas_avg_us_amostras.csv",
)
METRICAS_AVG_US_DISPOSITIVO_CODIGO = os.getenv(
    "METRICAS_AVG_US_DISPOSITIVO_CODIGO",
    "",
).strip()
INTERSCITY_QUEUE_MAX = _int_env("INTERSCITY_QUEUE_MAX", 1000)
INTERSCITY_WORKERS = _int_env("INTERSCITY_WORKERS", 1)
INTERSCITY_TIMEOUT_SECONDS = _int_env("INTERSCITY_TIMEOUT_SECONDS", 5)

NODE_UUID = os.getenv("NODE_UUID", "edge-node")
AUTOPONTO_API_URL = os.getenv("AUTOPONTO_API_URL", "").strip().rstrip("/")
AUTOPONTO_API_TOKEN = os.getenv("AUTOPONTO_API_TOKEN", "").strip()
FACE_EMBEDDING_ENCRYPTION_KEY = os.getenv(
    "FACE_EMBEDDING_ENCRYPTION_KEY",
    "",
).strip()
INTERSCITY_API_URL = os.getenv("INTERSCITY_API_URL", "").strip().rstrip("/")
RESOURCE_ADAPTOR_PATH = os.getenv(
    "RESOURCE_ADAPTOR_PATH",
    "/adaptor/resources",
)
