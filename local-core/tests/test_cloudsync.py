"""Push sync: local SQLite stays authoritative, rows go up over HTTP.

Tested against a fake Hrana endpoint that records every statement, so these
pin down the behaviour that matters when the network is unreliable: no
duplicates, no gaps, resume after failure, and progress even when a whole batch
shares one timestamp.
"""
import json

import pytest

from app.cloudsync import TursoPush, from_env
from app.db import Database
from app.store import EventStore


class FakeRemote:
    """Stands in for Turso. Records statements; can be told to fail."""

    def __init__(self):
        self.statements = []
        self.calls = 0
        self.fail_next = 0
        self.schema_statements = 0

    def pipeline(self, statements):
        self.calls += 1
        if self.fail_next > 0:
            self.fail_next -= 1
            from app.cloudsync import CloudSyncError
            raise CloudSyncError("simulated network failure")
        for s in statements:
            if s["sql"].lstrip().upper().startswith("CREATE"):
                self.schema_statements += 1
            else:
                self.statements.append(s)
        return [{"type": "ok"} for _ in statements]

    def rows_for(self, table):
        return [s for s in self.statements if f"INTO {table} " in s["sql"]]

    def ids_for(self, table):
        out = []
        for s in self.rows_for(table):
            cols = s["sql"].split("(", 1)[1].split(")", 1)[0].split(", ")
            args = s["args"]
            out.append(args[cols.index("id")].get("value"))
        return out


@pytest.fixture
def wired(tmp_path):
    db = Database(str(tmp_path / "strikee.db"))
    remote = FakeRemote()
    push = TursoPush(db, "libsql://fake.turso.io", "token", batch=3)
    push._pipeline = remote.pipeline
    yield db, push, remote
    db.close()


def _events(db, n, venue="v1", ts="2026-08-27T10:00:00+00:00"):
    store = EventStore(db)
    for i in range(n):
        store.append({"venue_id": venue, "type": "state_change", "ts": ts,
                      "origin": "system"})


def test_pushes_rows_and_creates_the_schema(wired):
    db, push, remote = wired
    _events(db, 2)
    result = push.push_once()
    assert result["ok"]
    assert result["tables"]["events"] == 2
    assert remote.schema_statements > 0, "remote schema never created"
    assert len(remote.ids_for("events")) == 2


def test_second_cycle_sends_nothing_new(wired):
    """The cursor must actually advance, or every cycle re-uploads everything."""
    db, push, remote = wired
    _events(db, 3)
    push.push_once()
    before = len(remote.rows_for("events"))
    result = push.push_once()
    assert result["rows"] == 0
    assert len(remote.rows_for("events")) == before


def test_only_new_rows_go_on_the_next_cycle(wired):
    db, push, remote = wired
    _events(db, 2)
    push.push_once()
    _events(db, 1)
    result = push.push_once()
    assert result["tables"]["events"] == 1
    assert len(set(remote.ids_for("events"))) == 3


def test_identical_timestamps_still_make_progress(wired):
    """A tick writes many rows in the same second. With a bare 'newer than T'
    cursor this loops forever on the same batch."""
    db, push, remote = wired
    _events(db, 7, ts="2026-08-27T10:00:00+00:00")     # all identical, batch=3
    result = push.push_once()
    assert result["tables"]["events"] == 7
    assert len(set(remote.ids_for("events"))) == 7


def test_batches_are_paged_until_drained(wired):
    db, push, remote = wired
    _events(db, 10)
    assert push.push_once()["tables"]["events"] == 10
    assert remote.calls > 1, "10 rows at batch=3 should take several requests"


def test_a_failed_cycle_loses_nothing(wired):
    """Local stays authoritative, so a network failure only costs freshness."""
    db, push, remote = wired
    _events(db, 2)
    remote.fail_next = 1
    first = push.push_once()
    assert not first["ok"] and "simulated" in first["error"]

    second = push.push_once()
    assert second["ok"]
    assert len(set(second["tables"].keys())) >= 1
    assert len(set(remote.ids_for("events"))) == 2


def test_upserts_so_a_resend_cannot_duplicate(wired):
    db, push, remote = wired
    _events(db, 1)
    push.push_once()
    stmt = remote.rows_for("events")[0]["sql"]
    assert stmt.startswith("INSERT OR REPLACE"), (
        "a plain INSERT would fail or duplicate when a row is resent")


def test_config_tables_are_pushed_before_history(wired):
    """The remote enforces the same foreign keys, so a child row arriving before
    its parent is rejected."""
    db, push, _ = wired
    names = [t for t, _ in push.tables]
    assert names.index("venues") < names.index("assets")
    assert names.index("assets") < names.index("sensors")
    assert names.index("sensors") < names.index("events")


def test_metric_samples_are_opt_in(tmp_path):
    db = Database(str(tmp_path / "a.db"))
    quiet = TursoPush(db, "libsql://x.turso.io", "t")
    loud = TursoPush(db, "libsql://x.turso.io", "t", include_metrics=True)
    assert "metric_samples" not in [t for t, _ in quiet.tables]
    assert "metric_samples" in [t for t, _ in loud.tables]
    db.close()


