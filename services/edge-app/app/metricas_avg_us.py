import csv
import logging
from datetime import datetime
from math import isfinite, sqrt
from pathlib import Path
from threading import Lock

from app.config import (
    METRICAS_AVG_US_AMOSTRAS_PATH,
    METRICAS_AVG_US_DISPOSITIVO_CODIGO,
    METRICAS_AVG_US_PATH,
)

logger = logging.getLogger(__name__)

AVG_US_KEYS = ("loop", "mqtt", "network", "camera", "display")
_lock = Lock()


def registrar_metricas_avg_us(
    dispositivo_codigo: str,
    avg_us: dict,
    avg_count: dict,
) -> None:
    if (
        not METRICAS_AVG_US_DISPOSITIVO_CODIGO
        or dispositivo_codigo != METRICAS_AVG_US_DISPOSITIVO_CODIGO
    ):
        return

    valores = {}
    for chave in AVG_US_KEYS:
        valor = avg_us.get(chave)
        peso = avg_count.get(chave)
        if (
            isinstance(valor, bool)
            or not isinstance(valor, (int, float))
            or not isfinite(float(valor))
            or isinstance(peso, bool)
            or not isinstance(peso, (int, float))
            or not isfinite(float(peso))
            or float(peso) <= 0
        ):
            continue
        valores[chave] = (float(valor), float(peso))

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
                "unidade=microssegundos",
                f"registros={registros}",
                f"periodo_inicio={periodo_inicio}",
                f"periodo_fim={agora}",
            ]

            _registrar_amostras(
                Path(METRICAS_AVG_US_AMOSTRAS_PATH),
                agora,
                dispositivo_codigo,
                valores,
            )

            for chave in AVG_US_KEYS:
                amostra_nova = valores.get(chave)
                media_antiga = _float_estado(estado.get(chave))
                peso_antigo = _float_estado(estado.get(f"{chave}_count")) or 0.0
                m2_antigo = _float_estado(estado.get(f"{chave}_m2")) or 0.0

                if amostra_nova is None and media_antiga is None:
                    continue
                if amostra_nova is None:
                    media = media_antiga
                    peso_total = peso_antigo
                    m2 = m2_antigo
                elif media_antiga is None or peso_antigo <= 0:
                    media, peso_total = amostra_nova
                    m2 = 0.0
                else:
                    media_nova, peso_novo = amostra_nova
                    peso_total = peso_antigo + peso_novo
                    diferenca = media_nova - media_antiga
                    media = (
                        (media_antiga * peso_antigo) + (media_nova * peso_novo)
                    ) / peso_total
                    m2 = (
                        m2_antigo
                        + (diferenca * diferenca * peso_antigo * peso_novo)
                        / peso_total
                    )

                linhas.append(f"{chave}={media:.2f}")
                if peso_total > 0:
                    desvio_padrao = sqrt(max(m2 / peso_total, 0.0))
                    linhas.append(f"{chave}_count={_formatar_peso(peso_total)}")
                    linhas.append(f"{chave}_desvio_padrao={desvio_padrao:.2f}")
                    linhas.append(f"{chave}_m2={m2:.6f}")

            caminho.parent.mkdir(parents=True, exist_ok=True)
            temporario = caminho.with_suffix(f"{caminho.suffix}.tmp")
            temporario.write_text("\n".join(linhas) + "\n", encoding="utf-8")
            temporario.replace(caminho)
        except Exception:
            logger.exception(
                "falha ao salvar metricas avg_us dispositivo_codigo=%s",
                dispositivo_codigo,
            )


def _registrar_amostras(
    caminho: Path,
    agora: str,
    dispositivo_codigo: str,
    valores: dict[str, tuple[float, float]],
) -> None:
    if str(caminho) == str(Path(METRICAS_AVG_US_PATH)):
        return

    caminho.parent.mkdir(parents=True, exist_ok=True)
    novo = not caminho.exists() or caminho.stat().st_size == 0
    with caminho.open("a", encoding="utf-8", newline="") as arquivo:
        escritor = csv.writer(arquivo)
        if novo:
            escritor.writerow(
                ["timestamp", "dispositivo_codigo", "metrica", "avg_us", "avg_count"]
            )
        for chave in AVG_US_KEYS:
            amostra = valores.get(chave)
            if amostra is None:
                continue
            media, peso = amostra
            escritor.writerow(
                [
                    agora,
                    dispositivo_codigo,
                    chave,
                    f"{media:.6f}",
                    _formatar_peso(peso),
                ]
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


def _float_estado(valor: str | None) -> float | None:
    if valor is None:
        return None
    try:
        numero = float(valor)
    except ValueError:
        return None
    return numero if isfinite(numero) else None


def _formatar_peso(valor: float) -> str:
    if valor.is_integer():
        return str(int(valor))
    return f"{valor:.6g}"
