"""Cloud-sync health reporting: sync_status() transitions + the API endpoint."""
import time

from app.db import Database


class _FakeConn:
    """Stands in for a libsql connection: sync() succeeds or raises on command."""
    def __init__(self):
        self.fail = False
    def sync(self):
        if self.fail:
            raise RuntimeError("network down")
    # minimal surface so Database.close() etc. don't choke
    def close(self):
        pass


def _turso_like_db():
    db = Database(":memory:")            # starts as sqlite3
    db._conn = _FakeConn()              # swap in a syncable connection
    db.backend = "turso"
    return db


def test_sqlite3_reports_local_only():
    db = Database(":memory:")
    st = db.sync_status()
    assert st["sync_enabled"] is False
    assert st["healthy"] is True        # local-only is not "unhealthy"
    db.close()


def test_healthy_after_successful_sync():
    db = _turso_like_db()
    assert db.sync() is True
    st = db.sync_status()
    assert st["sync_enabled"] is True
    assert st["healthy"] is True
    assert st["seconds_since_sync"] is not None and st["seconds_since_sync"] < 5
    assert st["consecutive_failures"] == 0
    assert st["sync_count"] == 1
    db.close()


def test_unhealthy_when_sync_fails():
    db = _turso_like_db()
    db.sync()                            # one good sync
    db._conn.fail = True
    assert db.sync() is False
    assert db.sync() is False
    st = db.sync_status()
    assert st["consecutive_failures"] == 2
    assert st["healthy"] is False        # a failing streak = not healthy
    assert "network down" in st["last_error"]
    db.close()


def test_unhealthy_when_stale(monkeypatch):
    db = _turso_like_db()
    db.sync()
    # pretend the last success was long ago
    db._sync_success_ts = time.time() - 10_000
    st = db.sync_status()
    assert st["healthy"] is False        # too long since last sync
    db.close()


def test_sync_health_endpoint(client):
    r = client.get("/api/sync-health")
    assert r.status_code == 200
    body = r.json()
    assert body["sync_enabled"] is False   # tests run on sqlite3
    assert body["healthy"] is True
