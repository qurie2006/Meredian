#!/usr/bin/env bash
# Meredian Bash/Zsh Terminal Hook Interceptor
# Usage: source interceptor/terminal-hook/meredian-hook.sh && meredian_exec "redis-cli CONFIG SET timeout 800"

meredian_exec() {
  local cmd_text="$*"
  local api_url="${MEREDIAN_API_URL:-http://127.0.0.1:8000}"
  local incident="${MEREDIAN_INCIDENT:-payments-memleak}"
  local actor="${MEREDIAN_ACTOR:-Aarav}"
  local site="${MEREDIAN_SITE:-Bengaluru}"

  python -c "
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

