from datetime import datetime, timezone
import json
import logging
from queue import Empty, Full, Queue
from socket import timeout as SocketTimeout
from threading import Event, Thread
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.config import (
    INTERSCITY_API_URL,
    INTERSCITY_QUEUE_MAX,
    INTERSCITY_TIMEOUT_SECONDS,
    INTERSCITY_WORKERS,
    RESOURCE_ADAPTOR_PATH,
)
from app.redis_store import obter_dispositivo_por_codigo
from tcc_evidencias import registrar_evento, registrar_tempo

logger = logging.getLogger(__name__)


def _timestamp(valor: str | None) -> str:
    try:
        data_hora = (
            datetime.fromisoformat(valor.replace("Z", "+00:00"))
            if valor
            else datetime.now(timezone.utc)
        )
    except ValueError:
        data_hora = datetime.now(timezone.utc)

    if data_hora.tzinfo is None:
        data_hora = data_hora.replace(tzinfo=timezone.utc)

    return (
        data_hora.astimezone(timezone.utc)
        .replace(tzinfo=None)
        .isoformat(timespec="milliseconds")
    )


def publicar_capacidades_dispositivo(
    dispositivo_codigo: str,
    capacidades: dict,
    timestamp: str | None = None,
) -> bool:
    dispositivo = obter_dispositivo_por_codigo(dispositivo_codigo)
    recurso_uuid = dispositivo.get("interscity_uuid") if dispositivo else None
    if not recurso_uuid or not INTERSCITY_API_URL or not RESOURCE_ADAPTOR_PATH:
        return False

    valores = {
        chave: valor for chave, valor in capacidades.items() if valor is not None
    }
    if not valores:
        return False

    ts = _timestamp(timestamp)
    url = (
        f"{INTERSCITY_API_URL.rstrip('/')}/"
        f"{RESOURCE_ADAPTOR_PATH.strip('/')}/{recurso_uuid}/data"
    )
    payload = {
        "data": {
            key: [{"value": value, "timestamp": ts}] for key, value in valores.items()
        }
    }
    requisicao = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )

    resposta = None
    try:
        resposta = urlopen(requisicao, timeout=INTERSCITY_TIMEOUT_SECONDS)
        return True
    except (TimeoutError, SocketTimeout, HTTPError, URLError, OSError) as exc:
        logger.warning(
            "falha ao publicar no interscity dispositivo_codigo=%s resource=%s error=%s",
            dispositivo_codigo,
            recurso_uuid,
            exc,
        )
        return False
    finally:
        if resposta and hasattr(resposta, "close"):
            resposta.close()


class PublicadorInterscity:
    def __init__(
        self,
        tamanho_fila: int = INTERSCITY_QUEUE_MAX,
        trabalhadores: int = INTERSCITY_WORKERS,
    ) -> None:
        self._fila: Queue[tuple[str, dict, str | None]] = Queue(maxsize=tamanho_fila)
        self._parar = Event()
        self._trabalhadores = max(1, trabalhadores)
        self._threads: list[Thread] = []

    def iniciar(self) -> None:
        if self._threads:
            return
        self._parar.clear()
        for indice in range(self._trabalhadores):
            thread = Thread(
                target=self._executar,
                name=f"interscity-publicador-{indice + 1}",
                daemon=True,
            )
            thread.start()
            self._threads.append(thread)

    def parar(self) -> None:
        self._parar.set()
        for thread in self._threads:
            thread.join(timeout=2)
        self._threads.clear()

    def enfileirar(
        self,
        dispositivo_codigo: str,
        capacidades: dict,
        timestamp: str | None = None,
    ) -> bool:
        try:
            self._fila.put_nowait((dispositivo_codigo, capacidades, timestamp))
        except Full:
            registrar_evento(
                "interscity_publicacao",
                "edge-app",
                status="falha",
                origem=dispositivo_codigo,
                detalhes={"motivo": "fila_cheia"},
            )
            logger.warning(
                "fila interscity cheia; publicacao descartada dispositivo_codigo=%s",
                dispositivo_codigo,
            )
            return False
        return True

    def _executar(self) -> None:
        while not self._parar.is_set() or not self._fila.empty():
            try:
                dispositivo_codigo, capacidades, timestamp = self._fila.get(timeout=0.2)
            except Empty:
                continue

            inicio = time.perf_counter()
            try:
                sucesso = publicar_capacidades_dispositivo(
                    dispositivo_codigo,
                    capacidades,
                    timestamp,
                )
                registrar_tempo(
                    "interscity_publicacao_ms",
                    (time.perf_counter() - inicio) * 1000,
                    "edge-app",
                    status="sucesso" if sucesso else "falha",
                    origem=dispositivo_codigo,
                    detalhes={"capacidades": sorted(capacidades.keys())},
                )
            except Exception:
                registrar_tempo(
                    "interscity_publicacao_ms",
                    (time.perf_counter() - inicio) * 1000,
                    "edge-app",
                    status="falha",
                    origem=dispositivo_codigo,
                    detalhes={"capacidades": sorted(capacidades.keys())},
                )
                logger.exception(
                    "erro inesperado no worker interscity dispositivo_codigo=%s",
                    dispositivo_codigo,
                )
            finally:
                self._fila.task_done()
