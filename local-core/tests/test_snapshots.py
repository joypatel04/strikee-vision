"""Game-start snapshots + daily games report."""
import os
import time

import numpy as np

from app.db import Database
from app.snapshots import SnapshotStore
from app.store import EventStore, SessionStore
from app.pipeline.sink import ChangeEvent, DbStateSink
from app.pipeline.types import AssetSnapshot


def _frame():
    return np.zeros((120, 160, 3), dtype=np.uint8)


def snap(label="Occupied", presence="present", asset_id="a1", name="Table 1",
         effective="2026-07-08T14:23:05+00:00"):
    return AssetSnapshot(asset_id=asset_id, name=name, business_unit_id="snooker",
                         presence=presence, activity="active", health="ok",
                         label=label, confidence=0.9, effective_at=effective)


def test_snapshot_store_saves_labelled_image(tmp_path):
    store = SnapshotStore(base_dir=str(tmp_path))
    rel = store.save("v1", "a1", "Table 1", _frame(), "2026-07-08T14:23:05+00:00")
    assert rel is not None
    full = tmp_path / rel
    assert full.exists() and full.suffix == ".jpg"
    assert "Table_1" in rel


def test_snapshot_store_none_frame_returns_none(tmp_path):
    assert SnapshotStore(base_dir=str(tmp_path)).save("v1", "a1", "T1", None) is None


def test_snapshot_cleanup_removes_old(tmp_path):
    store = SnapshotStore(base_dir=str(tmp_path))
    rel = store.save("v1", "a1", "Table 1", _frame())
    old = tmp_path / rel
    # backdate the file 10 days
    ten_days = time.time() - 10 * 86400
    os.utime(old, (ten_days, ten_days))
    assert store.cleanup(keep_days=7) == 1
    assert not old.exists()


class FakeSnapshotStore:
    def __init__(self):
        self.saved = []

    def save(self, venue_id, asset_id, asset_name, frame, ts=None):
        self.saved.append((asset_id, asset_name))
        return f"{asset_name}.jpg"


def test_sink_saves_snapshot_on_game_start():
    db = Database(":memory:")
    store = FakeSnapshotStore()
    sink = DbStateSink(EventStore(db), SessionStore(db),
                       snapshot_store=store, frame_provider=lambda aid: _frame())
    sink.handle("v1", [ChangeEvent("Available", snap())])
    # session carries the snapshot path
    session = SessionStore(db).list("v1")[0]
    assert session["start_snapshot"] == "Table 1.jpg"
    assert store.saved == [("a1", "Table 1")]
    db.close()


def test_sink_no_snapshot_without_frame():
    db = Database(":memory:")
    store = FakeSnapshotStore()
    sink = DbStateSink(EventStore(db), SessionStore(db),
                       snapshot_store=store, frame_provider=lambda aid: None)
    sink.handle("v1", [ChangeEvent("Available", snap())])
    assert SessionStore(db).list("v1")[0]["start_snapshot"] is None
    assert store.saved == []
    db.close()


def test_games_report_endpoint(client):
    db = client.app.state.db
    ss = SessionStore(db)
    s = ss.open("v1", "a1", "snooker", "2026-07-08T14:00:00+00:00",
                start_snapshot="v1/2026-07-08/Table_1_140000.jpg")
    ss.close(s["id"], "2026-07-08T14:45:00+00:00")
    # need the asset name to resolve
    from app.repository import Repository
    from app.entities import REGISTRY
    # games for the day
    r = client.get("/api/venues/v1/games?date=2026-07-08")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    g = body["games"][0]
    assert g["duration_sec"] == 2700
    assert g["snapshot"] == "/snapshots/v1/2026-07-08/Table_1_140000.jpg"
    # a different date returns nothing
    assert client.get("/api/venues/v1/games?date=2026-07-09").json()["count"] == 0
