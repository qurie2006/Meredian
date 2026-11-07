#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"

if [ -x ".venv/bin/python" ]; then
  PYTHON_CMD=".venv/bin/python"
elif [ -n "$VIRTUAL_ENV" ] && [ -x "$VIRTUAL_ENV/bin/python" ]; then
  PYTHON_CMD="$VIRTUAL_ENV/bin/python"
elif command -v python3.11 >/dev/null 2>&1; then
  PYTHON_CMD="python3.11"
else
  PYTHON_CMD="python3"
fi

export PYTHONPATH=.

TASK="${1:-demo}"

case "$TASK" in
  smoke)
    echo "[Meredian] Running Hindsight Smoke Test..."
    "$PYTHON_CMD" scripts/hindsight_smoke.py
    ;;
  eval)
    echo "[Meredian] Running Action Checker Evaluation Suite..."
    "$PYTHON_CMD" scripts/eval_checker.py
    ;;
  test)
    echo "[Meredian] Running Full Pytest Suite..."
    "$PYTHON_CMD" -m pytest -v
    ;;
  demo)
    echo "[Meredian] Running Stage Demo Walkthrough..."
    "$PYTHON_CMD" scripts/demo_walkthrough.py
    ;;
  hindsight-server)
    echo "[Meredian] Starting Local Hindsight API Server..."
    "$PYTHON_CMD" scripts/hindsight_local_server.py
    ;;
  dev)
    echo "[Meredian] Starting Meredian FastAPI Backend..."
    "$PYTHON_CMD" -m uvicorn api.main:app --host 127.0.0.1 --port 8000 --reload
    ;;
  *)
    echo "Usage: ./tasks.sh [smoke | eval | test | demo | hindsight-server | dev]"
    exit 1
    ;;
esac

