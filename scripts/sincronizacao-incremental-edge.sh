#!/usr/bin/env bash
set -Eeuo pipefail

DIRETORIO_SCRIPT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RAIZ_REPOSITORIO="$(cd "${DIRETORIO_SCRIPT}/.." && pwd)"

cd "${RAIZ_REPOSITORIO}"
mkdir -p data/logs

docker compose exec -T edge-app python -m app.sync
