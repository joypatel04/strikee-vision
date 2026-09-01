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


def test_suggests_a_redraw_command_per_camera(configured):
    """One command per camera - paired where the camera has screens, one per
    mode where it does not."""
    out = _run(configured)
    assert '--source-name "Gaming Camera A"' in out
    assert '--with-screen --mode occupancy' in out      # the gaming camera
    assert '--mode snooker_game' in out                 # the snooker camera


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


# ------------------------------------------------- two cameras, one name


def _dupe_named(tmp_path):
    """A channel set up with the wrong label: same name, different url."""
    db = str(tmp_path / "d.db")
    for ch in (11, 12):
        write_config(db, BASE.format(c=ch), "Strikee Club", "Gaming Camera C",
                     "Gaming Lounge", "Gaming Station",
                     [{"name": f"S{ch}", "polygon": POLY}], mode="occupancy")
    return db


def test_duplicate_camera_names_are_flagged(tmp_path):
    out = _run(_dupe_named(tmp_path))
    assert "DUPLICATE NAMES" in out
    assert "channel 11" in out and "channel 12" in out
    assert "tracking is unaffected" in out, (
        "does not say the important part - detection still works")


def test_by_name_lookup_refuses_rather_than_guessing(tmp_path):
    """Picking one of two silently would redraw zones on the wrong camera."""
    from field_setup import AmbiguousCamera
    with pytest.raises(AmbiguousCamera) as exc:
        source_uri_by_name(_dupe_named(tmp_path), "Strikee Club", "Gaming Camera C")
    assert len(exc.value.matches) == 2


def test_each_duplicate_still_watches_its_own_assets(tmp_path):
    """The names collide; the sensors do not. Nothing is actually crossed."""
    db = _dupe_named(tmp_path)
    out = _run(db)
    assert "watches: S11" in out and "watches: S12" in out


def test_renaming_resolves_the_ambiguity(tmp_path):
    db = _dupe_named(tmp_path)
    subprocess.run([sys.executable, str(ROOT / "tools" / "rename_cameras.py"),
                    "--db", db, "--auto"], capture_output=True, cwd=str(ROOT))
    uri = source_uri_by_name(db, "Strikee Club", "Channel 12")
    assert uri and "channel=12" in uri
    assert "DUPLICATE NAMES" not in _run(db)


def test_a_camera_with_screens_gets_one_paired_command(tmp_path):
    """Suggesting two separate redraws for a gaming camera means naming each
    screen to match its station again - which --with-screen exists to avoid."""
    db = str(tmp_path / "g.db")
    write_config(db, BASE.format(c=9), "Strikee Club", "Gaming Camera A",
                 "Gaming Lounge", "Gaming Station",
                 [{"name": "RED", "polygon": POLY, "kind": "asset"},
                  {"name": "RED", "polygon": POLY, "kind": "screen"}],
                 mode="occupancy")
    out = _run(db)
    section = out[out.index("To improve a zone"):]
    assert "--with-screen --mode occupancy" in section
    assert "--mode screen" not in section, "still suggesting a separate screen pass"


def test_a_snooker_camera_gets_one_command_per_mode(tmp_path):
    """Table 4 is watched two ways on one camera; each needs its own redraw
    because there is no screen to pair with."""
    db = str(tmp_path / "s.db")
    write_config(db, BASE.format(c=6), "Strikee Club", "Channel 6", "Snooker",
                 "Snooker Table", [{"name": "T4", "polygon": POLY}])
    write_config(db, BASE.format(c=6), "Strikee Club", "Channel 6", "Snooker",
                 "Snooker Table", [{"name": "T4", "polygon": POLY}],
                 mode="occupancy", attach=True)
    section = _run(db)
    section = section[section.index("To improve a zone"):]
    assert "--mode snooker_game" in section
    assert "--mode occupancy" in section
    assert "--with-screen" not in section


def test_suggested_commands_name_the_real_interpreter(configured):
    """A bare "python" resolves to whatever is first on PATH - on Windows the
    system install, which has none of the app's dependencies. The command then
    dies on `from app.entities import REGISTRY` with "No module named
    'pydantic'", which looks nothing like "you used the wrong python"."""
    out = _run(configured)
    line = next(l for l in out.splitlines() if "field_setup.py" in l).strip()
    interpreter = line.split(" field_setup.py")[0]
    assert interpreter not in ("python", "python3"), (
        f"suggests a bare interpreter: {line}")
    assert ".venv" in interpreter or interpreter.endswith(("python", "python.exe")), \
        f"unexpected interpreter: {interpreter}"
