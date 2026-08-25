"""Snapshot upload config.

The bug this pins down: SnapshotStore built a bare boto3 client, so an R2
bucket name was sent to Amazon S3 - and the blanket `except: pass` meant the
failure was invisible.
"""
from app.snapshots import SnapshotStore


def test_endpoint_and_region_come_from_the_snapshot_vars(monkeypatch):
    monkeypatch.setenv("STRIKEE_S3_BUCKET", "snaps")
    monkeypatch.setenv("STRIKEE_S3_ENDPOINT", "https://acct.r2.cloudflarestorage.com")
    monkeypatch.setenv("STRIKEE_S3_REGION", "apac")
    s = SnapshotStore("snapshots")
    assert s.s3_endpoint == "https://acct.r2.cloudflarestorage.com"
    assert s.s3_region == "apac"


def test_falls_back_to_the_backup_endpoint(monkeypatch):
    monkeypatch.delenv("STRIKEE_S3_ENDPOINT", raising=False)
    monkeypatch.delenv("STRIKEE_S3_REGION", raising=False)
    monkeypatch.setenv("STRIKEE_S3_BUCKET", "snaps")
    monkeypatch.setenv("STRIKEE_BACKUP_ENDPOINT", "https://acct.r2.cloudflarestorage.com")
    monkeypatch.setenv("STRIKEE_BACKUP_REGION", "auto")
    s = SnapshotStore("snapshots")
    assert s.s3_endpoint == "https://acct.r2.cloudflarestorage.com"
    assert s.s3_region == "auto"


def test_region_defaults_to_auto_which_is_what_r2_wants(monkeypatch):
    for v in ("STRIKEE_S3_ENDPOINT", "STRIKEE_S3_REGION",
              "STRIKEE_BACKUP_ENDPOINT", "STRIKEE_BACKUP_REGION"):
        monkeypatch.delenv(v, raising=False)
    assert SnapshotStore("snapshots").s3_region == "auto"


def test_client_passes_endpoint_url_to_boto3(monkeypatch):
    captured = {}

    class FakeBoto:
        @staticmethod
        def client(service, **kwargs):
            captured["service"] = service
            captured.update(kwargs)
            return object()

    import sys
    monkeypatch.setitem(sys.modules, "boto3", FakeBoto)
    s = SnapshotStore("snapshots", s3_bucket="snaps",
                      s3_endpoint="https://acct.r2.cloudflarestorage.com",
                      s3_region="auto")
    s._client()
    assert captured["service"] == "s3"
    assert captured["endpoint_url"] == "https://acct.r2.cloudflarestorage.com"
    assert captured["region_name"] == "auto"


def test_no_endpoint_means_no_endpoint_url_kwarg(monkeypatch):
    """Passing endpoint_url=None to boto3 is not the same as omitting it."""
    captured = {}

    class FakeBoto:
        @staticmethod
        def client(service, **kwargs):
            captured.update(kwargs)
            return object()

    import sys
    monkeypatch.setitem(sys.modules, "boto3", FakeBoto)
    SnapshotStore("snapshots", s3_bucket="snaps", s3_region="us-east-1")._client()
    assert "endpoint_url" not in captured


def test_upload_failures_are_counted_not_swallowed(monkeypatch, tmp_path):
    class FakeBoto:
        @staticmethod
        def client(service, **kwargs):
            class C:
                def upload_file(self, *a, **k):
                    raise RuntimeError("no such bucket")
            return C()

    import sys
    monkeypatch.setitem(sys.modules, "boto3", FakeBoto)
    s = SnapshotStore(str(tmp_path), s3_bucket="snaps")
    f = tmp_path / "x.jpg"
    f.write_bytes(b"jpeg")

    s._maybe_upload(f, "key.jpg")

    assert s.uploads_failed == 1
    assert "no such bucket" in s.last_upload_error
    assert s.upload_status()["failed"] == 1


def test_upload_success_is_counted(monkeypatch, tmp_path):
    class FakeBoto:
        @staticmethod
        def client(service, **kwargs):
            class C:
                def upload_file(self, *a, **k):
                    return None
            return C()

    import sys
    monkeypatch.setitem(sys.modules, "boto3", FakeBoto)
    s = SnapshotStore(str(tmp_path), s3_bucket="snaps")
    f = tmp_path / "x.jpg"
    f.write_bytes(b"jpeg")
    s._maybe_upload(f, "key.jpg")
    assert s.uploads_ok == 1 and s.uploads_failed == 0


def test_upload_is_skipped_entirely_when_no_bucket(tmp_path, monkeypatch):
    monkeypatch.delenv("STRIKEE_S3_BUCKET", raising=False)
    s = SnapshotStore(str(tmp_path))
    s._maybe_upload(tmp_path / "nope.jpg", "k")   # must not raise
    assert s.upload_status()["enabled"] is False


# --------------------------------------------------------- size and retention


def test_quality_defaults_to_80_not_opencvs_95(monkeypatch):
    monkeypatch.delenv("STRIKEE_SNAPSHOT_QUALITY", raising=False)
    assert SnapshotStore("snapshots").quality == 80


def test_quality_is_configurable(monkeypatch):
    monkeypatch.setenv("STRIKEE_SNAPSHOT_QUALITY", "70")
    assert SnapshotStore("snapshots").quality == 70


def test_quality_is_actually_applied_to_the_written_file(tmp_path):
    """Guards the setting being read but never passed to imwrite."""
    import numpy as np
    frame = np.zeros((240, 320, 3), dtype="uint8")
    frame[:, :160] = 255                      # some content to compress

    big = SnapshotStore(str(tmp_path / "hi"), quality=95)
    small = SnapshotStore(str(tmp_path / "lo"), quality=40)
    big.save("v", "a", "Table 1", frame)
    small.save("v", "a", "Table 1", frame)

    def total(store):
        return sum(f.stat().st_size for f in store.base.rglob("*.jpg"))

    assert total(small) < total(big)


def test_disk_usage_counts_what_is_there(tmp_path):
    store = SnapshotStore(str(tmp_path))
    d = tmp_path / "v" / "2026-08-25"
    d.mkdir(parents=True)
    (d / "a.jpg").write_bytes(b"x" * 1000)
    (d / "b.jpg").write_bytes(b"x" * 2000)
    usage = store.disk_usage()
    assert usage["files"] == 2
    assert usage["megabytes"] == 0.0        # 3 KB rounds to 0.0 MB


def test_disk_usage_on_an_empty_store(tmp_path):
    assert SnapshotStore(str(tmp_path / "nothing")).disk_usage() == {
        "files": 0, "megabytes": 0.0}


def test_cleanup_removes_old_and_keeps_recent(tmp_path):
    import os, time
    store = SnapshotStore(str(tmp_path))
    d = tmp_path / "v" / "2026-01-01"
    d.mkdir(parents=True)
    old, new = d / "old.jpg", d / "new.jpg"
    old.write_bytes(b"x"); new.write_bytes(b"x")
    ancient = time.time() - (40 * 86400)
    os.utime(old, (ancient, ancient))

    removed = store.cleanup(keep_days=30)

    assert removed == 1
    assert not old.exists() and new.exists()
