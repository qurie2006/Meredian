from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from api.store import StateStore
from attempts.builder import AttemptBuilder
from attempts.schemas import (
    Attempt,
    Briefing,
    CheckActionRequest,
    InterceptionRecord,
    OverrideRequest,
    OverrideResponse,
    ReplayRequest,
    Verdict,
    utc_now_iso,
)
from band_agent.client import BandAgentClient
from collector.adapters import CollectorPipeline
from data.replay import ReplayEngine
from decision.briefing import BriefingGenerator
from decision.checker import ActionChecker
from llm.gateway import GroqGateway
from memory.client import HindsightMemoryWrapper
from redactor.sanitizer import Redactor

load_dotenv()


class EventsIngestRequest(BaseModel):
    incident_id: str = "payments-memleak"
    events: list[dict[str, Any]] = Field(default_factory=list)
    rebuild_attempts: bool = True


class RebuildAttemptsRequest(BaseModel):
    incident_id: str = "payments-memleak"


class MemoryToggleRequest(BaseModel):
    memory_enabled: bool


def create_app(
    memory: Optional[HindsightMemoryWrapper] = None,
    db_path: Optional[str] = None,
    auto_seed: bool = True,
) -> FastAPI:
    application = FastAPI(
        title="Meredian API",
        description="Shared institutional memory of a follow-the-sun engineering team",
        version="0.1.0",
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    store = StateStore(db_path=db_path or os.getenv("MEREDIAN_DB_PATH", "meredian_state.db"))
    redactor = Redactor()
    llm = GroqGateway()
    mem = memory or HindsightMemoryWrapper()
    collector = CollectorPipeline()
    builder = AttemptBuilder(llm_gateway=llm, redactor=redactor)
    band = BandAgentClient()
    checker = ActionChecker(memory=mem, llm=llm)
    briefing_gen = BriefingGenerator(memory=mem, llm=llm)
    replay_engine = ReplayEngine(
        collector=collector,
        attempt_builder=builder,
        memory=mem,
        band_client=band,
    )

    if store.get_kv("memory_enabled") is None:
        store.set_kv("memory_enabled", True)
    if store.get_kv("current_day") is None:
        store.set_kv("current_day", 2)

    def _SeedDayState(incident_id: str, up_to_day: int, reset_first: bool = True) -> dict[str, Any]:
        if reset_first:
            store.clear_incident(incident_id)
        res = replay_engine.replay_incident(
            incident_id=incident_id,
            up_to_day=up_to_day,
            reset_first=reset_first,
        )
        for ev in replay_engine.get_events_for_incident(incident_id, up_to_day=up_to_day):
            clean_ev, _ = redactor.redact_event(ev)
            store.save_event(clean_ev)
        for att in res["attempts_built"]:
            store.save_attempt(att)
        store.set_kv("current_day", up_to_day)
        prev_redactions = int(store.get_kv("redactions_blocked", 0))
        if reset_first:
            store.set_kv("redactions_blocked", res["redactions_blocked"])
        else:
            store.set_kv("redactions_blocked", prev_redactions + res["redactions_blocked"])

        if up_to_day > 0:
            brief = briefing_gen.generate(incident_id)
            band.post_briefing(brief)
        return res

    if auto_seed:
        if not store.get_attempts("auth-token-storm"):
            _SeedDayState("auth-token-storm", up_to_day=2, reset_first=True)
        if not store.get_attempts("redis-failover-stall"):
            _SeedDayState("redis-failover-stall", up_to_day=5, reset_first=True)
        if not store.get_attempts("payments-memleak"):
            _SeedDayState("payments-memleak", up_to_day=2, reset_first=True)

    @application.get("/", response_class=HTMLResponse)
    def serve_web_dashboard() -> HTMLResponse:
        web_index = Path(__file__).resolve().parent.parent / "web" / "index.html"
        if web_index.exists():
            return HTMLResponse(content=web_index.read_text(encoding="utf-8"))
        return HTMLResponse(content="<h1>Meredian API is running</h1>")

    @application.get("/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "service": "meredian-api",
            "memory_enabled": bool(store.get_kv("memory_enabled", True)),
            "current_day": int(store.get_kv("current_day", 2)),
            "llm_live_configured": llm.is_live_configured,
        }

    @application.get("/memory/status")
    def memory_status(
        incident_id: str = Query(default="payments-memleak"),
        operation_id: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        status = mem.get_memory_status(incident_id=incident_id, operation_id=operation_id)
        status["memory_enabled"] = bool(store.get_kv("memory_enabled", True))
        return status

    @application.post("/memory/toggle")
    def toggle_memory(req: MemoryToggleRequest) -> dict[str, Any]:
        store.set_kv("memory_enabled", req.memory_enabled)
        return {"memory_enabled": req.memory_enabled}

    @application.post("/events")
    def ingest_events(req: EventsIngestRequest) -> dict[str, Any]:
        grouped = collector.collect_and_group(req.events, default_incident_id=req.incident_id)
        inc_events = grouped.get(req.incident_id, [])

        redacted_total = 0
        for ev in inc_events:
            clean_ev, r_count = redactor.redact_event(ev)
            redacted_total += r_count
            store.save_event(clean_ev)
            if clean_ev.source == "band" and clean_ev.payload.get("text"):
                band.receive_room_message(
                    sender=clean_ev.actor,
                    site=clean_ev.site,
                    text=str(clean_ev.payload["text"]),
                    incident_id=req.incident_id,
                )

        store.set_kv(
            "redactions_blocked",
            int(store.get_kv("redactions_blocked", 0)) + redacted_total,
        )

        built_attempts: list[Attempt] = []
        if req.rebuild_attempts and inc_events:
            built_attempts = builder.build_attempts_from_events(inc_events)
            for att in built_attempts:
                op = mem.retain_attempt(att)
                att.operation_id = op.get("operation_id")
                store.save_attempt(att)

        return {
            "incident_id": req.incident_id,
            "events_ingested": len(inc_events),
            "attempts_built": [a.model_dump() for a in built_attempts],
            "redactions_blocked": redacted_total,
        }

    @application.post("/attempts/rebuild")
    def rebuild_attempts(req: RebuildAttemptsRequest) -> dict[str, Any]:
        events = store.get_events(req.incident_id)
        if not events:
            events = replay_engine.get_events_for_incident(
                req.incident_id,
                up_to_day=int(store.get_kv("current_day", 2)),
            )
        mem.reset(req.incident_id)
        attempts = builder.build_attempts_from_events(events)
        for att in attempts:
            op = mem.retain_attempt(att)
            att.operation_id = op.get("operation_id")
            store.save_attempt(att)

        return {
            "incident_id": req.incident_id,
            "attempts_rebuilt": len(attempts),
            "attempts": [a.model_dump() for a in attempts],
        }

    @application.post("/check", response_model=Verdict)
    def check_action(req: CheckActionRequest) -> Verdict:
        global_enabled = bool(store.get_kv("memory_enabled", True))
        normalized_query, verdict = checker.check(req, global_memory_enabled=global_enabled)

        interception_id = f"int-{uuid.uuid4().hex[:8]}"
        verdict.interception_id = interception_id

        record = InterceptionRecord(
            id=interception_id,
            incident_id=req.incident_id,
            actor=req.actor,
            site=req.site,
            source=req.source,
            file_path=req.file_path,
            raw_action=req.diff_or_command,
            normalized_query=normalized_query,
            verdict=verdict,
        )
        store.save_interception(record)

        if verdict.policy_action in ("interrupt", "soft_warning"):
            band.post_interception_warning(
                incident_id=req.incident_id,
                actor=req.actor,
                site=req.site,
                proposed_action=req.diff_or_command,
                verdict=verdict,
            )

        return verdict

    @application.post("/check/compare")
    def compare_action_with_and_without_memory(req: CheckActionRequest) -> dict[str, Any]:
        req_off = req.model_copy(update={"memory_enabled": False})
        req_on = req.model_copy(update={"memory_enabled": True})
        query_off, verdict_off = checker.check(req_off, global_memory_enabled=False)
        query_on, verdict_on = checker.check(req_on, global_memory_enabled=True)
        return {
            "normalized_query": query_on,
            "without_memory": verdict_off.model_dump(),
            "with_memory": verdict_on.model_dump(),
        }

    @application.get("/briefing/{incident}", response_model=Briefing)
    def get_briefing(
        incident: str,
        post_to_band: bool = False,
    ) -> Briefing:
        brief = briefing_gen.generate(incident)
        if post_to_band:
            band.post_briefing(brief)
        return brief

    @application.post("/override", response_model=OverrideResponse)
    def record_override(req: OverrideRequest) -> OverrideResponse:
        override_id = f"ovr-{uuid.uuid4().hex[:8]}"
        clean_reason = redactor.redact_text(req.reason)
        clean_cond = redactor.redact_text(req.new_conditions)
        clean_action = redactor.redact_text(req.proposed_action)

        prior_id = req.prior_attempt_id
        if not prior_id and req.interception_id:
            existing_int = store.get_interception(req.interception_id)
            if existing_int and existing_int.verdict.matched_attempt_id:
                prior_id = existing_int.verdict.matched_attempt_id

        files_list = list(req.files_components) if req.files_components else ["config/redis.yml"]
        current_day = int(store.get_kv("current_day", 2))

        linked_attempt = Attempt(
            id=f"att-retry-{override_id[-6:]}",
            incident_id=req.incident_id,
            day=current_day,
            shift=f"Shift ({req.site})",
            who=req.actor,
            site=req.site,
            timestamp_utc=utc_now_iso(),
            hypothesis=f"Conditional retry: {clean_reason.text}",
            action=clean_action.text,
            files_components=files_list,
            evidence_refs=[override_id] + ([f"retry_of:{prior_id}"] if prior_id else []),
            outcome=req.outcome,
            reason=f"Overridden by {req.actor} ({req.site}): {clean_reason.text}",
            conclusion=(
                f"Retried under new conditions [{clean_cond.text or clean_reason.text}] "
                f"with outcome={req.outcome}"
            ),
            next_suspect="Monitor telemetry under new conditions",
            retry_of=prior_id,
            conditions=clean_cond.text or clean_reason.text,
            redactions_count=clean_reason.count + clean_cond.count + clean_action.count,
        )
        linked_attempt.narrative = HindsightMemoryWrapper.build_narrative(linked_attempt)

        op = mem.retain_attempt(linked_attempt)
        linked_attempt.operation_id = op.get("operation_id")
        store.save_attempt(linked_attempt)

        if req.interception_id:
            existing = store.get_interception(req.interception_id)
            if existing:
                existing.overridden = True
                existing.override_reason = clean_reason.text
                existing.override_conditions = clean_cond.text
                existing.override_attempt_id = linked_attempt.id
                store.save_interception(existing)

        band.receive_room_message(
            sender=req.actor,
            site=req.site,
            text=(
                f"Override recorded ({override_id}, retry_of={prior_id or 'none'}): "
                f"Testing `{clean_action.text}` because: {clean_reason.text} "
                f"[conditions: {clean_cond.text or 'updated'}]."
            ),
            incident_id=req.incident_id,
        )

        return OverrideResponse(
            override_id=override_id,
            retained_attempt=linked_attempt,
            updated_interception_id=req.interception_id,
            message=(
                f"Retained conditional retry `{linked_attempt.id}` "
                f"(retry_of={prior_id or 'none'}) in Hindsight bank `{req.incident_id}`."
            ),
        )

    @application.get("/timeline/{incident}")
    def get_timeline(incident: str) -> dict[str, Any]:
        meta = replay_engine.get_incident_meta(incident)
        attempts = store.get_attempts(incident)
        events = store.get_events(incident)
        dead_ends = [a for a in attempts if a.outcome == "failed"]
        return {
            "incident": {k: v for k, v in meta.items() if k != "events"},
            "current_day": int(store.get_kv("current_day", 2)),
            "attempts": [a.model_dump() for a in attempts],
            "events": [e.model_dump() for e in events],
            "total_attempts": len(attempts),
            "dead_ends_count": len(dead_ends),
            "redactions_blocked": int(store.get_kv("redactions_blocked", 0)),
        }

    @application.get("/interceptions")
    def get_interceptions(incident_id: Optional[str] = None) -> dict[str, Any]:
        records = store.get_interceptions(incident_id)
        interrupts = sum(1 for r in records if r.verdict.policy_action == "interrupt")
        warnings = sum(1 for r in records if r.verdict.policy_action == "soft_warning")
        silences = sum(1 for r in records if r.verdict.policy_action == "silent")
        overrides = sum(1 for r in records if r.overridden)
        return {
            "total": len(records),
            "interrupts": interrupts,
            "soft_warnings": warnings,
            "silences": silences,
            "overrides": overrides,
            "items": [r.model_dump() for r in records],
        }

    @application.post("/replay/start")
    def start_replay(req: ReplayRequest) -> dict[str, Any]:
        res = _SeedDayState(
            incident_id=req.incident_id,
            up_to_day=req.up_to_day,
            reset_first=req.reset_first,
        )
        brief = briefing_gen.generate(req.incident_id)
        return {
            "incident_id": req.incident_id,
            "up_to_day": req.up_to_day,
            "events_replayed": res["events_replayed"],
            "attempts_built": [a.model_dump() for a in res["attempts_built"]],
            "redactions_blocked": res["redactions_blocked"],
            "briefing": brief.model_dump(),
        }

    @application.get("/explorer/{incident}")
    def explore_memory(
        incident: str,
        q: str = "",
    ) -> dict[str, Any]:
        return mem.search_explorer(incident_id=incident, query=q)

    @application.get("/band/messages")
    def get_band_messages(incident_id: Optional[str] = None) -> dict[str, Any]:
        msgs = band.get_messages(incident_id)
        return {
            "room_id": band.room_id,
            "mode": band.mode,
            "count": len(msgs),
            "messages": [m.model_dump() for m in msgs],
        }

    @application.get("/overview")
    def get_overview(incident_id: str = "payments-memleak") -> dict[str, Any]:
        incidents = replay_engine.list_incidents_meta()
        attempts = store.get_attempts(incident_id)
        interceptions = store.get_interceptions(incident_id)

        dead_ends_recorded = sum(1 for a in attempts if a.outcome == "failed")
        repeats_stopped = sum(
            1 for r in interceptions
            if r.verdict.policy_action in ("interrupt", "soft_warning") and not r.overridden
        )
        dead_ends_avoided = max(repeats_stopped, dead_ends_recorded)
        hours_per_dead_end = 2.5
        estimated_hours_saved = round(dead_ends_avoided * hours_per_dead_end, 1)

        return {
            "company": replay_engine.load_world().get("company", {}),
            "active_incident_id": incident_id,
            "current_day": int(store.get_kv("current_day", 2)),
            "memory_enabled": bool(store.get_kv("memory_enabled", True)),
            "incidents": incidents,
            "metrics": {
                "active_incidents_count": len(incidents),
                "total_attempts_logged": len(attempts),
                "dead_ends_documented": dead_ends_recorded,
                "interceptions_triggered": repeats_stopped,
                "dead_ends_avoided": dead_ends_avoided,
                "estimated_hours_saved": estimated_hours_saved,
                "hours_saved_assumption": (
                    f"{dead_ends_avoided} avoided dead-end repeat(s) × {hours_per_dead_end} hrs "
                    "(avg build + 20m soak test + log triage per shift attempt)"
                ),
                "secrets_redacted": int(store.get_kv("redactions_blocked", 0)),
            },
        }

    application.state.handlers = {
        "health": health,
        "memory_status": memory_status,
        "toggle_memory": toggle_memory,
        "ingest_events": ingest_events,
        "rebuild_attempts": rebuild_attempts,
        "check_action": check_action,
        "compare_action": compare_action_with_and_without_memory,
        "get_briefing": get_briefing,
        "record_override": record_override,
        "get_timeline": get_timeline,
        "get_interceptions": get_interceptions,
        "start_replay": start_replay,
        "explore_memory": explore_memory,
        "get_band_messages": get_band_messages,
        "get_overview": get_overview,
    }

    return application


app = create_app()
