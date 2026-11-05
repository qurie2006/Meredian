from __future__ import annotations

from typing import Any, Optional

from attempts.schemas import (
    Briefing,
    ConflictItem,
    Observation,
    RuledOutItem,
)
from llm.gateway import GroqGateway
from memory.client import HindsightMemoryWrapper


class BriefingGenerator:

    def __init__(
        self,
        memory: HindsightMemoryWrapper,
        llm: Optional[GroqGateway] = None,
    ) -> None:
        self.memory = memory
        self.llm = llm or GroqGateway()

    def generate(self, incident_id: str) -> Briefing:
        reflection = self.memory.reflect_for_briefing(incident_id)
        facts: list[dict[str, Any]] = reflection.get("facts", [])
        raw_obs: list[dict[str, Any]] = reflection.get("observations", [])
        mem_status = reflection.get("memory_status", "ready")

        observations = [Observation(**o) for o in raw_obs]

        if not facts:
            return Briefing(
                incident_id=incident_id,
                bank_id=incident_id,
                day=1,
                headline="Day 1 Baseline: No prior shift attempts recorded in Hindsight yet.",
                ruled_out=[],
                leading_suspect="Unknown — initial triage in progress",
                leading_suspect_rationale="Memory bank is currently empty.",
                conflicts=[],
                open_questions=[
                    "Does the memory growth correlate with Redis socket churn or in-process object retention?",
                    "Can the leak be reproduced under 1,500 RPS staging soak?",
                ],
                recommended_first_step="Capture baseline heap profile (`py-spy` / `tracemalloc`) under staging load.",
                observations=[],
                mental_model="No engineering attempts recorded yet.",
                total_attempts=0,
                dead_ends_count=0,
                memory_status=mem_status,
            )

        max_day = max(int(f.get("day", 1)) for f in facts)
        ruled_out: list[RuledOutItem] = []
        worked_facts: list[dict[str, Any]] = []

        for f in facts:
            if f.get("outcome") == "failed":
                ruled_out.append(
                    RuledOutItem(
                        hypothesis_or_action=f"{f.get('action')} ({f.get('hypothesis')})",
                        who=f.get("who", "Engineer"),
                        site=f.get("site", "Global"),
                        when=f.get("timestamp_utc", ""),
                        outcome="failed",
                        reason=f.get("reason", ""),
                        evidence_refs=list(f.get("evidence_refs", [])),
                        conditions=f.get("conditions"),
                    )
                )
            elif f.get("outcome") == "worked":
                worked_facts.append(f)

        conflicts = self._DetectConflicts(facts)

        if worked_facts:
            latest_win = worked_facts[-1]
            leading_suspect = f"CONFIRMED ROOT CAUSE: {latest_win.get('action')}"
            rationale = (
                f"Verified by {latest_win.get('who')} ({latest_win.get('site')}) at "
                f"{latest_win.get('timestamp_utc')} ({', '.join(latest_win.get('evidence_refs', []))}): "
                f"{latest_win.get('reason')}."
            )
            open_questions = [
                "Are any other microservices sharing the unbounded session cache pattern?",
                "Should a regression lint rule be added to block unbounded module-level dicts in middleware?",
            ]
            first_step = (
                f"Verify canary rollout of `{', '.join(latest_win.get('files_components', []))}` "
                "and monitor p99 latency + RSS over the shift."
            )
            headline = (
                f"Day {max_day} Shift Briefing: Root cause verified in Auth middleware; "
                f"{len(ruled_out)} prior dead end(s) documented with evidence."
            )
        else:
            latest_fact = facts[-1]
            leading_suspect = latest_fact.get("next_suspect") or "Auth middleware `_SESSION_CACHE`"
            rationale = (
                f"After ruling out {len(ruled_out)} dead end(s) across {', '.join(sorted({f.get('site', '') for f in facts}))}, "
                f"evidence ({', '.join(latest_fact.get('evidence_refs', []))}) points to `{leading_suspect}`."
            )
            open_questions = [
                "Does bounding `_SESSION_CACHE` with a TTL cache stop RSS growth at 1,800+ RPS?",
                "Are retry storms leaving orphaned `SessionContext` entries when requests abort early?",
            ]
            first_step = (
                f"Inspect `{leading_suspect}` and replace unbounded session storage with a bounded `TTLCache`; "
                "do NOT re-run Redis timeout or connection pool changes."
            )
            headline = (
                f"Day {max_day} Shift Handover: {len(ruled_out)} dead end(s) ruled out; "
                f"focus narrowed to {leading_suspect}."
            )

        return Briefing(
            incident_id=incident_id,
            bank_id=incident_id,
            day=max_day,
            headline=headline,
            ruled_out=ruled_out,
            leading_suspect=leading_suspect,
            leading_suspect_rationale=rationale,
            conflicts=conflicts,
            open_questions=open_questions,
            recommended_first_step=first_step,
            observations=observations,
            mental_model=reflection.get("mental_model", ""),
            total_attempts=len(facts),
            dead_ends_count=len(ruled_out),
            memory_status=mem_status,
        )

    @staticmethod
    def _DetectConflicts(facts: list[dict[str, Any]]) -> list[ConflictItem]:
        by_file: dict[str, list[dict[str, Any]]] = {}
        for f in facts:
            for comp in f.get("files_components", []):
                if "/" in comp or ".py" in comp or ".yml" in comp:
                    by_file.setdefault(comp, []).append(f)

        conflicts: list[ConflictItem] = []
        for comp, group in by_file.items():
            outcomes = {g.get("outcome") for g in group}
            if len(group) >= 2 and len(outcomes) > 1 and ("partial" in outcomes or "worked" in outcomes) and "failed" in outcomes:
                attempts_desc = [
                    f"{g.get('who')} ({g.get('site')}, {', '.join(g.get('evidence_refs', []))}) -> {g.get('outcome')} under [{g.get('conditions') or 'standard load'}]"
                    for g in group
                ]
                all_refs = []
                for g in group:
                    for r in g.get("evidence_refs", []):
                        if r not in all_refs:
                            all_refs.append(r)
                conflicts.append(
                    ConflictItem(
                        topic=f"Condition-dependent outcome on `{comp}`",
                        summary=(
                            f"Changes to `{comp}` showed conflicting results across shifts depending on load conditions: "
                            + "; ".join(attempts_desc)
                        ),
                        attempts_involved=[g.get("attempt_id", "") for g in group],
                        conditions_diff=" vs. ".join(
                            f"{g.get('site')}: {g.get('conditions') or 'default'}" for g in group
                        ),
                        evidence_refs=all_refs,
                    )
                )
        return conflicts

    @staticmethod
    def format_for_band(briefing: Briefing) -> str:
        lines = [
            f"📋 **Meredian Shift-Start Briefing — `{briefing.incident_id}` (Day {briefing.day})**",
            f"**Summary:** {briefing.headline}",
        ]
        if briefing.ruled_out:
            lines.append("\n🚫 **Ruled Out (Do Not Repeat):**")
            for item in briefing.ruled_out:
                refs = ", ".join(item.evidence_refs)
                lines.append(
                    f"- {item.hypothesis_or_action} — tried by {item.who} ({item.site}) [{refs}]. Reason: {item.reason}"
                )
        if briefing.conflicts:
            lines.append("\n⚠️ **Cross-Site Condition Conflicts:**")
            for c in briefing.conflicts:
                lines.append(f"- {c.summary}")
        lines.append(f"\n🎯 **Leading Suspect:** {briefing.leading_suspect}")
        lines.append(f"   *{briefing.leading_suspect_rationale}*")
        lines.append(f"\n🚀 **Recommended First Step:** {briefing.recommended_first_step}")
        return "\n".join(lines)

