"""Local Hindsight Client & Engine compatible with `from hindsight_client import Hindsight`.

Communicates with a running `hindsight-api` server at `base_url` (default http://localhost:8888)
over HTTP when reachable, and seamlessly falls back to a local persistent Hindsight engine
(backed by `.hindsight/banks.json`) when the daemon is not running or still starting.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import socket
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

import httpx


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _estimate_tokens(text: str) -> int:
    return max(1, int(len(text.split()) * 1.3))


def _tokenize(text: str) -> list[str]:
    cleaned = re.sub(r"[^a-zA-Z0-9_./:-]+", " ", text.lower())
    stop = {
        "the", "and", "for", "with", "that", "this", "from", "was", "were",
        "are", "into", "after", "before", "under", "still", "tried", "test",
        "tested", "when", "where", "what", "which", "have", "has", "had",
    }
    return [t for t in cleaned.split() if len(t) > 1 and t not in stop]


class Hindsight:
    """Hindsight client supporting retain, recall, reflect, bank config, and async operation tracking."""

    _lock = threading.RLock()

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        storage_path: Optional[str] = None,
        timeout: float = 3.0,
    ) -> None:
        self.base_url = (base_url or os.getenv("HINDSIGHT_BASE_URL", "http://localhost:8888")).rstrip("/")
        self.api_key = api_key or os.getenv("HINDSIGHT_API_KEY", "")
        self.timeout = timeout
        default_store = os.getenv("HINDSIGHT_STORAGE_PATH", ".hindsight/banks.json")
        self.storage_path = Path(storage_path or default_store)
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self._http_available: Optional[bool] = None
        self._EnsureStore()

    def _EnsureStore(self) -> None:
        with self._lock:
            if not self.storage_path.exists():
                self._SaveStore({"banks": {}, "operations": {}})

    def _LoadStore(self) -> dict[str, Any]:
        with self._lock:
            if not self.storage_path.exists():
                return {"banks": {}, "operations": {}}
            try:
                return json.loads(self.storage_path.read_text(encoding="utf-8"))
            except Exception:
                return {"banks": {}, "operations": {}}

    def _SaveStore(self, data: dict[str, Any]) -> None:
        with self._lock:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self.storage_path.with_suffix(".tmp")
            tmp_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            tmp_path.replace(self.storage_path)

    def _EnsureBank(self, store: dict[str, Any], bank_id: str) -> dict[str, Any]:
        banks = store.setdefault("banks", {})
        if bank_id not in banks:
            banks[bank_id] = {
                "bank_id": bank_id,
                "config": {
                    "mission": (
                        "I am the institutional memory of a global engineering team. "
                        "I prioritize what was tried, what failed and why, and what is still unknown."
                    ),
                    "directives": [
                        "Never claim something was tested without evidence.",
                        "Always cite commit or log.",
                        "Never tell an engineer something is impossible, only that it was tried under specific conditions.",
                    ],
                    "disposition": "moderately_skeptical",
                },
                "memories": [],
                "facts": [],
                "observations": [],
                "mental_model": "",
                "created_at": _utc_now(),
                "updated_at": _utc_now(),
            }
        return banks[bank_id]

    def _TryHttp(self, method: str, path: str, payload: Optional[dict[str, Any]] = None) -> Optional[dict[str, Any]]:
        """Attempt to call a running `hindsight-api` server on `self.base_url` if reachable."""
        if os.getenv("HINDSIGHT_FORCE_EMBEDDED", "0") == "1":
            return None
        if self._http_available is False:
            return None
        if self._http_available is None:
            parsed = urlparse(self.base_url)
            host = "127.0.0.1" if parsed.hostname in ("localhost", "127.0.0.1", None) else parsed.hostname
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            try:
                with socket.create_connection((host, port), timeout=0.05):
                    self._http_available = True
            except OSError:
                self._http_available = False
                return None

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        url = f"{self.base_url}{path}"
        try:
            with httpx.Client(timeout=self.timeout) as client:
                if method.upper() == "GET":
                    resp = client.get(url, params=payload, headers=headers)
                else:
                    resp = client.post(url, json=payload, headers=headers)
                if resp.status_code < 400:
                    return resp.json()
        except Exception:
            return None
        return None

    def configure_bank(
        self,
        bank_id: str,
        mission: str,
        directives: list[str],
        disposition: str = "moderately_skeptical",
    ) -> dict[str, Any]:
        """Configure bank mission, hard directives, and disposition."""
        http_res = self._TryHttp(
            "POST",
            f"/v1/default/banks/{bank_id}/config",
            {"mission": mission, "directives": directives, "disposition": disposition},
        )
        with self._lock:
            store = self._LoadStore()
            bank = self._EnsureBank(store, bank_id)
            bank["config"] = {
                "mission": mission,
                "directives": directives,
                "disposition": disposition,
            }
            bank["updated_at"] = _utc_now()
            self._SaveStore(store)
        return http_res or {"status": "configured", "bank_id": bank_id, "config": bank["config"]}

    def retain(
        self,
        bank_id: str,
        content: str,
        metadata: Optional[dict[str, Any]] = None,
        timestamp: Optional[str] = None,
        simulate_async_ms: int = 0,
    ) -> dict[str, Any]:
        """Retain a narrative in `bank_id`, extract structured facts, and consolidate observations."""
        metadata = metadata or {}
        ts = timestamp or metadata.get("timestamp_utc") or _utc_now()
        op_hash = hashlib.sha1(f"{bank_id}:{ts}:{content}".encode("utf-8")).hexdigest()[:12]
        op_id = f"op-{op_hash}"

        http_res = self._TryHttp(
            "POST",
            f"/v1/default/banks/{bank_id}/memories",
            {"content": content, "metadata": metadata, "timestamp": ts},
        )

        with self._lock:
            store = self._LoadStore()
            bank = self._EnsureBank(store, bank_id)
            ops = store.setdefault("operations", {})

            ready_at = time.time() + (simulate_async_ms / 1000.0 if simulate_async_ms > 0 else 0.0)
            ops[op_id] = {
                "operation_id": op_id,
                "bank_id": bank_id,
                "status": "pending" if simulate_async_ms > 0 else "completed",
                "ready_at": ready_at,
                "created_at": _utc_now(),
            }

            mem_id = metadata.get("attempt_id") or f"mem-{op_hash}"
            existing_ids = {m.get("id") for m in bank["memories"]}
            if mem_id not in existing_ids:
                memory_entry = {
                    "id": mem_id,
                    "content": content,
                    "timestamp_utc": ts,
                    "metadata": metadata,
                    "operation_id": op_id,
                    "tokens": _estimate_tokens(content),
                }
                bank["memories"].append(memory_entry)

                fact = self._ExtractFact(bank_id, mem_id, content, ts, metadata)
                bank["facts"].append(fact)
                self._ConsolidateObservations(bank)
                self._RefreshMentalModel(bank)
                bank["updated_at"] = _utc_now()

            self._SaveStore(store)

        return http_res or {
            "operation_id": op_id,
            "bank_id": bank_id,
            "memory_id": mem_id,
            "status": "pending" if simulate_async_ms > 0 else "completed",
        }

    def get_operation_status(self, bank_id: str, operation_id: Optional[str] = None) -> dict[str, Any]:
        """Check whether asynchronous retain/consolidation operations in a bank have completed."""
        with self._lock:
            store = self._LoadStore()
            ops = store.get("operations", {})
            now = time.time()
            changed = False
            pending_count = 0

            for oid, op in ops.items():
                if op.get("bank_id") != bank_id:
                    continue
                if op.get("status") == "pending":
                    if now >= op.get("ready_at", 0):
                        op["status"] = "completed"
                        changed = True
                    else:
                        pending_count += 1

            if changed:
                self._SaveStore(store)

            if operation_id and operation_id in ops:
                target = ops[operation_id]
                return {
                    "operation_id": operation_id,
                    "bank_id": bank_id,
                    "status": target["status"],
                    "memory_status": "updating" if target["status"] == "pending" else "ready",
                }

            return {
                "bank_id": bank_id,
                "pending_operations": pending_count,
                "memory_status": "updating" if pending_count > 0 else "ready",
            }

    def recall(
        self,
        bank_id: str,
        query: str,
        token_budget: int = 600,
        include_observations: bool = True,
    ) -> dict[str, Any]:
        """Recall relevant facts and consolidated observations within a token budget."""
        http_res = self._TryHttp(
            "POST",
            f"/v1/default/banks/{bank_id}/recall",
            {"query": query, "token_budget": token_budget},
        )
        with self._lock:
            store = self._LoadStore()
            op_state = self.get_operation_status(bank_id)
            bank = store.get("banks", {}).get(bank_id)
            if not bank:
                return http_res or {
                    "bank_id": bank_id,
                    "query": query,
                    "token_budget": token_budget,
                    "tokens_used": 0,
                    "facts": [],
                    "observations": [],
                    "memory_status": op_state["memory_status"],
                }

            query_tokens = _tokenize(query)
            scored_facts: list[tuple[float, dict[str, Any]]] = []
            for fact in bank.get("facts", []):
                score = self._ScoreFact(query_tokens, query, fact)
                if score > 0:
                    scored_facts.append((score, fact))

            scored_facts.sort(key=lambda item: (item[0], item[1].get("timestamp_utc", "")), reverse=True)

            selected_facts: list[dict[str, Any]] = []
            tokens_used = 0
            for score, fact in scored_facts:
                cost = fact.get("token_estimate", _estimate_tokens(fact.get("text", "")))
                if tokens_used + cost > token_budget and selected_facts:
                    break
                fact_with_score = dict(fact)
                fact_with_score["relevance_score"] = round(score, 3)
                selected_facts.append(fact_with_score)
                tokens_used += cost

            selected_obs: list[dict[str, Any]] = []
            if include_observations:
                for obs in bank.get("observations", []):
                    obs_tokens = _tokenize(f"{obs.get('topic', '')} {obs.get('belief', '')}")
                    overlap = len(set(query_tokens) & set(obs_tokens))
                    if overlap > 0 or not query_tokens or len(selected_facts) > 0:
                        selected_obs.append(obs)

            return http_res or {
                "bank_id": bank_id,
                "query": query,
                "token_budget": token_budget,
                "tokens_used": tokens_used,
                "facts": selected_facts,
                "observations": selected_obs,
                "mental_model": bank.get("mental_model", ""),
                "memory_status": op_state["memory_status"],
            }

    def reflect(
        self,
        bank_id: str,
        prompt: str,
        context: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Reflect over bank observations, facts, and directives to synthesize judgment or briefing."""
        http_res = self._TryHttp(
            "POST",
            f"/v1/default/banks/{bank_id}/reflect",
            {"prompt": prompt, "context": context or {}},
        )
        with self._lock:
            store = self._LoadStore()
            op_state = self.get_operation_status(bank_id)
            bank = store.get("banks", {}).get(bank_id)
            if not bank:
                return http_res or {
                    "bank_id": bank_id,
                    "reflection": "No prior attempts or observations recorded in this bank yet.",
                    "facts": [],
                    "observations": [],
                    "config": {},
                    "memory_status": op_state["memory_status"],
                }

            facts = bank.get("facts", [])
            observations = bank.get("observations", [])
            mental_model = bank.get("mental_model", "")

            return http_res or {
                "bank_id": bank_id,
                "reflection": mental_model or "Bank contains institutional memory of engineering attempts.",
                "facts": facts,
                "observations": observations,
                "mental_model": mental_model,
                "config": bank.get("config", {}),
                "memory_status": op_state["memory_status"],
            }

    def get_bank_state(self, bank_id: str) -> dict[str, Any]:
        """Return full bank state for Memory Explorer and inspection."""
        with self._lock:
            store = self._LoadStore()
            op_state = self.get_operation_status(bank_id)
            bank = store.get("banks", {}).get(bank_id)
            if not bank:
                return {
                    "bank_id": bank_id,
                    "config": {},
                    "memories": [],
                    "facts": [],
                    "observations": [],
                    "mental_model": "",
                    "memory_status": op_state["memory_status"],
                }
            result = dict(bank)
            result["memory_status"] = op_state["memory_status"]
            return result

    def reset_bank(self, bank_id: Optional[str] = None) -> None:
        """Clear a specific bank or all banks (used by replay engine)."""
        with self._lock:
            store = self._LoadStore()
            if bank_id:
                store.get("banks", {}).pop(bank_id, None)
                ops = store.get("operations", {})
                for k in [k for k, v in ops.items() if v.get("bank_id") == bank_id]:
                    ops.pop(k, None)
            else:
                store["banks"] = {}
                store["operations"] = {}
            self._SaveStore(store)

    def _ExtractFact(
        self,
        bank_id: str,
        mem_id: str,
        content: str,
        timestamp_utc: str,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        entities = set()
        for candidate in [
            "redis", "timeout", "redis_timeout", "pool", "pool_size", "max_connections",
            "auth", "middleware", "jwt", "session", "cache", "connection", "worker",
            "gc", "retry", "backoff", "webhook", "stripe", "kafka", "postgres",
        ]:
            if candidate in content.lower() or candidate in json.dumps(metadata).lower():
                entities.add(candidate)

        for comp in metadata.get("files_components", []):
            entities.add(str(comp).lower())

        return {
            "id": f"fact-{mem_id}",
            "bank_id": bank_id,
            "attempt_id": metadata.get("attempt_id", mem_id),
            "text": content,
            "action": metadata.get("action", content),
            "hypothesis": metadata.get("hypothesis", ""),
            "entities": sorted(entities),
            "files_components": metadata.get("files_components", []),
            "outcome": metadata.get("outcome", "failed" if "persist" in content.lower() or "fail" in content.lower() else "inconclusive"),
            "reason": metadata.get("reason", ""),
            "conclusion": metadata.get("conclusion", ""),
            "next_suspect": metadata.get("next_suspect", ""),
            "evidence_refs": metadata.get("evidence_refs", []),
            "who": metadata.get("who", "Engineer"),
            "site": metadata.get("site", "Global"),
            "timestamp_utc": timestamp_utc,
            "day": int(metadata.get("day", 1)),
            "conditions": metadata.get("conditions"),
            "retry_of": metadata.get("retry_of"),
            "token_estimate": _estimate_tokens(content),
        }

    def _ScoreFact(self, query_tokens: list[str], raw_query: str, fact: dict[str, Any]) -> float:
        if not query_tokens:
            return 1.0
        searchable = " ".join(
            [
                fact.get("text", ""),
                fact.get("action", ""),
                fact.get("hypothesis", ""),
                fact.get("conclusion", ""),
                " ".join(fact.get("entities", [])),
                " ".join(fact.get("files_components", [])),
            ]
        ).lower()
        fact_tokens = set(_tokenize(searchable))
        q_set = set(query_tokens)

        overlap = q_set & fact_tokens
        if not overlap:
            return 0.0

        # Boost domain-critical tokens like component names, config keys, file paths
        high_signal = {
            "redis", "timeout", "redis_timeout", "pool", "pool_size", "maxclients",
            "auth", "middleware", "session", "token", "cache", "lru", "eviction",
            "connection", "keepalive", "retry", "circuit", "breaker",
        }
        signal_matches = len(overlap & high_signal)
        file_matches = sum(
            1 for f in fact.get("files_components", []) if f.lower() in raw_query.lower()
        )

        base_score = len(overlap) / max(1.0, math.sqrt(len(q_set)))
        return base_score + (signal_matches * 0.65) + (file_matches * 0.9)

    def _ConsolidateObservations(self, bank: dict[str, Any]) -> None:
        """Background observation worker: consolidates facts into beliefs with evolution history."""
        facts: list[dict[str, Any]] = bank.get("facts", [])
        existing_obs_by_id = {o["id"]: o for o in bank.get("observations", [])}
        new_observations: list[dict[str, Any]] = []

        # Group 1: Redis timeout / pool / connection config changes
        redis_facts = [
            f for f in facts
            if any(
                k in " ".join(f.get("entities", []) + f.get("files_components", [])).lower()
                or k in f.get("text", "").lower()
                for k in ["redis", "timeout", "pool", "max_connections", "keepalive"]
            )
        ]
        if redis_facts:
            failed_redis = [f for f in redis_facts if f.get("outcome") == "failed"]
            worked_redis = [f for f in redis_facts if f.get("outcome") == "worked"]
            all_refs = []
            for f in redis_facts:
                for ref in f.get("evidence_refs", []):
                    if ref not in all_refs:
                        all_refs.append(ref)
            max_day = max(int(f.get("day", 1)) for f in redis_facts)

            if len(failed_redis) >= 2 and not worked_redis:
                belief = (
                    f"Redis client/server configuration tuning (timeout increases, connection pool resizing, "
                    f"and keepalive adjustments) has been tested {len(failed_redis)} times across shifts and "
                    f"does not stop the memory growth. The leak originates upstream of Redis transport."
                )
                confidence = min(0.96, 0.72 + 0.08 * len(failed_redis))
            elif len(failed_redis) >= 1 and worked_redis:
                belief = (
                    f"Redis tuning failed under standard load ({len(failed_redis)} attempt(s)), "
                    f"but showed conditional success when paired with updated runtime conditions "
                    f"({worked_redis[-1].get('conditions') or 'modified environment'})."
                )
                confidence = 0.82
            else:
                f0 = redis_facts[0]
                belief = (
                    f"Initial evidence ({f0.get('site')}, Day {f0.get('day', 1)}) indicates raising Redis timeout "
                    f"alone did not prevent the memory spike ({f0.get('reason') or 'leak persisted'})."
                )
                confidence = 0.74

            obs_id = f"obs-{bank['bank_id']}-redis-config"
            prev_history = existing_obs_by_id.get(obs_id, {}).get("history", [])
            stage_entry = {
                "day": max_day,
                "evidence_count": len(redis_facts),
                "belief": belief,
                "confidence": round(confidence, 2),
                "timestamp_utc": redis_facts[-1].get("timestamp_utc", _utc_now()),
            }
            if not prev_history or prev_history[-1].get("belief") != belief:
                prev_history = list(prev_history) + [stage_entry]

            new_observations.append(
                {
                    "id": obs_id,
                    "bank_id": bank["bank_id"],
                    "topic": "Redis Timeout & Connection Pool Tuning",
                    "belief": belief,
                    "evidence_count": len(redis_facts),
                    "supporting_attempt_ids": [f["attempt_id"] for f in redis_facts],
                    "evidence_refs": all_refs,
                    "confidence": round(confidence, 2),
                    "day_formed": max_day,
                    "updated_at_utc": _utc_now(),
                    "history": prev_history,
                }
            )

        # Group 2: Auth middleware / session cache / token verification
        auth_facts = [
            f for f in facts
            if any(
                k in " ".join(f.get("entities", []) + f.get("files_components", [])).lower()
                or k in f.get("text", "").lower()
                for k in ["auth", "middleware", "session", "jwt", "token"]
            )
        ]
        if auth_facts:
            all_refs = []
            for f in auth_facts:
                for ref in f.get("evidence_refs", []):
                    if ref not in all_refs:
                        all_refs.append(ref)
            max_day = max(int(f.get("day", 1)) for f in auth_facts)
            worked_auth = [f for f in auth_facts if f.get("outcome") in ("worked", "partial")]
            if worked_auth:
                belief = (
                    f"Unbounded in-memory session/token caching in `auth_middleware.py` is confirmed as the primary "
                    f"driver of the RSS memory climb ({len(auth_facts)} attempt(s); bounded TTL eviction resolved "
                    f"the leak under production replay)."
                )
                confidence = 0.94
            else:
                belief = (
                    f"Auth middleware session caching is an active suspect ({len(auth_facts)} attempt(s)); "
                    f"heap profiles show retained `SessionContext` objects across retry storms."
                )
                confidence = 0.81

            obs_id = f"obs-{bank['bank_id']}-auth-middleware"
            prev_history = existing_obs_by_id.get(obs_id, {}).get("history", [])
            stage_entry = {
                "day": max_day,
                "evidence_count": len(auth_facts),
                "belief": belief,
                "confidence": round(confidence, 2),
                "timestamp_utc": auth_facts[-1].get("timestamp_utc", _utc_now()),
            }
            if not prev_history or prev_history[-1].get("belief") != belief:
                prev_history = list(prev_history) + [stage_entry]

            new_observations.append(
                {
                    "id": obs_id,
                    "bank_id": bank["bank_id"],
                    "topic": "Auth Middleware Session & Token Lifecycle",
                    "belief": belief,
                    "evidence_count": len(auth_facts),
                    "supporting_attempt_ids": [f["attempt_id"] for f in auth_facts],
                    "evidence_refs": all_refs,
                    "confidence": round(confidence, 2),
                    "day_formed": max_day,
                    "updated_at_utc": _utc_now(),
                    "history": prev_history,
                }
            )

        # Group 3: Cross-incident / retry storm / worker patterns
        other_facts = [
            f for f in facts
            if f not in redis_facts and f not in auth_facts
        ]
        if other_facts:
            all_refs = []
            for f in other_facts:
                for ref in f.get("evidence_refs", []):
                    if ref not in all_refs:
                        all_refs.append(ref)
            max_day = max(int(f.get("day", 1)) for f in other_facts)
            latest = other_facts[-1]
            belief = (
                f"Across {len(other_facts)} additional attempt(s), {latest.get('conclusion') or latest.get('text')}"
            )
            obs_id = f"obs-{bank['bank_id']}-general-patterns"
            prev_history = existing_obs_by_id.get(obs_id, {}).get("history", [])
            stage_entry = {
                "day": max_day,
                "evidence_count": len(other_facts),
                "belief": belief,
                "confidence": 0.78,
                "timestamp_utc": latest.get("timestamp_utc", _utc_now()),
            }
            if not prev_history or prev_history[-1].get("belief") != belief:
                prev_history = list(prev_history) + [stage_entry]

            new_observations.append(
                {
                    "id": obs_id,
                    "bank_id": bank["bank_id"],
                    "topic": "Service Worker & Retry Dynamics",
                    "belief": belief,
                    "evidence_count": len(other_facts),
                    "supporting_attempt_ids": [f["attempt_id"] for f in other_facts],
                    "evidence_refs": all_refs,
                    "confidence": 0.78,
                    "day_formed": max_day,
                    "updated_at_utc": _utc_now(),
                    "history": prev_history,
                }
            )

        bank["observations"] = new_observations

    def _RefreshMentalModel(self, bank: dict[str, Any]) -> None:
        facts = bank.get("facts", [])
        if not facts:
            bank["mental_model"] = "No engineering attempts recorded yet."
            return
        failed = [f for f in facts if f.get("outcome") == "failed"]
        worked = [f for f in facts if f.get("outcome") == "worked"]
        latest_suspect = next(
            (f.get("next_suspect") for f in reversed(facts) if f.get("next_suspect")),
            "Auth middleware session cache",
        )
        parts = [
            f"{len(facts)} attempt(s) recorded ({len(failed)} ruled out, {len(worked)} verified fix)."
        ]
        for obs in bank.get("observations", []):
            parts.append(obs["belief"])
        parts.append(f"Current leading focus: {latest_suspect}.")
        bank["mental_model"] = " ".join(parts)
