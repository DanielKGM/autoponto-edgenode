import logging
from datetime import datetime
from pathlib import Path
from threading import Lock

from app.config import METRICAS_AVG_US_DISPOSITIVO_CODIGO, METRICAS_AVG_US_PATH

logger = logging.getLogger(__name__)

AVG_US_KEYS = ("loop", "mqtt", "network", "camera", "display")
_lock = Lock()


def registrar_metricas_avg_us(dispositivo_codigo: str, avg_us: dict) -> None:
    if (
        not METRICAS_AVG_US_DISPOSITIVO_CODIGO
        or dispositivo_codigo != METRICAS_AVG_US_DISPOSITIVO_CODIGO
    ):
        return

    valores = {}
    for chave in AVG_US_KEYS:
        valor = avg_us.get(chave)
        if isinstance(valor, bool) or not isinstance(valor, (int, float)):
            continue
        valores[chave] = float(valor)

    if not valores:
        return

    caminho = Path(METRICAS_AVG_US_PATH)
    agora = datetime.now().astimezone().isoformat(timespec="seconds")

    with _lock:
        try:
            estado = _ler_estado(caminho)
            registros = int(estado.get("registros", "0")) + 1
            periodo_inicio = estado.get("periodo_inicio") or agora

            linhas = [
                f"registros={registros}",
                f"periodo_inicio={periodo_inicio}",
                f"periodo_fim={agora}",
            ]
            for chave in AVG_US_KEYS:
                valor_novo = valores.get(chave)
                valor_antigo = estado.get(chave)
                if valor_novo is None and valor_antigo is None:
                    continue
                if valor_novo is None:
                    media = float(valor_antigo)
                elif valor_antigo is None:
                    media = valor_novo
                else:
                    media = (float(valor_antigo) + valor_novo) / 2
                linhas.append(f"{chave}={media:.2f}")

            caminho.parent.mkdir(parents=True, exist_ok=True)
            temporario = caminho.with_suffix(f"{caminho.suffix}.tmp")
            temporario.write_text("\n".join(linhas) + "\n", encoding="utf-8")
            temporario.replace(caminho)
        except Exception:
            logger.exception(
                "falha ao salvar metricas avg_us dispositivo_codigo=%s",
                dispositivo_codigo,
            )


def _ler_estado(caminho: Path) -> dict:
    if not caminho.exists():
        return {}
    dados = {}
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        if "=" not in linha:
            continue
        chave, valor = linha.split("=", 1)
        dados[chave.strip()] = valor.strip()
    return dados
