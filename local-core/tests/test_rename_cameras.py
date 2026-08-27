"""Renaming cameras.

--source-name names the CAMERA, not the table, which is easy to get wrong when
one camera covers two tables. Nothing tracks by that name - a camera is matched
by its RTSP URL - so this only fixes how the config reads.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from app.db import Database
from app.entities import REGISTRY
from app.repository import Repository
from field_setup import write_config
from tools.rename_cameras import _mask, main

BASE = "rtsp://admin:secret%401962@10.0.0.5:554/cam/realmonitor?channel={c}&subtype=0"
POLY = [[0, 0], [10, 0], [10, 10]]


@pytest.fixture
def db_path(tmp_path):
    p = str(tmp_path / "strikee.db")
    write_config(p, BASE.format(c=1), "Club", "Table 1", "Snooker", "Snooker Table",
                 [{"name": "Snooker Table 1", "polygon": POLY}])
    write_config(p, BASE.format(c=6), "Club", "Table 3", "Snooker", "Snooker Table",
                 [{"name": "Snooker Table 3", "polygon": POLY},
                  {"name": "Snooker Table 4", "polygon": POLY}])
    return p


def _names(db_path):
    repo = Repository(next(s for s in REGISTRY if s.name == "video_source"))
    db = Database(db_path)
    try:
        with db.cursor() as cur:
            return {s["name"]: s["uri"] for s in repo.list(cur)}
    finally:
        db.close()


def _run(monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["rename_cameras.py", *argv])
    return main()


def test_password_is_masked_when_printed():
    out = _mask(BASE.format(c=1))
    assert "secret" not in out and "***" in out and "10.0.0.5" in out


def test_listing_changes_nothing(monkeypatch, db_path, capsys):
    before = _names(db_path)
    assert _run(monkeypatch, "--db", db_path) == 0
    assert _names(db_path) == before
    assert "Nothing changed" in capsys.readouterr().out


def test_auto_renames_from_the_channel_in_the_url(monkeypatch, db_path):
    _run(monkeypatch, "--db", db_path, "--auto")
    names = _names(db_path)
    assert set(names) == {"Channel 1", "Channel 6"}


def test_listing_shows_what_each_camera_watches(monkeypatch, db_path, capsys):
    """One camera covering two tables is exactly the case that produces a
    confusing name, so the assets it watches belong on screen."""
    _run(monkeypatch, "--db", db_path)
    out = capsys.readouterr().out
    assert "Snooker Table 3, Snooker Table 4" in out


def test_set_renames_one_by_id_prefix(monkeypatch, db_path, capsys):
    repo = Repository(next(s for s in REGISTRY if s.name == "video_source"))
    db = Database(db_path)
    with db.cursor() as cur:
        target = repo.list(cur)[0]
    db.close()

    _run(monkeypatch, "--db", db_path, "--set", target["id"][:8], "Gaming Camera A")
    assert "Gaming Camera A" in _names(db_path)


def test_unknown_id_changes_nothing(monkeypatch, db_path, capsys):
    before = _names(db_path)
    assert _run(monkeypatch, "--db", db_path, "--set", "zzzzzz", "X") == 1
    assert _names(db_path) == before


def test_a_url_without_a_channel_is_left_alone(monkeypatch, tmp_path, capsys):
    p = str(tmp_path / "s.db")
    write_config(p, "rtsp://cam/stream1", "Club", "Front Door", "Shared", "Zone",
                 [{"name": "Lobby", "polygon": POLY}], mode="occupancy")
    _run(monkeypatch, "--db", p, "--auto")
    assert "Front Door" in _names(p)
    assert "no channel in its URL" in capsys.readouterr().out


def test_renaming_does_not_touch_zones_or_sensors(monkeypatch, db_path):
    repos = {s.name: Repository(s) for s in REGISTRY}
    db = Database(db_path)
    with db.cursor() as cur:
        before = (len(repos["sensor"].list(cur)), len(repos["zone"].list(cur)),
                  len(repos["asset"].list(cur)))
    db.close()

    _run(monkeypatch, "--db", db_path, "--auto")

    db = Database(db_path)
    with db.cursor() as cur:
        after = (len(repos["sensor"].list(cur)), len(repos["zone"].list(cur)),
                 len(repos["asset"].list(cur)))
    db.close()
    assert before == after
