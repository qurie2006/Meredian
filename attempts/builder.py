from __future__ import annotations

import hashlib
import json
from typing import Any, Optional

from attempts.schemas import Attempt, Event
from llm.gateway import GroqGateway
from memory.client import HindsightMemoryWrapper
from redactor.sanitizer import Redactor


class AttemptBuilder:

    REQUIRED_LLM_KEYS = [
        "hypothesis",
        "action",
        "files_components",
        "outcome",
        "reason",
        "conclusion",
        "next_suspect",
    ]

    def __init__(
        self,
        llm_gateway: Optional[GroqGateway] = None,
        redactor: Optional[Redactor] = None,
    ) -> None:
        self.llm = llm_gateway or GroqGateway()
        self.redactor = redactor or Redactor()

    def group_events_into_clusters(self, events: list[Event]) -> list[list[Event]]:
        if not events:
            return []

        ordered = sorted(events, key=lambda e: e.timestamp_utc)
        clusters_by_key: dict[str, list[Event]] = {}
        cluster_order: list[str] = []

        for idx, ev in enumerate(ordered):
            group_key = ev.attempt_group_id or f"{ev.incident_id}:{ev.day}:{ev.actor}:{ev.site}:{idx // 3}"
            if group_key not in clusters_by_key:
                clusters_by_key[group_key] = []
                cluster_order.append(group_key)
            clusters_by_key[group_key].append(ev)

        return [clusters_by_key[k] for k in cluster_order]

    def build_attempts_from_events(self, events: list[Event]) -> list[Attempt]:
        sanitized_events: list[Event] = []
        redaction_counts_by_event: dict[str, int] = {}

        for ev in events:
            clean_ev, r_count = self.redactor.redact_event(ev)
            sanitized_events.append(clean_ev)
            redaction_counts_by_event[clean_ev.id] = r_count

        clusters = self.group_events_into_clusters(sanitized_events)
        attempts: list[Attempt] = []
        for cluster in clusters:
            total_redactions = sum(redaction_counts_by_event.get(e.id, 0) for e in cluster)
            att = self.build_single_attempt(cluster, redactions_count=total_redactions)
            attempts.append(att)

        return attempts

    def build_single_attempt(self, cluster: list[Event], redactions_count: int = 0) -> Attempt:
        last_ev = cluster[-1]
        attempt_id = last_ev.attempt_group_id or self._MakeAttemptId(cluster)

        evidence_refs = self._ExtractEvidenceRefs(cluster)
        files_components = self._ExtractFilesAndComponents(cluster)
        conditions = self._ExtractConditions(cluster)
        shift = self._ExtractShift(cluster)

        system_prompt = (
            "You are Meredian's Attempt Builder. Given raw engineering events (git commits, terminal "
            "logs, and Band room messages) from one troubleshooting attempt, output a JSON object with "
            "keys: hypothesis, action, files_components (array of strings), outcome "
            "(one of: failed, partial, worked, inconclusive), reason, conclusion, next_suspect."
        )
        user_prompt = json.dumps(
            [e.model_dump() for e in cluster],
            indent=2,
        )

        structured = self.llm.complete_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            required_keys=self.REQUIRED_LLM_KEYS,
            fallback_builder=lambda: self._TemplateExtract(cluster, files_components),
        )

        outcome_val = str(structured.get("outcome", "failed")).lower()
        if outcome_val not in ("failed", "partial", "worked", "inconclusive"):
            outcome_val = "inconclusive"

        merged_files = list(dict.fromkeys(files_components + list(structured.get("files_components") or [])))

        attempt = Attempt(
            id=attempt_id,
            incident_id=last_ev.incident_id,
            day=last_ev.day,
            shift=shift,
            who=last_ev.actor,
            site=last_ev.site,
            timestamp_utc=last_ev.timestamp_utc,
            hypothesis=str(structured.get("hypothesis") or "Investigating incident symptom"),
            action=str(structured.get("action") or "Applied configuration/code change"),
            files_components=merged_files,
            evidence_refs=evidence_refs,
            outcome=outcome_val,
            reason=str(structured.get("reason") or "Observed system behavior after change"),
            conclusion=str(structured.get("conclusion") or "Further investigation needed"),
            next_suspect=str(structured.get("next_suspect") or "Upstream middleware"),
            conditions=conditions,
            redactions_count=redactions_count,
        )
        attempt.narrative = HindsightMemoryWrapper.build_narrative(attempt)
        return attempt

    @staticmethod
    def _MakeAttemptId(cluster: list[Event]) -> str:
        raw = ":".join(e.id for e in cluster)
        digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8]
        return f"att-{cluster[-1].incident_id}-{digest}"

    @staticmethod
    def _ExtractEvidenceRefs(cluster: list[Event]) -> list[str]:
        refs: list[str] = []
        for ev in cluster:
            p = ev.payload
            if p.get("commit"):
                ref = f"commit {p['commit']}"
                if ref not in refs:
                    refs.append(ref)
            if p.get("log_ref"):
                ref = str(p["log_ref"])
                if ref not in refs:
                    refs.append(ref)
            if p.get("message_id"):
                ref = str(p["message_id"])
                if ref not in refs:
                    refs.append(ref)
        if not refs:
            refs.append(cluster[-1].id)
        return refs

    @staticmethod
    def _ExtractFilesAndComponents(cluster: list[Event]) -> list[str]:
        items: list[str] = []
        for ev in cluster:
            for f in ev.payload.get("files", []) or []:
                if f not in items:
                    items.append(str(f))
            blob = json.dumps(ev.payload).lower()
            if "redis" in blob and "Redis" not in items:
                items.append("Redis")
            if "auth_middleware" in blob and "Auth middleware" not in items:
                items.append("Auth middleware")
        return items

    @staticmethod
    def _ExtractConditions(cluster: list[Event]) -> Optional[str]:
        for ev in reversed(cluster):
            if ev.payload.get("conditions"):
                return str(ev.payload["conditions"])
        return None

    @staticmethod
    def _ExtractShift(cluster: list[Event]) -> str:
        for ev in reversed(cluster):
            if ev.payload.get("shift"):
                return str(ev.payload["shift"])
        site = cluster[-1].site
        shift_map = {
            "Seattle": "Shift A (Seattle)",
            "Bengaluru": "Shift B (Bengaluru)",
            "London": "Shift C (London)",
        }
        return shift_map.get(site, f"Shift ({site})")

    @staticmethod
    def _TemplateExtract(cluster: list[Event], files_components: list[str]) -> dict[str, Any]:
        hypothesis = ""
        action = ""
        outcome = "inconclusive"
        reason = ""
        conclusion = ""
        next_suspect = "Auth middleware"

        for ev in cluster:
            p = ev.payload
            if p.get("hypothesis"):
                hypothesis = str(p["hypothesis"])
            if p.get("action"):
                action = str(p["action"])
            elif ev.source == "git" and p.get("message") and not action:
                action = str(p["message"])
            elif ev.source == "terminal" and p.get("command") and not action:
                action = f"Executed `{p['command']}`"

            if p.get("outcome"):
                outcome = str(p["outcome"])
            if p.get("reason"):
                reason = str(p["reason"])
            elif ev.source == "terminal" and p.get("output") and not reason:
                lines = [ln.strip() for ln in str(p["output"]).splitlines() if ln.strip()]
                if lines:
                    reason = lines[-1]

            if p.get("conclusion"):
                conclusion = str(p["conclusion"])
            if p.get("next_suspect"):
                next_suspect = str(p["next_suspect"])

            if ev.source == "band" and p.get("text"):
                txt = str(p["text"])
                if not action:
                    action = txt.split(".")[0]
                if not reason and len(txt.split(".")) > 1:
                    reason = txt.split(".")[1].strip()
                if "still" in txt.lower() or "failed" in txt.lower() or "dead end" in txt.lower():
                    if outcome == "inconclusive":
                        outcome = "failed"
                elif "held flat" in txt.lower() or "resolved" in txt.lower() or "worked" in txt.lower():
                    if outcome == "inconclusive":
                        outcome = "worked"

        if not hypothesis:
            hypothesis = f"Changing {', '.join(files_components) or 'service config'} resolves the issue"
        if not conclusion:
            conclusion = (
                f"{action} did not resolve the problem"
                if outcome == "failed"
                else f"{action} produced outcome: {outcome}"
            )

        return {
            "hypothesis": hypothesis,
            "action": action or "Modified service configuration",
            "files_components": files_components,
            "outcome": outcome,
            "reason": reason or "Observed post-change service telemetry",
            "conclusion": conclusion,
            "next_suspect": next_suspect,
        }

