"""One station, several cameras, each contributing what its angle is good for.

The gaming lounge has four cameras covering six stations, and no single angle is
good at everything: the camera that frames a TV squarely is rarely the one that
sees the sofa without occlusion. The entity model already allows an asset to
carry several sensors on different cameras; these pin the behaviour that makes
that worth doing, because it is invisible from any single sensor's point of view.
"""
from app.pipeline.state import StateEngine
from app.pipeline.types import AssetRuntime, RawObservation, SensorRuntime

CAM_A, CAM_B, CAM_TV = "camA", "camB", "camTV"


def _station(sensors):
    return AssetRuntime(id="st1", name="Orange", business_unit_id="gaming",
                        sensors=sensors)


def _occ(sid, source, role="primary"):
    return SensorRuntime(id=sid, asset_id="st1", source_id=source,
                         kind="occupancy", role=role)


def _screen(sid, source):
    return SensorRuntime(id=sid, asset_id="st1", source_id=source, kind="screen")


def _drive(engine, asset, raw, ok, ticks=3):
    snap = None
    for _ in range(ticks):
        snap, _ = engine.update(asset, raw, ok)
    return snap


def _obs(present, conf=0.9):
    return RawObservation(present, conf if present else 0.0)


ALL_OK = {CAM_A: True, CAM_B: True, CAM_TV: True}


def test_a_second_angle_covers_what_the_first_one_misses():
    """The whole point: one camera occluded, the station still reads occupied."""
    asset = _station([_occ("a", CAM_A), _occ("b", CAM_B)])
    engine = StateEngine(enter_ticks=2, exit_ticks=3)

    snap = _drive(engine, asset, {"a": _obs(False), "b": _obs(True)}, ALL_OK)
    assert snap.presence == "present", "a blind angle vetoed a camera that saw them"


def test_a_supporting_angle_needs_confidence_to_override_an_empty_primary():
    """Supporting cameras are the awkward views, so they only speak up when sure -
    otherwise the worst angle in the room sets the venue's occupancy."""
    asset = _station([_occ("a", CAM_A), _occ("b", CAM_B, role="supporting")])
    engine = StateEngine(enter_ticks=2, exit_ticks=3, support_high_conf=0.6)

    unsure = _drive(engine, asset, {"a": _obs(False), "b": _obs(True, 0.4)}, ALL_OK)
    assert unsure.presence != "present"

    sure = _drive(engine, asset, {"a": _obs(False), "b": _obs(True, 0.85)}, ALL_OK)
    assert sure.presence == "present"


def test_the_tv_can_be_watched_by_a_different_camera_than_the_people():
    """The angle that frames a TV squarely is rarely the one that sees the sofa."""
    asset = _station([_occ("a", CAM_A), _screen("tv", CAM_TV)])
    engine = StateEngine(enter_ticks=2, exit_ticks=3)

    playing = _drive(engine, asset, {"a": _obs(True), "tv": _obs(True)}, ALL_OK)
    assert playing.presence == "present"

    # Same people, TV off on the OTHER camera -> not a paying session. A fresh
    # engine: state is keyed by asset id, so reusing the one above would carry
    # the occupied state (and its screen hold) into this case.
    idle_engine = StateEngine(enter_ticks=2, exit_ticks=3, screen_hold_ticks=2)
    idle = _drive(idle_engine, _station([_occ("a", CAM_A), _screen("tv", CAM_TV)]),
                  {"a": _obs(True), "tv": _obs(False)}, ALL_OK, ticks=6)
    assert idle.presence != "present"


def test_either_screen_angle_is_enough_to_call_the_tv_on():
    """Two cameras see the same TV; one is washed out by a reflection at this
    hour. The station must not close because the worse angle cannot tell."""
    asset = _station([_occ("a", CAM_A), _screen("tv1", CAM_A), _screen("tv2", CAM_TV)])
    engine = StateEngine(enter_ticks=2, exit_ticks=3)

    snap = _drive(engine, asset,
                  {"a": _obs(True), "tv1": _obs(False), "tv2": _obs(True)}, ALL_OK)
    assert snap.presence == "present"


def test_an_offline_camera_is_ignored_rather_than_counted_as_empty():
    """A camera that dropped its stream knows nothing; treating that as 'nobody
    there' would close stations every time the DVR hiccups."""
    asset = _station([_occ("a", CAM_A), _occ("b", CAM_B)])
    engine = StateEngine(enter_ticks=2, exit_ticks=3)

    snap = _drive(engine, asset, {"a": _obs(False), "b": _obs(True)},
                  {CAM_A: False, CAM_B: True, CAM_TV: True})
    assert snap.presence == "present"
    assert snap.health != "offline", "one dead camera of two marked the station offline"


def test_every_camera_down_is_unknown_not_free():
    asset = _station([_occ("a", CAM_A), _occ("b", CAM_B)])
    engine = StateEngine(enter_ticks=2, exit_ticks=3)
    snap = _drive(engine, asset, {"a": _obs(False), "b": _obs(False)},
                  {CAM_A: False, CAM_B: False, CAM_TV: False})
    assert snap.presence == "unknown", "a blind system reported the station free"
