"""End-to-end pipeline tests using fake capture + fake detector (no model)."""
import asyncio

from app.db import Database
from app.pipeline.broadcast import Broadcaster
from app.pipeline.capture import FakeFrameSource
from app.pipeline.manager import RuntimeManager
from app.pipeline.perception import FakeDetector
from app.pipeline.runtime import LiveRuntime, build_live_runtime, load_venue_config
from app.pipeline.state import StateEngine
from app.pipeline.types import (
    AssetRuntime, Detection, SensorRuntime, SourceRuntime,
)
from app.repository import Repository
from app.entities import REGISTRY

ZONE = [[0, 0], [100, 0], [100, 100], [0, 100]]


def person_in_zone():
    # feet at (50, 90) -> inside ZONE
    return [Detection(bbox=(40, 10, 60, 90), confidence=0.9)]


def person_outside():
    return [Detection(bbox=(140, 10, 160, 90), confidence=0.9)]


def _runtime_one_table(detector, engine=None):
    sensor = SensorRuntime(id="s1", asset_id="a1", source_id="src1",
                           kind="occupancy", role="primary",
                           conf_threshold=0.35, zone_polygons=[ZONE])
    asset = AssetRuntime(id="a1", name="Table 1", business_unit_id="bu1",
                         sensors=[sensor])
    source = SourceRuntime(id="src1", name="Cam A", uri="fake", sensors=[sensor])
    frame_sources = {"src1": FakeFrameSource("src1")}
    return LiveRuntime("v1", [asset], [source], frame_sources, detector,
                       engine or StateEngine(enter_ticks=2, exit_ticks=3))


def test_tick_end_to_end_occupied_then_available():
    # present for a while, then leaves
    script = [person_in_zone(), person_in_zone(), person_in_zone(),
              person_outside(), person_outside(), person_outside()]
    rt = _runtime_one_table(FakeDetector(script))

    labels = []
    for _ in range(6):
        _all, _changed = rt.tick()
        labels.append(rt.current_snapshots()[0].label)

    assert labels[1] == "Occupied"     # opened after 2 present ticks
    assert labels[-1] == "Available"   # closed after 3 empty ticks


def test_tick_offline_source_is_unknown():
    # source script exhausts immediately -> offline
    sensor = SensorRuntime(id="s1", asset_id="a1", source_id="src1",
                           kind="occupancy", zone_polygons=[ZONE])
    asset = AssetRuntime(id="a1", name="Table 1", business_unit_id=None, sensors=[sensor])
    source = SourceRuntime(id="src1", name="Cam A", uri="fake", sensors=[sensor])
    fs = FakeFrameSource("src1", script=[(False, None)])
    rt = LiveRuntime("v1", [asset], [source], {"src1": fs},
                     FakeDetector(lambda f: person_in_zone()), StateEngine())
    rt.tick()
    snap = rt.current_snapshots()[0]
    assert snap.health == "offline"
    assert snap.label == "Unknown"


def _seed_reference_venue(db):
    """Build a venue via repositories and return ids."""
    repos = {s.name: Repository(s) for s in REGISTRY}
    with db.cursor() as cur:
        org = repos["organization"].create(cur, {"name": "Strikee"})
        v = repos["venue"].create(cur, {"organization_id": org["id"], "name": "Club"})
        bu = repos["business_unit"].create(cur, {"venue_id": v["id"], "name": "Snooker"})
        sp = repos["space"].create(cur, {"venue_id": v["id"], "name": "Snooker Area"})
        src = repos["video_source"].create(cur, {"venue_id": v["id"], "space_id": sp["id"],
                                                  "name": "Cam A", "uri": "rtsp://x"})
        at = repos["asset_type"].create(cur, {"venue_id": v["id"], "name": "Snooker Table"})
        asset = repos["asset"].create(cur, {"venue_id": v["id"], "space_id": sp["id"],
                                            "business_unit_id": bu["id"],
                                            "asset_type_id": at["id"], "name": "Table 1"})
        zone = repos["zone"].create(cur, {"space_id": sp["id"], "name": "T1 Zone",
                                          "polygons": [ZONE]})
        repos["sensor"].create(cur, {"asset_id": asset["id"], "video_source_id": src["id"],
                                     "zone_id": zone["id"], "type": "occupancy",
                                     "role": "primary"})
    return v["id"], asset["id"], src["id"]


def test_load_venue_config_from_db():
    db = Database(":memory:")
    venue_id, asset_id, source_id = _seed_reference_venue(db)
    assets, sources = load_venue_config(db, venue_id)
    db.close()

    assert len(assets) == 1 and assets[0].id == asset_id
    assert len(assets[0].sensors) == 1
    s = assets[0].sensors[0]
    assert s.source_id == source_id
    assert s.zone_polygons == [ZONE]          # JSON parsed
    assert s.role == "primary"
    assert len(sources) == 1
    assert len(sources[0].sensors) == 1       # sensor wired to its source


def test_build_live_runtime_with_fake_source_factory():
    db = Database(":memory:")
    venue_id, _asset_id, _src = _seed_reference_venue(db)
    rt = build_live_runtime(
        db, venue_id, FakeDetector(lambda f: person_in_zone()),
        source_factory=lambda s: FakeFrameSource(s.id),
        engine=StateEngine(enter_ticks=1),
    )
    db.close()
    rt.tick()
    assert rt.current_snapshots()[0].label == "Occupied"


# --- broadcaster + manager loop -------------------------------------------

class FakeWS:
    def __init__(self):
        self.sent = []

    async def send_json(self, payload):
        self.sent.append(payload)


def test_broadcaster_sends_to_connections():
    async def run():
        b = Broadcaster()
        ws = FakeWS()
        b.add("v1", ws)
        rt = _runtime_one_table(FakeDetector(lambda f: person_in_zone()),
                                StateEngine(enter_ticks=1))
        rt.tick()
        await b.broadcast("v1", rt.current_snapshots())
        return ws
    ws = asyncio.run(run())
    assert ws.sent and ws.sent[0]["type"] == "state"
    assert ws.sent[0]["assets"][0]["label"] == "Occupied"


def test_manager_loop_broadcasts_change():
    async def run():
        b = Broadcaster()
        ws = FakeWS()
        b.add("v1", ws)
        mgr = RuntimeManager(db=None, broadcaster=b, interval=0.01)
        rt = _runtime_one_table(FakeDetector(lambda f: person_in_zone()),
                                StateEngine(enter_ticks=1))
        mgr.run_runtime("v1", rt)
        # let the loop tick a few times
        await asyncio.sleep(0.06)
        await mgr.stop("v1")
        return ws
    ws = asyncio.run(run())
    assert any(m["assets"][0]["label"] == "Occupied" for m in ws.sent)
