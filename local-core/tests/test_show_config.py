"""Listing the configuration, and redrawing without typing a password."""
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from field_setup import source_uri_by_name, write_config

BASE = "rtsp://admin:secret%401962@192.168.0.108:554/cam/realmonitor?channel={c}&subtype=0"
POLY = [[0, 0], [10, 0], [10, 10], [0, 10]]


@pytest.fixture
def configured(tmp_path):
    db = str(tmp_path / "strikee.db")
    write_config(db, BASE.format(c=1), "Strikee Club", "Channel 1", "Snooker",
                 "Snooker Table", [{"name": "Snooker Table 1", "polygon": POLY}])
    write_config(db, BASE.format(c=9), "Strikee Club", "Gaming Camera A",
                 "Gaming Lounge", "Gaming Station",
                 [{"name": "RED", "polygon": POLY, "kind": "asset"},
                  {"name": "RED", "polygon": POLY, "kind": "screen"}],
                 mode="occupancy")
    return db


def _run(db, *extra):
    return subprocess.run(
        [sys.executable, str(ROOT / "tools" / "show_config.py"), "--db", db, *extra],
        capture_output=True, text=True, cwd=str(ROOT)).stdout


def test_lists_assets_grouped_by_business_unit(configured):
    out = _run(configured)
    assert "Snooker" in out and "Gaming Lounge" in out
    assert "Snooker Table 1" in out and "RED" in out


def test_shows_every_sensor_on_an_asset(configured):
    """RED has two - occupancy and its screen - and both need to be visible or
    you cannot tell which one to redraw."""
    out = _run(configured)
    assert "occupancy" in out and "screen" in out


def test_never_prints_the_password(configured):
    """This output gets screenshotted."""
    out = _run(configured)
    assert "secret" not in out
    assert "***" in out


def test_suggests_a_redraw_command_per_camera_and_mode(configured):
    out = _run(configured)
    assert '--redraw --mode occupancy' in out
    assert '--redraw --mode screen' in out
    assert '--source-name "Gaming Camera A"' in out


def test_the_suggested_command_carries_no_url(configured):
    """Putting the url on the command line puts the DVR password into shell
    history and into any screenshot of the terminal."""
    out = _run(configured)
    redraw_section = out[out.index("To improve a zone"):]
    assert "rtsp://" not in redraw_section


def test_camera_lookup_resolves_a_name_to_its_url(configured):
    uri = source_uri_by_name(configured, "Strikee Club", "Gaming Camera A")
    assert uri and uri.endswith("channel=9&subtype=0")


def test_camera_lookup_returns_none_for_an_unknown_name(configured):
    assert source_uri_by_name(configured, "Strikee Club", "Nope") is None
    assert source_uri_by_name(configured, "No Venue", "Channel 1") is None


def test_an_asset_with_no_sensors_is_called_out(tmp_path):
    """An asset nothing observes looks configured and never reports anything."""
    db = str(tmp_path / "s.db")
    write_config(db, BASE.format(c=1), "Club", "Channel 1", "Snooker",
                 "Snooker Table", [{"name": "Ghost", "polygon": POLY}])
    import sqlite3
    conn = sqlite3.connect(db)
    conn.execute("DELETE FROM sensors")
    conn.commit(); conn.close()
    assert "never observed" in _run(db)
