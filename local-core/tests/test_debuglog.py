"""Field debug log writes per-tick rows the runtime can produce."""
import csv

from app.debuglog import DebugLog, COLUMNS
from app.pipeline.capture import FakeFrameSource
from app.pipeline.perception import FakeDetector
from app.pipeline.runtime import LiveRuntime
from app.pipeline.state import StateEngine
from app.pipeline.types import AssetRuntime, Detection, SensorRuntime, SourceRuntime

ZONE = [[0, 0], [400, 0], [400, 400], [0, 400]]


def rack():
    dets = [Detection(bbox=(50 + i * 8, 100, 62 + i * 8, 112), confidence=0.7,
                      label="red_ball") for i in range(12)]
    dets.append(Detection(bbox=(60, 90, 120, 150), confidence=0.5, label="game_start"))
    return dets


def test_debug_log_header_and_rows(tmp_path):
    dl = DebugLog(str(tmp_path / "d.csv"))
    dl.row({"ts": "t0", "table": "Table 1", "red": 12, "state": "IN_GAME"})
    dl.close()
    with open(tmp_path / "d.csv") as f:
        rows = list(csv.reader(f))
    assert rows[0] == COLUMNS
    assert rows[1][COLUMNS.index("red")] == "12"
    assert rows[1][COLUMNS.index("state")] == "IN_GAME"


def test_runtime_writes_debug_rows(tmp_path):
    dl = DebugLog(str(tmp_path / "run.csv"))
    sensor = SensorRuntime(id="s1", asset_id="a1", source_id="src1",
                           kind="snooker_game", conf_threshold=0.25, zone_polygons=[ZONE])
    asset = AssetRuntime(id="a1", name="Table 1", business_unit_id="snooker", sensors=[sensor])
    source = SourceRuntime(id="src1", name="Cam", uri="fake", sensors=[sensor])
    rt = LiveRuntime("v1", [asset], [source], {"src1": FakeFrameSource("src1")},
                     detector=None, engine=StateEngine(enter_ticks=1),
                     snooker_detector=FakeDetector(lambda f: rack()), debug_log=dl)
    for _ in range(3):
        rt.tick()
    dl.close()
    with open(tmp_path / "run.csv") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 3
    assert rows[0]["table"] == "Table 1"
    assert int(rows[0]["red"]) == 12
    assert rows[0]["state"] in ("SEARCH", "IN_GAME")
