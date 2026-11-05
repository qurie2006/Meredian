"""SQLite persistence layer for Meredian API (events, attempts, interception log, settings)."""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Optional

from attempts.schemas import Attempt, Event, InterceptionRecord


class StateStore:
    """Thread-safe SQLite store for events, attempts, interceptions, and runtime toggles."""

    def __init__(self, db_path: str = "meredian_state.db") -> None:
        self.db_path = db_path
        self._lock = threading.RLock()
        self._InitDb()

    def _Connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _InitDb(self) -> None:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self._Connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id TEXT PRIMARY KEY,
                    incident_id TEXT NOT NULL,
                    timestamp_utc TEXT NOT NULL,
                    day INTEGER NOT NULL,
                    data_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS attempts (
                    id TEXT PRIMARY KEY,
                    incident_id TEXT NOT NULL,
                    timestamp_utc TEXT NOT NULL,
                    day INTEGER NOT NULL,
                    data_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS interceptions (
                    id TEXT PRIMARY KEY,
                    incident_id TEXT NOT NULL,
                    timestamp_utc TEXT NOT NULL,
                    data_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS kv_state (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL
                );
                """
            )

    def save_event(self, event: Event) -> None:
        with self._lock, self._Connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO events (id, incident_id, timestamp_utc, day, data_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (event.id, event.incident_id, event.timestamp_utc, event.day, event.model_dump_json()),
            )

    def get_events(self, incident_id: Optional[str] = None) -> list[Event]:
        with self._lock, self._Connect() as conn:
            if incident_id:
                rows = conn.execute(
                    "SELECT data_json FROM events WHERE incident_id = ? ORDER BY timestamp_utc ASC",
                    (incident_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT data_json FROM events ORDER BY timestamp_utc ASC"
                ).fetchall()
            return [Event.model_validate_json(r["data_json"]) for r in rows]

    def save_attempt(self, attempt: Attempt) -> None:
        with self._lock, self._Connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO attempts (id, incident_id, timestamp_utc, day, data_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (attempt.id, attempt.incident_id, attempt.timestamp_utc, attempt.day, attempt.model_dump_json()),
            )

    def get_attempts(self, incident_id: Optional[str] = None) -> list[Attempt]:
        with self._lock, self._Connect() as conn:
            if incident_id:
                rows = conn.execute(
                    "SELECT data_json FROM attempts WHERE incident_id = ? ORDER BY timestamp_utc ASC",
                    (incident_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT data_json FROM attempts ORDER BY timestamp_utc ASC"
                ).fetchall()
            return [Attempt.model_validate_json(r["data_json"]) for r in rows]

    def save_interception(self, record: InterceptionRecord) -> None:
        with self._lock, self._Connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO interceptions (id, incident_id, timestamp_utc, data_json)
                VALUES (?, ?, ?, ?)
                """,
                (record.id, record.incident_id, record.timestamp_utc, record.model_dump_json()),
            )

    def get_interception(self, interception_id: str) -> Optional[InterceptionRecord]:
        with self._lock, self._Connect() as conn:
            row = conn.execute(
                "SELECT data_json FROM interceptions WHERE id = ?",
                (interception_id,),
            ).fetchone()
            return InterceptionRecord.model_validate_json(row["data_json"]) if row else None

    def get_interceptions(self, incident_id: Optional[str] = None) -> list[InterceptionRecord]:
        with self._lock, self._Connect() as conn:
            if incident_id:
                rows = conn.execute(
                    "SELECT data_json FROM interceptions WHERE incident_id = ? ORDER BY timestamp_utc DESC",
                    (incident_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT data_json FROM interceptions ORDER BY timestamp_utc DESC"
                ).fetchall()
            return [InterceptionRecord.model_validate_json(r["data_json"]) for r in rows]

    def set_kv(self, key: str, value: Any) -> None:
        with self._lock, self._Connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO kv_state (key, value_json) VALUES (?, ?)",
                (key, json.dumps(value)),
            )

    def get_kv(self, key: str, default: Any = None) -> Any:
        with self._lock, self._Connect() as conn:
            row = conn.execute(
                "SELECT value_json FROM kv_state WHERE key = ?",
                (key,),
            ).fetchone()
            return json.loads(row["value_json"]) if row else default

    def clear_incident(self, incident_id: Optional[str] = None) -> None:
        with self._lock, self._Connect() as conn:
            if incident_id:
                conn.execute("DELETE FROM events WHERE incident_id = ?", (incident_id,))
                conn.execute("DELETE FROM attempts WHERE incident_id = ?", (incident_id,))
            else:
                conn.execute("DELETE FROM events")
                conn.execute("DELETE FROM attempts")
                conn.execute("DELETE FROM interceptions")

