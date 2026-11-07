from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Optional

from attempts.schemas import CheckActionRequest, Verdict
from llm.gateway import GroqGateway
from memory.client import HindsightMemoryWrapper, INTERCEPTOR_TOKEN_BUDGET


def normalize_action(file_path: Optional[str], diff_or_command: str, conditions: Optional[str] = None) -> str:
    raw = f"{file_path or ''} {diff_or_command}".strip()
    lower = raw.lower()
    tags: list[str] = []

    if "redis-cli" in lower or "redis" in lower:
        tags.append("redis")
    if "timeout" in lower or "redis_timeout" in lower:
        tags.extend(["redis", "timeout", "redis_timeout", "config/redis.yml"])
    if "max_connections" in lower or "pool" in lower or "maxclients" in lower:
        tags.extend(["redis", "pool", "pool_size", "max_connections", "config/redis.yml"])
    if "keepalive" in lower:
        tags.extend(["redis", "keepalive", "config/redis.yml"])
    if "gc_sweep" in lower or "gc.collect" in lower:
        tags.extend(["gc", "worker", "services/payments/worker.py"])
    if "auth_middleware" in lower or "_session_cache" in lower or "ttlcache" in lower:
        tags.extend(["auth", "middleware", "session", "cache", "services/auth/auth_middleware.py"])
    if "jwks" in lower:
        tags.extend(["auth", "jwks", "timeout", "services/auth/jwks_client.py"])

    dedup_tags = list(dict.fromkeys(tags))
    cond_part = f" [conditions: {conditions}]" if conditions else ""
    tag_part = f" ({' '.join(dedup_tags)})" if dedup_tags else ""
    return f"{raw}{tag_part}{cond_part}".strip()


