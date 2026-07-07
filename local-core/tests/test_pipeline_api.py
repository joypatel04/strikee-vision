"""Pipeline HTTP + WebSocket surface, using the app with fakes injected."""
from app.pipeline.capture import FakeFrameSource
from app.pipeline.perception import FakeDetector
from app.pipeline.runtime import LiveRuntime
from app.pipeline.state import StateEngine
from app.pipeline.types import AssetRuntime, Detection, SensorRuntime, SourceRuntime

ZONE = [[0, 0], [100, 0], [100, 100], [0, 100]]


def _make_runtime():
    sensor = SensorRuntime(id="s1", asset_id="a1", source_id="src1",
                           kind="occupancy", zone_polygons=[ZONE])
    asset = AssetRuntime(id="a1", name="Table 1", business_unit_id="bu1", sensors=[sensor])
    source = SourceRuntime(id="src1", name="Cam A", uri="fake", sensors=[sensor])
    detector = FakeDetector(lambda f: [Detection(bbox=(40, 10, 60, 90), confidence=0.9)])
    rt = LiveRuntime("v1", [asset], [source], {"src1": FakeFrameSource("src1")},
                     detector, StateEngine(enter_ticks=1))
    return rt


def test_pipeline_status_defaults_stopped(client):
    r = client.get("/api/venues/v1/pipeline/status")
    assert r.status_code == 200
    body = r.json()
    assert body["running"] is False
    assert body["assets"] == 0


def test_ws_sends_current_snapshot_on_connect(client):
    # register a runtime with known state (no loop) so connect returns a snapshot
    rt = _make_runtime()
    rt.tick()  # -> Table 1 Occupied
    client.app.state.runtime.set_runtime("v1", rt)

    with client.websocket_connect("/ws/venues/v1") as ws:
        msg = ws.receive_json()
    assert msg["type"] == "state"
    assert msg["venue_id"] == "v1"
    assert msg["assets"][0]["name"] == "Table 1"
    assert msg["assets"][0]["label"] == "Occupied"


def test_ws_connect_counts_as_viewer(client):
    rt = _make_runtime()
    client.app.state.runtime.set_runtime("v1", rt)
    with client.websocket_connect("/ws/venues/v1") as ws:
        ws.receive_json()  # drain snapshot
        assert client.get("/api/venues/v1/pipeline/status").json()["viewers"] == 1
