#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"

echo "============================================================================"
echo "  MEREDIAN — Follow-the-Sun Engineering Memory (macOS / Linux Launcher)"
echo "============================================================================"

if [ ! -f ".env" ] && [ -f ".env.example" ]; then
  echo "[Meredian] Creating default .env from .env.example..."
  cp .env.example .env
fi

export PYTHONPATH=.
MEREDIAN_HOST="${MEREDIAN_API_HOST:-127.0.0.1}"
MEREDIAN_PORT="${MEREDIAN_API_PORT:-8000}"

if [ -x ".venv/bin/python" ]; then
  PYTHON_CMD=".venv/bin/python"
elif [ -n "$VIRTUAL_ENV" ] && [ -x "$VIRTUAL_ENV/bin/python" ]; then
  PYTHON_CMD="$VIRTUAL_ENV/bin/python"
elif command -v python3.11 >/dev/null 2>&1; then
  PYTHON_CMD="python3.11"
else
  PYTHON_CMD="python3"
fi

echo "[Meredian] Starting Local Hindsight Server on http://127.0.0.1:8888 using ${PYTHON_CMD} ..."
"$PYTHON_CMD" scripts/hindsight_local_server.py >/dev/null 2>&1 &
HINDSIGHT_PID=$!

cleanup() {
  if kill -0 "$HINDSIGHT_PID" >/dev/null 2>&1; then
    kill "$HINDSIGHT_PID" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT INT TERM

URL="http://${MEREDIAN_HOST}:${MEREDIAN_PORT}"
echo "[Meredian] Opening ${URL} ..."
if command -v open >/dev/null 2>&1; then
  (sleep 1.5 && open "$URL") &
elif command -v xdg-open >/dev/null 2>&1; then
  (sleep 1.5 && xdg-open "$URL") &
fi

echo "[Meredian] Starting Meredian API + Web Dashboard on ${URL} ..."
"$PYTHON_CMD" -m uvicorn api.main:app --host "$MEREDIAN_HOST" --port "$MEREDIAN_PORT" --reload

