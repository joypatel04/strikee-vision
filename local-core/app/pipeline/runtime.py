"""LiveRuntime: builds the per-venue pipeline from DB config and runs it tick
by tick. The tick is synchronous and fully injectable (fake sources + detector),
so it is testable without cameras or a model.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Callable, Optional

import math

from .observe import observe, PERSON_KINDS, SNOOKER_KIND
from .perception import Detector
from .sink import ChangeEvent, StateSink
from .snooker_game import SnookerGameTracker
from .state import StateEngine
from .types import (
    AssetRuntime, AssetSnapshot, RawObservation, SensorRuntime, SourceRuntime,
    PRESENCE_PRESENT, HEALTH_OK,
)


_NO_OBS = RawObservation(False, 0.0)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _centroid(points: list) -> Optional[tuple]:
    n = len(points)
    if n == 0:
        return None
    return (sum(p[0] for p in points) / n, sum(p[1] for p in points) / n)


def _motion(prev: Optional[list], cur: list, threshold: float) -> bool:
    """Movement between ticks. Needs prior history — the first sighting of a
    person is not counted as motion (we can't measure it yet)."""
    if not cur or prev is None or not prev:
        return False
    if len(cur) != len(prev):
        return True
    cn, cp = _centroid(cur), _centroid(prev)
    return math.hypot(cn[0] - cp[0], cn[1] - cp[1]) > threshold


# --- config loading from the SQLite config store --------------------------

def load_venue_config(db, venue_id: str) -> tuple[list[AssetRuntime], list[SourceRuntime]]:
    """Read a venue's assets, sensors (with zone polygons), and video sources."""
    with db.cursor() as cur:
        cur.execute("SELECT * FROM assets WHERE venue_id = ?", (venue_id,))
        asset_rows = [dict(r) for r in cur.fetchall()]
        asset_ids = [a["id"] for a in asset_rows]

        sensor_rows: list[dict] = []
        if asset_ids:
            placeholders = ",".join("?" * len(asset_ids))
            cur.execute(
                f"""SELECT s.*, z.polygons AS zone_polygons
                    FROM sensors s
                    LEFT JOIN zones z ON s.zone_id = z.id
                    WHERE s.asset_id IN ({placeholders}) AND s.enabled = 1""",
                asset_ids,
            )
            sensor_rows = [dict(r) for r in cur.fetchall()]

        cur.execute("SELECT * FROM video_sources WHERE venue_id = ?", (venue_id,))
        source_rows = [dict(r) for r in cur.fetchall()]

    # build sensor runtimes
    sensors_by_asset: dict[str, list[SensorRuntime]] = {}
    sensors_by_source: dict[str, list[SensorRuntime]] = {}
    for r in sensor_rows:
        polys = json.loads(r["zone_polygons"]) if r.get("zone_polygons") else []
        sr = SensorRuntime(
            id=r["id"], asset_id=r["asset_id"], source_id=r.get("video_source_id"),
            kind=r["type"], role=r["role"], conf_threshold=r["conf_threshold"],
            zone_polygons=polys,
        )
        sensors_by_asset.setdefault(sr.asset_id, []).append(sr)
        if sr.source_id:
            sensors_by_source.setdefault(sr.source_id, []).append(sr)

    assets = [
        AssetRuntime(id=a["id"], name=a["name"],
                     business_unit_id=a.get("business_unit_id"),
                     sensors=sensors_by_asset.get(a["id"], []))
        for a in asset_rows
    ]
    sources = [
        SourceRuntime(id=s["id"], name=s["name"], uri=s.get("uri"),
                      sensors=sensors_by_source.get(s["id"], []))
        for s in source_rows
    ]
    return assets, sources


# --- the runtime ----------------------------------------------------------

class LiveRuntime:
    def __init__(
        self,
        venue_id: str,
        assets: list[AssetRuntime],
        sources: list[SourceRuntime],
        frame_sources: dict,          # source_id -> FrameSource
        detector: Detector,
        engine: Optional[StateEngine] = None,
        sink: Optional[StateSink] = None,
        sampler=None,
        clock=_now,
        motion_threshold: float = 8.0,
        snooker_detector: Optional[Detector] = None,
        min_game_sec: float = 0.0,
        max_game_sec: float = 2700.0,
        rack_red_threshold: int = 8,
        rerack_jump: int = 6,
        rerack_low_band: int = 2,
        rerack_high_band: int = 7,
        debug_log=None,
    ):
        self.venue_id = venue_id
        self.assets = assets
        self.debug_log = debug_log
        self.sources = sources
        self.frame_sources = frame_sources
        self.detector = detector                 # person / general detector
        self.snooker_detector = snooker_detector  # best.pt (optional)
        self.engine = engine or StateEngine()
        self.sink = sink
        self.sampler = sampler
        self._clock = clock
        self.motion_threshold = motion_threshold
        self._last_label: dict[str, str] = {}
        self._prev_points: dict[str, list] = {}
        self._last_frames: dict[str, object] = {}   # source_id -> last frame

        # one game state machine per asset that has a snooker sensor
        self._game_trackers: dict[str, SnookerGameTracker] = {}
        for asset in assets:
            if any(s.kind == SNOOKER_KIND for s in asset.sensors):
                self._game_trackers[asset.id] = SnookerGameTracker(
                    min_game_sec=min_game_sec, max_game_sec=max_game_sec,
                    rack_red_threshold=rack_red_threshold, rerack_jump=rerack_jump,
                    rerack_low_band=rerack_low_band, rerack_high_band=rerack_high_band)

        # map each asset to its primary (or first) source, for snapshots
        self._asset_source: dict[str, str] = {}
        for src in sources:
            for sensor in src.sensors:
                cur = self._asset_source.get(sensor.asset_id)
                if cur is None or sensor.role == "primary":
                    self._asset_source[sensor.asset_id] = src.id

        # let the sink pull the current frame for an asset (for game snapshots)
        if self.sink is not None and hasattr(self.sink, "frame_provider") \
                and self.sink.frame_provider is None:
            self.sink.frame_provider = self.frame_for_asset

    def frame_for_asset(self, asset_id: str):
        return self._last_frames.get(self._asset_source.get(asset_id))

    def current_snapshots(self) -> list[AssetSnapshot]:
        return [self.engine.snapshot(a) for a in self.assets]

    def tick(self) -> tuple[list[AssetSnapshot], list[AssetSnapshot]]:
        """One pipeline tick. Returns (all_snapshots, changed_snapshots)."""
        source_ok: dict[str, bool] = {}
        # per source: {"person": [...], "snooker": [...]}
        dets_by_source: dict[str, dict] = {}

        for src in self.sources:
            kinds = {s.kind for s in src.sensors}
            fs = self.frame_sources.get(src.id)
            person, snooker = [], []
            ok = False
            if fs is not None:
                ok, frame = fs.read()
                if ok:
                    self._last_frames[src.id] = frame
                    if kinds & PERSON_KINDS and self.detector is not None:
                        person = self.detector.detect(frame)
                    if SNOOKER_KIND in kinds and self.snooker_detector is not None:
                        snooker = self.snooker_detector.detect(frame)
            source_ok[src.id] = ok
            dets_by_source[src.id] = {"person": person, "snooker": snooker}

        # raw per-sensor observations via the per-kind observation strategy
        raw_by_sensor: dict[str, RawObservation] = {}
        snooker_obs: dict[str, dict] = {}   # sensor_id -> full obs (for the game tracker)
        for src in self.sources:
            bucket = dets_by_source.get(src.id, {"person": [], "snooker": []})
            for sensor in src.sensors:
                dets = bucket["snooker"] if sensor.kind == SNOOKER_KIND else bucket["person"]
                obs = observe(sensor.kind, dets, sensor)
                if sensor.kind == SNOOKER_KIND:
                    snooker_obs[sensor.id] = obs
                points = obs["points"]
                active = _motion(self._prev_points.get(sensor.id), points,
                                 self.motion_threshold)
                self._prev_points[sensor.id] = points
                if sensor.kind == SNOOKER_KIND:
                    # a table is "in use" only when there is PLAY (motion) or a
                    # new rack — NOT merely because balls sit on it (players
                    # leave balls between games).
                    game_start = obs.get("game_start", False)
                    raw_by_sensor[sensor.id] = RawObservation(
                        present=active or game_start, confidence=obs["confidence"],
                        count=obs["count"], active=active, game_start=game_start)
                else:
                    raw_by_sensor[sensor.id] = RawObservation(
                        present=obs["present"], confidence=obs["confidence"],
                        count=obs["count"], active=active)

        all_snaps: list[AssetSnapshot] = []
        changed: list[AssetSnapshot] = []
        change_events: list[ChangeEvent] = []
        for asset in self.assets:
            snap, was_changed = self.engine.update(asset, raw_by_sensor, source_ok)
            all_snaps.append(snap)
            if was_changed:
                prev = self._last_label.get(asset.id, "Unknown")
                changed.append(snap)
                change_events.append(ChangeEvent(prev_label=prev, snapshot=snap))
            self._last_label[asset.id] = snap.label

        if self.sink is not None and change_events:
            self.sink.handle(self.venue_id, change_events)

        # snooker game state machine -> game_start / game_end events
        if self._game_trackers:
            snap_by_asset = {s.asset_id: s for s in all_snaps}
            game_ts = self._clock()
            for asset in self.assets:
                tracker = self._game_trackers.get(asset.id)
                if tracker is None:
                    continue
                red, colored, gs, player = 0, False, False, False
                for s in asset.sensors:
                    o = snooker_obs.get(s.id)
                    if not o:
                        continue
                    red = max(red, o.get("red_count", 0))
                    colored = colored or o.get("colored_present", False)
                    gs = gs or o.get("game_start", False)
                    player = player or o.get("player", False)
                evs = tracker.update(game_ts, red, colored, gs, player)
                snap = snap_by_asset.get(asset.id)
                if self.sink is not None:
                    for ev in evs:
                        if ev.kind == "game_start" and hasattr(self.sink, "record_game_start"):
                            self.sink.record_game_start(self.venue_id, snap, ts=ev.ts,
                                                        game_number=ev.game_number)
                        elif ev.kind == "game_end" and hasattr(self.sink, "record_game_end"):
                            self.sink.record_game_end(self.venue_id, snap, ts=ev.ts,
                                                      game_number=ev.game_number)
                if self.debug_log is not None and snap is not None:
                    self.debug_log.row({
                        "ts": game_ts, "table": asset.name, "red": red,
                        "colored": int(colored), "game_start": int(gs),
                        "player": int(player), "state": tracker.state,
                        "red_floor": tracker._red_floor, "label": snap.label,
                        "activity": snap.activity,
                        "event": ";".join(e.kind for e in evs),
                    })

        if self.sampler is not None:
            self._sample(all_snaps, raw_by_sensor)
        return all_snaps, changed

    def _sample(self, snaps: list[AssetSnapshot], raw_by_sensor: dict) -> None:
        """Emit one set of scalar metric samples per asset this tick."""
        ts = self._clock()
        # persons per asset = max count across its occupancy sensors (avoid
        # double-counting the same people across primary+supporting views).
        persons: dict[str, int] = {}
        for asset in self.assets:
            best = 0
            for s in asset.sensors:
                if s.kind in ("occupancy", "presence", "snooker_game"):
                    obs = raw_by_sensor.get(s.id)
                    if obs:
                        best = max(best, obs.count)
            persons[asset.id] = best

        samples = []
        for snap in snaps:
            base = {"asset_id": snap.asset_id, "business_unit_id": snap.business_unit_id}
            samples.append({**base, "metric": "present",
                            "value": 1.0 if snap.presence == PRESENCE_PRESENT else 0.0})
            samples.append({**base, "metric": "persons", "value": persons.get(snap.asset_id, 0)})
            samples.append({**base, "metric": "confidence", "value": snap.confidence})
            samples.append({**base, "metric": "health_ok",
                            "value": 1.0 if snap.health == HEALTH_OK else 0.0})
        self.sampler.record(self.venue_id, ts, samples)

    def release(self) -> None:
        for fs in self.frame_sources.values():
            try:
                fs.release()
            except Exception:
                pass


def build_live_runtime(
    db, venue_id: str, detector: Detector,
    source_factory: Callable,     # (SourceRuntime) -> FrameSource
    engine: Optional[StateEngine] = None,
    sink: Optional[StateSink] = None,
    sampler=None,
    motion_threshold: float = 8.0,
    snooker_detector: Optional[Detector] = None,
    min_game_sec: float = 0.0,
    max_game_sec: float = 2700.0,
    rack_red_threshold: int = 8,
    rerack_jump: int = 6,
    rerack_low_band: int = 2,
    rerack_high_band: int = 7,
    debug_log=None,
) -> LiveRuntime:
    assets, sources = load_venue_config(db, venue_id)
    frame_sources = {}
    for src in sources:
        if src.uri:
            frame_sources[src.id] = source_factory(src)
    return LiveRuntime(venue_id, assets, sources, frame_sources, detector,
                       engine, sink, sampler, motion_threshold=motion_threshold,
                       snooker_detector=snooker_detector,
                       min_game_sec=min_game_sec, max_game_sec=max_game_sec,
                       rack_red_threshold=rack_red_threshold, rerack_jump=rerack_jump,
                       rerack_low_band=rerack_low_band, rerack_high_band=rerack_high_band,
                       debug_log=debug_log)
