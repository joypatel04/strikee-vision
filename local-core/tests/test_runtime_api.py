"""M3 HTTP surface: events/sessions endpoints + review, and an end-to-end
runtime→sink→session flow driving the API."""
from app.db import Database
from app.store import EventStore, SessionStore
from app.pipeline.capture import FakeFrameSource
from app.pipeline.perception import FakeDetector
from app.pipeline.runtime import LiveRuntime
from app.pipeline.sink import DbStateSink
from app.pipeline.state import StateEngine
from app.pipeline.types import (
    AssetRuntime, Detection, SensorRuntime, SourceRuntime,
)

ZONE = [[0, 0], [100, 0], [100, 100], [0, 100]]
INSIDE = [Detection(bbox=(40, 10, 60, 90), confidence=0.9)]
OUTSIDE = []


def test_events_and_sessions_endpoints_empty(client):
    assert client.get("/api/venues/v1/events").json() == []
    assert client.get("/api/venues/v1/sessions").json() == []
    assert client.get("/api/sessions/nope").status_code == 404
    assert client.post("/api/sessions/nope/confirm").status_code == 404


def test_review_endpoints_via_http(client):
    db = client.app.state.db
    ss = SessionStore(db)
    s = ss.open("v1", "a1", "bu1", start_ts="2026-07-07T10:00:00+00:00")
    ss.close(s["id"], end_ts="2026-07-07T10:05:00+00:00")

    r = client.post(f"/api/sessions/{s['id']}/confirm", json={"actor": "mgr"})
    assert r.status_code == 200 and r.json()["status"] == "confirmed"

    r = client.post(f"/api/sessions/{s['id']}/correct",
                    json={"end_ts": "2026-07-07T10:04:00+00:00", "actor": "mgr"})
    assert r.json()["status"] == "corrected" and r.json()["duration_sec"] == 240

    r = client.post(f"/api/sessions/{s['id']}/void", json={"reason": "false"})
    assert r.json()["status"] == "voided"

    # events surfaced via API
    types = [e["type"] for e in client.get("/api/venues/v1/events").json()]
    assert "session_confirmed" in types and "session_voided" in types


def test_end_to_end_runtime_produces_session_via_db(client):
    """A live runtime with fakes + a DB sink produces a real session that the
    API then serves."""
    db = client.app.state.db
    sink = DbStateSink(EventStore(db), SessionStore(db))

    sensor = SensorRuntime(id="s1", asset_id="a1", source_id="src1",
                           kind="occupancy", zone_polygons=[ZONE])
    asset = AssetRuntime(id="a1", name="Table 1", business_unit_id="bu1", sensors=[sensor])
    source = SourceRuntime(id="src1", name="Cam A", uri="fake", sensors=[sensor])

    # present x2 (opens), then empty x3 (closes)
    script = [INSIDE, INSIDE, OUTSIDE, OUTSIDE, OUTSIDE]
    rt = LiveRuntime("v1", [asset], [source], {"src1": FakeFrameSource("src1")},
                     FakeDetector(script), StateEngine(enter_ticks=2, exit_ticks=3),
                     sink=sink)
    for _ in range(5):
        rt.tick()

    sessions = client.get("/api/venues/v1/sessions").json()
    assert len(sessions) == 1
    assert sessions[0]["asset_id"] == "a1"
    assert sessions[0]["business_unit_id"] == "bu1"
    assert sessions[0]["end_ts"] is not None        # opened AND closed
    # filter by business unit works
    assert len(client.get("/api/venues/v1/sessions?business_unit_id=bu1").json()) == 1
    assert len(client.get("/api/venues/v1/sessions?business_unit_id=other").json()) == 0
