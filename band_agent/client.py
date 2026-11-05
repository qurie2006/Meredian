"""Band SDK / Room integration with Mock & Live adapter support."""
from __future__ import annotations

import os
import uuid
from typing import Any, Callable, Optional

import httpx
from pydantic import BaseModel, Field

from attempts.schemas import Briefing, Verdict, utc_now_iso
from decision.briefing import BriefingGenerator


class BandMessage(BaseModel):
    id: str = Field(default_factory=lambda: f"band-post-{uuid.uuid4().hex[:8]}")
    room_id: str = "payments-memleak-room"
    sender: str = "Meredian Agent"
    site: str = "System"
    kind: str = "interception"  # interception | briefing | engineer_update
    incident_id: str = "payments-memleak"
    text: str
    timestamp_utc: str = Field(default_factory=utc_now_iso)
    metadata: dict[str, Any] = Field(default_factory=dict)


class BandAgentClient:
    """Connects Meredian to Band rooms to listen for shift updates and post stop warnings/briefings."""

    def __init__(
        self,
        mode: Optional[str] = None,
        api_key: Optional[str] = None,
        room_id: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> None:
        self.mode = (mode or os.getenv("BAND_MODE", "mock")).lower()
        self.api_key = api_key if api_key is not None else os.getenv("BAND_API_KEY", "")
        self.room_id = room_id or os.getenv("BAND_ROOM_ID", "payments-memleak-room")
        self.base_url = (base_url or os.getenv("BAND_BASE_URL", "https://api.band.ai")).rstrip("/")
        self.room_messages: list[BandMessage] = []
        self._listeners: list[Callable[[BandMessage], None]] = []

    def register_listener(self, callback: Callable[[BandMessage], None]) -> None:
        self._listeners.append(callback)

    def receive_room_message(
        self,
        sender: str,
        site: str,
        text: str,
        incident_id: str = "payments-memleak",
        metadata: Optional[dict[str, Any]] = None,
    ) -> BandMessage:
        """Ingest an engineer/agent update from the Band room and notify registered listeners."""
        msg = BandMessage(
            room_id=self.room_id,
            sender=sender,
            site=site,
            kind="engineer_update",
            incident_id=incident_id,
            text=text,
            metadata=metadata or {},
        )
        self.room_messages.append(msg)
        for cb in self._listeners:
            cb(msg)
        return msg

    def post_interception_warning(
        self,
        incident_id: str,
        actor: str,
        site: str,
        proposed_action: str,
        verdict: Verdict,
    ) -> Optional[BandMessage]:
        """Post a repeat-attempt Stop message or soft warning to the Band room."""
        if verdict.policy_action == "silent" or not verdict.band_message:
            return None

        msg = BandMessage(
            room_id=self.room_id,
            sender="Meredian",
            site="Global Memory",
            kind=verdict.policy_action,
            incident_id=incident_id,
            text=verdict.band_message,
            metadata={
                "target_actor": actor,
                "target_site": site,
                "proposed_action": proposed_action,
                "verdict": verdict.verdict,
                "confidence": verdict.confidence,
                "evidence": verdict.evidence,
            },
        )
        self._DispatchPost(msg)
        return msg

    def post_briefing(self, briefing: Briefing) -> BandMessage:
        """Post the shift-start State of the Problem briefing to the Band room."""
        formatted = BriefingGenerator.format_for_band(briefing)
        msg = BandMessage(
            room_id=self.room_id,
            sender="Meredian",
            site="Global Memory",
            kind="briefing",
            incident_id=briefing.incident_id,
            text=formatted,
            metadata={"day": briefing.day, "dead_ends_count": briefing.dead_ends_count},
        )
        self._DispatchPost(msg)
        return msg

    def get_messages(self, incident_id: Optional[str] = None) -> list[BandMessage]:
        if not incident_id:
            return list(self.room_messages)
        return [m for m in self.room_messages if m.incident_id == incident_id]

    def clear(self, incident_id: Optional[str] = None) -> None:
        if not incident_id:
            self.room_messages.clear()
        else:
            self.room_messages = [m for m in self.room_messages if m.incident_id != incident_id]

    def _DispatchPost(self, msg: BandMessage) -> None:
        self.room_messages.append(msg)
        if self.mode == "live" and self.api_key:
            try:
                with httpx.Client(timeout=4.0) as client:
                    client.post(
                        f"{self.base_url}/v1/rooms/{self.room_id}/messages",
                        headers={"Authorization": f"Bearer {self.api_key}"},
                        json={
                            "sender": msg.sender,
                            "text": msg.text,
                            "metadata": msg.metadata,
                        },
                    )
            except Exception:
                pass

