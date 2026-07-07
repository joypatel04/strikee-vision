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


def test_snooker_runtime_game_session_end_to_end():
    """A game (balls on table) opens a session; clearing the table closes it."""
    db = Database(":memory:")
    sink = DbStateSink(EventStore(db), SessionStore(db))
    sensor = _snooker_sensor()
    asset = AssetRuntime(id="a1", name="Table 1", business_unit_id="snooker",
                         sensors=[sensor])
    source = SourceRuntime(id="src1", name="Overhead Cam", uri="fake", sensors=[sensor])

    rack, clear = a_rack(), []   # game in progress, then table cleared
    script = [rack, rack, rack, clear, clear, clear]
    rt = LiveRuntime("v1", [asset], [source], {"src1": FakeFrameSource("src1")},
                     detector=None, engine=StateEngine(enter_ticks=2, exit_ticks=3),
                     sink=sink, snooker_detector=FakeDetector(script))

    labels = []
    for _ in range(6):
        rt.tick()
        labels.append(rt.current_snapshots()[0].label)

    # game detected while balls present, then Available once cleared
    assert labels[1] in ("Occupied", "Active (In Use)", "Occupied – Idle")
    assert labels[-1] == "Available"

    sessions = SessionStore(db).list("v1")
    assert len(sessions) == 1                      # one game session
    assert sessions[0]["business_unit_id"] == "snooker"
    assert sessions[0]["end_ts"] is not None       # game opened AND closed
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

    rack_hi = [ball(50 + i * 8, 100, conf=0.8) for i in range(10)]
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
