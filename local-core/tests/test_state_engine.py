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


# ------------------------------------------------- seconds-based grace windows


def _asset_with(sensor_kind="snooker_game", asset_id="a1"):
    from app.pipeline.types import AssetRuntime, SensorRuntime
    return AssetRuntime(
        id=asset_id, name=asset_id, business_unit_id="bu",
        sensors=[SensorRuntime(id=asset_id + "s", asset_id=asset_id,
                               source_id="src", kind=sensor_kind)])


def _absent_reads(engine, asset, n):
    """Feed n consecutive 'nobody there' reads."""
    from app.pipeline.types import RawObservation
    last = None
    for _ in range(n):
        last, _ = engine.update(asset, {asset.sensors[0].id: RawObservation(False, 0.0)},
                                {"src": True})
    return last


def _present_reads(engine, asset, n):
    from app.pipeline.types import RawObservation
    last = None
    for _ in range(n):
        last, _ = engine.update(asset, {asset.sensors[0].id: RawObservation(True, 0.9)},
                                {"src": True})
    return last


def test_seconds_window_converts_using_each_assets_own_rate():
    """120s of grace must mean 120s on a table grabbed every 13s AND on a
    station grabbed every 5s - the bug a shared tick count creates."""
    from app.pipeline.state import StateEngine

    table = _asset_with("snooker_game", "table")
    station = _asset_with("occupancy", "station")
    rates = {"table": 13.0, "station": 5.0}
    engine = StateEngine(exit_sec=120.0, enter_sec=0,
                         interval_for=lambda a: rates[a.id])

    # 120 / 13 -> 9 ticks; 120 / 5 -> 24 ticks
    assert engine._thresholds(table)[1] == 9
    assert engine._thresholds(station)[1] == 24


def test_seconds_window_actually_holds_the_session_open():
    from app.pipeline.state import StateEngine

    table = _asset_with("snooker_game", "table")
    engine = StateEngine(enter_ticks=1, exit_sec=120.0,
                         interval_for=lambda a: 13.0)

    _present_reads(engine, table, 2)
    assert engine.snapshot(table).presence == "present"

    # 8 absent reads = 104s: still inside the 120s window
    snap = _absent_reads(engine, table, 8)
    assert snap.presence == "present", "table freed early; sessions would fragment"

    snap = _absent_reads(engine, table, 1)          # 9th read = 117s -> threshold
    assert snap.presence == "absent"


def test_ticks_still_win_when_no_seconds_configured():
    """Default behaviour is unchanged for anyone not setting the new knobs."""
    from app.pipeline.state import StateEngine
    engine = StateEngine(enter_ticks=2, exit_ticks=3, activity_still_ticks=4,
                         interval_for=lambda a: 13.0)
    assert engine._thresholds(_asset_with()) == (2, 3, 4)


def test_missing_interval_falls_back_to_ticks():
    """An asset whose source has no configured rate must still derive state."""
    from app.pipeline.state import StateEngine
    engine = StateEngine(enter_ticks=2, exit_ticks=3, exit_sec=120.0,
                         interval_for=lambda a: None)
    assert engine._thresholds(_asset_with())[1] == 3


def test_broken_interval_resolver_never_breaks_state():
    from app.pipeline.state import StateEngine

    def boom(asset):
        raise RuntimeError("bad config")

    engine = StateEngine(enter_ticks=2, exit_ticks=3, exit_sec=120.0,
                         interval_for=boom)
    assert engine._thresholds(_asset_with())[1] == 3


def test_window_never_rounds_below_one_tick():
    """A window shorter than the sampling interval must still take one read,
    not zero - which would flip presence on the very first observation."""
    from app.pipeline.state import StateEngine
    engine = StateEngine(exit_sec=2.0, interval_for=lambda a: 13.0)
    assert engine._thresholds(_asset_with())[1] == 1
