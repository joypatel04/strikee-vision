"""M4: metric sampling + analytics aggregates."""
from app.db import Database
from app.store import EventStore, MetricStore, SessionStore
from app.analytics import AnalyticsStore
from app.pipeline.capture import FakeFrameSource
from app.pipeline.perception import FakeDetector
from app.pipeline.runtime import LiveRuntime
from app.pipeline.state import StateEngine
from app.pipeline.types import AssetRuntime, Detection, SensorRuntime, SourceRuntime

ZONE = [[0, 0], [100, 0], [100, 100], [0, 100]]
TWO_INSIDE = [Detection(bbox=(40, 10, 60, 90), confidence=0.9),
              Detection(bbox=(20, 10, 35, 88), confidence=0.8)]


def _clock_seq():
    times = iter([
        "2026-07-07T10:00:00+00:00", "2026-07-07T10:00:07+00:00",
        "2026-07-07T10:00:14+00:00", "2026-07-07T10:00:21+00:00",
    ])
    return lambda: next(times)


def test_metric_store_record_and_query():
    db = Database(":memory:")
    ms = MetricStore(db)
    ms.record("v1", "2026-07-07T10:00:00+00:00", [
        {"asset_id": "a1", "business_unit_id": "bu1", "metric": "present", "value": 1},
        {"asset_id": "a1", "business_unit_id": "bu1", "metric": "persons", "value": 2},
    ])
    rows = ms.list("v1", asset_id="a1", metric="persons")
    assert len(rows) == 1 and rows[0]["value"] == 2.0
    db.close()


def test_runtime_emits_metric_samples_per_tick():
    db = Database(":memory:")
    sampler = MetricStore(db)
    sensor = SensorRuntime(id="s1", asset_id="a1", source_id="src1",
                           kind="occupancy", zone_polygons=[ZONE])
    asset = AssetRuntime(id="a1", name="Table 1", business_unit_id="bu1", sensors=[sensor])
    source = SourceRuntime(id="src1", name="Cam A", uri="fake", sensors=[sensor])
    rt = LiveRuntime("v1", [asset], [source], {"src1": FakeFrameSource("src1")},
                     FakeDetector(lambda f: TWO_INSIDE), StateEngine(enter_ticks=1),
                     sampler=sampler, clock=_clock_seq())
    rt.tick()
    # one tick -> 4 metrics for the asset
    persons = sampler.list("v1", asset_id="a1", metric="persons")
    assert persons[0]["value"] == 2.0            # counted both people in zone
    present = sampler.list("v1", asset_id="a1", metric="present")
    assert present[0]["value"] == 1.0
    assert {m["metric"] for m in sampler.list("v1")} == {
        "present", "persons", "confidence", "health_ok"}
    db.close()


def _seed_sessions(db):
    ss = SessionStore(db)
    # snooker: 2 sessions, 300s + 120s
    s1 = ss.open("v1", "a1", "snooker", "2026-07-07T10:00:00+00:00")
    ss.close(s1["id"], "2026-07-07T10:05:00+00:00")
    s2 = ss.open("v1", "a2", "snooker", "2026-07-07T11:00:00+00:00")
    ss.close(s2["id"], "2026-07-07T11:02:00+00:00")
    # gaming: 1 open session
    ss.open("v1", "a3", "gaming", "2026-07-07T12:00:00+00:00")


def test_summary_by_business_unit():
    db = Database(":memory:")
    _seed_sessions(db)
    rows = {r["business_unit_id"]: r for r in AnalyticsStore(db).summary_by_business_unit("v1")}
    assert rows["snooker"]["session_count"] == 2
    assert rows["snooker"]["total_duration_sec"] == 420      # 300 + 120
    assert rows["snooker"]["avg_duration_sec"] == 210.0
    assert rows["gaming"]["session_count"] == 1
    assert rows["gaming"]["open_sessions"] == 1
    db.close()


def test_asset_utilization_and_overview():
    db = Database(":memory:")
    _seed_sessions(db)
    a = AnalyticsStore(db)
    util = {r["asset_id"]: r for r in a.asset_utilization("v1")}
    assert util["a1"]["occupied_sec"] == 300
    ov = a.venue_overview("v1")
    assert ov["active_sessions"] == 1 and ov["total_sessions"] == 3
    db.close()


def test_occupancy_series_hourly():
    db = Database(":memory:")
    ms = MetricStore(db)
    # two samples in the same hour: present 1 and 0 -> avg 0.5, peak 1
    ms.record("v1", "2026-07-07T10:00:00+00:00",
              [{"asset_id": "a1", "metric": "present", "value": 1}])
    ms.record("v1", "2026-07-07T10:30:00+00:00",
              [{"asset_id": "a1", "metric": "present", "value": 0}])
    series = AnalyticsStore(db).occupancy_series("v1", "a1", "present")
    assert len(series) == 1
    assert series[0]["hour"] == "2026-07-07T10"
    assert series[0]["avg_value"] == 0.5
    assert series[0]["peak_value"] == 1.0
    db.close()


def test_analytics_endpoints(client):
    db = client.app.state.db
    _seed_sessions(db)
    summary = client.get("/api/venues/v1/analytics/summary").json()
    assert summary["overview"]["total_sessions"] == 3
    assert any(b["business_unit_id"] == "snooker" for b in summary["by_business_unit"])
    assets = client.get("/api/venues/v1/analytics/assets").json()
    assert any(a["asset_id"] == "a1" for a in assets)
