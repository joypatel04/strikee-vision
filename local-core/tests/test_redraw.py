"""Redrawing a zone in place.

Improving a polygon must not cost the asset. Deleting and re-adding would take
its sessions, its games and any screen sensor with it - and accuracy history is
exactly what you were trying to improve.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from app.db import Database
from app.entities import REGISTRY
from app.repository import Repository
from field_setup import existing_zones, redraw_zones, write_config

URI = "rtsp://ch9"
SEAT = [[40, 150], [260, 150], [260, 400], [40, 400]]
TV = [[300, 60], [560, 60], [560, 220], [300, 220]]
BETTER = [[30, 120], [280, 120], [280, 430], [30, 430]]


def _setup(db_path, paired=True):
    zones = [{"name": "RED", "polygon": SEAT, "kind": "asset"}]
    if paired:
        zones.append({"name": "RED", "polygon": TV, "kind": "screen"})
    write_config(db_path, URI, "Strikee Club", "Gaming Camera A", "Gaming Lounge",
                 "Gaming Station", zones, mode="occupancy")


def _state(db_path):
    repos = {s.name: Repository(s) for s in REGISTRY}
    db = Database(db_path)
    try:
        with db.cursor() as cur:
            assets = {a["id"]: a["name"] for a in repos["asset"].list(cur)}
            zones = {z["id"]: z["polygons"] for z in repos["zone"].list(cur)}
            sensors = {(assets[s["asset_id"]], s["type"]): zones[s["zone_id"]]
                       for s in repos["sensor"].list(cur)}
            return assets, sensors
    finally:
        db.close()


@pytest.fixture
def db_path(tmp_path):
    p = str(tmp_path / "t.db")
    _setup(p)
    return p


def test_redraw_replaces_the_polygon(db_path):
    updated, missing = redraw_zones(db_path, URI, "Strikee Club",
                                    [{"name": "RED", "polygon": BETTER}], "occupancy")
    assert (updated, missing) == (1, [])
    _, sensors = _state(db_path)
    assert sensors[("RED", "occupancy")] == [BETTER]


def test_redraw_keeps_the_asset_and_its_history(db_path):
    """The asset id must survive, or every session and game pointing at it is
    orphaned."""
    before_assets, _ = _state(db_path)
    redraw_zones(db_path, URI, "Strikee Club",
                 [{"name": "RED", "polygon": BETTER}], "occupancy")
    after_assets, _ = _state(db_path)
    assert before_assets == after_assets


def test_redraw_leaves_the_screen_zone_alone(db_path):
    """Fixing the seating area must not disturb the TV zone beside it."""
    redraw_zones(db_path, URI, "Strikee Club",
                 [{"name": "RED", "polygon": BETTER}], "occupancy")
    _, sensors = _state(db_path)
    assert sensors[("RED", "screen")] == [TV]


def test_redraw_can_target_the_screen_instead(db_path):
    tighter = [[320, 80], [540, 80], [540, 200], [320, 200]]
    updated, _ = redraw_zones(db_path, URI, "Strikee Club",
                              [{"name": "RED", "polygon": tighter}], "screen")
    assert updated == 1
    _, sensors = _state(db_path)
    assert sensors[("RED", "screen")] == [tighter]
    assert sensors[("RED", "occupancy")] == [SEAT], "seating zone was disturbed"


def test_an_unknown_name_changes_nothing(db_path):
    updated, missing = redraw_zones(db_path, URI, "Strikee Club",
                                    [{"name": "BLUE", "polygon": BETTER}], "occupancy")
    assert (updated, missing) == (0, ["BLUE"])
    _, sensors = _state(db_path)
    assert sensors[("RED", "occupancy")] == [SEAT]


def test_a_wrong_camera_changes_nothing(db_path):
    """A zone belongs to a camera; redrawing from a different one must not
    silently move it."""
    updated, missing = redraw_zones(db_path, "rtsp://other", "Strikee Club",
                                    [{"name": "RED", "polygon": BETTER}], "occupancy")
    assert updated == 0 and missing == ["RED"]
    _, sensors = _state(db_path)
    assert sensors[("RED", "occupancy")] == [SEAT]


def test_existing_zones_reports_what_is_drawn(db_path):
    found = existing_zones(db_path, "Strikee Club", URI)
    names = sorted(z["name"] for z in found)
    assert names == ["RED", "RED"]        # seating and screen
    occ = existing_zones(db_path, "Strikee Club", URI, mode="occupancy")
    assert len(occ) == 1 and occ[0]["polygon"] == SEAT


def test_existing_zones_on_an_unknown_camera_is_empty(db_path):
    assert existing_zones(db_path, "Strikee Club", "rtsp://nope") == []
