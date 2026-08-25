"""Capture scheduler — runs many cameras through a small, fixed budget of
concurrent connections without ever exceeding it.

The DVR only tolerates a few simultaneous main-stream connections (measured
K=3 on the club's Dahua). But each camera needs a *different* sampling rate:
entry/footfall cameras every ~3s, gaming-zone cameras every ~5s, snooker
tables every ~12-15s. So we can't hold one persistent connection per camera.

`CaptureSchedule` is the pure policy: given each source's target interval and a
concurrency cap K, it decides *which source to grab next*, always picking the
most-overdue one and never letting more than K be in flight at once. It is
clock-injectable and has no threads, so it is deterministically testable.

`ThreadedCapturePool` is the thin runtime around it: K worker threads that each
claim the next due source, grab one frame (a short-lived open→read→close, so at
most K connections are ever open), and hand it to a processing callback.
"""
from __future__ import annotations

import threading
import time
from typing import Callable, Optional

# sensor kinds → capture priority. Snooker tables sample slowly (a game is a
# slow signal); footfall/entry cameras fast (people cross in seconds); other
# people cameras (gaming zone) in between. See the measured K=3 budget: at
# ~1.7s/grab, 3 lanes ≈ 106 grabs/min, and entries 3s + gaming 5s + tables
# 12-15s fits inside it.
_SNOOKER_KIND = "snooker_game"
_ENTRY_KINDS = {"footfall", "entry"}
_PERSON_KINDS = {"occupancy", "presence", "person"}


def source_intervals(
    sources, table: float = 13.0, gaming: float = 5.0, entry: float = 3.0,
    default: float = 5.0,
) -> dict[str, float]:
    """Map each source (with a uri) to its target grab interval by sensor kind.
    Sources with no uri can't be grabbed and are skipped."""
    out: dict[str, float] = {}
    for src in sources:
        if not getattr(src, "uri", None):
            continue
        kinds = {s.kind for s in src.sensors}
        if _SNOOKER_KIND in kinds:
            iv = table
        elif kinds & _ENTRY_KINDS:
            iv = entry
        elif kinds & _PERSON_KINDS:
            iv = gaming
        else:
            iv = default
        out[src.id] = iv
    return out


class CaptureSchedule:
    """Decides the next camera to grab, honouring per-source target intervals
    and a hard concurrency cap. Pure and thread-safe; no I/O.

    Intervals are measured from the *start* of each grab, so a source with a
    3s interval is grabbed every 3s (as long as a grab finishes within 3s) —
    not 3s-plus-grab-time. A source already being grabbed is never handed out
    again until it completes.
    """

    def __init__(self, intervals: dict[str, float], max_concurrent: int = 3,
                 clock: Callable[[], float] = time.monotonic,
                 backoff_factor: float = 2.0, max_backoff: float = 120.0):
        if max_concurrent < 1:
            raise ValueError("max_concurrent must be >= 1")
        self._interval = {sid: float(iv) for sid, iv in intervals.items()}
        self._k = max_concurrent
        self._clock = clock
        self._backoff_factor = backoff_factor
        self._max_backoff = max_backoff
        self._started_at: dict[str, Optional[float]] = {sid: None for sid in self._interval}
        self._fails: dict[str, int] = {sid: 0 for sid in self._interval}
        self._inflight: set[str] = set()
        self._lock = threading.Lock()

    @property
    def max_concurrent(self) -> int:
        return self._k

    @property
    def source_ids(self) -> list[str]:
        return list(self._interval)

    def _ready_at(self, sid: str) -> float:
        """When this source may next be grabbed.

        A source that keeps failing is pushed further out each time
        (interval x factor^failures, capped). An unplugged or wedged camera
        otherwise costs a full lane on every rotation - and a dead RTSP host
        blocks for the ffmpeg timeout, tens of seconds, starving the cameras
        that do work. One success clears it back to the normal interval.
        """
        started = self._started_at[sid]
        if started is None:
            return 0.0
        interval = self._interval[sid]
        fails = self._fails.get(sid, 0)
        if fails:
            interval = min(self._max_backoff,
                           interval * (self._backoff_factor ** fails))
        return started + interval

    def due(self, now: Optional[float] = None) -> Optional[str]:
        """Claim the most-overdue idle source that is due, if under the cap.

        Marks it in-flight and stamps its start time. Returns the source id, or
        None if the cap is reached or nothing is due yet. Tie-break: most
        overdue first, then the shortest interval (highest-rate cameras win a
        tie, so entries beat tables when both come due at once).
        """
        if now is None:
            now = self._clock()
        with self._lock:
            if len(self._inflight) >= self._k:
                return None
            best: Optional[str] = None
            best_key = None
            for sid in self._interval:
                if sid in self._inflight:
                    continue
                ready_at = self._ready_at(sid)
                if now + 1e-9 < ready_at:
                    continue  # not due yet
                key = (-(now - ready_at), self._interval[sid], sid)
                if best_key is None or key < best_key:
                    best_key = key
                    best = sid
            if best is not None:
                self._inflight.add(best)
                self._started_at[best] = now
            return best

    def complete(self, sid: str, ok: bool = True, now: Optional[float] = None) -> None:
        """Mark a grab finished, freeing a concurrency slot.

        `ok=False` counts a failure and lengthens this source's next wait; a
        success resets it. Capped at 16 so the exponent can never run away.
        """
        with self._lock:
            self._inflight.discard(sid)
            if sid in self._fails:
                self._fails[sid] = 0 if ok else min(self._fails[sid] + 1, 16)

    def failures(self, sid: str) -> int:
        """Consecutive failed grabs for a source (0 when healthy)."""
        with self._lock:
            return self._fails.get(sid, 0)

    def snapshot(self, now: Optional[float] = None) -> list[dict]:
        """Per-source capture health, for the diagnostics panel: what rate each
        camera is on, whether it is failing, and how long since it was tried."""
        if now is None:
            now = self._clock()
        with self._lock:
            out = []
            for sid, interval in self._interval.items():
                started = self._started_at[sid]
                fails = self._fails.get(sid, 0)
                effective = interval
                if fails:
                    effective = min(self._max_backoff,
                                    interval * (self._backoff_factor ** fails))
                out.append({
                    "source_id": sid,
                    "interval_sec": interval,
                    "effective_interval_sec": round(effective, 1),
                    "consecutive_failures": fails,
                    "in_flight": sid in self._inflight,
                    "last_started_ago_sec": (None if started is None
                                             else round(now - started, 1)),
                })
            return out

    def wait_time(self, now: Optional[float] = None) -> float:
        """Seconds until the next source is due. 0 if something is due now.
        A small floor when the cap is full (we're waiting on a completion, not
        the clock) so callers poll rather than sleep forever."""
        if now is None:
            now = self._clock()
        with self._lock:
            if len(self._inflight) >= self._k:
                return 0.05
            waits = [max(0.0, self._ready_at(sid) - now)
                     for sid in self._interval if sid not in self._inflight]
            if not waits:
                return 0.5
            return min(waits)


