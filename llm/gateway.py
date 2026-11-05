from __future__ import annotations

import json
import os
import re
import socket
import time
from typing import Any, Callable, Optional

import httpx


class GroqGateway:

    PRIMARY_MODEL = "openai/gpt-oss-120b"
    FALLBACK_MODEL = "qwen/qwen3-32b"
    GROQ_BASE_URL = "https://api.groq.com/openai/v1/chat/completions"

    def __init__(
        self,
        api_key: Optional[str] = None,
        primary_model: Optional[str] = None,
        fallback_model: Optional[str] = None,
        transport_fn: Optional[Callable[[str, list[dict[str, str]]], str]] = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else os.getenv("GROQ_API_KEY", "")
        self.primary_model = primary_model or os.getenv("GROQ_PRIMARY_MODEL", self.PRIMARY_MODEL)
        self.fallback_model = fallback_model or os.getenv("GROQ_FALLBACK_MODEL", self.FALLBACK_MODEL)
        self._transport_fn = transport_fn
        self._network_reachable: Optional[bool] = None
        self.call_count = 0
        self.repair_count = 0
        self.fallback_count = 0

    def _IsGroqReachable(self) -> bool:
        if self._transport_fn is not None:
            return True
        if os.getenv("MEREDIAN_OFFLINE_MODE", "0") == "1":
            return False
        if self._network_reachable is not None:
            return self._network_reachable
        try:
            with socket.create_connection(("api.groq.com", 443), timeout=0.35):
                self._network_reachable = True
        except OSError:
            self._network_reachable = False
        return self._network_reachable

    @property
    def is_live_configured(self) -> bool:
        return bool(
            (self.api_key and self.api_key != "your_groq_api_key_here")
            or self._transport_fn is not None
        )

    def complete_json(
        self,
        system_prompt: str,
        user_prompt: str,
        required_keys: Optional[list[str]] = None,
        fallback_builder: Optional[Callable[[], dict[str, Any]]] = None,
    ) -> dict[str, Any]:
        required_keys = required_keys or []
        if not self.is_live_configured or not self._IsGroqReachable():
            if fallback_builder:
                return fallback_builder()
            return {}

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        raw_response: Optional[str] = None
        for model in (self.primary_model, self.fallback_model):
            try:
                raw_response = self._CallWithBackoff(model, messages)
                break
            except Exception:
                self.fallback_count += 1
                continue

        if raw_response is None:
            return fallback_builder() if fallback_builder else {}

        parsed = self._TryParseJson(raw_response, required_keys)
        if parsed is not None:
            return parsed

        self.repair_count += 1
        repair_messages = [
            {
                "role": "system",
                "content": (
                    "You are a strict JSON repair assistant. Return ONLY valid JSON object "
                    f"containing keys {required_keys}. Do not include markdown fences or commentary."
                ),
            },
            {
                "role": "user",
                "content": f"Repair this malformed JSON response:\n\n{raw_response}",
            },
        ]
        try:
            repaired_raw = self._CallWithBackoff(self.fallback_model, repair_messages)
            repaired = self._TryParseJson(repaired_raw, required_keys)
            if repaired is not None:
                return repaired
        except Exception:
            pass

        self.fallback_count += 1
        return fallback_builder() if fallback_builder else {}

    def _CallWithBackoff(self, model: str, messages: list[dict[str, str]]) -> str:
        self.call_count += 1
        if self._transport_fn is not None:
            return self._transport_fn(model, messages)

        delays = [0.2, 0.5]
        last_err: Optional[Exception] = None
        for attempt_idx in range(len(delays) + 1):
            try:
                with httpx.Client(timeout=8.0) as client:
                    resp = client.post(
                        self.GROQ_BASE_URL,
                        headers={
                            "Authorization": f"Bearer {self.api_key}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "model": model,
                            "messages": messages,
                            "temperature": 0.1,
                        },
                    )
                    if resp.status_code == 429 and attempt_idx < len(delays):
                        time.sleep(delays[attempt_idx])
                        continue
                    resp.raise_for_status()
                    data = resp.json()
                    return data["choices"][0]["message"]["content"]
            except Exception as exc:
                last_err = exc
                if attempt_idx < len(delays):
                    time.sleep(delays[attempt_idx])
        raise RuntimeError(f"Groq call failed for {model}: {last_err}")

    @staticmethod
    def _TryParseJson(raw: str, required_keys: list[str]) -> Optional[dict[str, Any]]:
        if not raw:
            return None
        cleaned = raw.strip()
        fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, flags=re.DOTALL)
        if fence_match:
            cleaned = fence_match.group(1)
        else:
            brace_start = cleaned.find("{")
            brace_end = cleaned.rfind("}")
            if brace_start != -1 and brace_end != -1 and brace_end > brace_start:
                cleaned = cleaned[brace_start : brace_end + 1]

        try:
            obj = json.loads(cleaned)
            if not isinstance(obj, dict):
                return None
            for k in required_keys:
                if k not in obj:
                    return None
            return obj
        except Exception:
            return None

