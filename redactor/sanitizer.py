from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from attempts.schemas import Event


@dataclass
class RedactionResult:
    text: str
    count: int
    categories: dict[str, int] = field(default_factory=dict)


class Redactor:

    PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
        (
            "api_key",
            re.compile(
                r"\b(?:gsk_[A-Za-z0-9]{16,}|sk-[A-Za-z0-9_-]{16,}|ghp_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|xox[baprs]-[A-Za-z0-9-]{10,})\b"
            ),
            "[REDACTED_API_KEY]",
        ),
        (
            "token",
            re.compile(
                r"(?:Bearer\s+[A-Za-z0-9._\-]+|\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{3,}\b)"
            ),
            "[REDACTED_TOKEN]",
        ),
        (
            "uri_password",
            re.compile(r"([a-zA-Z0-9+.-]+://[^:\s/@]*:)([^@\s]+)(@)"),
            r"\1[REDACTED_PASSWORD]\3",
        ),
        (
            "password",
            re.compile(
                r"(?i)\b(password|passwd|secret|api_key|apikey|access_token|auth_token)\s*([=:])\s*([^\s,;\"']+)"
            ),
            r"\1\2[REDACTED_SECRET]",
        ),
        (
            "email",
            re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
            "[REDACTED_EMAIL]",
        ),
        (
            "internal_host",
            re.compile(
                r"\b[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)*\.(?:internal\.[a-zA-Z0-9.-]+|corp|lan|local)\b"
            ),
            "[REDACTED_INTERNAL_HOST]",
        ),
    ]

    def __init__(self) -> None:
        self.total_redactions: int = 0
        self.category_totals: dict[str, int] = {}

    def redact_text(self, text: str) -> RedactionResult:
        if not text:
            return RedactionResult(text=text, count=0, categories={})

        current = text
        total = 0
        cats: dict[str, int] = {}

        for category, pattern, replacement in self.PATTERNS:
            current, n = pattern.subn(replacement, current)
            if n > 0:
                total += n
                cats[category] = cats.get(category, 0) + n
                self.total_redactions += n
                self.category_totals[category] = self.category_totals.get(category, 0) + n

        return RedactionResult(text=current, count=total, categories=cats)

    def redact_value(self, value: Any) -> tuple[Any, int]:
        if isinstance(value, str):
            res = self.redact_text(value)
            return res.text, res.count
        if isinstance(value, list):
            out_list = []
            c_total = 0
            for item in value:
                sanitized, c = self.redact_value(item)
                out_list.append(sanitized)
                c_total += c
            return out_list, c_total
        if isinstance(value, dict):
            out_dict = {}
            c_total = 0
            for k, v in value.items():
                sanitized, c = self.redact_value(v)
                out_dict[k] = sanitized
                c_total += c
            return out_dict, c_total
        return value, 0

    def redact_event(self, event: Event) -> tuple[Event, int]:
        sanitized_payload, count = self.redact_value(event.payload)
        cloned = event.model_copy(deep=True)
        cloned.payload = sanitized_payload
        return cloned, count

    def reset_stats(self) -> None:
        self.total_redactions = 0
        self.category_totals.clear()

