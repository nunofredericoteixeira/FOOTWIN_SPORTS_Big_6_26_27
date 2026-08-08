#!/bin/bash

set -u

PROJECT_DIR="/Users/admin/PycharmProjects/pythonProject/FOOTWIN_SPORTS_Big_6_26_27"
PYTHON_BIN="$PROJECT_DIR/.venv/bin/python"
LOG_DIR="$PROJECT_DIR/logs"
LOCK_DIR="/tmp/footwin_lineup_prediction_cycle.lock"

mkdir -p "$LOG_DIR"

TIMESTAMP="$(date '+%Y-%m-%d %H:%M:%S %Z')"

echo
echo "===================================================================================================="
echo "FOOTWIN — INÍCIO DO CICLO: $TIMESTAMP"
echo "===================================================================================================="

if ! mkdir "$LOCK_DIR" 2>/dev/null; then
    echo "Já existe outro ciclo em execução. Esta execução será ignorada."
    exit 0
fi

cleanup() {
    rmdir "$LOCK_DIR" 2>/dev/null || true
}

trap cleanup EXIT INT TERM

cd "$PROJECT_DIR" || {
    echo "ERRO: não foi possível entrar em $PROJECT_DIR"
    exit 1
}

if [ ! -x "$PYTHON_BIN" ]; then
    echo "ERRO: Python do ambiente virtual não encontrado:"
    echo "$PYTHON_BIN"
    exit 1
fi

export PYTHONPATH="$PROJECT_DIR"
export TZ="Europe/Lisbon"
export PYTHONUNBUFFERED="1"

"$PYTHON_BIN" run_lineup_prediction_cycle.py \
    --season "2026/27" \
    --window-start 75 \
    --window-end 5

EXIT_CODE=$?

echo
echo "Código de saída: $EXIT_CODE"
echo "FOOTWIN — FIM DO CICLO: $(date '+%Y-%m-%d %H:%M:%S %Z')"
echo "===================================================================================================="

exit "$EXIT_CODE"
