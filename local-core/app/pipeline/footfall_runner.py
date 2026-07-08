"""FootfallRunner — the dedicated continuous lane for the entrance camera.

Unlike the tables (grabbed slowly by the rotating scheduler), footfall needs
consecutive frames for tracking, so this holds one persistent connection and
reads at a few fps in its own thread: read → track → count line crossings →
periodically persist the day's totals. Best-effort and self-contained; a bad
frame never kills the loop.

Testable without cameras/threads via `step()` (drive one frame) or with a
FakeFrameSource + a short real run.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Callable, Optional

from .footfall import CountingLine, FootfallCounter, Tracker


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


class FootfallRunner:
    def __init__(
        self,
        source,                       # FrameSource: .read() -> (ok, frame)
        tracker: Tracker,
        lines: list[CountingLine],
        fps: float = 5.0,
        roi_bbox: Optional[tuple] = None,
        on_crossing: Optional[Callable] = None,   # (Crossing) -> None
        persist: Optional[Callable] = None,       # (list[daily-dict]) -> None
        persist_every_sec: float = 30.0,
        clock: Callable[[], str] = _now_iso,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ):
        self.source = source
        self.counter = FootfallCounter(lines, tracker, roi_bbox=roi_bbox)
        self.lines = lines
        self.fps = max(1.0, fps)
        self.on_crossing = on_crossing
        self.persist = persist
        self.persist_every = persist_every_sec
        self._clock = clock
        self._sleep = sleep
        self._monotonic = monotonic
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_persist = 0.0

    # --- one frame (also the test seam) ------------------------------------

    def step(self) -> list:
        ok, frame = self.source.read()
        if not ok or frame is None:
            return []
        crossings = self.counter.process(frame, self._clock())
        if self.on_crossing:
            for c in crossings:
                try:
                    self.on_crossing(c)
                except Exception:
                    pass
        return crossings

    def _maybe_persist(self, now: float, force: bool = False) -> None:
        if not self.persist:
            return
        if not force and now - self._last_persist < self.persist_every:
            return
        self._last_persist = now
        try:
            self.persist(self.daily_rows())
        except Exception:
            pass

    def daily_rows(self) -> list[dict]:
        date = self._clock()[:10]
        return [self.counter.daily(ln.name, date) for ln in self.lines]

    # --- threaded loop -----------------------------------------------------

    def start(self) -> None:
        if self._thread:
            return
        self._thread = threading.Thread(target=self._loop, name="footfall", daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        period = 1.0 / self.fps
        while not self._stop.is_set():
            t0 = self._monotonic()
            try:
                self.step()
            except Exception:
                pass
            self._maybe_persist(t0)
            dt = self._monotonic() - t0
            self._sleep(max(0.0, period - dt))
        self._maybe_persist(self._monotonic(), force=True)   # final flush

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=timeout)
            self._thread = None

    def totals(self) -> dict:
        return self.counter.totals()
