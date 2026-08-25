"""Watchdog: the two networks fail independently, and each looks fine from the
other side. These tests pin down what gets reported and, just as important,
what does not."""
import pytest

from app.watchdog import CAMERA_FAILURE_THRESHOLD, Watchdog, check


class FakeRT:
    def __init__(self, cameras=None, venues=("v1",)):
        self._cameras = cameras if cameras is not None else []
        self._venues = list(venues)

    def running_venues(self):
        return list(self._venues)

    def capture_status(self, venue_id):
        return self._cameras


class FakeDB:
    def __init__(self, sync=None):
        self._sync = sync or {"sync_enabled": False, "healthy": True}

    def sync_status(self):
        return self._sync


def _cam(sid, failures=0):
    return {"source_id": sid, "consecutive_failures": failures,
            "interval_sec": 13.0, "effective_interval_sec": 13.0}


def _keys(faults):
    return {f["key"].split(":")[0] for f in faults}


# ------------------------------------------------------------------- cameras


def test_healthy_cameras_raise_nothing():
    faults = check(FakeDB(), FakeRT([_cam("a"), _cam("b")]))
    assert "cameras-down" not in _keys(faults)
    assert "dvr-unreachable" not in _keys(faults)


def test_one_failure_is_not_a_fault():
    """A single miss is normal - the scheduler already backs off."""
    faults = check(FakeDB(), FakeRT([_cam("a", 1), _cam("b")]))
    assert "cameras-down" not in _keys(faults)


def test_some_cameras_down_is_reported_as_partial():
    cams = [_cam("a", CAMERA_FAILURE_THRESHOLD), _cam("b"), _cam("c")]
    faults = check(FakeDB(), FakeRT(cams))
    assert "cameras-down" in _keys(faults)
    fault = next(f for f in faults if f["key"].startswith("cameras-down"))
    assert "1 of 3" in fault["title"]
    assert fault["severity"] == "critical"


def test_all_cameras_down_is_reported_as_a_network_fault():
    """N cameras failing together is one network problem, not N camera problems -
    naming it that way points at the thing to actually fix."""
    cams = [_cam(s, CAMERA_FAILURE_THRESHOLD + 2) for s in "abc"]
    faults = check(FakeDB(), FakeRT(cams))
    assert "dvr-unreachable" in _keys(faults)
    assert "cameras-down" not in _keys(faults)
    fault = next(f for f in faults if f["key"].startswith("dvr-unreachable"))
    assert "extender" in fault["action"]


# ---------------------------------------------------------------- cloud sync


def test_local_only_never_reports_sync_trouble():
    db = FakeDB({"sync_enabled": False, "healthy": True})
    assert "sync-stalled" not in _keys(check(db, FakeRT([_cam("a")])))


def test_stalled_sync_is_a_warning_not_an_error():
    """Nothing is lost when sync stalls - the local replica keeps recording."""
    db = FakeDB({"sync_enabled": True, "healthy": False, "seconds_since_sync": 900})
    faults = check(db, FakeRT([_cam("a")]))
    fault = next(f for f in faults if f["key"] == "sync-stalled")
    assert fault["severity"] == "warning"
    assert "nothing is\nlost" in fault["detail"] or "nothing is lost" in fault["detail"].replace("\n", " ")


def test_healthy_sync_is_quiet():
    db = FakeDB({"sync_enabled": True, "healthy": True, "seconds_since_sync": 4})
    assert "sync-stalled" not in _keys(check(db, FakeRT([_cam("a")])))


# ------------------------------------------------------- nothing running yet


def test_stopped_pipeline_is_only_informational_when_not_unattended(monkeypatch):
    monkeypatch.delenv("STRIKEE_AUTOSTART_VENUE", raising=False)
    faults = check(FakeDB(), FakeRT(venues=()))
    fault = next(f for f in faults if f["key"] == "pipeline-stopped")
    assert fault["severity"] == "info"


def test_stopped_pipeline_is_a_warning_when_autostart_is_configured(monkeypatch):
    monkeypatch.setenv("STRIKEE_AUTOSTART_VENUE", "all")
    faults = check(FakeDB(), FakeRT(venues=()))
    fault = next(f for f in faults if f["key"] == "pipeline-stopped")
    assert fault["severity"] == "warning"


# ------------------------------------------------------------ recording rules


class FakeNotifications:
    def __init__(self):
        self.created = []

    def create(self, n):
        self.created.append(n)
        return n


def test_new_fault_is_recorded_once_then_held_by_cooldown():
    clock = [0.0]
    notes = FakeNotifications()
    cams = [_cam("a", 9)]
    wd = Watchdog(FakeDB(), FakeRT(cams), notes, cooldown_sec=900,
                  clock=lambda: clock[0])

    wd.poll()
    assert len(notes.created) == 1
    clock[0] = 100
    wd.poll()
    assert len(notes.created) == 1, "cooldown not honoured; would spam the log"
    clock[0] = 1000
    wd.poll()
    assert len(notes.created) == 2


def test_clearing_a_fault_rearms_it():
    """A camera that recovers and fails again is genuinely new information."""
    clock = [0.0]
    notes = FakeNotifications()
    rt = FakeRT([_cam("a", 9)])
    wd = Watchdog(FakeDB(), rt, notes, cooldown_sec=900, clock=lambda: clock[0])

    wd.poll()
    assert len(notes.created) == 1
    rt._cameras = [_cam("a", 0)]      # recovered
    clock[0] = 10
    wd.poll()
    rt._cameras = [_cam("a", 9)]      # failed again, still inside the cooldown
    clock[0] = 20
    wd.poll()
    assert len(notes.created) == 2


def test_informational_faults_are_not_written_to_history(monkeypatch):
    monkeypatch.delenv("STRIKEE_AUTOSTART_VENUE", raising=False)
    notes = FakeNotifications()
    wd = Watchdog(FakeDB(), FakeRT(venues=()), notes)
    wd.poll()
    assert notes.created == []


def test_watchdog_survives_a_broken_runtime():
    class Broken:
        def running_venues(self):
            raise RuntimeError("boom")

    wd = Watchdog(FakeDB(), Broken(), FakeNotifications())
    wd.poll()          # must not raise


def test_watchdog_survives_a_broken_notification_store():
    class BadNotes:
        def create(self, n):
            raise RuntimeError("db gone")

    wd = Watchdog(FakeDB(), FakeRT([_cam("a", 9)]), BadNotes())
    assert wd.poll()   # fault still reported even though recording failed


# --------------------------------------------------------------------- route


def test_system_health_route(client):
    r = client.get("/api/system-health")
    assert r.status_code == 200
    assert "faults" in r.json()


def test_dashboard_shows_the_banner(client):
    body = client.get("/").text
    assert 'id="faults"' in body
    assert "/api/system-health" in body
