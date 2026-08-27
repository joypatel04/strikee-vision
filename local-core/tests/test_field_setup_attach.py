"""Attaching a sensor to an existing asset.

A TV is not an asset - it is evidence about one - and the same is true of a
second way of watching a table. A pool table observed for balls AND for people
is one table with two sensors, not two tables.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from app.db import Database
from app.entities import REGISTRY
from app.repository import Repository
from field_setup import write_config

POLY = [[0, 0], [10, 0], [10, 10]]


def _z(name):
    return {"name": name, "polygon": POLY}


def _inspect(db_path):
    repos = {s.name: Repository(s) for s in REGISTRY}
    db = Database(db_path)
    try:
        with db.cursor() as cur:
            names = {a["id"]: a["name"] for a in repos["asset"].list(cur)}
            sensors = {}
            for s in repos["sensor"].list(cur):
                sensors.setdefault(names[s["asset_id"]], []).append(
                    (s["type"], s["role"]))
            return sorted(names.values()), sensors
    finally:
        db.close()


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "t.db")


def _snooker(db_path, zones, **kw):
    return write_config(db_path, "rtsp://ch6", "Strikee Club", "Channel 6",
                        "Snooker", "Snooker Table", zones, **kw)


def test_attach_adds_a_sensor_without_creating_an_asset(db_path):
    _snooker(db_path, [_z("Table 3"), _z("Table 4")])
    _snooker(db_path, [_z("Table 4")], mode="occupancy", attach=True)

    names, sensors = _inspect(db_path)
    assert names == ["Table 3", "Table 4"], "attaching created a duplicate asset"
    assert sorted(sensors["Table 4"]) == [("occupancy", "supporting"),
                                          ("snooker_game", "primary")]
    assert sensors["Table 3"] == [("snooker_game", "primary")]


def test_attach_completes_the_transaction(db_path):
    """Regression: the attach branch closed the database from inside the cursor
    context, so the commit afterwards hit a closed connection. Nothing was
    written and --mode screen raised."""
    _snooker(db_path, [_z("Station 1")], mode="occupancy")
    _snooker(db_path, [_z("Station 1")], mode="screen", attach=True)

    _, sensors = _inspect(db_path)
    assert ("screen", "supporting") in sensors["Station 1"], (
        "the screen sensor was never committed")


def test_screen_mode_attaches_without_the_flag(db_path):
    _snooker(db_path, [_z("Station 1")], mode="occupancy")
    _snooker(db_path, [_z("Station 1")], mode="screen")
    names, sensors = _inspect(db_path)
    assert names == ["Station 1"]
    assert ("screen", "supporting") in sensors["Station 1"]


def test_attaching_to_a_name_that_does_not_exist_creates_nothing(db_path, capsys):
    _snooker(db_path, [_z("Table 3")])
    _snooker(db_path, [_z("Table 9")], mode="occupancy", attach=True)

    names, _ = _inspect(db_path)
    assert names == ["Table 3"], "a typo silently became a new asset"
    assert "NO ASSET NAMED: Table 9" in capsys.readouterr().out


def test_role_can_be_forced(db_path):
    """A second camera on the same table may deserve to be primary."""
    _snooker(db_path, [_z("Table 3")])
    _snooker(db_path, [_z("Table 3")], mode="occupancy", attach=True, role="primary")
    _, sensors = _inspect(db_path)
    assert ("occupancy", "primary") in sensors["Table 3"]


def test_normal_mode_still_creates_assets(db_path):
    _snooker(db_path, [_z("Table 1"), _z("Table 2")])
    names, sensors = _inspect(db_path)
    assert names == ["Table 1", "Table 2"]
    assert all(s == [("snooker_game", "primary")] for s in sensors.values())


def test_a_mismatch_shows_what_names_do_exist(db_path, capsys):
    """The match is exact and the usual failure is a slightly different name -
    'Table 4' against 'Snooker Table 4'. Naming only what is missing leaves you
    guessing what to type instead."""
    _snooker(db_path, [_z("Snooker Table 3"), _z("Snooker Table 4")])
    _snooker(db_path, [_z("Table 4")], mode="occupancy", attach=True)

    out = capsys.readouterr().out
    assert "NO ASSET NAMED: Table 4" in out
    assert "Snooker Table 3, Snooker Table 4" in out, (
        "did not list the names that would have worked")
