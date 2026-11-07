from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, Optional
from pydantic import BaseModel, Field


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Event(BaseModel):

    id: str
    source: Literal["git", "terminal", "band"]
    actor: str
    site: str
    timestamp_utc: str
    type: str
    payload: dict[str, Any]
    incident_id: str
    day: int = 1
    attempt_group_id: Optional[str] = None


class Attempt(BaseModel):

    id: str
    incident_id: str
    day: int = 1
    shift: str = "Shift A"
    who: str
    site: str
    timestamp_utc: str
    hypothesis: str
    action: str
    files_components: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    outcome: Literal["failed", "partial", "worked", "inconclusive"]
    reason: str
    conclusion: str
    next_suspect: str
    narrative: str = ""
    retry_of: Optional[str] = None
    conditions: Optional[str] = None
    redactions_count: int = 0
    operation_id: Optional[str] = None
    operation_status: Literal["pending", "completed", "failed"] = "completed"


class BankConfig(BaseModel):

    bank_id: str
    mission: str = (
        "I am the institutional memory of a global engineering team. "
        "I prioritize what was tried, what failed and why, and what is still unknown."
    )
    directives: list[str] = Field(
        default_factory=lambda: [
            "Never claim something was tested without evidence.",
            "Always cite commit hash, terminal log line, or chat message ID.",
            "Never tell an engineer something is impossible; only state that it was tried under specific conditions.",
        ]
    )
    disposition: str = (
        "Moderately skeptical: carefully distinguish 'failed under these specific conditions' "
        "from 'can never work under any conditions'."
    )


class MemoryFact(BaseModel):

    id: str
    bank_id: str
    attempt_id: str
    text: str
    entities: list[str] = Field(default_factory=list)
    files_components: list[str] = Field(default_factory=list)
    outcome: str
    reason: str
    conclusion: str
    next_suspect: str
    evidence_refs: list[str] = Field(default_factory=list)
    who: str
    site: str
    timestamp_utc: str
    day: int = 1
    conditions: Optional[str] = None
    retry_of: Optional[str] = None
    token_estimate: int = 40


class Observation(BaseModel):

    id: str
    bank_id: str
    topic: str
    belief: str
    evidence_count: int
    supporting_attempt_ids: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    confidence: float = 0.8
    day_formed: int = 1
    updated_at_utc: str = Field(default_factory=utc_now_iso)
    history: list[dict[str, Any]] = Field(default_factory=list)


class Verdict(BaseModel):

    verdict: Literal["repeat", "related", "new"]
    confidence: float = Field(ge=0.0, le=1.0)
    what_was_tried: str = ""
    outcome: str = ""
    who: str = ""
    site: str = ""
    when: str = ""
    evidence: list[str] = Field(default_factory=list)
    differences: str = ""
    suggested_next: str = ""
    policy_action: Literal["interrupt", "soft_warning", "silent"] = "silent"
    matched_attempt_id: Optional[str] = None
    matched_observations: list[str] = Field(default_factory=list)
    memory_enabled: bool = True
    memory_status: str = "ready"
    interception_id: Optional[str] = None
    band_message: Optional[str] = None
    latency_ms: Optional[float] = None
    engine_path: Optional[str] = "Groq LPU + Vectorize Hindsight (400-token budget)"


class CheckActionRequest(BaseModel):

    incident_id: str = "payments-memleak"
    actor: str = "Aarav"
    site: str = "Bengaluru"
    source: Literal["vscode", "terminal", "watcher", "web"] = "vscode"
    file_path: Optional[str] = None
    diff_or_command: str
    conditions: Optional[str] = None
    memory_enabled: Optional[bool] = None


class InterceptionRecord(BaseModel):

    id: str
    timestamp_utc: str = Field(default_factory=utc_now_iso)
    incident_id: str
    actor: str
    site: str
    source: str
    file_path: Optional[str] = None
    raw_action: str
    normalized_query: str
    verdict: Verdict
    overridden: bool = False
    override_reason: Optional[str] = None
    override_conditions: Optional[str] = None
    override_attempt_id: Optional[str] = None


class RuledOutItem(BaseModel):

    hypothesis_or_action: str
    who: str
    site: str
    when: str
    outcome: str
    reason: str
    evidence_refs: list[str] = Field(default_factory=list)
    conditions: Optional[str] = None


class ConflictItem(BaseModel):

    topic: str
    summary: str
    attempts_involved: list[str] = Field(default_factory=list)
    conditions_diff: str
    evidence_refs: list[str] = Field(default_factory=list)


class Briefing(BaseModel):

    incident_id: str
    bank_id: str
    generated_at_utc: str = Field(default_factory=utc_now_iso)
    day: int = 1
    headline: str
    ruled_out: list[RuledOutItem] = Field(default_factory=list)
    leading_suspect: str
    leading_suspect_rationale: str
    conflicts: list[ConflictItem] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    recommended_first_step: str
    observations: list[Observation] = Field(default_factory=list)
    mental_model: str = ""
    total_attempts: int = 0
    dead_ends_count: int = 0
    memory_status: str = "ready"


class OverrideRequest(BaseModel):

    incident_id: str = "payments-memleak"
    interception_id: Optional[str] = None
    prior_attempt_id: Optional[str] = None
    actor: str = "Aarav"
    site: str = "Bengaluru"
    proposed_action: str
    reason: str
    new_conditions: str = ""
    files_components: list[str] = Field(default_factory=list)
    outcome: Literal["failed", "partial", "worked", "inconclusive"] = "inconclusive"


class OverrideResponse(BaseModel):

    override_id: str
    retained_attempt: Attempt
    updated_interception_id: Optional[str] = None
    message: str


class ReplayRequest(BaseModel):

    incident_id: str = "payments-memleak"
    up_to_day: int = 2
    reset_first: bool = True
    speed_multiplier: float = 100.0

