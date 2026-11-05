from __future__ import annotations

import os
from typing import Any, Optional

from attempts.schemas import Attempt, BankConfig, MemoryFact, Observation
from hindsight_client import Hindsight

TEAM_PATTERNS_BANK = "meredian-team-patterns"

INTERCEPTOR_TOKEN_BUDGET = 400
BRIEFING_TOKEN_BUDGET = 1600


class HindsightMemoryWrapper:

    def __init__(
        self,
        base_url: Optional[str] = None,
        storage_path: Optional[str] = None,
    ) -> None:
        self.base_url = base_url or os.getenv("HINDSIGHT_BASE_URL", "http://localhost:8888")
        self.client = Hindsight(base_url=self.base_url, storage_path=storage_path)
        self._configured_banks: set[str] = set()
        self.ensure_bank_configured(TEAM_PATTERNS_BANK)

    def ensure_bank_configured(self, bank_id: str) -> BankConfig:
        config = BankConfig(bank_id=bank_id)
        if bank_id not in self._configured_banks:
            self.client.configure_bank(
                bank_id=bank_id,
                mission=config.mission,
                directives=config.directives,
                disposition=config.disposition,
            )
            self._configured_banks.add(bank_id)
        return config

    def retain_attempt(
        self,
        attempt: Attempt,
        also_retain_team_pattern: bool = False,
        simulate_async_ms: int = 0,
    ) -> dict[str, Any]:
        bank_id = attempt.incident_id
        self.ensure_bank_configured(bank_id)

        narrative = attempt.narrative or self.build_narrative(attempt)
        metadata = {
            "attempt_id": attempt.id,
            "incident_id": attempt.incident_id,
            "day": attempt.day,
            "shift": attempt.shift,
            "who": attempt.who,
            "site": attempt.site,
            "timestamp_utc": attempt.timestamp_utc,
            "hypothesis": attempt.hypothesis,
            "action": attempt.action,
            "files_components": attempt.files_components,
            "evidence_refs": attempt.evidence_refs,
            "outcome": attempt.outcome,
            "reason": attempt.reason,
            "conclusion": attempt.conclusion,
            "next_suspect": attempt.next_suspect,
            "retry_of": attempt.retry_of,
            "conditions": attempt.conditions,
        }

        result = self.client.retain(
            bank_id=bank_id,
            content=narrative,
            metadata=metadata,
            timestamp=attempt.timestamp_utc,
            simulate_async_ms=simulate_async_ms,
        )

        if also_retain_team_pattern or attempt.day >= 5 or attempt.outcome == "worked":
            self.ensure_bank_configured(TEAM_PATTERNS_BANK)
            pattern_narrative = (
                f"[{attempt.incident_id} | Day {attempt.day} | {attempt.site}] "
                f"{narrative}"
            )
            self.client.retain(
                bank_id=TEAM_PATTERNS_BANK,
                content=pattern_narrative,
                metadata=metadata,
                timestamp=attempt.timestamp_utc,
            )

        return result

    def recall_for_action(
        self,
        incident_id: str,
        normalized_query: str,
        token_budget: int = INTERCEPTOR_TOKEN_BUDGET,
    ) -> dict[str, Any]:
        self.ensure_bank_configured(incident_id)
        incident_recall = self.client.recall(
            bank_id=incident_id,
            query=normalized_query,
            token_budget=token_budget,
            include_observations=True,
        )
        team_recall = self.client.recall(
            bank_id=TEAM_PATTERNS_BANK,
            query=normalized_query,
            token_budget=max(120, token_budget // 2),
            include_observations=True,
        )

        facts = list(incident_recall.get("facts", []))
        seen_ids = {f.get("attempt_id") for f in facts}
        for tf in team_recall.get("facts", []):
            if tf.get("attempt_id") not in seen_ids:
                facts.append(tf)

        observations = list(incident_recall.get("observations", []))
        seen_obs = {o.get("id") for o in observations}
        for tobs in team_recall.get("observations", []):
            if tobs.get("id") not in seen_obs:
                observations.append(tobs)

        return {
            "bank_id": incident_id,
            "query": normalized_query,
            "token_budget": token_budget,
            "tokens_used": incident_recall.get("tokens_used", 0),
            "facts": facts,
            "observations": observations,
            "mental_model": incident_recall.get("mental_model", ""),
            "memory_status": incident_recall.get("memory_status", "ready"),
        }

    def reflect_for_briefing(
        self,
        incident_id: str,
        token_budget: int = BRIEFING_TOKEN_BUDGET,
    ) -> dict[str, Any]:
        self.ensure_bank_configured(incident_id)
        reflection = self.client.reflect(
            bank_id=incident_id,
            prompt=(
                "Synthesize the current State of the Problem: (1) What has been ruled out with commit/log "
                "evidence, (2) What is the leading suspect, (3) Any conflicts across sites or conditions, "
                "(4) Open questions, and (5) Recommended first step for the incoming shift."
            ),
            context={"token_budget": token_budget},
        )
        team_state = self.client.get_bank_state(TEAM_PATTERNS_BANK)
        reflection["team_observations"] = team_state.get("observations", [])
        return reflection

    def get_memory_status(
        self,
        incident_id: str,
        operation_id: Optional[str] = None,
    ) -> dict[str, Any]:
        return self.client.get_operation_status(bank_id=incident_id, operation_id=operation_id)

    def search_explorer(self, incident_id: str, query: str = "") -> dict[str, Any]:
        bank_state = self.client.get_bank_state(incident_id)
        team_state = self.client.get_bank_state(TEAM_PATTERNS_BANK)
        if not query.strip():
            return {
                "bank_id": incident_id,
                "query": "",
                "config": bank_state.get("config", {}),
                "facts": bank_state.get("facts", []),
                "observations": bank_state.get("observations", []),
                "team_observations": team_state.get("observations", []),
                "mental_model": bank_state.get("mental_model", ""),
                "memory_status": bank_state.get("memory_status", "ready"),
            }

        recalled = self.recall_for_action(
            incident_id=incident_id,
            normalized_query=query,
            token_budget=BRIEFING_TOKEN_BUDGET,
        )
        recalled["config"] = bank_state.get("config", {})
        recalled["team_observations"] = team_state.get("observations", [])
        return recalled

    def reset(self, incident_id: Optional[str] = None) -> None:
        self.client.reset_bank(incident_id)
        if incident_id is None:
            self._configured_banks.clear()
            self.ensure_bank_configured(TEAM_PATTERNS_BANK)

    @staticmethod
    def build_narrative(attempt: Attempt) -> str:
        refs = ", ".join(attempt.evidence_refs) if attempt.evidence_refs else "unreferenced log"
        comps = ", ".join(attempt.files_components) if attempt.files_components else "service config"
        cond_clause = f" under conditions [{attempt.conditions}]" if attempt.conditions else ""
        retry_clause = f" (retry of {attempt.retry_of})" if attempt.retry_of else ""
        return (
            f"On Day {attempt.day} at {attempt.timestamp_utc}, {attempt.who} ({attempt.site}, {attempt.shift}) "
            f"tested hypothesis '{attempt.hypothesis}' by performing action '{attempt.action}' on {comps}"
            f"{cond_clause}{retry_clause} (evidence: {refs}). "
            f"Outcome: {attempt.outcome}. Reason: {attempt.reason}. "
            f"Conclusion: {attempt.conclusion}. Next suspect: {attempt.next_suspect}."
        )


class FakeMemory(HindsightMemoryWrapper):

    def __init__(self, storage_path: str = ".hindsight/test_banks.json") -> None:
        super().__init__(base_url="http://localhost:8888", storage_path=storage_path)
        self.reset()

