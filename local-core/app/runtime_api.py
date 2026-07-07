"""HTTP surface for runtime facts: events, sessions, and session review."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .api import get_db
from .db import Database
from .review import ReviewService
from .store import EventStore, SessionStore


class CorrectBody(BaseModel):
    start_ts: Optional[str] = None
    end_ts: Optional[str] = None
    actor: Optional[str] = None
    reason: Optional[str] = None


class ActorBody(BaseModel):
    actor: Optional[str] = None
    reason: Optional[str] = None


def build_runtime_router() -> APIRouter:
    router = APIRouter(tags=["runtime"])

    @router.get("/api/venues/{venue_id}/events")
    def list_events(venue_id: str, asset_id: Optional[str] = None,
                    limit: int = 100, db: Database = Depends(get_db)):
        return EventStore(db).list(venue_id, asset_id=asset_id, limit=limit)

    @router.get("/api/venues/{venue_id}/sessions")
    def list_sessions(venue_id: str, asset_id: Optional[str] = None,
                      business_unit_id: Optional[str] = None, limit: int = 100,
                      db: Database = Depends(get_db)):
        return SessionStore(db).list(venue_id, asset_id=asset_id,
                                     business_unit_id=business_unit_id, limit=limit)

    @router.get("/api/sessions/{session_id}")
    def get_session(session_id: str, db: Database = Depends(get_db)):
        s = SessionStore(db).get(session_id)
        if s is None:
            raise HTTPException(404, "session not found")
        return s

    @router.post("/api/sessions/{session_id}/confirm")
    def confirm(session_id: str, body: ActorBody = ActorBody(),
                db: Database = Depends(get_db)):
        svc = ReviewService(SessionStore(db), EventStore(db))
        s = svc.confirm(session_id, actor=body.actor)
        if s is None:
            raise HTTPException(404, "session not found")
        return s

    @router.post("/api/sessions/{session_id}/correct")
    def correct(session_id: str, body: CorrectBody,
                db: Database = Depends(get_db)):
        svc = ReviewService(SessionStore(db), EventStore(db))
        s = svc.correct(session_id, start_ts=body.start_ts, end_ts=body.end_ts,
                        actor=body.actor, reason=body.reason)
        if s is None:
            raise HTTPException(404, "session not found")
        return s

    @router.post("/api/sessions/{session_id}/void")
    def void(session_id: str, body: ActorBody = ActorBody(),
             db: Database = Depends(get_db)):
        svc = ReviewService(SessionStore(db), EventStore(db))
        s = svc.void(session_id, actor=body.actor, reason=body.reason)
        if s is None:
            raise HTTPException(404, "session not found")
        return s

    return router
