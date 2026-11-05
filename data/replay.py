"""Replay Engine: feeds synthetic incident events through Collector -> Redactor -> Attempt Builder -> Hindsight."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from attempts.builder import AttemptBuilder
from attempts.schemas import Attempt, Event
from band_agent.client import BandAgentClient
from collector.adapters import CollectorPipeline
from memory.client import HindsightMemoryWrapper


class ReplayEngine:
    """Deterministic time-ordered replay engine supporting Day 0 (baseline), Day 1, Day 2, and Day 5."""

    def __init__(
        self,
        collector: CollectorPipeline,
        attempt_builder: AttemptBuilder,
        memory: HindsightMemoryWrapper,
        band_client: Optional[BandAgentClient] = None,
        data_file: Optional[str] = None,
    ) -> None:
        self.collector = collector
        self.builder = attempt_builder
        self.memory = memory
        self.band = band_client
        self.data_path = Path(data_file or Path(__file__).parent / "incidents.json")

    def load_world(self) -> dict[str, Any]:
        return json.loads(self.data_path.read_text(encoding="utf-8"))

    def get_incident_meta(self, incident_id: str) -> dict[str, Any]:
        world = self.load_world()
        for inc in world.get("incidents", []):
            if inc["id"] == incident_id:
                return inc
        return {
            "id": incident_id,
            "title": incident_id,
            "service": "payments",
            "severity": "SEV-2",
            "status": "active",
            "estimated_hours_per_dead_end": 2.5,
            "events": [],
        }

    def list_incidents_meta(self) -> list[dict[str, Any]]:
        world = self.load_world()
        out = []
        for inc in world.get("incidents", []):
            meta = {k: v for k, v in inc.items() if k != "events"}
            meta["event_count"] = len(inc.get("events", []))
            out.append(meta)
        return out

    def get_events_for_incident(self, incident_id: str, up_to_day: int = 5) -> list[Event]:
        inc = self.get_incident_meta(incident_id)
        if up_to_day <= 0:
            return []
        raw_events = [
            e for e in inc.get("events", [])
            if int(e.get("day", 1)) <= up_to_day
        ]
        grouped = self.collector.collect_and_group(raw_events, default_incident_id=incident_id)
        return grouped.get(incident_id, [])

    def replay_incident(
        self,
        incident_id: str = "payments-memleak",
        up_to_day: int = 2,
        reset_first: bool = True,
    ) -> dict[str, Any]:
        """Replay events up to `up_to_day` (0 = empty bank baseline, 1 = Day 1, 2 = Day 2, 5 = Day 5)."""
        if reset_first:
            self.memory.reset(incident_id)
            if self.band:
                self.band.clear(incident_id)

        events = self.get_events_for_incident(incident_id, up_to_day=up_to_day)
        if not events:
            return {
                "incident_id": incident_id,
                "up_to_day": up_to_day,
                "events_replayed": 0,
                "attempts_built": [],
                "redactions_blocked": 0,
            }

        # Mirror Band events into the Band room feed
        if self.band:
            for ev in events:
                if ev.source == "band" and ev.payload.get("text"):
                    self.band.receive_room_message(
                        sender=ev.actor,
                        site=ev.site,
                        text=str(ev.payload["text"]),
                        incident_id=incident_id,
                        metadata={"day": ev.day, "shift": ev.payload.get("shift", "")},
                    )

        attempts: list[Attempt] = self.builder.build_attempts_from_events(events)
        for att in attempts:
            op = self.memory.retain_attempt(att, also_retain_team_pattern=(att.day >= 5))
            att.operation_id = op.get("operation_id")
            att.operation_status = op.get("status", "completed")  # type: ignore[assignment]

        # On Day 5, also seed cross-incident learnings from the other synthetic incidents
        if up_to_day >= 5:
            for other_inc in ("auth-token-storm", "redis-failover-stall"):
                if other_inc != incident_id:
                    other_events = self.get_events_for_incident(other_inc, up_to_day=up_to_day)
                    other_attempts = self.builder.build_attempts_from_events(other_events)
                    for o_att in other_attempts:
                        self.memory.retain_attempt(o_att, also_retain_team_pattern=True)

        total_redactions = sum(a.redactions_count for a in attempts)
        return {
            "incident_id": incident_id,
            "up_to_day": up_to_day,
            "events_replayed": len(events),
            "attempts_built": attempts,
            "redactions_blocked": total_redactions,
        }

