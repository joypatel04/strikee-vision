"""HTTP surface for runtime facts: events, sessions, and session review."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .analytics import AnalyticsStore
from .api import get_db
from .db import Database
from .notify import RULE_TEMPLATES
from .review import ReviewService
from .store import (
    EventStore, MetricStore, NotificationStore, SessionStore,
)


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

    # --- metric samples + analytics (M4) ----------------------------------

    @router.get("/api/venues/{venue_id}/metrics")
    def list_metrics(venue_id: str, asset_id: Optional[str] = None,
                     metric: Optional[str] = None, limit: int = 500,
                     db: Database = Depends(get_db)):
        return MetricStore(db).list(venue_id, asset_id=asset_id, metric=metric, limit=limit)

    @router.get("/api/venues/{venue_id}/analytics/summary")
    def analytics_summary(venue_id: str, db: Database = Depends(get_db)):
        a = AnalyticsStore(db)
        return {
            "overview": a.venue_overview(venue_id),
            "by_business_unit": a.summary_by_business_unit(venue_id),
            "event_counts": a.event_counts(venue_id),
        }

    @router.get("/api/venues/{venue_id}/analytics/assets")
    def analytics_assets(venue_id: str, db: Database = Depends(get_db)):
        return AnalyticsStore(db).asset_utilization(venue_id)

    @router.get("/api/venues/{venue_id}/analytics/occupancy")
    def analytics_occupancy(venue_id: str, asset_id: str, metric: str = "present",
                            db: Database = Depends(get_db)):
        return AnalyticsStore(db).occupancy_series(venue_id, asset_id, metric=metric)

    # --- rule templates + notifications (M5) ------------------------------

    @router.get("/api/rule-templates")
    def rule_templates():
        return RULE_TEMPLATES

    @router.get("/api/venues/{venue_id}/notifications")
    def list_notifications(venue_id: str, status: Optional[str] = None,
                           limit: int = 100, db: Database = Depends(get_db)):
        return NotificationStore(db).list(venue_id, status=status, limit=limit)

    @router.post("/api/notifications/{notif_id}/ack")
    def ack_notification(notif_id: str, body: ActorBody = ActorBody(),
                         db: Database = Depends(get_db)):
        n = NotificationStore(db).acknowledge(notif_id, actor=body.actor)
        if n is None:
            raise HTTPException(404, "notification not found")
        return n

    @router.post("/api/notifications/{notif_id}/resolve")
    def resolve_notification(notif_id: str, body: ActorBody = ActorBody(),
                             db: Database = Depends(get_db)):
        n = NotificationStore(db).resolve(notif_id, actor=body.actor, reason=body.reason)
        if n is None:
            raise HTTPException(404, "notification not found")
        return n

    @router.get("/api/venues/{venue_id}/games")
    def games_report(venue_id: str, date: Optional[str] = None,
                     db: Database = Depends(get_db)):
        """Daily games log for staff reconciliation: each game with its start
        time, duration, table, status, and evidence snapshot. `date` filters to
        YYYY-MM-DD (start_ts prefix); omit for the most recent games."""
        rows = SessionStore(db).list(venue_id, limit=500)
        if date:
            rows = [r for r in rows if (r["start_ts"] or "").startswith(date)]
        # attach asset names
        names = {}
        with db.cursor() as cur:
            cur.execute("SELECT id, name FROM assets WHERE venue_id = ?", (venue_id,))
            names = {r["id"]: r["name"] for r in cur.fetchall()}
        games = [{
            "session_id": r["id"],
            "table": names.get(r["asset_id"], r["asset_id"]),
            "business_unit_id": r["business_unit_id"],
            "start_ts": r["start_ts"],
            "end_ts": r["end_ts"],
            "duration_sec": r["duration_sec"],
            "status": r["status"],
            "snapshot": f"/snapshots/{r['start_snapshot']}" if r.get("start_snapshot") else None,
        } for r in rows]
        return {"date": date, "count": len(games), "games": games}

    @router.get("/api/venues/{venue_id}/review-queue")
    def review_queue(venue_id: str, db: Database = Depends(get_db)):
        """Things needing a human: unreviewed sessions + open notifications."""
        sessions = [s for s in SessionStore(db).list(venue_id, limit=200)
                    if s["status"] == "detected"]
        notifs = [n for n in NotificationStore(db).list(venue_id, limit=200)
                  if n["status"] in ("pending", "delivered", "acknowledged")]
        return {"sessions": sessions, "notifications": notifs,
                "total": len(sessions) + len(notifs)}

    return router