def test_status_reports_unhealthy_before_the_first_success(wired):
    _, push, _ = wired
    status = push.status()
    assert status["sync_enabled"] and not status["healthy"]
    assert status["backend"] == "turso-push"


def test_status_becomes_healthy_after_a_push(wired):
    db, push, _ = wired
    _events(db, 1)
    push.push_once()
    status = push.status()
    assert status["healthy"] and status["rows_pushed"] == 1
    assert status["error"] is None


def test_status_carries_the_error_after_a_failure(wired):
    db, push, remote = wired
    _events(db, 1)
    remote.fail_next = 1
    push.push_once()
    status = push.status()
    assert not status["healthy"] and "simulated" in status["error"]


# ------------------------------------------------------------------- wiring


def test_from_env_needs_push_mode(monkeypatch, tmp_path):
    db = Database(str(tmp_path / "b.db"))
    monkeypatch.setenv("TURSO_DATABASE_URL", "libsql://x.turso.io")
    monkeypatch.setenv("TURSO_AUTH_TOKEN", "t")
    monkeypatch.delenv("STRIKEE_SYNC_MODE", raising=False)
    assert from_env(db) is None
    monkeypatch.setenv("STRIKEE_SYNC_MODE", "push")
    assert from_env(db) is not None
    db.close()


def test_push_mode_stops_the_replica_backend(monkeypatch, tmp_path):
    """Both use TURSO_*; push mode must not also open an embedded replica."""
    from app.db import _turso_env
    monkeypatch.setenv("TURSO_DATABASE_URL", "libsql://x.turso.io")
    monkeypatch.setenv("TURSO_AUTH_TOKEN", "t")
    monkeypatch.setenv("STRIKEE_SYNC_MODE", "push")
    assert _turso_env() is None
    monkeypatch.setenv("STRIKEE_SYNC_MODE", "replica")
    assert _turso_env() is not None


def test_watchdog_uses_the_push_status(monkeypatch):
    from app.watchdog import check

    class RT:
        def running_venues(self): return ["v1"]
        def capture_status(self, v): return [{"source_id": "a", "consecutive_failures": 0}]

    class DB:
        def sync_status(self): return {"sync_enabled": False, "healthy": True}

    stalled = lambda: {"sync_enabled": True, "healthy": False, "seconds_since_sync": 600}
    faults = check(DB(), RT(), sync_status=stalled)
    assert any(f["key"] == "sync-stalled" for f in faults)


# --------------------------------------------- the two silent-loss regressions


def test_same_second_inserts_all_arrive(wired):
    """Events get random UUID ids. Several written in the same second sort in an
    order unrelated to arrival, so a (timestamp, id) cursor skips whichever ids
    happen to sort low - losing games with no error anywhere."""
    db, push, remote = wired
    _events(db, 5)
    push.push_once()
    _events(db, 5)          # same second, ids interleave with the first five
    push.push_once()

    ids = remote.ids_for("events")
    assert len(set(ids)) == 10, f"only {len(set(ids))} of 10 events reached the cloud"

    with db.cursor() as cur:
        cur.execute("SELECT id FROM events")
        local = {r[0] for r in cur.fetchall()}
    assert local == set(ids), "local and cloud disagree about which events exist"


def test_session_closed_in_the_same_second_still_syncs(wired):
    """A session opened and closed inside one second keeps its updated_at, so a
    strictly-after cursor never sees the close. That is the row the
    reconciliation app cares about most."""
    from app.store import SessionStore
    db, push, remote = wired
    store = SessionStore(db)
    s = store.open("v1", "table1", None, start_ts="2026-08-27T20:00:00+05:30",
                   confidence=0.9)
    push.push_once()
    store.close(s["id"], end_ts="2026-08-27T21:00:00+05:30")
    push.push_once()

    sent = remote.rows_for("sessions")
    cols = sent[-1]["sql"].split("(", 1)[1].split(")", 1)[0].split(", ")
    end_ts = sent[-1]["args"][cols.index("end_ts")]
    assert end_ts.get("value") == "2026-08-27T21:00:00+05:30", (
        "the closed session never reached the cloud")


def test_a_much_later_edit_still_syncs(wired):
    """Voiding a session days later must sync even though its rowid is long past
    the insert cursor."""
    from app.store import SessionStore
    db, push, remote = wired
    store = SessionStore(db)
    s = store.open("v1", "t1", None, start_ts="2026-08-20T10:00:00+05:30", confidence=0.9)
    push.push_once()
    remote.statements.clear()

    store.set_status(s["id"], "voided")
    push.push_once()

    sent = remote.rows_for("sessions")
    assert sent, "the voided session was never re-sent"
    cols = sent[-1]["sql"].split("(", 1)[1].split(")", 1)[0].split(", ")
    assert sent[-1]["args"][cols.index("status")].get("value") == "voided"


def test_append_only_tables_are_not_swept(wired):
    """events never change after insert, so re-scanning them by timestamp every
    cycle would be pure waste on the busiest table."""
    db, push, remote = wired
    _events(db, 3)
    push.push_once()
    remote.statements.clear()
    push.push_once()
    assert remote.rows_for("events") == []
