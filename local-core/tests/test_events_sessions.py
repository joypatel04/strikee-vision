"""M3: event append-only store, sink-driven sessions, and review service."""
from app.db import Database
from app.store import EventStore, SessionStore
from app.review import ReviewService
from app.pipeline.sink import ChangeEvent, DbStateSink
from app.pipeline.types import AssetSnapshot


def snap(label, presence, asset_id="a1", effective="2026-07-07T10:00:00+00:00",
         activity="unknown", health="ok", conf=0.9):
    return AssetSnapshot(asset_id=asset_id, name="Table 1", business_unit_id="bu1",
                         presence=presence, activity=activity, health=health,
                         label=label, confidence=conf, effective_at=effective)


def test_event_store_append_and_list():
    db = Database(":memory:")
    es = EventStore(db)
    e = es.append({"venue_id": "v1", "asset_id": "a1", "type": "state_change",
                   "ts": "2026-07-07T10:00:00+00:00", "label": "Occupied"})
    assert e["id"] and e["type"] == "state_change"
    rows = es.list("v1")
    assert len(rows) == 1 and rows[0]["label"] == "Occupied"
    db.close()


def test_sink_opens_and_closes_session():
    db = Database(":memory:")
    sink = DbStateSink(EventStore(db), SessionStore(db))
    # asset becomes present -> session opens
    sink.handle("v1", [ChangeEvent("Unknown",
                 snap("Occupied", "present", effective="2026-07-07T10:00:00+00:00"))])
    sessions = SessionStore(db).list("v1")
    assert len(sessions) == 1
    assert sessions[0]["end_ts"] is None
    assert sessions[0]["status"] == "detected"

    # asset becomes absent -> session closes with duration
    sink.handle("v1", [ChangeEvent("Occupied",
                 snap("Available", "absent", effective="2026-07-07T10:05:00+00:00"))])
    s = SessionStore(db).list("v1")[0]
    assert s["end_ts"] == "2026-07-07T10:05:00+00:00"
    assert s["duration_sec"] == 300

    # events recorded: 2 state_change + session_start + session_end
    types = [e["type"] for e in EventStore(db).list("v1")]
    assert types.count("state_change") == 2
    assert "session_start" in types and "session_end" in types
    db.close()


def test_sink_does_not_double_open():
    db = Database(":memory:")
    sink = DbStateSink(EventStore(db), SessionStore(db))
    sink.handle("v1", [ChangeEvent("Unknown", snap("Occupied", "present"))])
    # a second present change (e.g. label churn) must not open a 2nd session
    sink.handle("v1", [ChangeEvent("Occupied", snap("Active (In Use)", "present"))])
    assert len(SessionStore(db).list("v1")) == 1
    db.close()


def test_unknown_does_not_close_session():
    """Health going Unknown means lost visibility, not that the asset left."""
    db = Database(":memory:")
    sink = DbStateSink(EventStore(db), SessionStore(db))
    sink.handle("v1", [ChangeEvent("Unknown", snap("Occupied", "present"))])
    sink.handle("v1", [ChangeEvent("Occupied",
                 snap("Unknown", "unknown", health="offline"))])
    s = SessionStore(db).list("v1")[0]
    assert s["end_ts"] is None      # still open
    db.close()


def test_review_confirm_correct_void_preserve_history():
    db = Database(":memory:")
    es, ss = EventStore(db), SessionStore(db)
    session = ss.open("v1", "a1", "bu1", start_ts="2026-07-07T10:00:00+00:00")
    ss.close(session["id"], end_ts="2026-07-07T10:05:00+00:00")
    svc = ReviewService(ss, es)

    # confirm
    assert svc.confirm(session["id"], actor="mgr")["status"] == "confirmed"

    # correct end time -> original preserved, status corrected, duration recomputed
    corrected = svc.correct(session["id"], end_ts="2026-07-07T10:03:00+00:00",
                            actor="mgr", reason="left earlier")
    assert corrected["status"] == "corrected"
    assert corrected["orig_end_ts"] == "2026-07-07T10:05:00+00:00"   # preserved
    assert corrected["end_ts"] == "2026-07-07T10:03:00+00:00"
    assert corrected["duration_sec"] == 180

    # void
    assert svc.void(session["id"], actor="mgr")["status"] == "voided"

    # every review action left an immutable correction event
    types = [e["type"] for e in es.list("v1")]
    assert "session_confirmed" in types
    assert "session_corrected" in types
    assert "session_voided" in types
    db.close()


def test_review_missing_session_returns_none():
    db = Database(":memory:")
    svc = ReviewService(SessionStore(db), EventStore(db))
    assert svc.confirm("nope") is None
    db.close()
