"""State sink: consumes state changes from the LiveRuntime and turns them into
append-only Events and materialized Sessions.

Kept behind a Protocol so the runtime can be tested with a FakeSink (capturing
calls) instead of a database.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .types import (
    AssetSnapshot, PRESENCE_ABSENT, PRESENCE_PRESENT,
)


@dataclass
class ChangeEvent:
    prev_label: str
    snapshot: AssetSnapshot


class StateSink(Protocol):
    def handle(self, venue_id: str, changes: list[ChangeEvent]) -> None:
        ...


class FakeSink:
    """Records handled changes for tests."""

    def __init__(self):
        self.calls: list[tuple[str, list[ChangeEvent]]] = []

    def handle(self, venue_id: str, changes: list[ChangeEvent]) -> None:
        self.calls.append((venue_id, list(changes)))


class DbStateSink:
    """Persists each state change as an event and drives session open/close.

    Session rule (G05): open when presence becomes present (no open session),
    close when presence becomes absent (open session exists). The grace window
    lives in the presence smoothing upstream, so this layer stays simple.
    Unknown/degraded does not close an open session (we lost visibility, we did
    not observe the asset leave).
    """

    def __init__(self, event_store, session_store, notifier=None,
                 snapshot_store=None, frame_provider=None):
        self.events = event_store
        self.sessions = session_store
        self.notifier = notifier
        self.snapshot_store = snapshot_store       # SnapshotStore (optional)
        self.frame_provider = frame_provider       # callable(asset_id) -> frame

    def handle(self, venue_id: str, changes: list[ChangeEvent]) -> None:
        for ch in changes:
            s = ch.snapshot
            evt = self.events.append({
                "venue_id": venue_id,
                "asset_id": s.asset_id,
                "business_unit_id": s.business_unit_id,
                "type": "state_change",
                "ts": s.effective_at,
                "presence": s.presence,
                "activity": s.activity,
                "health": s.health,
                "label": s.label,
                "prev_label": ch.prev_label,
                "confidence": s.confidence,
                "origin": "system",
            })

            if self.notifier is not None:
                self.notifier.on_event(venue_id, evt)

            if s.presence == PRESENCE_PRESENT:
                if self.sessions.get_open_for_asset(s.asset_id) is None:
                    snapshot = self._capture_snapshot(venue_id, s)
                    session = self.sessions.open(
                        venue_id, s.asset_id, s.business_unit_id,
                        start_ts=s.effective_at, confidence=s.confidence,
                        start_event_id=evt["id"], start_snapshot=snapshot,
                    )
                    self.events.append({
                        "venue_id": venue_id, "asset_id": s.asset_id,
                        "business_unit_id": s.business_unit_id,
                        "type": "session_start", "ts": s.effective_at,
                        "origin": "system", "correlation_id": session["id"],
                    })
                    continue  # handled this change
            if s.presence == PRESENCE_ABSENT:
                open_session = self.sessions.get_open_for_asset(s.asset_id)
                if open_session is not None:
                    self.sessions.close(open_session["id"], end_ts=s.effective_at,
                                        end_event_id=evt["id"])
                    self.events.append({
                        "venue_id": venue_id, "asset_id": s.asset_id,
                        "business_unit_id": s.business_unit_id,
                        "type": "session_end", "ts": s.effective_at,
                        "origin": "system", "correlation_id": open_session["id"],
                    })

    def record_game_start(self, venue_id: str, s: AssetSnapshot) -> None:
        """A new rack was detected -> log a game_start event with a snapshot.
        This is the counted 'a new game began' marker for staff reconciliation."""
        snapshot = self._capture_snapshot(venue_id, s)
        self.events.append({
            "venue_id": venue_id, "asset_id": s.asset_id,
            "business_unit_id": s.business_unit_id,
            "type": "game_start", "ts": s.effective_at,
            "origin": "system", "snapshot": snapshot,
        })

    def _capture_snapshot(self, venue_id: str, s: AssetSnapshot):
        """Save a labelled evidence image at game start (best-effort)."""
        if self.snapshot_store is None or self.frame_provider is None:
            return None
        frame = self.frame_provider(s.asset_id)
        if frame is None:
            return None
        try:
            return self.snapshot_store.save(venue_id, s.asset_id, s.name, frame,
                                            s.effective_at)
        except Exception:
            return None
