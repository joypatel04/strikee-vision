"""Live frames and the disk/cloud bounds on images.

The whole point of a live frame is that it is cheap to keep forever, so the two
things worth pinning are that it cannot accumulate and that it never reaches the
bucket. Both are properties of the design, not of any one call, which is exactly
the kind of thing that rots silently.
"""
import os
import time

import numpy as np

from app.snapshots import LiveFrameStore, SnapshotStore


def _frame(value=120):
    return np.full((48, 64, 3), value, dtype=np.uint8)


class _PixelSource:
    """FakeFrameSource yields a placeholder string, which is fine for detection
    scripts but cannot be drawn on. Live frames need real pixels."""

    def read(self):
        return True, _frame(90)

    def close(self):
        pass


def _jpgs(root):
    return sorted(p.name for p in root.rglob("*.jpg"))


# ------------------------------------------------------------- live frames


def test_repeated_writes_leave_one_file_per_camera(tmp_path):
    """The bound that matters: written every few seconds, forever."""
    store = LiveFrameStore(str(tmp_path))
    for i in range(25):
        store.write("v1", "camA", _frame(i * 5))
        store.write("v1", "camB", _frame(i * 5))

    assert len(_jpgs(tmp_path)) == 2, "live frames accumulated"
    assert store.written == 50


def test_write_overwrites_rather_than_versions(tmp_path):
    store = LiveFrameStore(str(tmp_path))
    store.write("v1", "camA", _frame(10))
    first = store.path_for("v1", "camA").read_bytes()
    store.write("v1", "camA", _frame(240))
    assert store.path_for("v1", "camA").read_bytes() != first


def test_describe_reports_absence_rather_than_lying(tmp_path):
    store = LiveFrameStore(str(tmp_path))
    assert store.describe("v1", "ghost") == {"available": False, "age_sec": None,
                                             "bytes": None}
    assert store.path_for("v1", "ghost") is None

    store.write("v1", "camA", _frame())
    info = store.describe("v1", "camA")
    assert info["available"] is True
    assert info["bytes"] > 0
    assert info["age_sec"] < 10


def test_a_bad_frame_never_raises(tmp_path):
    """Tracking must outlive anything that goes wrong in the viewing path."""
    store = LiveFrameStore(str(tmp_path))
    assert store.write("v1", "camA", None) is None
    assert store.write("v1", "camA", "not a frame") is None
    assert store.last_error


def test_live_store_has_no_upload_path(tmp_path):
    """Not a disabled uploader - none at all, so it cannot be switched on."""
    store = LiveFrameStore(str(tmp_path))
    for attr in ("s3_bucket", "_maybe_upload", "_client"):
        assert not hasattr(store, attr), f"live frames gained {attr}"


# --------------------------------------------------------------- cleanup


def _aged(store, days, name="old"):
    """An evidence image with an mtime `days` in the past."""
    path = store.base / "v1" / "2020-01-01" / f"{name}.jpg"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * 1024)
    old = time.time() - days * 86400
    os.utime(path, (old, old))
    return path


def test_cleanup_leaves_live_frames_alone(tmp_path):
    """A month-old live frame is the best evidence about a pipeline that stopped
    a month ago; deleting it as 'stale' throws that away."""
    snaps = SnapshotStore(str(tmp_path))
    live = LiveFrameStore(str(tmp_path))
    live.write("v1", "camA", _frame())
    stale = live.path_for("v1", "camA")
    old = time.time() - 400 * 86400
    os.utime(stale, (old, old))
    _aged(snaps, days=90)

    removed = snaps.cleanup(keep_days=30)

    assert removed == 1, "the evidence image should have gone"
    assert stale.exists(), "cleanup ate a live frame"


def test_cleanup_enforces_a_size_budget(tmp_path):
    """Age is not a disk bound - a busy weekend outweighs a quiet fortnight."""
    store = SnapshotStore(str(tmp_path))
    for i in range(10):
        p = _aged(store, days=1, name=f"img{i:02d}")
        p.write_bytes(b"x" * 100_000)          # ~1MB total
        age = time.time() - (10 - i) * 60      # img00 oldest
        os.utime(p, (age, age))

    removed = store.cleanup(keep_days=30, max_mb=0.5)

    left = _jpgs(tmp_path)
    assert removed > 0 and len(left) < 10
    assert "img09.jpg" in left, "newest image was deleted first"
    assert "img00.jpg" not in left, "oldest image survived"


def test_size_budget_off_by_default_keeps_everything(tmp_path):
    store = SnapshotStore(str(tmp_path))
    for i in range(5):
        _aged(store, days=1, name=f"img{i}").write_bytes(b"x" * 100_000)
    assert store.cleanup(keep_days=30, max_mb=0) == 0
    assert len(_jpgs(tmp_path)) == 5


# ------------------------------------------------------------ upload policy


def test_upload_policy_none_skips_the_bucket(tmp_path, monkeypatch):
    monkeypatch.setenv("STRIKEE_S3_BUCKET", "some-bucket")
    monkeypatch.setenv("STRIKEE_S3_UPLOAD", "none")
    store = SnapshotStore(str(tmp_path))

    def explode(*a, **k):
        raise AssertionError("uploaded despite STRIKEE_S3_UPLOAD=none")

    monkeypatch.setattr(store, "_client", explode)
    assert store.save("v1", "a1", "Table 1", _frame()) is not None
    assert store.upload_status()["enabled"] is False


def test_upload_policy_defaults_to_all(tmp_path, monkeypatch):
    monkeypatch.delenv("STRIKEE_S3_UPLOAD", raising=False)
    monkeypatch.setenv("STRIKEE_S3_BUCKET", "some-bucket")
    store = SnapshotStore(str(tmp_path))
    assert store.upload_policy == "all"
    assert store.upload_status()["enabled"] is True


