"""Footfall line-crossing logic: direction, no-false-counts, cooldown, two
lines, occupancy, and hourly/daily aggregation. Pure geometry — FakeTracker."""
from app.pipeline.footfall import (
    CountingLine, FootfallCounter, FakeTracker, Track,
)


def _person(tid, x, y, w=20, h=40):
    """A person whose FEET (bottom-centre) are at (x, y)."""
    return Track(id=tid, bbox=(x - w / 2, y - h, x + w / 2, y))


# A vertical line at x=100 spanning y 0..200. Left side (x<100) is 'outside',
# right side (x>100) is 'inside'. Moving left→right should read as 'in'.
def _vline(flip=False):
    return CountingLine(name="door", a=(100, 0), b=(100, 200), flip=flip)


def _run(script, lines):
    fc = FootfallCounter(lines, FakeTracker(script), cooldown_frames=3)
    all_cross = []
    for i, _ in enumerate(script):
        all_cross += fc.process("FRAME", ts=f"2026-07-08T20:{i:02d}:00")
    return fc, all_cross


def test_crossing_left_to_right_counts_in():
    # feet walk from x=80 to x=120 across the x=100 line
    script = [[_person(1, 80, 100)], [_person(1, 120, 100)]]
    fc, cross = _run(script, [_vline()])
    assert len(cross) == 1
    assert cross[0].direction == "in"
    assert fc.totals()["door"] == {"in": 1, "out": 0, "occupancy": 1}


def test_crossing_right_to_left_counts_out():
    script = [[_person(1, 120, 100)], [_person(1, 80, 100)]]
    fc, cross = _run(script, [_vline()])
    assert cross[0].direction == "out"
    assert fc.totals()["door"]["occupancy"] == -1


def test_flip_reverses_direction():
    script = [[_person(1, 80, 100)], [_person(1, 120, 100)]]
    fc, cross = _run(script, [_vline(flip=True)])
    assert cross[0].direction == "out"


def test_walking_parallel_does_not_count():
    # stays on the left, never crosses the segment
    script = [[_person(1, 60, 100)], [_person(1, 70, 100)], [_person(1, 60, 100)]]
    _, cross = _run(script, [_vline()])
    assert cross == []


def test_passing_beyond_segment_extent_does_not_count():
    # crosses x=100 but far BELOW the segment (y=400, segment ends at y=200)
    script = [[_person(1, 80, 400)], [_person(1, 120, 400)]]
    _, cross = _run(script, [_vline()])
    assert cross == []


def test_cooldown_prevents_double_count_on_jitter():
    # jitters back and forth across the line on consecutive frames
    script = [[_person(1, 98, 100)], [_person(1, 102, 100)],
              [_person(1, 98, 100)], [_person(1, 102, 100)]]
    fc, cross = _run(script, [_vline()])
    # cooldown_frames=3 suppresses the immediate re-crosses -> at most one count
    assert len(cross) == 1


def test_two_people_two_counts():
    script = [
        [_person(1, 80, 90), _person(2, 80, 120)],
        [_person(1, 120, 90), _person(2, 120, 120)],
    ]
    fc, cross = _run(script, [_vline()])
    assert fc.totals()["door"]["in"] == 2


def test_two_lines_one_camera():
    # a club-entrance line (x=100) and a gaming line (x=300)
    club = CountingLine("club", (100, 0), (100, 200))
    gaming = CountingLine("gaming", (300, 0), (300, 200))
    # person enters the club (crosses x=100), then enters gaming (crosses x=300)
    script = [[_person(1, 80, 100)], [_person(1, 120, 100)],
              [_person(1, 280, 100)], [_person(1, 320, 100)]]
    fc, _ = _run(script, [club, gaming])
    assert fc.totals()["club"]["in"] == 1
    assert fc.totals()["gaming"]["in"] == 1


def test_daily_and_hourly_aggregation():
    fc = FootfallCounter([_vline()], FakeTracker([
        [_person(1, 80, 100)], [_person(1, 120, 100)],     # in @ 20:00
        [_person(2, 80, 100)], [_person(2, 120, 100)],     # in @ 20:00
    ]), cooldown_frames=3)
    for i in range(4):
        fc.process("F", ts=f"2026-07-08T20:0{i}:00")
    day = fc.daily("door", "2026-07-08")
    assert day["in"] == 2 and day["out"] == 0
    series = fc.hourly_series("door", "2026-07-08")
    assert series[0]["hour"] == "2026-07-08T20" and series[0]["in"] == 2


def test_occupancy_returns_to_zero_when_everyone_leaves():
    # in, dwell inside past the jitter-cooldown, then out -> occupancy 0
    # (the self-correcting number for someone who steps out and is gone)
    script = [[_person(1, 80, 100)], [_person(1, 120, 100)],    # in
              [_person(1, 120, 100)], [_person(1, 120, 100)],
              [_person(1, 120, 100)],                            # dwell inside
              [_person(1, 80, 100)]]                             # out
    fc, cross = _run(script, [_vline()])
    assert [c.direction for c in cross] == ["in", "out"]
    assert fc.totals()["door"]["occupancy"] == 0
