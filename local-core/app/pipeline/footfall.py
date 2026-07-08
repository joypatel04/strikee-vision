"""Footfall counting by directional line-crossing.

A person is tracked frame-to-frame (a temporary id that lasts while they're on
screen — no face/identity needed). When a track's path crosses a **counting
line** we count a directional passage: `in` or `out`. Footfall = `in` crossings;
occupancy = running (in − out), which self-corrects when someone steps out and
returns.

This is deliberately a *trend* tool: it counts passages accurately (given a
person is detected), but it cannot know a re-entering regular is the same person
without re-identification — so treat the daily number as a consistent proxy, not
an exact headcount. See FIELD-TEST.md.

Everything here is pure geometry + state — no cv2/torch — so it's fully testable
with a FakeTracker. The real ByteTrack tracker lives in tracking.py.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Protocol

Point = tuple[float, float]


# --- geometry ---------------------------------------------------------------

def _orient(a: Point, b: Point, c: Point) -> float:
    """Signed area sign of triangle a,b,c: >0 c is left of a→b, <0 right."""
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _segments_cross(p1: Point, p2: Point, p3: Point, p4: Point) -> bool:
    """True if segment p1→p2 strictly crosses segment p3→p4."""
    d1 = _orient(p3, p4, p1)
    d2 = _orient(p3, p4, p2)
    d3 = _orient(p1, p2, p3)
    d4 = _orient(p1, p2, p4)
    return (d1 > 0) != (d2 > 0) and (d3 > 0) != (d4 > 0)


# --- tracks -----------------------------------------------------------------

@dataclass
class Track:
    """One tracked person this frame."""
    id: int
    bbox: tuple[float, float, float, float]   # x1,y1,x2,y2

    @property
    def ground(self) -> Point:
        """Feet point (bottom-centre) — the position that crosses a floor line."""
        x1, y1, x2, y2 = self.bbox
        return ((x1 + x2) / 2.0, y2)


class Tracker(Protocol):
    def update(self, frame) -> list[Track]:
        ...


class FakeTracker:
    """Scripted tracker for tests: feed a list of per-frame Track lists."""

    def __init__(self, script: list[list[Track]]):
        self._script = list(script)
        self._i = 0

    def update(self, frame) -> list[Track]:
        if self._i < len(self._script):
            out = self._script[self._i]
            self._i += 1
            return out
        return []


# --- one counting line ------------------------------------------------------

@dataclass
class CountingLine:
    """A doorway tripwire. `a`,`b` are the segment endpoints. A track moving
    from the RIGHT side of a→b to the LEFT counts as `in` (flip=True swaps),
    so orient the segment so 'inside' is on the left of a→b (or set flip)."""
    name: str
    a: Point
    b: Point
    flip: bool = False


class LineCounter:
    """Counts directional crossings of one line, with a per-track cooldown so a
    person loitering on the line (detector jitter) isn't counted repeatedly."""

    def __init__(self, line: CountingLine, cooldown_frames: int = 8):
        self.line = line
        self.cooldown_frames = cooldown_frames
        self.in_count = 0
        self.out_count = 0
        self._last_cross: dict[int, int] = {}   # track_id -> frame index

    def check(self, track_id: int, prev: Point, cur: Point, frame: int) -> Optional[str]:
        last = self._last_cross.get(track_id)
        if last is not None and frame - last < self.cooldown_frames:
            return None
        if not _segments_cross(prev, cur, self.line.a, self.line.b):
            return None
        # side of the PREVIOUS point decides direction of travel
        side = _orient(self.line.a, self.line.b, prev)
        direction = "in" if side > 0 else "out"
        if self.line.flip:
            direction = "out" if direction == "in" else "in"
        if direction == "in":
            self.in_count += 1
        else:
            self.out_count += 1
        self._last_cross[track_id] = frame
        return direction

    @property
    def occupancy(self) -> int:
        return self.in_count - self.out_count


# --- the engine -------------------------------------------------------------

@dataclass
class Crossing:
    line: str
    track_id: int
    direction: str      # "in" | "out"
    ts: str


class FootfallCounter:
    """Runs a tracker over frames and counts crossings of one or more lines.
    Keeps per-line totals + occupancy and hourly buckets for daily reporting."""

    def __init__(self, lines: list[CountingLine], tracker: Tracker,
                 cooldown_frames: int = 8, forget_frames: int = 30,
                 roi_bbox: Optional[tuple[float, float, float, float]] = None):
        self.counters = {ln.name: LineCounter(ln, cooldown_frames) for ln in lines}
        self.tracker = tracker
        self.forget_frames = forget_frames
        # only count people whose FEET fall inside this box — used to ignore the
        # dead centre/right of the ch7 frame (pillar, elevator door, window).
        self.roi_bbox = roi_bbox
        self._frame = 0
        self._last_pos: dict[int, Point] = {}
        self._last_seen: dict[int, int] = {}
        # hourly buckets: {(line, "YYYY-MM-DDTHH"): {"in": n, "out": n}}
        self.hourly: dict[tuple[str, str], dict[str, int]] = {}

    def _in_roi(self, ground: Point) -> bool:
        if self.roi_bbox is None:
            return True
        x1, y1, x2, y2 = self.roi_bbox
        return x1 <= ground[0] <= x2 and y1 <= ground[1] <= y2

    def process(self, frame, ts: str) -> list[Crossing]:
        self._frame += 1
        crossings: list[Crossing] = []
        tracks = [t for t in self.tracker.update(frame) if self._in_roi(t.ground)]
        seen: set[int] = set()

        for t in tracks:
            seen.add(t.id)
            cur = t.ground
            prev = self._last_pos.get(t.id)
            self._last_pos[t.id] = cur
            self._last_seen[t.id] = self._frame
            if prev is None:
                continue
            for counter in self.counters.values():
                direction = counter.check(t.id, prev, cur, self._frame)
                if direction:
                    crossings.append(Crossing(counter.line.name, t.id, direction, ts))
                    self._bucket(counter.line.name, direction, ts)

        self._forget(seen)
        return crossings

    def _bucket(self, line: str, direction: str, ts: str) -> None:
        hour = ts[:13]                       # "YYYY-MM-DDTHH"
        key = (line, hour)
        b = self.hourly.setdefault(key, {"in": 0, "out": 0})
        b[direction] += 1

    def _forget(self, seen: set[int]) -> None:
        """Drop tracks not seen for a while so ids/positions don't leak."""
        stale = [tid for tid, f in self._last_seen.items()
                 if tid not in seen and self._frame - f > self.forget_frames]
        for tid in stale:
            self._last_pos.pop(tid, None)
            self._last_seen.pop(tid, None)

    # --- reporting ---------------------------------------------------------

    def totals(self) -> dict:
        return {name: {"in": c.in_count, "out": c.out_count, "occupancy": c.occupancy}
                for name, c in self.counters.items()}

    def daily(self, line: str, date: str) -> dict:
        """Sum a line's crossings for a date ('YYYY-MM-DD')."""
        ins = outs = 0
        for (ln, hour), b in self.hourly.items():
            if ln == line and hour.startswith(date):
                ins += b["in"]
                outs += b["out"]
        return {"date": date, "line": line, "in": ins, "out": outs}

    def hourly_series(self, line: str, date: str) -> list[dict]:
        """Per-hour in/out for a date, sorted by hour."""
        rows = [{"hour": hour, **b} for (ln, hour), b in self.hourly.items()
                if ln == line and hour.startswith(date)]
        return sorted(rows, key=lambda r: r["hour"])
