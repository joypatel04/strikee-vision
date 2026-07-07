from app.pipeline.state import StateEngine
from app.pipeline.types import AssetRuntime, SensorRuntime, RawObservation


def asset(sensors):
    return AssetRuntime(id="a1", name="Table 1", business_unit_id="bu1", sensors=sensors)


def occ(sid, source, role="primary", conf=0.35):
    return SensorRuntime(id=sid, asset_id="a1", source_id=source,
                         kind="occupancy", role=role, conf_threshold=conf)


def drive(engine, a, raw, source_ok, n):
    snap = None
    for _ in range(n):
        snap, _ = engine.update(a, raw, source_ok)
    return snap


def test_presence_smoothing_enter_then_exit():
    eng = StateEngine(enter_ticks=2, exit_ticks=3)
    a = asset([occ("s1", "src1")])
    # two present reads -> Occupied
    snap = drive(eng, a, {"s1": RawObservation(True, 0.9)}, {"src1": True}, 2)
    assert snap.presence == "present"
    assert snap.label == "Occupied"
    # three empty reads -> Available
    snap = drive(eng, a, {"s1": RawObservation(False, 0.0)}, {"src1": True}, 3)
    assert snap.presence == "absent"
    assert snap.label == "Available"


def test_single_stray_read_does_not_open():
    eng = StateEngine(enter_ticks=2, exit_ticks=3)
    a = asset([occ("s1", "src1")])
    snap, changed = eng.update(a, {"s1": RawObservation(True, 0.9)}, {"src1": True})
    assert snap.presence != "present"     # needs 2 consecutive
    assert snap.label == "Unknown"


def test_supporting_overrides_empty_primary_when_confident():
    eng = StateEngine(enter_ticks=2, support_high_conf=0.6)
    a = asset([occ("s1", "src1", "primary"), occ("s2", "src2", "supporting")])
    raw = {"s1": RawObservation(False, 0.1), "s2": RawObservation(True, 0.9)}
    snap = drive(eng, a, raw, {"src1": True, "src2": True}, 2)
    assert snap.presence == "present"       # occlusion override
    assert snap.label == "Occupied"


def test_low_confidence_supporting_does_not_override():
    eng = StateEngine(enter_ticks=2, exit_ticks=3, support_high_conf=0.6)
    a = asset([occ("s1", "src1", "primary"), occ("s2", "src2", "supporting")])
    raw = {"s1": RawObservation(False, 0.1), "s2": RawObservation(True, 0.5)}  # 0.5 < 0.6
    snap = drive(eng, a, raw, {"src1": True, "src2": True}, 3)
    assert snap.presence == "absent"


def test_offline_source_yields_unknown():
    eng = StateEngine()
    a = asset([occ("s1", "src1")])
    snap, _ = eng.update(a, {"s1": RawObservation(True, 0.9)}, {"src1": False})
    assert snap.health == "offline"
    assert snap.presence == "unknown"
    assert snap.label == "Unknown"


def test_health_degraded_when_one_of_two_sources_down():
    eng = StateEngine(enter_ticks=1)
    a = asset([occ("s1", "src1", "primary"), occ("s2", "src2", "supporting")])
    raw = {"s1": RawObservation(True, 0.9), "s2": RawObservation(False, 0.0)}
    snap, _ = eng.update(a, raw, {"src1": True, "src2": False})
    assert snap.health == "degraded"
    # health takes display priority over presence
    assert snap.label == "Degraded"


def test_health_priority_over_presence():
    """A present asset on a degraded feed shows Degraded, not Occupied."""
    eng = StateEngine(enter_ticks=1)
    a = asset([occ("s1", "src1", "primary"), occ("s2", "src2", "supporting")])
    raw = {"s1": RawObservation(True, 0.95), "s2": RawObservation(False, 0.0)}
    snap, _ = eng.update(a, raw, {"src1": True, "src2": False})
    assert snap.label == "Degraded"


def test_grace_absorbs_single_empty_blip():
    eng = StateEngine(enter_ticks=2, exit_ticks=3)
    a = asset([occ("s1", "src1")])
    drive(eng, a, {"s1": RawObservation(True, 0.9)}, {"src1": True}, 2)   # Occupied
    # one empty blip, then present again -> stays present (exit needs 3)
    eng.update(a, {"s1": RawObservation(False, 0.0)}, {"src1": True})
    snap, _ = eng.update(a, {"s1": RawObservation(True, 0.9)}, {"src1": True})
    assert snap.presence == "present"
