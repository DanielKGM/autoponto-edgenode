#!/usr/bin/env bash
set -Eeuo pipefail

DIRETORIO_SCRIPT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RAIZ_REPOSITORIO="$(cd "${DIRETORIO_SCRIPT}/.." && pwd)"
CAMINHO_JSON="${RAIZ_REPOSITORIO}/data/horarios_ufma_fallback.json"
ANTECEDENCIA_MINUTOS="${ANTECEDENCIA_MINUTOS:-5}"
SIMULAR=0
AGENDAR_REBOOT=1

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)
      SIMULAR=1
      shift
      ;;
    --json)
      CAMINHO_JSON="$2"
      shift 2
      ;;
    --antecedencia-minutos)
      ANTECEDENCIA_MINUTOS="$2"
      shift 2
      ;;
    --sem-reboot)
      AGENDAR_REBOOT=0
      shift
      ;;
    *)
      echo "Argumento desconhecido: $1" >&2
      exit 2
      ;;
  esac
done

if [[ ! -f "${CAMINHO_JSON}" ]]; then
  echo "JSON de horarios nao encontrado: ${CAMINHO_JSON}" >&2
  exit 1
fi

BLOCO_AGENDAMENTOS="$(
  python3 - "${CAMINHO_JSON}" "${ANTECEDENCIA_MINUTOS}" "${RAIZ_REPOSITORIO}" "${AGENDAR_REBOOT}" <<'PY'
import json
import shlex
import sys
from datetime import datetime, timedelta
from pathlib import Path

caminho_json, antecedencia_texto, raiz_repositorio, agendar_reboot_texto = sys.argv[1:]
antecedencia_minutos = int(antecedencia_texto)
agendar_reboot = agendar_reboot_texto == "1"
horarios = json.loads(Path(caminho_json).read_text(encoding="utf-8"))

script_completo = shlex.quote(f"{raiz_repositorio}/scripts/sincronizacao-completa-edge.sh")
script_incremental = shlex.quote(f"{raiz_repositorio}/scripts/sincronizacao-incremental-edge.sh")
log_completo = shlex.quote(f"{raiz_repositorio}/data/logs/sincronizacao-completa.log")
log_incremental = shlex.quote(f"{raiz_repositorio}/data/logs/sincronizacao-incremental.log")

print("# AUTOPONTO EDGE SYNC BEGIN")
if agendar_reboot:
    print(f"@reboot sleep 60 && {script_completo} >> {log_completo} 2>&1")
print(f"0 0 * * * {script_completo} >> {log_completo} 2>&1")

por_horario: dict[tuple[int, int], list[str]] = {}
for item in horarios:
    codigo = str(item["codigo"])
    hora, minuto = [int(parte) for parte in str(item["horario_inicio"])[:5].split(":")]
    agendado = datetime(2000, 1, 1, hora, minuto) - timedelta(
        minutes=antecedencia_minutos
    )
    por_horario.setdefault((agendado.hour, agendado.minute), []).append(codigo)

for (hora, minuto), codigos in sorted(por_horario.items()):
    comentario = ",".join(sorted(codigos))
    print(
        f"{minuto} {hora} * * * {script_incremental} >> {log_incremental} 2>&1 "
        f"# slots {comentario}, antecedencia {antecedencia_minutos}min"
    )
print("# AUTOPONTO EDGE SYNC END")
PY
)"

CRONTAB_ATUAL="$(crontab -l 2>/dev/null || true)"
CRONTAB_SEM_BLOCOS="$(
  printf "%s\n" "${CRONTAB_ATUAL}" |
    sed '/^# AUTOPONTO EDGE TAREFAS BEGIN$/,/^# AUTOPONTO EDGE TAREFAS END$/d' |
    sed '/^# AUTOPONTO EDGE SYNC BEGIN$/,/^# AUTOPONTO EDGE SYNC END$/d'
)"

NOVO_CRONTAB="$(
  printf "%s\n" "${CRONTAB_SEM_BLOCOS}" | sed '/^[[:space:]]*$/d'
  printf "%s\n" "${BLOCO_AGENDAMENTOS}"
)"

if [[ "${SIMULAR}" == "1" ]]; then
  printf "%s\n" "${NOVO_CRONTAB}"
  exit 0
fi

mkdir -p "${RAIZ_REPOSITORIO}/data/logs"
printf "%s\n" "${NOVO_CRONTAB}" | crontab -
echo "Agendamentos AutoPonto Edge atualizados na crontab do usuario atual."
