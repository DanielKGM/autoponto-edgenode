from __future__ import annotations

import csv
import json
import logging
import math
import os
import statistics
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from threading import Lock

try:
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None


logger = logging.getLogger(__name__)

CSV_FIELDS = (
    "timestamp",
    "servico",
    "metrica",
    "unidade",
    "valor",
    "status",
    "origem",
    "detalhes",
)

_lock = Lock()


def registrar_tempo(
    metrica: str,
    valor_ms: float,
    servico: str,
    status: str = "sucesso",
    origem: str = "",
    detalhes: dict | None = None,
) -> None:
    registrar_valor(
        metrica=metrica,
        valor=valor_ms,
        unidade="ms",
        servico=servico,
        status=status,
        origem=origem,
        detalhes=detalhes,
    )


def registrar_evento(
    metrica: str,
    servico: str,
    status: str,
    origem: str = "",
    detalhes: dict | None = None,
) -> None:
    registrar_valor(
        metrica=metrica,
        valor=None,
        unidade="evento",
        servico=servico,
        status=status,
        origem=origem,
        detalhes=detalhes,
    )


def registrar_valor(
    metrica: str,
    valor: float | int | None,
    unidade: str,
    servico: str,
    status: str = "sucesso",
    origem: str = "",
    detalhes: dict | None = None,
) -> None:
    if not _habilitado():
        return

    try:
        diretorio = _diretorio()
        diretorio.mkdir(parents=True, exist_ok=True)
        amostras = diretorio / "metricas_amostras.csv"
        resumo = diretorio / "metricas_resumo.txt"
        lockfile = diretorio / ".metricas.lock"
        linha = {
            "timestamp": datetime.now().astimezone().isoformat(timespec="milliseconds"),
            "servico": servico,
            "metrica": metrica,
            "unidade": unidade,
            "valor": _formatar_valor(valor),
            "status": status,
            "origem": origem or "",
            "detalhes": json.dumps(
                detalhes or {},
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            ),
        }

        with _lock:
            with lockfile.open("a+", encoding="utf-8") as arquivo_lock:
                with _bloqueio_arquivo(arquivo_lock):
                    novo = not amostras.exists() or amostras.stat().st_size == 0
                    with amostras.open("a", encoding="utf-8", newline="") as arquivo:
                        escritor = csv.DictWriter(arquivo, fieldnames=CSV_FIELDS)
                        if novo:
                            escritor.writeheader()
                        escritor.writerow(linha)
                    _atualizar_resumo(amostras, resumo)
    except Exception:
        logger.exception("falha ao registrar evidencia tcc metrica=%s", metrica)


def _habilitado() -> bool:
    valor = os.getenv("TCC_EVIDENCIAS_ENABLED", "0").strip().lower()
    return valor not in {"", "0", "false", "no", "nao", "off"}


def _diretorio() -> Path:
    return Path(os.getenv("TCC_EVIDENCIAS_DIR", "/data/logs/tcc"))


@contextmanager
def _bloqueio_arquivo(arquivo):
    if fcntl is None:
        yield
        return

    fcntl.flock(arquivo.fileno(), fcntl.LOCK_EX)
    try:
        yield
    finally:
        fcntl.flock(arquivo.fileno(), fcntl.LOCK_UN)


def _formatar_valor(valor: float | int | None) -> str:
    if valor is None or isinstance(valor, bool):
        return ""
    numero = float(valor)
    if not math.isfinite(numero):
        return ""
    return f"{numero:.6f}".rstrip("0").rstrip(".")


def _atualizar_resumo(amostras: Path, resumo: Path) -> None:
    grupos: dict[tuple[str, str, str], dict] = {}
    total = 0

    with amostras.open("r", encoding="utf-8", newline="") as arquivo:
        for linha in csv.DictReader(arquivo):
            total += 1
            chave = (
                linha.get("metrica", ""),
                linha.get("servico", ""),
                linha.get("unidade", ""),
            )
            grupo = grupos.setdefault(
                chave,
                {
                    "valores": [],
                    "sucesso": 0,
                    "falha": 0,
                    "outros": 0,
                    "amostras": 0,
                },
            )
            grupo["amostras"] += 1
            status = (linha.get("status") or "").lower()
            if status in {"sucesso", "ok", "aceito"}:
                grupo["sucesso"] += 1
            elif status in {"falha", "erro", "failure"} or status.startswith("falha"):
                grupo["falha"] += 1
            else:
                grupo["outros"] += 1

            try:
                valor = float(linha.get("valor") or "")
            except ValueError:
                continue
            if math.isfinite(valor):
                grupo["valores"].append(valor)

    linhas = [
        f"gerado_em={datetime.now().astimezone().isoformat(timespec='seconds')}",
        f"arquivo_amostras={amostras}",
        f"amostras={total}",
        "desvio_padrao=amostral",
        "",
        "metrica|servico|unidade|amostras|media|desvio_padrao|sucesso|falha|outros",
    ]

    for (metrica, servico, unidade), grupo in sorted(grupos.items()):
        valores = grupo["valores"]
        if valores:
            media = f"{statistics.fmean(valores):.3f}"
            desvio = (
                f"{statistics.stdev(valores):.3f}"
                if len(valores) > 1
                else "0.000"
            )
        else:
            media = ""
            desvio = ""

        linhas.append(
            "|".join(
                [
                    metrica,
                    servico,
                    unidade,
                    str(grupo["amostras"]),
                    media,
                    desvio,
                    str(grupo["sucesso"]),
                    str(grupo["falha"]),
                    str(grupo["outros"]),
                ]
            )
        )

    resumo.write_text("\n".join(linhas) + "\n", encoding="utf-8")