# ------------------------------------------------------------ http surface


def _venue_with_camera(client, tmp_path):
    org = client.post("/api/organizations", json={"name": "Acme"}).json()
    venue = client.post("/api/venues", json={
        "organization_id": org["id"], "name": "Strikee Club",
        "timezone": "Asia/Kolkata"}).json()
    cam = client.post("/api/video-sources", json={
        "venue_id": venue["id"], "name": "Gaming Camera A",
        "uri": "rtsp://user:secret@host/ch1"}).json()
    return venue, cam


def test_listing_includes_cameras_that_have_produced_nothing(client, tmp_path,
                                                             monkeypatch):
    """A camera missing from the list reads as a camera that is fine, when it is
    the one that never returned a picture."""
    monkeypatch.setenv("STRIKEE_SNAPSHOT_DIR", str(tmp_path))
    venue, cam = _venue_with_camera(client, tmp_path)

    rows = client.get(f"/api/venues/{venue['id']}/live-frames").json()
    assert len(rows) == 1
    assert rows[0]["name"] == "Gaming Camera A"
    assert rows[0]["available"] is False
    assert client.get(rows[0]["url"]).status_code == 404


def test_frame_is_served_once_written(client, tmp_path, monkeypatch):
    monkeypatch.setenv("STRIKEE_SNAPSHOT_DIR", str(tmp_path))
    venue, cam = _venue_with_camera(client, tmp_path)
    LiveFrameStore(str(tmp_path)).write(venue["id"], cam["id"], _frame())

    rows = client.get(f"/api/venues/{venue['id']}/live-frames").json()
    assert rows[0]["available"] is True and rows[0]["bytes"] > 0

    img = client.get(rows[0]["url"])
    assert img.status_code == 200
    assert img.headers["content-type"] == "image/jpeg"
    # overwritten in place, so a cached copy is the past served as the present
    assert img.headers.get("cache-control") == "no-store"
    assert img.content[:2] == b"\xff\xd8", "not a JPEG"


def test_the_listing_never_exposes_the_camera_password(client, tmp_path,
                                                       monkeypatch):
    """This panel is the one people screenshot and send on when asking for help."""
    monkeypatch.setenv("STRIKEE_SNAPSHOT_DIR", str(tmp_path))
    venue, _ = _venue_with_camera(client, tmp_path)
    body = client.get(f"/api/venues/{venue['id']}/live-frames").text
    assert "secret" not in body and "rtsp://" not in body


def test_dashboard_wires_the_camera_panel(client):
    """index.html is served as a file, so a broken edit here is invisible to
    every other test."""
    body = client.get("/").text
    assert 'id="camsBody"' in body
    assert "/live-frames" in body
    assert "initCameraFrames()" in body


# ------------------------------------------------- the runtime actually writes


def test_runtime_writes_an_annotated_frame_per_pass(tmp_path):
    """The path that produces these in the field.

    Worth its own test because everything in _write_live_frame is wrapped in a
    best-effort except: a TypeError in here would show up as no frames and no
    reason, which is precisely the failure mode the panel exists to remove.
    """
    from app.pipeline.perception import FakeDetector
    from app.pipeline.runtime import LiveRuntime
    from app.pipeline.state import StateEngine
    from app.pipeline.types import (AssetRuntime, Detection, SensorRuntime,
                                    SourceRuntime)

    zone = [[0, 0], [200, 0], [200, 200], [0, 200]]
    sensor = SensorRuntime(id="s1", asset_id="a1", source_id="src1",
                           kind="occupancy", zone_polygons=[zone])
    asset = AssetRuntime(id="a1", name="Station 1", business_unit_id="bu1",
                         sensors=[sensor])
    source = SourceRuntime(id="src1", name="Gaming Camera A", uri="fake",
                           sensors=[sensor])
    live = LiveFrameStore(str(tmp_path))
    rt = LiveRuntime("v1", [asset], [source], {"src1": _PixelSource()},
                     FakeDetector([[Detection(bbox=(20, 100, 40, 190),
                                              confidence=0.9)]] * 3),
                     StateEngine(enter_ticks=1), live_frames=live)

    for _ in range(3):
        rt.tick()

    assert live.written == 3, f"no live frame written ({live.last_error})"
    assert len(_jpgs(tmp_path)) == 1, "one camera should mean one file"
    assert live.describe("v1", "src1")["available"] is True


def test_runtime_without_a_live_store_still_tracks(tmp_path):
    """Live frames are a diagnostic, never a dependency of tracking."""
    from app.pipeline.perception import FakeDetector
    from app.pipeline.runtime import LiveRuntime
    from app.pipeline.state import StateEngine
    from app.pipeline.types import (AssetRuntime, Detection, SensorRuntime,
                                    SourceRuntime)

    zone = [[0, 0], [200, 0], [200, 200], [0, 200]]
    sensor = SensorRuntime(id="s1", asset_id="a1", source_id="src1",
                           kind="occupancy", zone_polygons=[zone])
    asset = AssetRuntime(id="a1", name="Station 1", business_unit_id="bu1",
                         sensors=[sensor])
    source = SourceRuntime(id="src1", name="Cam", uri="fake", sensors=[sensor])
    rt = LiveRuntime("v1", [asset], [source], {"src1": _PixelSource()},
                     FakeDetector([[Detection(bbox=(20, 100, 40, 190),
                                              confidence=0.9)]] * 2),
                     StateEngine(enter_ticks=1), live_frames=None)
    rt.tick()
    assert rt.current_snapshots()[0].presence == "present"
    assert not list(tmp_path.rglob("*.jpg"))
