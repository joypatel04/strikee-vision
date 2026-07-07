"""D-T4: motion-based activity facet (Active vs Occupied–Idle)."""
from app.pipeline.capture import FakeFrameSource
from app.pipeline.perception import FakeDetector
from app.pipeline.runtime import LiveRuntime, _motion
from app.pipeline.state import StateEngine
from app.pipeline.types import (
    AssetRuntime, Detection, RawObservation, SensorRuntime, SourceRuntime,
)

ZONE = [[0, 0], [200, 0], [200, 200], [0, 200]]


def det(x):
    """A person box centred near x (feet inside the zone)."""
    return [Detection(bbox=(x, 100, x + 20, 190), confidence=0.9)]


def test_motion_helper():
    assert _motion(None, [(10, 10)], 8.0) is False        # first sighting
    assert _motion([(10, 10)], [(10, 10)], 8.0) is False  # no move
    assert _motion([(10, 10)], [(30, 10)], 8.0) is True   # moved 20px
    assert _motion([(10, 10)], [], 8.0) is False          # left
    assert _motion([(10, 10)], [(10, 10), (50, 50)], 8.0) is True  # count changed


def _runtime(script, engine):
    sensor = SensorRuntime(id="s1", asset_id="a1", source_id="src1",
                           kind="occupancy", zone_polygons=[ZONE])
    asset = AssetRuntime(id="a1", name="T1", business_unit_id="bu1", sensors=[sensor])
    source = SourceRuntime(id="src1", name="Cam A", uri="fake", sensors=[sensor])
    return LiveRuntime("v1", [asset], [source], {"src1": FakeFrameSource("src1")},
                       FakeDetector(script), engine, motion_threshold=8.0)


def test_moving_person_reads_active():
    # person present and moving across ticks
    script = [det(20), det(60), det(100), det(140)]
    rt = _runtime(script, StateEngine(enter_ticks=1, activity_still_ticks=3))
    labels = []
    for _ in range(4):
        rt.tick()
        labels.append(rt.current_snapshots()[0].label)
    assert "Active (In Use)" in labels


def test_still_person_becomes_idle():
    # present but stationary -> Occupied, then Occupied – Idle after still ticks
    script = [det(100)] * 6
    rt = _runtime(script, StateEngine(enter_ticks=1, activity_still_ticks=3))
    labels = []
    for _ in range(6):
        rt.tick()
        labels.append(rt.current_snapshots()[0].label)
    assert labels[0] == "Occupied"               # just arrived, no motion yet
    assert labels[-1] == "Occupied – Idle"       # idle after stillness


def test_engine_activity_from_raw_active():
    eng = StateEngine(enter_ticks=1, activity_still_ticks=2)
    sensor = SensorRuntime(id="s1", asset_id="a1", source_id="src1", kind="occupancy")
    asset = AssetRuntime(id="a1", name="T1", business_unit_id=None, sensors=[sensor])
    # present + moving
    snap, _ = eng.update(asset, {"s1": RawObservation(True, 0.9, active=True)}, {"src1": True})
    assert snap.activity == "active" and snap.label == "Active (In Use)"
    # goes still -> after 2 still ticks becomes inactive
    eng.update(asset, {"s1": RawObservation(True, 0.9, active=False)}, {"src1": True})
    snap, _ = eng.update(asset, {"s1": RawObservation(True, 0.9, active=False)}, {"src1": True})
    assert snap.activity == "inactive" and snap.label == "Occupied – Idle"


def test_activity_unknown_when_absent():
    eng = StateEngine(enter_ticks=1, exit_ticks=1)
    sensor = SensorRuntime(id="s1", asset_id="a1", source_id="src1", kind="occupancy")
    asset = AssetRuntime(id="a1", name="T1", business_unit_id=None, sensors=[sensor])
    snap, _ = eng.update(asset, {"s1": RawObservation(False, 0.0)}, {"src1": True})
    assert snap.activity == "unknown"
