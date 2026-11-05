from __future__ import annotations

from attempts.builder import AttemptBuilder
from attempts.schemas import Event
from llm.gateway import GroqGateway


def test_llm_gateway_repairs_malformed_json_on_retry() -> None:
    responses = [
        "Here is the output: {hypothesis: 'missing quotes', broken",
        '{"hypothesis": "Redis timeout churn", "action": "Raised timeout", "files_components": ["config/redis.yml"], "outcome": "failed", "reason": "Still leaked", "conclusion": "Not Redis", "next_suspect": "Auth middleware"}',
    ]

    def fake_transport(model: str, messages: list[dict[str, str]]) -> str:
        return responses.pop(0)

    gw = GroqGateway(api_key="test-key", transport_fn=fake_transport)
    out = gw.complete_json(
        system_prompt="sys",
        user_prompt="usr",
        required_keys=["hypothesis", "action", "outcome"],
        fallback_builder=lambda: {"hypothesis": "fallback", "action": "fallback", "outcome": "failed"},
    )
    assert out["hypothesis"] == "Redis timeout churn"
    assert gw.repair_count == 1


def test_llm_gateway_falls_back_to_template_when_repair_also_fails() -> None:
    def always_broken(model: str, messages: list[dict[str, str]]) -> str:
        return "not json at all {{{{"

    gw = GroqGateway(api_key="test-key", transport_fn=always_broken)
    builder = AttemptBuilder(llm_gateway=gw)
    ev = Event(
        id="evt-test-1",
        source="band",
        actor="Maya",
        site="Seattle",
        timestamp_utc="2026-11-01T03:14:00Z",
        type="room_message",
        payload={
            "message_id": "band-msg-1",
            "hypothesis": "Redis timeout causes leak",
            "action": "Raised REDIS_TIMEOUT 200ms -> 800ms",
            "outcome": "failed",
            "reason": "Memory still reached 2.1GB",
            "conclusion": "Redis timeout is not the cause",
            "next_suspect": "Auth middleware",
            "files": ["config/redis.yml"],
        },
        incident_id="payments-memleak",
    )

    attempts = builder.build_attempts_from_events([ev])
    assert len(attempts) == 1
    att = attempts[0]
    assert att.outcome == "failed"
    assert "Maya" in att.narrative
    assert "config/redis.yml" in att.files_components