class ActionChecker:

    def __init__(
        self,
        memory: HindsightMemoryWrapper,
        llm: Optional[GroqGateway] = None,
        repeat_threshold: Optional[float] = None,
        related_threshold: Optional[float] = None,
    ) -> None:
        self.memory = memory
        self.llm = llm or GroqGateway()
        self.repeat_threshold = repeat_threshold or float(
            os.getenv("MEREDIAN_REPEAT_CONFIDENCE_THRESHOLD", "0.75")
        )
        self.related_threshold = related_threshold or float(
            os.getenv("MEREDIAN_RELATED_CONFIDENCE_THRESHOLD", "0.45")
        )

    def check(
        self,
        req: CheckActionRequest,
        global_memory_enabled: bool = True,
    ) -> tuple[str, Verdict]:
        t0 = time.perf_counter()
        effective_memory_enabled = (
            req.memory_enabled if req.memory_enabled is not None else global_memory_enabled
        )
        normalized_query = normalize_action(req.file_path, req.diff_or_command, req.conditions)

        if not effective_memory_enabled:
            verdict = Verdict(
                verdict="new",
                confidence=0.0,
                what_was_tried="Memory is toggled OFF (baseline mode without Meredian).",
                suggested_next="Enable Memory ON to check prior shift attempts in Hindsight.",
                policy_action="silent",
                memory_enabled=False,
                memory_status="disabled",
                latency_ms=round((time.perf_counter() - t0) * 1000, 2),
                engine_path="Local Mock Engine (Memory Bypassed)",
            )
            return normalized_query, verdict

        recalled = self.memory.recall_for_action(
            incident_id=req.incident_id,
            normalized_query=normalized_query,
            token_budget=INTERCEPTOR_TOKEN_BUDGET,
        )
        facts: list[dict[str, Any]] = recalled.get("facts", [])
        observations: list[dict[str, Any]] = recalled.get("observations", [])
        mem_status = recalled.get("memory_status", "ready")

        if not facts:
            verdict = Verdict(
                verdict="new",
                confidence=0.1,
                what_was_tried="No prior matching attempts in Hindsight bank.",
                suggested_next="Proceed and log outcome so subsequent shifts inherit the evidence.",
                policy_action="silent",
                memory_enabled=True,
                memory_status=mem_status,
                latency_ms=round((time.perf_counter() - t0) * 1000, 2),
                engine_path="Groq LPU + Vectorize Hindsight (400-token budget)",
            )
            return normalized_query, verdict

        verdict = self._JudgeAction(req, normalized_query, facts, observations, mem_status)
        verdict = self._ApplyPolicy(verdict)
        verdict.latency_ms = round((time.perf_counter() - t0) * 1000, 2)
        verdict.engine_path = "Groq LPU + Vectorize Hindsight (400-token budget)"
        return normalized_query, verdict

    def _JudgeAction(
        self,
        req: CheckActionRequest,
        normalized_query: str,
        facts: list[dict[str, Any]],
        observations: list[dict[str, Any]],
        mem_status: str,
    ) -> Verdict:
        system_prompt = (
            "You are Meredian's Action Judge. Given a proposed engineering action from the current shift "
            "and recalled attempts/observations from Hindsight, classify the action into JSON with keys: "
            "verdict ('repeat' | 'related' | 'new'), confidence (0.0 to 1.0), what_was_tried, outcome, "
            "who, site, when, evidence (array of strings), differences, suggested_next.\n"
            "Rules:\n"
            "- 'repeat': the same fix/parameter family was already tested and failed under similar conditions.\n"
            "- 'related': a similar fix was tested before, but the engineer provided materially different "
            "runtime conditions or prior shifts had conflicting results under different load.\n"
            "- 'new': this targets a different component/mechanism or implements the recommended next step "
            "(such as fixing a leak rather than repeating a ruled-out config tweak)."
        )
        user_prompt = json.dumps(
            {
                "proposed_action": req.diff_or_command,
                "file_path": req.file_path,
                "conditions": req.conditions,
                "recalled_facts": facts[:4],
                "observations": observations[:3],
            },
            indent=2,
        )

        judged_dict = self.llm.complete_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            required_keys=["verdict", "confidence", "what_was_tried", "outcome", "evidence", "suggested_next"],
            fallback_builder=lambda: self._RuleJudge(req, facts, observations),
        )

        v_type = str(judged_dict.get("verdict", "new")).lower()
        if v_type not in ("repeat", "related", "new"):
            v_type = "new"

        matched_obs_texts = [o.get("belief", "") for o in observations if o.get("belief")]

        return Verdict(
            verdict=v_type,
            confidence=max(0.0, min(1.0, float(judged_dict.get("confidence", 0.5)))),
            what_was_tried=str(judged_dict.get("what_was_tried", "")),
            outcome=str(judged_dict.get("outcome", "")),
            who=str(judged_dict.get("who", "")),
            site=str(judged_dict.get("site", "")),
            when=str(judged_dict.get("when", "")),
            evidence=list(judged_dict.get("evidence") or []),
            differences=str(judged_dict.get("differences", "")),
            suggested_next=str(judged_dict.get("suggested_next", "")),
            matched_attempt_id=judged_dict.get("matched_attempt_id"),
            matched_observations=matched_obs_texts,
            memory_enabled=True,
            memory_status=mem_status,
        )

    @staticmethod
    def _RuleJudge(
        req: CheckActionRequest,
        facts: list[dict[str, Any]],
        observations: list[dict[str, Any]],
    ) -> dict[str, Any]:
        action_text = f"{req.file_path or ''} {req.diff_or_command}".lower()
        cond_text = (req.conditions or "").strip().lower()

        if any(
            k in action_text
            for k in [
                "ttlcache",
                "_session_cache",
                "auth_middleware.py",
                "metrics.py",
                "postgres.yml",
                "statement_timeout",
                "webhooks.py",
                "kafka_consumer.py",
                "max_poll_records",
                "singleflight",
            ]
        ):
            failed_auth = [
                f for f in facts
                if "auth_middleware" in " ".join(f.get("files_components", [])).lower()
                and f.get("outcome") == "failed"
            ]
            if not failed_auth:
                return {
                    "verdict": "new",
                    "confidence": 0.92,
                    "what_was_tried": "This targets a new hypothesis or the recommended suspect (not a ruled-out dead end).",
                    "outcome": "untested",
                    "who": "",
                    "site": "",
                    "when": "",
                    "evidence": [],
                    "differences": "Targets new component or recommended fix path.",
                    "suggested_next": "Proceed with test and record telemetry in Band.",
                    "matched_attempt_id": None,
                }

        failed_facts = [f for f in facts if f.get("outcome") == "failed"]
        if not failed_facts:
            failed_facts = facts

        matched: Optional[dict[str, Any]] = None

        is_redis_action = any(
            k in action_text
            for k in ["redis_timeout", "redis-cli", "config set timeout", "redis_max_connections", "redis_keepalive", "config/redis.yml"]
        )
        if is_redis_action:
            redis_failed = [
                f for f in failed_facts
                if any(
                    rk in (f.get("text", "") + " " + " ".join(f.get("files_components", []))).lower()
                    for rk in ["redis", "timeout", "max_connections", "keepalive"]
                )
            ]
            if redis_failed:
                if "max_connections" in action_text or "pool" in action_text:
                    pool_matches = [f for f in redis_failed if "max_connections" in f.get("text", "").lower() or "pool" in f.get("text", "").lower()]
                    matched = pool_matches[0] if pool_matches else redis_failed[0]
                else:
                    timeout_matches = [f for f in redis_failed if "timeout" in f.get("text", "").lower()]
                    matched = timeout_matches[0] if timeout_matches else redis_failed[0]

        is_gc_action = "gc_sweep_interval" in action_text or "gc.collect" in action_text or "worker.py" in action_text
        if is_gc_action and matched is None:
            gc_facts = [
                f for f in facts
                if "gc_sweep" in f.get("text", "").lower() or "worker.py" in " ".join(f.get("files_components", [])).lower()
            ]
            if gc_facts:
                failed_gc = [f for f in gc_facts if f.get("outcome") == "failed"]
                matched = failed_gc[0] if failed_gc else gc_facts[0]

        if "jwks" in action_text and "timeout" in action_text and matched is None:
            jwks_facts = [f for f in failed_facts if "jwks" in f.get("text", "").lower()]
            if jwks_facts:
                matched = jwks_facts[0]

        if matched is None:
            return {
                "verdict": "new",
                "confidence": 0.85,
                "what_was_tried": "No matching dead-end attempt found for this file/parameter.",
                "outcome": "untested",
                "who": "",
                "site": "",
                "when": "",
                "evidence": [],
                "differences": "Distinct component or mechanism.",
                "suggested_next": "Proceed and monitor metrics.",
                "matched_attempt_id": None,
            }

        prior_cond = (matched.get("conditions") or "").strip().lower()
        has_new_conditions = bool(
            cond_text
            and cond_text != prior_cond
            and not ("prod-replay-1800rps" in cond_text and "prod-replay-1800rps" in prior_cond)
        )

        evidence_list = list(matched.get("evidence_refs", []))
        for obs in observations:
            for ref in obs.get("evidence_refs", []):
                if ref not in evidence_list:
                    evidence_list.append(ref)

        if has_new_conditions:
            return {
                "verdict": "related",
                "confidence": 0.68,
                "what_was_tried": f"{matched.get('action')} ({matched.get('reason')})",
                "outcome": matched.get("outcome", "failed"),
                "who": matched.get("who", "Engineer"),
                "site": matched.get("site", "Seattle"),
                "when": matched.get("timestamp_utc", ""),
                "evidence": evidence_list,
                "differences": (
                    f"Previously tested under [{matched.get('conditions') or 'standard staging/canary load'}], "
                    f"whereas current action specifies [{req.conditions}]."
                ),
                "suggested_next": (
                    f"Proceed with caution or use Override to link this test as a conditional retry; "
                    f"note that prior shifts narrowed the root cause to: {matched.get('next_suspect')}."
                ),
                "matched_attempt_id": matched.get("attempt_id"),
            }

        return {
            "verdict": "repeat",
            "confidence": 0.91,
            "what_was_tried": f"{matched.get('action')} — {matched.get('reason')}",
            "outcome": matched.get("outcome", "failed"),
            "who": matched.get("who", "Maya"),
            "site": matched.get("site", "Seattle"),
            "when": matched.get("timestamp_utc", ""),
            "evidence": evidence_list,
            "differences": "None — targets the same parameter/component under equivalent conditions.",
            "suggested_next": matched.get("next_suspect") or "Inspect Auth middleware _SESSION_CACHE",
            "matched_attempt_id": matched.get("attempt_id"),
        }

    def _ApplyPolicy(self, verdict: Verdict) -> Verdict:
        if verdict.verdict == "repeat" and verdict.confidence >= self.repeat_threshold:
            verdict.policy_action = "interrupt"
            ev_str = ", ".join(verdict.evidence) if verdict.evidence else "logged evidence"
            time_short = verdict.when[11:16] + " UTC" if len(verdict.when) >= 16 else verdict.when
            verdict.band_message = (
                f"Stop: {verdict.site} ({verdict.who}) tested this at {time_short} ({ev_str}): "
                f"{verdict.what_was_tried}. Outcome: {verdict.outcome}. "
                f"They narrowed it to: {verdict.suggested_next}."
            )
        elif verdict.verdict in ("related", "repeat") and verdict.confidence >= self.related_threshold:
            verdict.policy_action = "soft_warning"
            ev_str = ", ".join(verdict.evidence) if verdict.evidence else "logged evidence"
            verdict.band_message = (
                f"Heads up: Tried before under different conditions by {verdict.who} ({verdict.site}, {ev_str}). "
                f"{verdict.differences} Prior conclusion pointed to: {verdict.suggested_next}."
            )
        else:
            verdict.policy_action = "silent"
            verdict.band_message = None
        return verdict

