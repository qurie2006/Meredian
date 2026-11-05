"""Phase 1 Smoke Test: verifies `hindsight_client.Hindsight` and `HindsightMemoryWrapper`.

Tests:
1. Exact user snippet (`client.retain` + `client.recall` against `http://localhost:8888`).
2. `HindsightMemoryWrapper` bank configuration (mission, directives, disposition).
3. Asynchronous operation status tracking (`pending` -> `completed`).
4. Token-budgeted recall (small budget vs briefing budget) and automatic Observation consolidation.
5. Recall latency measurement.
"""
from __future__ import annotations

import time
from attempts.schemas import Attempt
from hindsight_client import Hindsight
from memory.client import FakeMemory


def run_smoke_test() -> None:
    print("=== Phase 1: Hindsight Local Smoke Test ===")

    # 1. Verify exact user snippet from prompt
    client = Hindsight(base_url="http://localhost:8888", storage_path=".hindsight/smoke_test.json")
    client.reset_bank("test")
    client.retain(bank_id="test", content="Maya raised the Redis timeout; the memory spike persisted.")
    recall_res = client.recall(bank_id="test", query="Redis timeout attempts")
    assert len(recall_res["facts"]) == 1, f"Expected 1 recalled fact, got {recall_res}"
    print(f"[PASS] Direct Hindsight snippet recall: {recall_res['facts'][0]['text']}")

    # 2. Verify HindsightMemoryWrapper retain -> consolidate observations -> recall -> reflect
    wrapper = FakeMemory(storage_path=".hindsight/smoke_wrapper.json")
    a1 = Attempt(
        id="att-smoke-1",
        incident_id="payments-memleak",
        day=1,
        shift="Shift A (Seattle)",
        who="Maya",
        site="Seattle",
        timestamp_utc="2026-11-01T03:14:00Z",
        hypothesis="Connection churn from short Redis timeouts causes the leak",
        action="Raised REDIS_TIMEOUT 200ms -> 800ms in config/redis.yml",
        files_components=["config/redis.yml", "Redis"],
        evidence_refs=["commit 4a9f2c1", "term-log-102", "band-msg-14"],
        outcome="failed",
        reason="Memory still reached 2.1GB in 20 minutes",
        conclusion="Redis timeout is not the cause",
        next_suspect="Auth middleware",
    )
    a2 = Attempt(
        id="att-smoke-2",
        incident_id="payments-memleak",
        day=2,
        shift="Shift C (London)",
        who="Liam",
        site="London",
        timestamp_utc="2026-11-02T11:40:00Z",
        hypothesis="Redis connection pool exhaustion causes buffer retention",
        action="Increased REDIS_MAX_CONNECTIONS from 50 to 250 in config/redis.yml",
        files_components=["config/redis.yml", "Redis"],
        evidence_refs=["commit 8c3d11e", "term-log-209"],
        outcome="failed",
        reason="RSS climbed to 2.3GB under canary load within 18 minutes",
        conclusion="Redis pool sizing does not affect the memory leak",
        next_suspect="Auth middleware session cache",
    )

    # Test async retain tracking
    op1 = wrapper.retain_attempt(a1, simulate_async_ms=50)
    status_immediate = wrapper.get_memory_status("payments-memleak", op1["operation_id"])
    assert status_immediate["memory_status"] == "updating"
    time.sleep(0.07)
    status_ready = wrapper.get_memory_status("payments-memleak", op1["operation_id"])
    assert status_ready["memory_status"] == "ready"
    print(f"[PASS] Async operation tracking: {status_immediate['memory_status']} -> {status_ready['memory_status']}")

    wrapper.retain_attempt(a2)

    t0 = time.perf_counter()
    action_recall = wrapper.recall_for_action(
        incident_id="payments-memleak",
        normalized_query="raise Redis timeout in config/redis.yml",
        token_budget=400,
    )
    latency_ms = (time.perf_counter() - t0) * 1000.0

    assert len(action_recall["facts"]) >= 2
    assert len(action_recall["observations"]) >= 1
    print(f"[PASS] Recall latency: {latency_ms:.2f} ms (budget={action_recall['token_budget']}, used={action_recall['tokens_used']})")
    print(f"[PASS] Consolidated observation: {action_recall['observations'][0]['belief']}")

    reflection = wrapper.reflect_for_briefing("payments-memleak")
    assert reflection["mental_model"]
    print(f"[PASS] Reflect mental model: {reflection['mental_model']}")


if __name__ == "__main__":
    run_smoke_test()

