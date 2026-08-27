"""Which network is down.

The box is on two networks that fail independently, and from inside the app
both failures look like "grabs stopped". Telling someone the cameras are
failing when a dongle fell off the extender sends them to the wrong room.
"""
import pytest

from app import netcheck, watchdog


class FakeDB:
    def __init__(self, uris=("rtsp://admin:p@192.168.0.108:554/cam?channel=1",)):
        self._uris = list(uris)

    def cursor(self):
        rows = [(u,) for u in self._uris]

        class Cur:
            def __enter__(self_): return self_
            def __exit__(self_, *a): return False
            def execute(self_, *a): pass
            def fetchall(self_): return rows
        return Cur()

    def sync_status(self):
        return {"sync_enabled": False, "healthy": True}


class RT:
    def running_venues(self): return []
    def capture_status(self, v): return []


def test_camera_hosts_are_read_from_the_configured_urls():
    hosts = netcheck.camera_hosts(FakeDB())
    assert hosts == [("192.168.0.108", 554)]


def test_default_rtsp_port_is_assumed():
    hosts = netcheck.camera_hosts(FakeDB(["rtsp://192.168.0.108/stream"]))
    assert hosts == [("192.168.0.108", 554)]


def test_duplicate_hosts_are_collapsed():
    db = FakeDB([f"rtsp://192.168.0.108:554/cam?channel={c}" for c in (1, 4, 6)])
    assert netcheck.camera_hosts(db) == [("192.168.0.108", 554)]


def test_unparseable_urls_are_skipped():
    assert netcheck.camera_hosts(FakeDB(["not a url", ""])) == []


def _faults(monkeypatch, *, cameras_ok, internet_ok, configured=1):
    monkeypatch.setattr(netcheck, "check", lambda db, timeout=3.0: {
        "cameras_configured": configured,
        "cameras_reachable": configured if cameras_ok else 0,
        "camera_hosts": [{"host": "192.168.0.108", "port": 554,
                          "reachable": cameras_ok}],
        "internet": internet_ok,
    })
    return {f["key"]: f for f in watchdog.check(FakeDB(), RT())}


def test_cameras_down_with_internet_up_blames_the_camera_adapter(monkeypatch):
    """The case that actually happens: the box is online, so it is not 'the
    internet is down' - it is the dongle on the extender."""
    faults = _faults(monkeypatch, cameras_ok=False, internet_ok=True)
    assert "camera-network-down" in faults
    f = faults["camera-network-down"]
    assert f["severity"] == "critical"
    assert "does have internet" in f["detail"]
    assert "extender" in f["action"] and "192.168.0.x" in f["action"]


def test_both_down_is_one_fault_not_two(monkeypatch):
    faults = _faults(monkeypatch, cameras_ok=False, internet_ok=False)
    assert "all-networks-down" in faults
    assert "camera-network-down" not in faults


def test_internet_only_down_is_a_warning_and_says_nothing_is_lost(monkeypatch):
    faults = _faults(monkeypatch, cameras_ok=True, internet_ok=False)
    assert "internet-down" in faults
    f = faults["internet-down"]
    assert f["severity"] == "warning"
    assert "nothing is\nlost" in f["detail"] or "nothing is lost" in f["detail"].replace("\n", " ")


def test_all_well_reports_no_network_fault(monkeypatch):
    faults = _faults(monkeypatch, cameras_ok=True, internet_ok=True)
    assert not {"camera-network-down", "internet-down", "all-networks-down"} & set(faults)


def test_a_stalled_sync_is_not_also_reported_when_the_internet_is_down(monkeypatch):
    """Two alarms for one cause trains people to ignore alarms."""
    monkeypatch.setattr(netcheck, "check", lambda db, timeout=3.0: {
        "cameras_configured": 1, "cameras_reachable": 1,
        "camera_hosts": [], "internet": False})
    stalled = lambda: {"sync_enabled": True, "healthy": False,
                       "seconds_since_sync": 900}
    keys = {f["key"] for f in watchdog.check(FakeDB(), RT(), sync_status=stalled)}
    assert "internet-down" in keys
    assert "sync-stalled" not in keys


def test_camera_failures_are_not_also_reported_when_the_network_is_down(monkeypatch):
    monkeypatch.setattr(netcheck, "check", lambda db, timeout=3.0: {
        "cameras_configured": 1, "cameras_reachable": 0,
        "camera_hosts": [{"host": "h", "port": 554, "reachable": False}],
        "internet": True})

    class Running:
        def running_venues(self): return ["v1"]
        def capture_status(self, v):
            return [{"source_id": "a", "consecutive_failures": 9}]

    keys = {f["key"].split(":")[0] for f in watchdog.check(FakeDB(), Running())}
    assert "camera-network-down" in keys
    assert "dvr-unreachable" not in keys and "cameras-down" not in keys


def test_reachable_never_raises():
    assert netcheck.reachable("192.0.2.1", 9, timeout=0.2) is False
    assert netcheck.reachable("not a host at all", 554, timeout=0.2) is False
