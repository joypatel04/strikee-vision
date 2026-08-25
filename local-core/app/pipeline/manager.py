"""RuntimeManager: owns per-venue LiveRuntime instances and their async tick
loops, and broadcasts changed state over the Broadcaster.

The real pipeline (YOLO + OpenCV) is built lazily and only when a venue's
pipeline is started, so importing this module never pulls heavy deps.
"""
from __future__ import annotations

import asyncio
import os
import threading
from typing import Optional

from ..notify import NotificationEngine
from ..snapshots import SnapshotStore
from ..store import (
    EventStore, MetricStore, NotificationStore, RuleStore, SessionStore,
)
from .broadcast import Broadcaster
from .runtime import LiveRuntime, build_live_runtime
from .sink import DbStateSink
from .state import StateEngine


class PerceptionUnavailable(RuntimeError):
    pass


class RuntimeManager:
    def __init__(self, db, broadcaster: Broadcaster, interval: float = 7.0,
                 model: str = "yolo11n.pt"):
        self._db = db
        self._bcast = broadcaster
        self._interval = interval
        self._model = model
        self._runtimes: dict[str, LiveRuntime] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._pools: dict[str, object] = {}   # venue_id -> ThreadedCapturePool
        self._budget = None                   # process-wide DVR connection cap
        self._budget_k = 0

    def get(self, venue_id: str) -> Optional[LiveRuntime]:
        return self._runtimes.get(venue_id)

    def is_running(self, venue_id: str) -> bool:
        return venue_id in self._tasks or venue_id in self._pools

    def status(self, venue_id: str) -> dict:
        rt = self._runtimes.get(venue_id)
        return {
            "venue_id": venue_id,
            "running": self.is_running(venue_id),
            "assets": len(rt.assets) if rt else 0,
            "sources": len(rt.sources) if rt else 0,
            "viewers": self._bcast.count(venue_id),
            "interval_sec": self._interval,
            "scheduled": venue_id in self._pools,
        }

    def _venue_sensor_kinds(self, venue_id: str) -> set:
        with self._db.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT s.type FROM sensors s JOIN assets a "
                "ON s.asset_id = a.id WHERE a.venue_id = ? AND s.enabled = 1",
                (venue_id,),
            )
            return {r[0] for r in cur.fetchall()}

    async def start(self, venue_id: str) -> dict:
        """Build and run the real detection pipeline for a venue. Loads only the
        models the venue's sensors need (person and/or snooker)."""
        if self.is_running(venue_id):
            return self.status(venue_id)
        try:
            from .capture import OpenCVFrameSource, grab_once
            from .observe import PERSON_KINDS, SNOOKER_KIND
            from .perception import SnookerDetector, YOLODetector
            from .scheduler import (
                CaptureSchedule, ThreadedCapturePool, source_intervals,
            )
        except Exception as exc:  # pragma: no cover - import guard
            raise PerceptionUnavailable(
                "Perception extra not installed. Run: pip install -e '.[perception]'"
            ) from exc

        notifier = NotificationEngine(
            RuleStore(self._db), NotificationStore(self._db), self._bcast)
        snapshots = SnapshotStore(os.environ.get("STRIKEE_SNAPSHOT_DIR", "snapshots"))
        sink = DbStateSink(EventStore(self._db), SessionStore(self._db), notifier,
                           snapshot_store=snapshots)
        sampler = MetricStore(self._db)

        # Field-test tunables via env (no code edit needed at the venue).
        # Prefer the *_SEC windows: they mean the same thing on a table grabbed
        # every 13s and a gaming station grabbed every 5s, where a shared tick
        # count does not. Ticks remain the default so behaviour is unchanged
        # unless a window is set explicitly.
        def _sec(name):
            raw = os.environ.get(name)
            return float(raw) if raw else None

        engine = StateEngine(
            enter_ticks=int(os.environ.get("STRIKEE_ENTER_TICKS", "2")),
            exit_ticks=int(os.environ.get("STRIKEE_EXIT_TICKS", "3")),
            activity_still_ticks=int(os.environ.get("STRIKEE_STILL_TICKS", "3")),
            enter_sec=_sec("STRIKEE_ENTER_SEC"),
            exit_sec=_sec("STRIKEE_EXIT_SEC"),
            still_sec=_sec("STRIKEE_STILL_SEC"),
        )
        motion = float(os.environ.get("STRIKEE_MOTION_THRESHOLD", "8.0"))
        person_model = os.environ.get("STRIKEE_PERSON_MODEL", self._model)
        snooker_model = os.environ.get("STRIKEE_SNOOKER_MODEL", "best.pt")
        min_game = float(os.environ.get("STRIKEE_MIN_GAME_MIN", "0")) * 60.0
        # a pure safety net for a stuck/abandoned game — set well beyond any real
        # frame (2h) so a genuinely long game is never cut short.
        max_game = float(os.environ.get("STRIKEE_MAX_GAME_MIN", "120")) * 60.0
        rack_reds = int(os.environ.get("STRIKEE_RACK_REDS", "8"))
        rerack_jump = int(os.environ.get("STRIKEE_RERACK_JUMP", "6"))
        rerack_low = int(os.environ.get("STRIKEE_RERACK_LOW", "2"))
        rerack_high = int(os.environ.get("STRIKEE_RERACK_HIGH", "7"))
        kinds = self._venue_sensor_kinds(venue_id)

        debug_log = None
        if os.environ.get("STRIKEE_DEBUG"):
            from ..debuglog import DebugLog
            debug_log = DebugLog(os.environ.get("STRIKEE_DEBUG_FILE", f"debug_{venue_id}.csv"))

        # scheduled capture (default): the pool grabs frames within the K-stream
        # budget, so no persistent per-source connection. STRIKEE_SCHEDULER=0
        # falls back to the legacy tick loop (persistent connections — only safe
        # when #cameras <= the DVR's concurrent limit).
        scheduled = os.environ.get("STRIKEE_SCHEDULER", "1") != "0"

        def _build():
            person = YOLODetector(person_model) if (kinds & PERSON_KINDS) else None
            snooker = SnookerDetector(snooker_model) if (SNOOKER_KIND in kinds) else None
            factory = None if scheduled else (lambda s: OpenCVFrameSource(s.id, s.uri))
            return build_live_runtime(
                self._db, venue_id, person,
                source_factory=factory,
                engine=engine, sink=sink, sampler=sampler, motion_threshold=motion,
                snooker_detector=snooker, min_game_sec=min_game, max_game_sec=max_game,
                rack_red_threshold=rack_reds, rerack_jump=rerack_jump,
                rerack_low_band=rerack_low, rerack_high_band=rerack_high,
                debug_log=debug_log,
            )

        rt = await asyncio.to_thread(_build)
        if scheduled:
            self._start_scheduler(venue_id, rt, CaptureSchedule,
                                  ThreadedCapturePool, source_intervals, grab_once)
        else:
            self.run_runtime(venue_id, rt)
        return self.status(venue_id)

    def capture_status(self, venue_id: str) -> list[dict]:
        """Per-camera capture health for a running venue ([] when stopped)."""
        pool = self._pools.get(venue_id)
        if pool is None or not hasattr(pool, "status"):
            return []
        try:
            return pool.status()
        except Exception:
            return []

    def running_venues(self) -> list[str]:
        return list(self._runtimes)

    def runtime_for(self, venue_id: str):
        return self._runtimes.get(venue_id)

    def _stream_budget(self, k: int):
        """One connection budget shared by every running venue.

        Each pool caps only itself, so two venues at K=3 would open six
        simultaneous streams - and this DVR was measured to drop them at four.
        The cap belongs to the DVR, not to a venue, so it lives here and every
        pool draws from it.
        """
        if self._budget is None or self._budget_k != k:
            self._budget = threading.BoundedSemaphore(k)
            self._budget_k = k
        return self._budget

    def _start_scheduler(self, venue_id, rt, CaptureSchedule, ThreadedCapturePool,
                         source_intervals, grab_once) -> None:
        """Run a venue's capture on the K-slot rotating scheduler. Each grabbed
        frame is processed for its source and the changed snapshots are bridged
        back to the async broadcaster."""
        k = int(os.environ.get("STRIKEE_MAX_STREAMS", "3"))
        intervals = source_intervals(
            rt.sources,
            table=float(os.environ.get("STRIKEE_RATE_TABLE", "13")),
            gaming=float(os.environ.get("STRIKEE_RATE_GAMING", "5")),
            entry=float(os.environ.get("STRIKEE_RATE_ENTRY", "3")),
        )
        if not intervals:
            # nothing grabbable (no uris) — register for serving state only
            self.set_runtime(venue_id, rt)
            return
        uris = {s.id: s.uri for s in rt.sources if s.uri and s.id in intervals}
        src_by_id = {s.id: s for s in rt.sources}

        # Tell the state engine how often each asset is actually sampled, so a
        # grace window given in seconds converts correctly per asset. An asset
        # watched by several cameras takes the fastest of them.
        def _interval_for(asset):
            ivs = [intervals[s.source_id] for s in asset.sensors
                   if s.source_id in intervals]
            return min(ivs) if ivs else None

        rt.engine.interval_for = _interval_for
        loop = asyncio.get_running_loop()

        def on_frame(sid, ok, frame):
            src = src_by_id.get(sid)
            if src is None:
                return
            _all, changed = rt.process_and_evaluate(src, ok, frame)
            if changed:
                asyncio.run_coroutine_threadsafe(
                    self._bcast.broadcast(venue_id, changed), loop)

        schedule = CaptureSchedule(intervals, max_concurrent=k)
        pool = ThreadedCapturePool(schedule, uris, grab_once, on_frame,
                                   budget=self._stream_budget(k))
        self._runtimes[venue_id] = rt
        self._pools[venue_id] = pool
        pool.start()

    def run_runtime(self, venue_id: str, runtime: LiveRuntime) -> None:
        """Register a runtime and spawn its tick loop (used by start() and tests)."""
        if getattr(runtime, "engine", None) is not None and \
                getattr(runtime.engine, "interval_for", None) is None:
            # legacy loop: one tick interval for every asset
            runtime.engine.interval_for = lambda asset: self._interval
        self._runtimes[venue_id] = runtime
        self._tasks[venue_id] = asyncio.create_task(self._loop(venue_id))

    def set_runtime(self, venue_id: str, runtime: LiveRuntime) -> None:
        """Register a runtime WITHOUT a loop (for serving current state)."""
        self._runtimes[venue_id] = runtime

    async def _loop(self, venue_id: str) -> None:
        rt = self._runtimes[venue_id]
        try:
            while True:
                _all, changed = await asyncio.to_thread(rt.tick)
                if changed:
                    await self._bcast.broadcast(venue_id, changed)
                await asyncio.sleep(self._interval)
        except asyncio.CancelledError:  # pragma: no cover
            pass

    async def stop(self, venue_id: str) -> dict:
        task = self._tasks.pop(venue_id, None)
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        pool = self._pools.pop(venue_id, None)
        if pool:
            await asyncio.to_thread(pool.stop)
        rt = self._runtimes.pop(venue_id, None)
        if rt:
            rt.release()
        return {"venue_id": venue_id, "running": False}

    async def stop_all(self) -> None:
        for venue_id in list(set(self._tasks) | set(self._pools)):
            await self.stop(venue_id)