class ThreadedCapturePool:
    """Runs a CaptureSchedule with K worker threads.

    Each worker claims the next due source, grabs one frame via `grab(uri)`
    (expected to open→read→close, so only one connection per worker exists at a
    time → at most K open across the pool), then calls `on_frame(source_id, ok,
    frame)`. Detection/processing inside `on_frame` is serialised behind a lock
    by default (grabs stay concurrent, but only one frame is processed at a
    time — safer for the model and cheaper than the grabs anyway).
    """

    def __init__(
        self,
        schedule: CaptureSchedule,
        uris: dict[str, str],
        grab: Callable[[str], tuple[bool, object]],
        on_frame: Callable[[str, bool, object], None],
        serialize_processing: bool = True,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        budget: Optional["threading.BoundedSemaphore"] = None,
    ):
        self._budget = budget
        self._schedule = schedule
        self._uris = uris
        self._grab = grab
        self._on_frame = on_frame
        self._proc_lock = threading.Lock() if serialize_processing else None
        self._clock = clock
        self._sleep = sleep
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []

    def start(self) -> None:
        if self._threads:
            return
        for i in range(self._schedule.max_concurrent):
            t = threading.Thread(target=self._worker, name=f"capture-{i}", daemon=True)
            t.start()
            self._threads.append(t)

    def _worker(self) -> None:
        while not self._stop.is_set():
            # The budget, when shared, is what actually caps DVR connections
            # across every running venue - each pool's own K only caps itself.
            # Taken before claiming a source and released the moment the grab
            # ends, so it is never held across the (much longer) processing.
            if self._budget is not None and not self._budget.acquire(timeout=0.2):
                continue
            sid = self._schedule.due()
            if sid is None:
                if self._budget is not None:
                    self._budget.release()
                self._sleep(min(0.5, max(0.02, self._schedule.wait_time())))
                continue
            ok, frame = False, None
            try:
                ok, frame = self._grab(self._uris.get(sid))
            except Exception:
                ok, frame = False, None
            finally:
                # A failed grab is normal: the camera is skipped, its slot is
                # freed, and it comes round again (later each time it fails).
                self._schedule.complete(sid, ok=ok)
                if self._budget is not None:
                    self._budget.release()
            if self._stop.is_set():
                break
            try:
                if self._proc_lock is not None:
                    with self._proc_lock:
                        self._on_frame(sid, ok, frame)
                else:
                    self._on_frame(sid, ok, frame)
            except Exception:
                pass  # one bad frame must never kill a worker

    def status(self) -> list[dict]:
        """Per-source capture health from the underlying schedule."""
        return self._schedule.snapshot()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        for t in self._threads:
            t.join(timeout=timeout)
        self._threads = []
