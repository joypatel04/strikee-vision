"""When a session actually started and ended.

The venue bills by time, so a systematic error here is money. Presence flips
only after the smoothing window has elapsed, which makes the flip time late at
both ends - and by different amounts, since arriving takes a couple of reads
and leaving takes the full grace window. Stamping sessions with the flip time
inflated every duration by roughly the exit window.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.pipeline.state import StateEngine, _shift
from app.pipeline.types import AssetRuntime, RawObservation, SensorRuntime

START = datetime(2026, 8, 28, 20, 0, 0, tzinfo=timezone.utc)


class Clock:
    """Advances a fixed interval per read, like a camera being sampled."""

    def __init__(self, interval):
        self.t = START
        self.interval = interval

    def __call__(self):
        return self.t.isoformat(timespec="seconds")

    def tick(self):
        self.t += timedelta(seconds=self.interval)


def _asset():
    return AssetRuntime(id="a", name="Table", business_unit_id="bu",
                        sensors=[SensorRuntime(id="s", asset_id="a",
                                               source_id="cam", kind="occupancy")])


def _feed(engine, asset, clock, present, reads):
    snap = None
    for _ in range(reads):
        clock.tick()
        snap, _ = engine.update(asset, {"s": RawObservation(present, 0.9)},
                                {"cam": True})
    return snap


def test_shift_moves_a_timestamp_back():
    assert _shift("2026-08-28T20:02:00+00:00", 120) == "2026-08-28T20:00:00+00:00"


def test_shift_leaves_an_unparseable_clock_alone():
    """Tests inject string clocks; tuning must never break state derivation."""
    assert _shift("tick-7", 30) == "tick-7"


def test_arrival_is_backdated_to_the_first_present_read():
    interval = 5.0
    clock = Clock(interval)
    engine = StateEngine(enter_ticks=3, exit_ticks=4, clock=clock,
                         interval_for=lambda a: interval)
    asset = _asset()
    snap = _feed(engine, asset, clock, True, 3)

    assert snap.presence == "present"
    # flipped on the 3rd read; they arrived on the 1st, two intervals earlier
    flip = datetime.fromisoformat(snap.effective_at)
    began = datetime.fromisoformat(snap.presence_since)
    assert (flip - began).total_seconds() == pytest.approx(2 * interval)


def test_departure_is_backdated_by_the_whole_exit_window():
    """This is the one that matters: the grace window is minutes, and without
    backdating every session carries it as phantom occupancy."""
    interval = 5.0
    clock = Clock(interval)
    engine = StateEngine(enter_ticks=1, exit_ticks=24, clock=clock,
                         interval_for=lambda a: interval)
    asset = _asset()
    _feed(engine, asset, clock, True, 2)
    snap = _feed(engine, asset, clock, False, 24)

    assert snap.presence == "absent"
    flip = datetime.fromisoformat(snap.effective_at)
    ended = datetime.fromisoformat(snap.presence_since)
    assert (flip - ended).total_seconds() == pytest.approx(24 * interval)


def test_a_recorded_duration_matches_the_real_one():
    """End to end: sit down, stay 10 minutes, leave. The recorded session should
    be 10 minutes, not 10 plus the grace window."""
    interval = 5.0
    clock = Clock(interval)
    engine = StateEngine(enter_ticks=2, exit_ticks=24, clock=clock,
                         interval_for=lambda a: interval)
    asset = _asset()

    arrived_at = START + timedelta(seconds=interval)      # the first present read
    present_reads = 120                                   # 10 minutes at 5s
    arrival_snap = _feed(engine, asset, clock, True, present_reads)
    began = datetime.fromisoformat(arrival_snap.presence_since)
    left_at = clock.t                                     # last present read
    snap = _feed(engine, asset, clock, False, 24)

    ended = datetime.fromisoformat(snap.presence_since)
    recorded = (ended - began).total_seconds()
    actual = (left_at - arrived_at).total_seconds()
    assert recorded == pytest.approx(actual, abs=interval), (
        f"recorded {recorded}s for a {actual}s visit")



def test_no_interval_configured_falls_back_safely():
    """Without a known sampling rate there is nothing to backdate by, and the
    old behaviour is still correct-ish rather than broken."""
    engine = StateEngine(enter_ticks=2, exit_ticks=2, interval_for=None)
    asset = _asset()
    for _ in range(2):
        snap, _ = engine.update(asset, {"s": RawObservation(True, 0.9)},
                                {"cam": True})
    assert snap.presence == "present"
    assert snap.presence_since == snap.effective_at
