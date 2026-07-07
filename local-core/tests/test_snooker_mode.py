"""Snooker game observation mode: balls-in-zone -> game in progress -> session."""
from app.db import Database
from app.store import EventStore, SessionStore
from app.pipeline.capture import FakeFrameSource
from app.pipeline.observe import observe_snooker_game, observe
from app.pipeline.perception import FakeDetector
from app.pipeline.runtime import LiveRuntime
from app.pipeline.sink import DbStateSink
from app.pipeline.state import StateEngine
from app.pipeline.types import (
    AssetRuntime, Detection, SensorRuntime, SourceRuntime,
)

ZONE = [[0, 0], [400, 0], [400, 400], [0, 400]]


def ball(x, y, label="red_ball", conf=0.6):
    return Detection(bbox=(x, y, x + 12, y + 12), confidence=conf, label=label)


def _snooker_sensor(min_balls=3):
    return SensorRuntime(id="s1", asset_id="a1", source_id="src1",
                         kind="snooker_game", conf_threshold=0.25,
                         zone_polygons=[ZONE])


def a_rack():
    # 10 red balls clustered on the table + a game_start
    dets = [ball(50 + i * 8, 100) for i in range(10)]
    dets.append(Detection(bbox=(60, 90, 120, 150), confidence=0.5, label="game_start"))
    return dets


def test_observe_snooker_counts_balls_in_zone():
    obs = observe_snooker_game(a_rack(), _snooker_sensor())
    assert obs["count"] == 10
    assert obs["present"] is True
    assert obs["game_start"] is True


def test_observe_snooker_empty_table_not_present():
    obs = observe_snooker_game([], _snooker_sensor())
    assert obs["present"] is False and obs["count"] == 0


def test_observe_snooker_below_min_balls_not_present():
    # only 2 balls, min is 3 -> table effectively clear (end of frame)
    obs = observe_snooker_game([ball(50, 100), ball(60, 100)], _snooker_sensor(min_balls=3))
    assert obs["present"] is False


def test_balls_outside_zone_ignored():
    outside = [ball(500, 500) for _ in range(10)]   # centres outside ZONE
    obs = observe_snooker_game(outside, _snooker_sensor())
    assert obs["count"] == 0 and obs["present"] is False


def test_observe_dispatch_by_kind():
    obs = observe("snooker_game", a_rack(), _snooker_sensor())
    assert obs["count"] == 10


def _moving_rack(offset):
    # a rack whose balls are shifted by `offset` px so consecutive frames show
    # motion (a shot in progress)
    dets = [ball(50 + i * 8 + offset, 100) for i in range(10)]
    return dets


def _scattered_balls():
    # leftover balls from a finished game — present on the table, but NOT a rack
    # (no game_start) and static (no motion)
    return [ball(50, 100), ball(200, 300), ball(350, 150), ball(120, 250)]


def test_idle_balls_are_available_not_in_use():
    """Leftover balls sitting with NO motion and NO rack must read Available
    (players left the balls between games)."""
    db = Database(":memory:")
    sink = DbStateSink(EventStore(db), SessionStore(db))
    sensor = _snooker_sensor()
    asset = AssetRuntime(id="a1", name="Table 1", business_unit_id="snooker",
                         sensors=[sensor])
    source = SourceRuntime(id="src1", name="Cam", uri="fake", sensors=[sensor])
    # static scattered balls every tick -> present but no motion, no rack
    rt = LiveRuntime("v1", [asset], [source], {"src1": FakeFrameSource("src1")},
                     detector=None, engine=StateEngine(enter_ticks=1, exit_ticks=1),
                     sink=sink, snooker_detector=FakeDetector(lambda f: _scattered_balls()))
    for _ in range(4):
        rt.tick()
    # balls are there, but nobody is playing -> Available
    assert rt.current_snapshots()[0].label == "Available"
    assert len(SessionStore(db).list("v1")) == 0    # no usage session opened
    db.close()


