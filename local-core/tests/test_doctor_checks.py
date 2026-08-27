"""The doctor is the gate before setup, so its checks have to actually check.

The dangerous ones are the storage credentials: uploads are best-effort by
design, so bad keys fail silently forever. The only honest test is a real
write/read/delete.
"""
import pytest

from app import doctor


def test_disk_check_passes_with_room(capsys):
    assert doctor._check_disk(".") is True
    assert "GB free" in capsys.readouterr().out


def test_disk_check_fails_when_nearly_full(monkeypatch, capsys):
    import shutil
    monkeypatch.setattr(shutil, "disk_usage",
                        lambda p: type("U", (), {"free": 500_000_000})())
    assert doctor._check_disk(".") is False
    assert "will fill" in capsys.readouterr().out


def test_storage_is_skipped_when_no_bucket(monkeypatch, capsys):
    monkeypatch.delenv("STRIKEE_S3_BUCKET", raising=False)
    monkeypatch.delenv("STRIKEE_BACKUP_BUCKET", raising=False)
    assert doctor._check_object_storage() is True
    assert "skipped object storage" in capsys.readouterr().out


class _Client:
    def __init__(self, fail=False):
        self.fail = fail
        self.deleted = False
    def put_object(self, **kw):
        if self.fail:
            raise RuntimeError("AccessDenied")
    def get_object(self, **kw):
        return {"Body": type("B", (), {"read": lambda s: b"strikee-doctor"})()}
    def delete_object(self, **kw):
        self.deleted = True


def test_storage_round_trip_passes_and_cleans_up(monkeypatch, capsys):
    monkeypatch.setenv("STRIKEE_S3_BUCKET", "strikee-snapshots")
    monkeypatch.delenv("STRIKEE_BACKUP_BUCKET", raising=False)
    client = _Client()
    from app.snapshots import SnapshotStore
    monkeypatch.setattr(SnapshotStore, "_client", lambda self: client)

    assert doctor._check_object_storage() is True
    out = capsys.readouterr().out
    assert "wrote, read and deleted" in out
    assert client.deleted, "left a test object behind in the customer's bucket"


def test_storage_failure_is_reported_with_what_to_check(monkeypatch, capsys):
    monkeypatch.setenv("STRIKEE_S3_BUCKET", "strikee-snapshots")
    monkeypatch.delenv("STRIKEE_BACKUP_BUCKET", raising=False)
    from app.snapshots import SnapshotStore
    monkeypatch.setattr(SnapshotStore, "_client", lambda self: _Client(fail=True))

    assert doctor._check_object_storage() is False
    out = capsys.readouterr().out
    assert "AccessDenied" in out and "s3:PutObject" in out


def test_backup_bucket_uses_its_own_prefix(monkeypatch, capsys):
    """Backups can share the snapshot bucket, so the test object must land under
    the configured folder rather than the bucket root."""
    monkeypatch.delenv("STRIKEE_S3_BUCKET", raising=False)
    monkeypatch.setenv("STRIKEE_BACKUP_BUCKET", "strikee-snapshots")
    monkeypatch.setenv("STRIKEE_BACKUP_PREFIX", "db-backup")
    seen = {}

    class C(_Client):
        def put_object(self, **kw):
            seen["key"] = kw["Key"]

    import app.backup as b
    monkeypatch.setattr(b, "_client", lambda cfg: C())
    assert doctor._check_object_storage() is True
    assert seen["key"].startswith("db-backup/")


def test_env_file_check_reports_when_absent(monkeypatch, capsys):
    from app import platform_env
    monkeypatch.setattr(platform_env, "ENV_FILE_PATH", None)
    assert doctor._check_env_file() is True
    assert "no .env found" in capsys.readouterr().out


def test_multi_channel_rtsp_tests_each_one(monkeypatch, capsys):
    tried = []
    monkeypatch.setattr(doctor, "_check_rtsp",
                        lambda uri, label="x": (tried.append(uri) or True))
    monkeypatch.setattr(doctor, "_check_turso", lambda: True)
    monkeypatch.setattr(doctor, "_check_object_storage", lambda: True)
    monkeypatch.setattr(doctor, "_check_model", lambda m: True)
    monkeypatch.setattr(doctor, "_check_torch", lambda: True)
    monkeypatch.setattr(doctor, "_check_cv2", lambda: True)

    doctor.run(rtsp="rtsp://x/ch{ch}", channels=[1, 4, 6])
    assert tried == ["rtsp://x/ch1", "rtsp://x/ch4", "rtsp://x/ch6"]
