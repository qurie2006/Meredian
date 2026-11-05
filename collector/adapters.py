from __future__ import annotations

import uuid
from typing import Any

from attempts.schemas import Event, utc_now_iso


class GitAdapter:

    @staticmethod
    def to_event(raw: dict[str, Any], default_incident_id: str = "payments-memleak") -> Event:
        payload = raw.get("payload") or {
            "commit": raw.get("commit", "unknown"),
            "branch": raw.get("branch", "main"),
            "files": raw.get("files", []),
            "message": raw.get("message", ""),
            "diff": raw.get("diff", ""),
            "shift": raw.get("shift", "Shift A"),
        }
        return Event(
            id=raw.get("id") or f"evt-git-{uuid.uuid4().hex[:8]}",
            source="git",
            actor=raw.get("actor", "Engineer"),
            site=raw.get("site", "Seattle"),
            timestamp_utc=raw.get("timestamp_utc") or utc_now_iso(),
            type=raw.get("type", "commit"),
            payload=payload,
            incident_id=raw.get("incident_id", default_incident_id),
            day=int(raw.get("day", 1)),
            attempt_group_id=raw.get("attempt_group_id"),
        )


class TerminalAdapter:

    @staticmethod
    def to_event(raw: dict[str, Any], default_incident_id: str = "payments-memleak") -> Event:
        payload = raw.get("payload") or {
            "command": raw.get("command", ""),
            "output": raw.get("output", ""),
            "log_ref": raw.get("log_ref", f"term-log-{uuid.uuid4().hex[:6]}"),
            "conditions": raw.get("conditions"),
        }
        return Event(
            id=raw.get("id") or f"evt-term-{uuid.uuid4().hex[:8]}",
            source="terminal",
            actor=raw.get("actor", "Engineer"),
            site=raw.get("site", "Seattle"),
            timestamp_utc=raw.get("timestamp_utc") or utc_now_iso(),
            type=raw.get("type", "command_output"),
            payload=payload,
            incident_id=raw.get("incident_id", default_incident_id),
            day=int(raw.get("day", 1)),
            attempt_group_id=raw.get("attempt_group_id"),
        )


class BandAdapter:

    @staticmethod
    def to_event(raw: dict[str, Any], default_incident_id: str = "payments-memleak") -> Event:
        payload = raw.get("payload") or {
            "message_id": raw.get("message_id", f"band-msg-{uuid.uuid4().hex[:6]}"),
            "room": raw.get("room", "Payments memory leak"),
            "text": raw.get("text", ""),
            "shift": raw.get("shift", "Shift A"),
            "hypothesis": raw.get("hypothesis"),
            "action": raw.get("action"),
            "outcome": raw.get("outcome"),
            "reason": raw.get("reason"),
            "conclusion": raw.get("conclusion"),
            "next_suspect": raw.get("next_suspect"),
            "conditions": raw.get("conditions"),
        }
        return Event(
            id=raw.get("id") or f"evt-band-{uuid.uuid4().hex[:8]}",
            source="band",
            actor=raw.get("actor", "Engineer"),
            site=raw.get("site", "Seattle"),
            timestamp_utc=raw.get("timestamp_utc") or utc_now_iso(),
            type=raw.get("type", "room_message"),
            payload=payload,
            incident_id=raw.get("incident_id", default_incident_id),
            day=int(raw.get("day", 1)),
            attempt_group_id=raw.get("attempt_group_id"),
        )


class CollectorPipeline:

    def __init__(self) -> None:
        self.git = GitAdapter()
        self.terminal = TerminalAdapter()
        self.band = BandAdapter()

    def normalize_event(self, raw: Event | dict[str, Any], default_incident_id: str = "payments-memleak") -> Event:
        if isinstance(raw, Event):
            return raw
        source = str(raw.get("source", "band")).lower()
        if source == "git":
            return self.git.to_event(raw, default_incident_id=default_incident_id)
        if source == "terminal":
            return self.terminal.to_event(raw, default_incident_id=default_incident_id)
        return self.band.to_event(raw, default_incident_id=default_incident_id)

    def collect_and_group(
        self,
        raw_events: list[Event | dict[str, Any]],
        default_incident_id: str = "payments-memleak",
    ) -> dict[str, list[Event]]:
        grouped: dict[str, list[Event]] = {}
        for item in raw_events:
            ev = self.normalize_event(item, default_incident_id=default_incident_id)
            grouped.setdefault(ev.incident_id, []).append(ev)

        for inc_id, ev_list in grouped.items():
            ev_list.sort(key=lambda e: e.timestamp_utc)
        return grouped

