"""Tests for Hindsight Memory layer and all Section 5 Edge Cases."""
from __future__ import annotations

import time
from attempts.builder import AttemptBuilder
from attempts.schemas import CheckActionRequest
from collector.adapters import CollectorPipeline
from data.replay import ReplayEngine
from decision.briefing import BriefingGenerator
from decision.checker import ActionChecker
from memory.client import FakeMemory


def test_empty_bank_day1_baseline_gives_no_warnings() -> None:
    mem = FakeMemory(storage_path=".hindsight/test_edge_empty.json")
    checker = ActionChecker(memory=mem)
    req = CheckActionRequest(
        incident_id="payments-memleak",
        actor="Aarav",
        site="Bengaluru",
        source="vscode",
        file_path="config/redis.yml",
        diff_or_command="REDIS_TIMEOUT: 200ms -> 800ms",
    )
    _, verdict = checker.check(req)
    assert verdict.verdict == "new"
    assert verdict.policy_action == "silent"


def test_conflicting_attempts_across_sites_detected_in_briefing() -> None:
    mem = FakeMemory(storage_path=".hindsight/test_edge_conflicts.json")
    replay = ReplayEngine(
        collector=CollectorPipeline(),
        attempt_builder=AttemptBuilder(),
        memory=mem,
    )
    replay.replay_incident("payments-memleak", up_to_day=2, reset_first=True)

    briefing = BriefingGenerator(memory=mem).generate("payments-memleak")
    assert len(briefing.conflicts) >= 1
    conflict = briefing.conflicts[0]
    assert "worker.py" in conflict.topic
    assert "Seattle" in conflict.conditions_diff and "London" in conflict.conditions_diff


def test_hindsight_async_processing_status_transition() -> None:
    mem = FakeMemory(storage_path=".hindsight/test_edge_async.json")
    replay = ReplayEngine(
        collector=CollectorPipeline(),
        attempt_builder=AttemptBuilder(),
        memory=mem,
    )
    events = replay.get_events_for_incident("payments-memleak", up_to_day=1)
    att = AttemptBuilder().build_attempts_from_events(events)[0]

    op = mem.retain_attempt(att, simulate_async_ms=60)
    st1 = mem.get_memory_status("payments-memleak", op["operation_id"])
    assert st1["memory_status"] == "updating"
    time.sleep(0.08)
    st2 = mem.get_memory_status("payments-memleak", op["operation_id"])
    assert st2["memory_status"] == "ready"

