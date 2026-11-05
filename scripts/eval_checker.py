"""Phase 4 Evaluation Script: tests ActionChecker against the 15 labelled proposed actions."""
from __future__ import annotations

import json
from pathlib import Path

from attempts.builder import AttemptBuilder
from attempts.schemas import CheckActionRequest
from collector.adapters import CollectorPipeline
from data.replay import ReplayEngine
from decision.checker import ActionChecker
from memory.client import FakeMemory


def run_eval() -> None:
    print("=== Phase 4: Action Checker Verdict & Policy Evaluation ===")
    memory = FakeMemory(storage_path=".hindsight/eval_banks.json")
    collector = CollectorPipeline()
    builder = AttemptBuilder()
    replay = ReplayEngine(collector=collector, attempt_builder=builder, memory=memory)

    # Seed Day 2 state of payments-memleak (Redis timeout, Redis pool, GC sweep conflict)
    replay_res = replay.replay_incident("payments-memleak", up_to_day=2, reset_first=True)
    print(
        f"Seeded `payments-memleak` (Day 2): {replay_res['events_replayed']} events -> "
        f"{len(replay_res['attempts_built'])} attempts ({replay_res['redactions_blocked']} secrets redacted)"
    )

    checker = ActionChecker(memory=memory)
    eval_items = json.loads(Path("data/eval_actions.json").read_text(encoding="utf-8"))

    verdict_correct = 0
    policy_correct = 0
    false_interrupts_on_new = 0

    for item in eval_items:
        req = CheckActionRequest(
            incident_id=item["incident_id"],
            actor="Aarav",
            site="Bengaluru",
            source="vscode",
            file_path=item.get("file_path"),
            diff_or_command=item["diff_or_command"],
            conditions=item.get("conditions"),
        )
        _, verdict = checker.check(req)
        v_ok = verdict.verdict == item["expected_verdict"]
        p_ok = verdict.policy_action == item["expected_policy"]
        if v_ok:
            verdict_correct += 1
        if p_ok:
            policy_correct += 1
        if item["expected_verdict"] == "new" and verdict.policy_action == "interrupt":
            false_interrupts_on_new += 1

        status_icon = "PASS" if (v_ok and p_ok) else "FAIL"
        print(
            f"[{status_icon}] {item['id']} | expected=({item['expected_verdict']}/{item['expected_policy']}) "
            f"got=({verdict.verdict}/{verdict.policy_action}, conf={verdict.confidence:.2f}) | {item['description']}"
        )

    total = len(eval_items)
    v_acc = (verdict_correct / total) * 100.0
    p_acc = (policy_correct / total) * 100.0
    print(f"\nVerdict Accuracy: {verdict_correct}/{total} ({v_acc:.1f}%)")
    print(f"Policy Accuracy:  {policy_correct}/{total} ({p_acc:.1f}%)")
    print(f"False Interrupts on 'new': {false_interrupts_on_new}")

    assert v_acc >= 85.0, f"Verdict accuracy {v_acc:.1f}% is below 85% threshold"
    assert false_interrupts_on_new == 0, f"Had {false_interrupts_on_new} false interrupts on 'new' actions"


if __name__ == "__main__":
    run_eval()

