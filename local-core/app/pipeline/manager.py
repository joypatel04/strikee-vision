"""RuntimeManager: owns per-venue LiveRuntime instances and their async tick
loops, and broadcasts changed state over the Broadcaster.

The real pipeline (YOLO + OpenCV) is built lazily and only when a venue's
pipeline is started, so importing this module never pulls heavy deps.
"""
from __future__ import annotations

import asyncio
import os
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

    def get(self, venue_id: str) -> Optional[LiveRuntime]:
        return self._runtimes.get(venue_id)

    def is_running(self, venue_id: str) -> bool:
        return venue_id in self._tasks

    def status(self, venue_id: str) -> dict:
        rt = self._runtimes.get(venue_id)
        return {
            "venue_id": venue_id,
            "running": self.is_running(venue_id),
            "assets": len(rt.assets) if rt else 0,
            "sources": len(rt.sources) if rt else 0,
            "viewers": self._bcast.count(venue_id),
            "interval_sec": self._interval,
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
            from .capture import OpenCVFrameSource
            from .observe import PERSON_KINDS, SNOOKER_KIND
            from .perception import SnookerDetector, YOLODetector
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
        engine = StateEngine(
            enter_ticks=int(os.environ.get("STRIKEE_ENTER_TICKS", "2")),
            exit_ticks=int(os.environ.get("STRIKEE_EXIT_TICKS", "3")),
            activity_still_ticks=int(os.environ.get("STRIKEE_STILL_TICKS", "3")),
        )
        motion = float(os.environ.get("STRIKEE_MOTION_THRESHOLD", "8.0"))
        person_model = os.environ.get("STRIKEE_PERSON_MODEL", self._model)
        snooker_model = os.environ.get("STRIKEE_SNOOKER_MODEL", "best.pt")
        kinds = self._venue_sensor_kinds(venue_id)

        def _build():
            person = YOLODetector(person_model) if (kinds & PERSON_KINDS) else None
            snooker = SnookerDetector(snooker_model) if (SNOOKER_KIND in kinds) else None
            return build_live_runtime(
                self._db, venue_id, person,
                source_factory=lambda s: OpenCVFrameSource(s.id, s.uri),
                engine=engine, sink=sink, sampler=sampler, motion_threshold=motion,
                snooker_detector=snooker,
            )

        rt = await asyncio.to_thread(_build)
        self.run_runtime(venue_id, rt)
        return self.status(venue_id)

    def run_runtime(self, venue_id: str, runtime: LiveRuntime) -> None:
        """Register a runtime and spawn its tick loop (used by start() and tests)."""
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
        rt = self._runtimes.pop(venue_id, None)
        if rt:
            rt.release()
        return {"venue_id": venue_id, "running": False}

    async def stop_all(self) -> None:
        for venue_id in list(self._tasks.keys()):
            await self.stop(venue_id)
