"""Tests for the capture scheduler: the pure scheduling policy (deterministic,
fake clock) and a light threaded-pool integration."""
import threading
import time

import pytest

from app.pipeline.scheduler import (
    CaptureSchedule, ThreadedCapturePool, source_intervals,
)
from app.pipeline.types import SensorRuntime, SourceRuntime


def _src(sid, kind, uri="rtsp://x"):
    return SourceRuntime(id=sid, name=sid, uri=uri,
                         sensors=[SensorRuntime(id=sid + "s", asset_id="a",
                                                source_id=sid, kind=kind)])


def test_source_intervals_by_kind():
    sources = [
        _src("table", "snooker_game"),
        _src("gaming", "occupancy"),
        _src("entry", "footfall"),
        _src("nouri", "occupancy", uri=None),   # not grabbable
    ]
    iv = source_intervals(sources, table=13, gaming=5, entry=3)
    assert iv == {"table": 13, "gaming": 5, "entry": 3}   # no-uri skipped


class FakeClock:
    def __init__(self, t=0.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


def test_cap_never_exceeded():
    clk = FakeClock()
    sch = CaptureSchedule({"a": 3, "b": 5, "c": 12, "d": 3}, max_concurrent=3, clock=clk)
    # everything is due at t=0; we can claim exactly K then no more
    claimed = [sch.due() for _ in range(5)]
    got = [c for c in claimed if c is not None]
    assert len(got) == 3                 # cap = 3
    assert claimed[3] is None and claimed[4] is None
    # freeing one slot lets exactly one more through
    sch.complete(got[0])
    assert sch.due() is not None
    assert sch.due() is None


def test_tiebreak_prefers_highest_rate():
    """When several are equally overdue, the shortest interval wins (entries
    before gaming before tables)."""
    clk = FakeClock()
    sch = CaptureSchedule({"table": 13, "gaming": 5, "entry": 3},
                          max_concurrent=1, clock=clk)
    assert sch.due() == "entry"          # shortest interval
    sch.complete("entry")
    assert sch.due() == "gaming"
    sch.complete("gaming")
    assert sch.due() == "table"


def test_interval_is_honoured():
    clk = FakeClock()
    sch = CaptureSchedule({"a": 3.0}, max_concurrent=1, clock=clk)
    assert sch.due() == "a"              # due at t=0
    sch.complete("a")
    assert sch.due() is None             # not due again immediately
    clk.advance(2.9)
    assert sch.due() is None             # still inside the 3s window
    clk.advance(0.2)                     # t=3.1
    assert sch.due() == "a"              # due again


def test_interval_measured_from_start_not_completion():
    """A grab that takes ~2s should not push the next grab to interval+2s."""
    clk = FakeClock()
    sch = CaptureSchedule({"a": 3.0}, max_concurrent=1, clock=clk)
    assert sch.due() == "a"              # claimed at t=0, start stamped now
    clk.advance(2.0)                     # grab took 2s
    sch.complete("a", now=clk())
    clk.advance(1.05)                    # t=3.05, 3s since START
    assert sch.due() == "a"              # due 3s after start, not 5s


def test_most_overdue_wins_when_both_due():
    clk = FakeClock()
    sch = CaptureSchedule({"a": 3.0, "b": 3.0}, max_concurrent=1, clock=clk)
    # grab a at t=0, b at t=1
    assert sch.due() == "a"; sch.complete("a")
    clk.advance(1.0)
    assert sch.due() == "b"; sch.complete("b")
    # at t=4.5: a was last started t=0 (overdue 1.5), b at t=1 (overdue 0.5)
    clk.advance(3.5)
    assert sch.due() == "a"              # a is more overdue


def test_wait_time():
    clk = FakeClock()
    sch = CaptureSchedule({"a": 3.0, "b": 10.0}, max_concurrent=2, clock=clk)
    assert sch.wait_time() == 0.0        # both due now
    sch.due(); sch.due()                 # claim both
    sch.complete("a"); sch.complete("b")
    clk.advance(1.0)                     # t=1: a due at 3 (in 2s), b at 10 (in 9s)
    assert sch.wait_time() == pytest.approx(2.0)


def test_threaded_pool_grabs_and_processes():
    """Real threads, fake grab: high-rate source gets grabbed clearly more
    often than the low-rate one, and the concurrency cap holds."""
    sch = CaptureSchedule({"fast": 0.01, "slow": 0.20}, max_concurrent=2)
    counts = {"fast": 0, "slow": 0}
    live = {"n": 0, "max": 0}
    lock = threading.Lock()

    def grab(uri):
        with lock:
            live["n"] += 1
            live["max"] = max(live["max"], live["n"])
        time.sleep(0.005)
        with lock:
            live["n"] -= 1
        return True, "FRAME"

    def on_frame(sid, ok, frame):
        counts[sid] += 1

    pool = ThreadedCapturePool(sch, {"fast": "u1", "slow": "u2"}, grab, on_frame)
    pool.start()
    time.sleep(0.6)
    pool.stop()

    assert counts["fast"] > counts["slow"]        # higher rate → more grabs
    assert counts["slow"] >= 1                     # low-rate still serviced
    assert live["max"] <= 2                        # never exceeded the cap


def test_threaded_pool_survives_grab_errors():
    sch = CaptureSchedule({"a": 0.01}, max_concurrent=1)
    seen = {"n": 0}

    def grab(uri):
        seen["n"] += 1
        raise RuntimeError("boom")

    def on_frame(sid, ok, frame):
        assert ok is False                         # errors surface as not-ok

    pool = ThreadedCapturePool(sch, {"a": "u"}, grab, on_frame)
    pool.start()
    time.sleep(0.1)
    pool.stop()
    assert seen["n"] >= 2                           # kept going after the error


# --- the scheduled per-source path drives the real runtime ------------------

def _snooker_runtime(script, db):
    from app.store import EventStore, SessionStore
    from app.pipeline.perception import FakeDetector
    from app.pipeline.runtime import LiveRuntime
    from app.pipeline.sink import DbStateSink
    from app.pipeline.state import StateEngine
    from app.pipeline.types import AssetRuntime, SensorRuntime, SourceRuntime

    sensor = SensorRuntime(id="s1", asset_id="a1", source_id="src1",
                           kind="snooker_game", conf_threshold=0.25,
                           zone_polygons=[[[0, 0], [400, 0], [400, 400], [0, 400]]])
    asset = AssetRuntime(id="a1", name="Table 1", business_unit_id="snooker",
                         sensors=[sensor])
    source = SourceRuntime(id="src1", name="Cam", uri="rtsp://x", sensors=[sensor])
    sink = DbStateSink(EventStore(db), SessionStore(db))
    rt = LiveRuntime("v1", [asset], [source], frame_sources={}, detector=None,
                     engine=StateEngine(enter_ticks=1), sink=sink,
                     snooker_detector=FakeDetector(script))
    return rt, source


def test_process_and_evaluate_detects_game_like_tick():
    """Feeding frames through the scheduler's per-source entry point (not the
    global tick) still counts the game — proving the scheduled path is
    equivalent for the pieces that matter."""
    from app.db import Database
    from app.pipeline.types import Detection
    from app.store import EventStore

    def ball(x, label="red_ball", conf=0.6):
        return Detection(bbox=(x, 100, x + 12, 112), confidence=conf, label=label)

    rack = [ball(50 + i * 8) for i in range(10)]
    rack.append(Detection(bbox=(60, 90, 120, 150), confidence=0.5, label="game_start"))

    db = Database(":memory:")
    rt, source = _snooker_runtime([rack] * 6, db)
    # drive it exactly as the capture pool would: one source at a time
    for _ in range(6):
        rt.process_and_evaluate(source, True, "FRAME")
    starts = [e for e in EventStore(db).list("v1") if e["type"] == "game_start"]
    assert len(starts) == 1
    db.close()


# --------------------------------------------------------------------- backoff


def test_failing_source_backs_off_and_recovers():
    """A wedged camera must not cost a lane every rotation. Each consecutive
    failure doubles its wait; one success clears it."""
    clk = FakeClock()
    sch = CaptureSchedule({"a": 10.0}, max_concurrent=1, clock=clk,
                          backoff_factor=2.0, max_backoff=120.0)

    assert sch.due() == "a"
    sch.complete("a", ok=False)          # 1 failure -> next wait 20s
    assert sch.failures("a") == 1
    clk.advance(10.5)
    assert sch.due() is None, "backed-off source came due at the normal interval"
    clk.advance(10.0)                    # t=20.5
    assert sch.due() == "a"

    sch.complete("a", ok=False)          # 2 failures -> 40s
    assert sch.failures("a") == 2
    clk.advance(20.5)
    assert sch.due() is None
    clk.advance(20.0)
    assert sch.due() == "a"

    sch.complete("a", ok=True)           # recovered -> back to 10s
    assert sch.failures("a") == 0
    clk.advance(10.5)
    assert sch.due() == "a"


def test_backoff_is_capped():
    clk = FakeClock()
    sch = CaptureSchedule({"a": 10.0}, max_concurrent=1, clock=clk,
                          backoff_factor=2.0, max_backoff=30.0)
    for _ in range(8):                   # would be 10 * 2^8 = 2560s uncapped
        sch.due()
        sch.complete("a", ok=False)
        clk.advance(30.1)
    assert sch.due() == "a", "cap not honoured; a dead camera would never retry"


def test_healthy_source_keeps_its_interval_while_another_fails():
    """One dead camera must not slow down the working ones."""
    clk = FakeClock()
    sch = CaptureSchedule({"dead": 5.0, "live": 5.0}, max_concurrent=2, clock=clk)
    assert sch.due() in ("dead", "live")
    assert sch.due() in ("dead", "live")
    sch.complete("dead", ok=False)
    sch.complete("live", ok=True)

    clk.advance(5.1)
    due = [sch.due(), sch.due()]
    assert "live" in due
    assert "dead" not in due


def test_default_complete_still_counts_as_success():
    """Existing callers pass no ok= and must not accrue backoff."""
    sch = CaptureSchedule({"a": 1.0}, max_concurrent=1)
    sch.due()
    sch.complete("a")
    assert sch.failures("a") == 0


# ---------------------------------------------------------------- shared budget


def test_shared_budget_caps_concurrency_across_two_pools():
    """Each pool caps only itself. Two venues at K=2 would open four streams
    against a DVR that drops them at four - so the budget is shared."""
    budget = threading.BoundedSemaphore(2)
    peak = 0
    live = 0
    lock = threading.Lock()

    def grab(uri):
        nonlocal peak, live
        with lock:
            live += 1
            peak = max(peak, live)
        time.sleep(0.02)
        with lock:
            live -= 1
        return True, object()

    pools = []
    for venue in ("v1", "v2"):
        ids = {f"{venue}-{i}": 0.0 for i in range(3)}
        sch = CaptureSchedule(ids, max_concurrent=2)
        pools.append(ThreadedCapturePool(
            sch, {sid: "rtsp://x" for sid in ids}, grab,
            lambda sid, ok, frame: None, budget=budget))

    for p in pools:
        p.start()
    time.sleep(0.5)
    for p in pools:
        p.stop(timeout=2)

    assert peak <= 2, f"shared budget exceeded: {peak} concurrent grabs"
    assert peak >= 1


def test_pool_without_budget_is_unchanged():
    """budget=None keeps the previous behaviour for existing callers."""
    seen = []
    sch = CaptureSchedule({"a": 0.0}, max_concurrent=1)
    pool = ThreadedCapturePool(sch, {"a": "rtsp://x"},
                               lambda uri: (True, "frame"),
                               lambda sid, ok, frame: seen.append((sid, ok)))
    pool.start()
    time.sleep(0.2)
    pool.stop(timeout=2)
    assert seen and all(ok for _, ok in seen)


def test_pool_reports_grab_failure_as_backoff():
    """A grab that raises is skipped, frees its slot, and counts as a failure -
    the camera is simply picked up again on a later rotation."""
    sch = CaptureSchedule({"a": 0.0}, max_concurrent=1)

    def boom(uri):
        raise RuntimeError("stream timeout")

    got = []
    pool = ThreadedCapturePool(sch, {"a": "rtsp://x"}, boom,
                               lambda sid, ok, frame: got.append(ok))
    pool.start()
    time.sleep(0.2)
    pool.stop(timeout=2)

    assert got and got[0] is False, "a failed grab should reach on_frame as ok=False"
    assert sch.failures("a") >= 1, "failure not recorded, so no backoff would apply"
