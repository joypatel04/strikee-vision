"""Session review service: confirm / correct / void.

Each action updates the materialized session status and appends an immutable
correction Event. Original session times are preserved by the SessionStore.
"""
from __future__ import annotations

from typing import Optional

from .store import EventStore, SessionStore


class ReviewService:
    def __init__(self, sessions: SessionStore, events: EventStore):
        self.sessions = sessions
        self.events = events

    def _correction_event(self, session: dict, kind: str, actor: Optional[str],
                          reason: Optional[str]) -> None:
        self.events.append({
            "venue_id": session["venue_id"],
            "asset_id": session["asset_id"],
            "business_unit_id": session.get("business_unit_id"),
            "type": kind,                       # session_confirmed|corrected|voided
            "ts": session.get("end_ts") or session["start_ts"],
            "origin": "user",
            "actor": actor,
            "reason": reason,
            "correlation_id": session["id"],
        })

    def confirm(self, session_id: str, actor: Optional[str] = None) -> Optional[dict]:
        s = self.sessions.set_status(session_id, "confirmed")
        if s:
            self._correction_event(s, "session_confirmed", actor, None)
        return s

    def correct(self, session_id: str, start_ts: Optional[str] = None,
                end_ts: Optional[str] = None, actor: Optional[str] = None,
                reason: Optional[str] = None) -> Optional[dict]:
        s = self.sessions.correct_times(session_id, start_ts, end_ts)
        if s:
            self._correction_event(s, "session_corrected", actor, reason)
        return s

    def void(self, session_id: str, actor: Optional[str] = None,
             reason: Optional[str] = None) -> Optional[dict]:
        s = self.sessions.set_status(session_id, "voided")
        if s:
            self._correction_event(s, "session_voided", actor, reason)
        return s
