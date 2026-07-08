"""FootfallCounter ROI filtering + FootfallRunner (step, persist, threaded)."""
import time

from app.pipeline.capture import FakeFrameSource
from app.pipeline.footfall import CountingLine, FootfallCounter, FakeTracker, Track
from app.pipeline.footfall_runner import FootfallRunner


def _person(tid, x, y):
    return Track(id=tid, bbox=(x - 10, y - 40, x + 10, y))


def _vline():
    return CountingLine("door", (100, 0), (100, 200))


def test_roi_ignores_people_outside_the_box():
    # same left→right cross, but ROI only covers the left strip (x<=150).
    # A person crossing at x 80->120 is inside; one at x 480->520 is ignored.
    script = [
        [_person(1, 80, 100), _person(2, 480, 100)],
        [_person(1, 120, 100), _person(2, 520, 100)],
    ]
    fc = FootfallCounter([_vline()], FakeTracker(script), cooldown_frames=3,
                         roi_bbox=(0, 0, 150, 300))
    for _ in range(2):
        fc.process("F", ts="2026-07-08T20:00:00")
    # only line at x=100 exists; person 2 is outside ROI anyway. person 1 counts.
    assert fc.totals()["door"]["in"] == 1


class _ClockSeq:
    def __init__(self, times): self._t = list(times); self._i = 0
    def __call__(self):
        v = self._t[min(self._i, len(self._t) - 1)]; self._i += 1
        return v


def test_runner_step_counts_and_reports_crossing():
    script = [[_person(1, 80, 100)], [_person(1, 120, 100)]]
    seen = []
    r = FootfallRunner(
        FakeFrameSource("s", script=[(True, "F"), (True, "F")]),
        FakeTracker(script), [_vline()], fps=5,
        on_crossing=lambda c: seen.append((c.line, c.direction)),
        clock=_ClockSeq(["2026-07-08T20:00:00", "2026-07-08T20:00:01"]),
    )
    r.step()                     # frame 1: person at x=80
    r.step()                     # frame 2: crosses to x=120 -> in
    assert seen == [("door", "in")]
    assert r.totals()["door"]["in"] == 1


def test_runner_persist_receives_daily_rows():
    script = [[_person(1, 80, 100)], [_person(1, 120, 100)]]
    rows = {}
    r = FootfallRunner(
        FakeFrameSource("s", script=[(True, "F"), (True, "F")]),
        FakeTracker(script), [_vline()], fps=5,
        persist=lambda daily: rows.update({d["line"]: d for d in daily}),
        clock=_ClockSeq(["2026-07-08T20:00:00", "2026-07-08T20:00:01"]),
    )
    r.step(); r.step()
    r._maybe_persist(now=1000.0, force=True)
    assert rows["door"]["in"] == 1 and rows["door"]["date"] == "2026-07-08"


def test_runner_threaded_start_stop():
    # a source that always yields frames; a fake tracker that never crosses.
    r = FootfallRunner(
        FakeFrameSource("s"),                      # always (True, token)
        FakeTracker([[] for _ in range(1000)]),    # no people
        [_vline()], fps=50,
    )
    r.start()
    time.sleep(0.15)
    r.stop()
    assert r.totals()["door"]["in"] == 0           # ran cleanly, counted nothing
