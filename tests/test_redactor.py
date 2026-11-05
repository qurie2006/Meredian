"""Unit tests for the Redactor security layer."""
from __future__ import annotations

from attempts.schemas import Event
from redactor.sanitizer import Redactor


def test_redactor_strips_all_secret_types_and_counts() -> None:
    redactor = Redactor()
    sample = (
        "Connecting to redis://:mySuperSecretPass99@redis-prod-01.internal.northwind.corp:6379 "
        "with GROQ key gsk_1234567890abcdefghijklmnop and OpenAI sk-proj1234567890abcdefghijkl "
        "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.sig "
        "contact maya@northwindpay.io or password=plainTextPass42!"
    )

    res = redactor.redact_text(sample)
    assert "mySuperSecretPass99" not in res.text
    assert "redis-prod-01.internal.northwind.corp" not in res.text
    assert "gsk_1234567890abcdefghijklmnop" not in res.text
    assert "sk-proj1234567890abcdefghijkl" not in res.text
    assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in res.text
    assert "maya@northwindpay.io" not in res.text
    assert "plainTextPass42!" not in res.text
    assert res.count >= 7
    assert redactor.total_redactions == res.count


def test_redact_event_preserves_structure_and_sanitizes_nested_payload() -> None:
    redactor = Redactor()
    ev = Event(
        id="evt-1",
        source="terminal",
        actor="Maya",
        site="Seattle",
        timestamp_utc="2026-11-01T03:12:00Z",
        type="command_output",
        payload={
            "command": "curl -H 'Authorization: Bearer secretJwt.payloadPart123.sig'",
            "output": "Alert sent to devon@northwindpay.io from host auth-02.internal.northwind.local",
        },
        incident_id="payments-memleak",
    )
    clean_ev, count = redactor.redact_event(ev)
    assert count >= 3
    assert "devon@northwindpay.io" not in clean_ev.payload["output"]
    assert "auth-02.internal.northwind.local" not in clean_ev.payload["output"]

