from __future__ import annotations

from pathlib import Path

from api.main import create_app
from attempts.schemas import CheckActionRequest, OverrideRequest, ReplayRequest
from memory.client import FakeMemory


def test_full_api_lifecycle_and_contracts(tmp_path: Path) -> None:
    mem = FakeMemory(storage_path=str(tmp_path / "banks.json"))
    db_file = str(tmp_path / "meredian_test.db")
    app = create_app(memory=mem, db_path=db_file, auto_seed=True)
    h_map = app.state.handlers

    h = h_map["health"]()
    assert h["status"] == "ok"
    assert h["memory_enabled"] is True

    ov = h_map["get_overview"](incident_id="payments-memleak")
    assert ov["metrics"]["dead_ends_documented"] >= 3
    assert ov["metrics"]["secrets_redacted"] >= 5

    chk = h_map["check_action"](
        CheckActionRequest(
            incident_id="payments-memleak",
            actor="Aarav",
            site="Bengaluru",
            source="vscode",
            file_path="config/redis.yml",
            diff_or_command="Raise REDIS_TIMEOUT 200ms -> 900ms in config/redis.yml",
        )
    )
    assert chk.verdict == "repeat"
    assert chk.policy_action == "interrupt"
    assert chk.interception_id

    ovr = h_map["record_override"](
        OverrideRequest(
            incident_id="payments-memleak",
            interception_id=chk.interception_id,
            prior_attempt_id=chk.matched_attempt_id,
            actor="Aarav",
            site="Bengaluru",
            proposed_action="Raise REDIS_TIMEOUT 200ms -> 900ms in config/redis.yml",
            reason="Testing under new Redis 7.4 cluster with Envoy multiplexing",
            new_conditions="redis-7.4-cluster-envoy-multiplexing",
            files_components=["config/redis.yml"],
            outcome="worked",
        )
    )
    assert ovr.retained_attempt.retry_of == chk.matched_attempt_id

    brief = h_map["get_briefing"]("payments-memleak")
    assert len(brief.ruled_out) >= 3
    assert brief.leading_suspect

    tl = h_map["get_timeline"]("payments-memleak")
    assert tl["total_attempts"] >= 5

    intr = h_map["get_interceptions"](incident_id="payments-memleak")
    assert intr["total"] >= 1
    assert intr["overrides"] == 1

    exp = h_map["explore_memory"]("payments-memleak", q="Redis")
    assert len(exp["facts"]) >= 2
    assert len(exp["observations"]) >= 1

    cmp = h_map["compare_action"](
        CheckActionRequest(
            incident_id="payments-memleak",
            actor="Aarav",
            site="Bengaluru",
            source="web",
            file_path="config/redis.yml",
            diff_or_command="REDIS_TIMEOUT: 200ms -> 800ms",
        )
    )
    assert cmp["without_memory"]["policy_action"] == "silent"
    assert cmp["with_memory"]["policy_action"] == "interrupt"

    rep5 = h_map["start_replay"](
        ReplayRequest(incident_id="payments-memleak", up_to_day=5, reset_first=True)
    )
    assert rep5["up_to_day"] == 5
    assert "CONFIRMED ROOT CAUSE" in rep5["briefing"]["leading_suspect"]

    # Test Hypothesis Elimination Tree
    tree = h_map["get_hypothesis_tree"]("payments-memleak")
    assert tree["incident_id"] == "payments-memleak"
    assert len(tree["nodes"]) >= 3
    assert tree["counts"]["ruled_out"] >= 1

    # Test Product Onboarding (Custom Incident Bank)
    from api.main import CreateIncidentRequest, GitHubWebhookRequest
    created = h_map["create_incident"](
        CreateIncidentRequest(
            id="checkout-deadlock",
            title="Checkout Transaction Lock Saturation",
            service="checkout-service",
            severity="SEV-1",
            initial_symptom="Postgres statement timeout under 800 RPS flash sale",
        )
    )
    assert created["status"] == "created"
    assert created["incident"]["id"] == "checkout-deadlock"

    # Test Overview includes custom product and Enterprise ROI
    ov_custom = h_map["get_overview"](incident_id="checkout-deadlock")
    assert any(inc["id"] == "checkout-deadlock" for inc in ov_custom["incidents"])
    assert "cost_avoided_usd" in ov_custom["metrics"]
    assert "mttr_reduction_pct" in ov_custom["metrics"]

    # Test List Incidents endpoint
    inc_list = h_map["list_incidents"]()
    assert any(inc["id"] == "checkout-deadlock" for inc in inc_list["incidents"])

    # Test GitHub PR Interceptor Webhook
    gh_resp = h_map["handle_github_webhook"](
        GitHubWebhookRequest(
            incident_id="payments-memleak",
            pr_number=42,
            pr_title="Raise redis timeout to fix latency",
            author="maya-seattle",
            changed_files=["config/redis.yml"],
            diff="REDIS_TIMEOUT: 200ms -> 1000ms",
        )
    )
    assert gh_resp["action"] == "blocked"
    assert "Meredian Institutional Memory PR Check #42" in gh_resp["comment_markdown"]
    assert "BLOCKED — REPEAT DEAD END DETECTED" in gh_resp["comment_markdown"]

    # Test Institutional Memory RAG Query & Indexing
    from api.main import RAGQueryRequest
    rag_resp = h_map["query_rag"](
        RAGQueryRequest(
            incident_id="payments-memleak",
            query="Why did raising Redis timeout fail on Day 1?",
        )
    )
    assert len(rag_resp["answer"]) > 20
    assert len(rag_resp["citations"]) > 0
    assert len(rag_resp["suggested_chips"]) > 0

    status_resp = h_map["rag_status"](incident="payments-memleak")
    assert status_resp["indexed_documents"] > 0
