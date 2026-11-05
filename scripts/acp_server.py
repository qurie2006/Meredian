from __future__ import annotations

import json
import os
import sys
from typing import Any

import httpx

API_BASE = os.getenv("MEREDIAN_API_URL", "http://127.0.0.1:8000")


def send_rpc(msg: dict[str, Any]) -> None:
    line = json.dumps(msg) + "\n"
    sys.stdout.write(line)
    sys.stdout.flush()


def log_debug(msg: str) -> None:
    sys.stderr.write(f"[Meredian ACP] {msg}\n")
    sys.stderr.flush()


def handle_initialize(req_id: Any, params: dict[str, Any]) -> None:
    resp = {
        "jsonrpc": "2.0",
        "id": req_id,
        "result": {
            "protocolVersion": params.get("protocolVersion", 1),
            "agentCapabilities": {
                "loadSession": True,
                "modelSelector": False,
            },
            "agentInfo": {
                "name": "Meredian",
                "version": "0.1.0",
            },
            "authMethods": [],
        },
    }
    send_rpc(resp)
    log_debug("Completed initialize handshake with Band Desktop.")


def handle_session_new(req_id: Any, params: dict[str, Any]) -> None:
    session_id = "meredian-session-01"
    send_rpc({"jsonrpc": "2.0", "id": req_id, "result": {"sessionId": session_id}})
    log_debug(f"Created session {session_id}")


def handle_session_prompt(req_id: Any, params: dict[str, Any]) -> None:
    prompt_text = str(params.get("prompt") or "")
    session_id = params.get("sessionId", "meredian-session-01")

    answer = ""
    try:
        with httpx.Client(timeout=4.0) as client:
            if "briefing" in prompt_text.lower() or "state" in prompt_text.lower() or "suspect" in prompt_text.lower():
                b = client.get(f"{API_BASE}/briefing/payments-memleak").json()
                answer = f"📋 Meredian Briefing:\n{b.get('headline')}\n\nLeading Suspect: {b.get('leading_suspect')}\nRecommended First Step: {b.get('recommended_first_step')}"
            else:
                chk = client.post(
                    f"{API_BASE}/check",
                    json={
                        "incident_id": "payments-memleak",
                        "actor": "BandEngineer",
                        "site": "BandRoom",
                        "source": "terminal",
                        "diff_or_command": prompt_text,
                    },
                ).json()
                answer = f"🔍 Meredian Verdict: {chk.get('verdict', '').upper()} ({chk.get('policy_action', '')})\n{chk.get('what_was_tried', '')}\nNext: {chk.get('suggested_next', '')}"
    except Exception as exc:
        answer = f"Meredian memory bot is active: {exc}"

    send_rpc(
        {
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {
                "sessionId": session_id,
                "update": {
                    "type": "agent_message",
                    "content": answer,
                },
            },
        }
    )
    send_rpc({"jsonrpc": "2.0", "id": req_id, "result": {"status": "ok"}})


def main() -> None:
    log_debug("Meredian ACP Server starting on stdio...")
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            req = json.loads(line)
        except Exception as e:
            log_debug(f"JSON parse error: {e}")
            continue

        method = req.get("method")
        req_id = req.get("id")
        params = req.get("params") or {}

        if method == "initialize":
            handle_initialize(req_id, params)
        elif method in ("session/new", "session/create"):
            handle_session_new(req_id, params)
        elif method in ("session/prompt", "session/chat"):
            handle_session_prompt(req_id, params)
        elif req_id is not None:
            send_rpc({"jsonrpc": "2.0", "id": req_id, "result": {}})


if __name__ == "__main__":
    main()

