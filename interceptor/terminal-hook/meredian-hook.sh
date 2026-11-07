#!/usr/bin/env bash

meredian_exec() {
  local cmd_text="$*"
  local api_url="${MEREDIAN_API_URL:-http://127.0.0.1:8000}"
  local incident="${MEREDIAN_INCIDENT:-payments-memleak}"
  local actor="${MEREDIAN_ACTOR:-Aarav}"
  local site="${MEREDIAN_SITE:-Bengaluru}"
  local python_bin="${MEREDIAN_PYTHON:-python3}"

  if [ -x ".venv/bin/python" ]; then
    python_bin=".venv/bin/python"
  elif [ -n "$VIRTUAL_ENV" ] && [ -x "$VIRTUAL_ENV/bin/python" ]; then
    python_bin="$VIRTUAL_ENV/bin/python"
  fi

  "$python_bin" -c "
import sys, httpx
resp = httpx.post('$api_url/check', json={
    'incident_id': '$incident',
    'actor': '$actor',
    'site': '$site',
    'source': 'terminal',
    'diff_or_command': '''$cmd_text'''
}, timeout=5.0).json()
if resp.get('policy_action') in ('interrupt', 'soft_warning'):
    print('\n[MEREDIAN STOP]', resp.get('band_message'))
    print('Evidence:', ', '.join(resp.get('evidence', [])))
    print('Suggested next:', resp.get('suggested_next'))
    sys.exit(2)
"
  local status=$?
  if [ $status -eq 2 ]; then
    echo "[Meredian] Execution blocked to prevent repeating a documented dead end."
    return 1
  fi
  eval "$cmd_text"
}