def test_play_motion_makes_table_in_use():
    """Motion on the table (a shot) -> the table reads in use."""
    db = Database(":memory:")
    sink = DbStateSink(EventStore(db), SessionStore(db))
    sensor = _snooker_sensor()
    asset = AssetRuntime(id="a1", name="Table 1", business_unit_id="snooker",
                         sensors=[sensor])
    source = SourceRuntime(id="src1", name="Cam", uri="fake", sensors=[sensor])
    # balls MOVE each tick -> motion -> play
    script = [_moving_rack(0), _moving_rack(30), _moving_rack(60), _moving_rack(90)]
    rt = LiveRuntime("v1", [asset], [source], {"src1": FakeFrameSource("src1")},
                     detector=None, engine=StateEngine(enter_ticks=1, exit_ticks=3),
                     sink=sink, snooker_detector=FakeDetector(script))
    for _ in range(4):
        rt.tick()
    assert rt.current_snapshots()[0].presence == "present"   # in use (play)
    db.close()


def test_confirmed_rack_emits_one_game_start():
    """A rack confirmed over consecutive ticks -> exactly one game_start event
    (the state machine suppresses the lingering-rack re-detections)."""
    db = Database(":memory:")
    sink = DbStateSink(EventStore(db), SessionStore(db))
    sensor = _snooker_sensor()
    asset = AssetRuntime(id="a1", name="Table 1", business_unit_id="snooker",
                         sensors=[sensor])
    source = SourceRuntime(id="src1", name="Cam", uri="fake", sensors=[sensor])
    # the rack lingers for many ticks (slow break) -> still ONE counted game
    script = [a_rack()] * 8
    rt = LiveRuntime("v1", [asset], [source], {"src1": FakeFrameSource("src1")},
                     detector=None, engine=StateEngine(enter_ticks=1),
                     sink=sink, snooker_detector=FakeDetector(script))
    for _ in range(8):
        rt.tick()
    game_starts = [e for e in EventStore(db).list("v1") if e["type"] == "game_start"]
    assert len(game_starts) == 1
    db.close()


def test_snooker_missing_frame_persists_via_fusion():
    """Two cameras on one table: the primary misses the balls (bad angle/light)
    but the supporting camera sees a confident rack -> the game stays detected.
    Robustness to a single-angle model miss, via primary/supporting fusion."""
    prim = SensorRuntime(id="p", asset_id="a1", source_id="srcP", kind="snooker_game",
                         role="primary", conf_threshold=0.25, zone_polygons=[ZONE])
    supp = SensorRuntime(id="s", asset_id="a1", source_id="srcS", kind="snooker_game",
                         role="supporting", conf_threshold=0.25, zone_polygons=[ZONE])
    asset = AssetRuntime(id="a1", name="Table 1", business_unit_id="snooker",
                         sensors=[prim, supp])
    srcP = SourceRuntime(id="srcP", name="End A", uri="fake", sensors=[prim])
    srcS = SourceRuntime(id="srcS", name="End B", uri="fake", sensors=[supp])

    # supporting sees a fresh rack (game_start) at high confidence
    rack_hi = [ball(50 + i * 8, 100, conf=0.8) for i in range(10)]
    rack_hi.append(Detection(bbox=(60, 90, 120, 150), confidence=0.8, label="game_start"))
    # detector diverges by frame token: primary's source empty, supporting's full
    detector = FakeDetector(lambda tok: rack_hi if tok == "S" else [])
    rt = LiveRuntime(
        "v1", [asset], [srcP, srcS],
        {"srcP": FakeFrameSource("srcP", token="P"),
         "srcS": FakeFrameSource("srcS", token="S")},
        detector=None, engine=StateEngine(enter_ticks=1, support_high_conf=0.6),
        snooker_detector=detector,
    )
    rt.tick()
    assert rt.current_snapshots()[0].presence == "present"   # fusion kept it alive
