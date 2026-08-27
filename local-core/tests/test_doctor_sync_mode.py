"""The doctor must not fail a correctly-configured push setup.

In push mode the backend IS sqlite3 - that is the design, not a fault - so the
replica checks do not apply and libsql need not be installed at all.
"""
import pytest

from app.doctor import _check_turso


def test_push_mode_checks_the_remote_not_the_backend(monkeypatch, capsys):
    monkeypatch.setenv("STRIKEE_SYNC_MODE", "push")
    monkeypatch.setenv("TURSO_DATABASE_URL", "libsql://x.turso.io")
    monkeypatch.setenv("TURSO_AUTH_TOKEN", "ey.a.b")

    from app import cloudsync
    monkeypatch.setattr(cloudsync.TursoPush, "_pipeline",
                        lambda self, statements: [{"type": "ok"}])

    assert _check_turso() is True
    out = capsys.readouterr().out
    assert "push" in out.lower()
    assert "backend is" not in out, "still complaining about the sqlite3 backend"


def test_push_mode_fails_when_the_remote_rejects_writes(monkeypatch, capsys):
    monkeypatch.setenv("STRIKEE_SYNC_MODE", "push")
    monkeypatch.setenv("TURSO_DATABASE_URL", "libsql://x.turso.io")
    monkeypatch.setenv("TURSO_AUTH_TOKEN", "ey.a.b")

    from app import cloudsync

    def boom(self, statements):
        raise cloudsync.CloudSyncError("HTTP 401: unauthorized")

    monkeypatch.setattr(cloudsync.TursoPush, "_pipeline", boom)

    assert _check_turso() is False
    out = capsys.readouterr().out
    assert "401" in out and "turso_check.py" in out


def test_push_mode_without_credentials_fails(monkeypatch, capsys):
    monkeypatch.setenv("STRIKEE_SYNC_MODE", "push")
    monkeypatch.delenv("TURSO_DATABASE_URL", raising=False)
    monkeypatch.delenv("TURSO_AUTH_TOKEN", raising=False)
    assert _check_turso() is False
    assert "not set" in capsys.readouterr().out


def test_off_mode_is_skipped(monkeypatch, capsys):
    monkeypatch.setenv("STRIKEE_SYNC_MODE", "off")
    monkeypatch.setenv("TURSO_DATABASE_URL", "libsql://x.turso.io")
    monkeypatch.setenv("TURSO_AUTH_TOKEN", "ey.a.b")
    assert _check_turso() is True
    assert "off" in capsys.readouterr().out


def test_replica_mode_still_reports_a_wrong_backend(monkeypatch, capsys):
    """The old check stays for anyone actually using a replica - but now it
    names push mode as the way out."""
    monkeypatch.setenv("STRIKEE_SYNC_MODE", "replica")
    monkeypatch.setenv("TURSO_DATABASE_URL", "libsql://x.turso.io")
    monkeypatch.setenv("TURSO_AUTH_TOKEN", "ey.a.b")
    pytest.importorskip("libsql")

    import app.db as dbmod
    monkeypatch.setattr(dbmod, "_turso_env", lambda: None)   # forces sqlite3

    assert _check_turso() is False
    out = capsys.readouterr().out
    assert "STRIKEE_SYNC_MODE=push" in out, "does not point at the fix"
