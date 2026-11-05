from __future__ import annotations

from pathlib import Path

from api.main import create_app
from attempts.schemas import CheckActionRequest, OverrideRequest, ReplayRequest
from memory.client import FakeMemory


def run_demo() -> None:
    tmp_dir = Path(".hindsight/demo_run")
    tmp_dir.mkdir(parents=True, exist_ok=True)
    mem = FakeMemory(storage_path=str(tmp_dir / "banks.json"))
    app = create_app(memory=mem, db_path=str(tmp_dir / "demo.db"), auto_seed=False)
    h = app.state.handlers

    action_req = CheckActionRequest(
        incident_id="payments-memleak",
        actor="Aarav",
        site="Bengaluru",
        source="vscode",
        file_path="config/redis.yml",
        diff_or_command="Raise REDIS_TIMEOUT 200ms -> 800ms in config/redis.yml",
    )

    print("=" * 78)
    print("MEREDIAN STAGE DEMO: FOLLOW-THE-SUN LEARNING CURVE (DAY 1 -> DAY 2 -> DAY 5)")
    print("=" * 78)

    h["start_replay"](ReplayRequest(incident_id="payments-memleak", up_to_day=0, reset_first=True))
    v_day0 = h["check_action"](action_req)
    print("\n[STAGE 1 — DAY 1 BASELINE (Without Prior Shift Memory)]")
    print(f"  Proposed Action : {action_req.diff_or_command}")
    print(f"  Verdict / Policy: {v_day0.verdict.upper()} / {v_day0.policy_action.upper()}")
    print(f"  Note            : {v_day0.what_was_tried}")

    rep2 = h["start_replay"](ReplayRequest(incident_id="payments-memleak", up_to_day=2, reset_first=True))
    v_day2 = h["check_action"](action_req)
    print("\n[STAGE 2 — DAY 2 (After Seattle & London Shifts Replayed)]")
    print(f"  Replayed Events : {rep2['events_replayed']} events -> {len(rep2['attempts_built'])} attempts ({rep2['redactions_blocked']} secrets redacted)")
    print(f"  Proposed Action : {action_req.diff_or_command}")
    print(f"  Verdict / Policy: {v_day2.verdict.upper()} / {v_day2.policy_action.upper()} (confidence={v_day2.confidence:.0%})")
    print(f"  Band Room Post  : {v_day2.band_message}")
    print(f"  Observation     : {v_day2.matched_observations[0]}")
    print(f"  Briefing Suspect: {rep2['briefing']['leading_suspect']}")

    ovr = h["record_override"](
        OverrideRequest(
            incident_id="payments-memleak",
            interception_id=v_day2.interception_id,
            prior_attempt_id=v_day2.matched_attempt_id,
            actor="Aarav",
            site="Bengaluru",
            proposed_action=action_req.diff_or_command,
            reason="Testing under Redis 7.4 cluster with Envoy connection multiplexing",
            new_conditions="redis-7.4-envoy-multiplexing",
            files_components=["config/redis.yml"],
        )
    )
    print("\n[STAGE 3 — OVERRIDE & FEEDBACK LOOP]")
    print(f"  Retained Retry  : {ovr.retained_attempt.id} (retry_of={ovr.retained_attempt.retry_of})")

    rep5 = h["start_replay"](ReplayRequest(incident_id="payments-memleak", up_to_day=5, reset_first=True))
    exp5 = h["explore_memory"]("payments-memleak")
    print("\n[STAGE 4 — DAY 5 (Root Cause Confirmed + Cross-Incident Learning)]")
    print(f"  Briefing Headline: {rep5['briefing']['headline']}")
    print(f"  Leading Suspect  : {rep5['briefing']['leading_suspect']}")
    print(f"  Team Patterns    : {len(exp5.get('team_observations', []))} cross-incident observation(s) in `meredian-team-patterns`")
    print("=" * 78)


if __name__ == "__main__":
    run_demo()
