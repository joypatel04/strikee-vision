"""LiveRuntime: builds the per-venue pipeline from DB config and runs it tick
by tick. The tick is synchronous and fully injectable (fake sources + detector),
so it is testable without cameras or a model.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Callable, Optional

import math

from .geometry import detection_in_any_polygon, ground_point
from .perception import Detector
from .sink import ChangeEvent, StateSink
from .state import StateEngine
from .types import (
    AssetRuntime, AssetSnapshot, RawObservation, SensorRuntime, SourceRuntime,
    PRESENCE_PRESENT, HEALTH_OK,
)


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
    ):
        self.venue_id = venue_id
        self.assets = assets
        self.sources = sources
        self.frame_sources = frame_sources
        self.detector = detector
        self.engine = engine or StateEngine()
        self.sink = sink
        self.sampler = sampler
        self._clock = clock
        self.motion_threshold = motion_threshold
        self._last_label: dict[str, str] = {}
        self._prev_points: dict[str, list] = {}

    def current_snapshots(self) -> list[AssetSnapshot]:
        return [self.engine.snapshot(a) for a in self.assets]

    def tick(self) -> tuple[list[AssetSnapshot], list[AssetSnapshot]]:
        """One pipeline tick. Returns (all_snapshots, changed_snapshots)."""
        source_ok: dict[str, bool] = {}
        detections: dict[str, list] = {}

        for src in self.sources:
            fs = self.frame_sources.get(src.id)
            if fs is None:
                source_ok[src.id] = False
                detections[src.id] = []
                continue
            ok, frame = fs.read()
            source_ok[src.id] = ok
            detections[src.id] = self.detector.detect_persons(frame) if ok else []

        # raw per-sensor observations (person-in-zone)
        raw_by_sensor: dict[str, RawObservation] = {}
        for src in self.sources:
            dets = detections.get(src.id, [])
            for sensor in src.sensors:
                in_zone = [d for d in dets
                           if d.confidence >= sensor.conf_threshold
                           and detection_in_any_polygon(d, sensor.zone_polygons)]
                present = len(in_zone) > 0
                conf = max((d.confidence for d in in_zone), default=0.0)
                cur_points = [ground_point(d.bbox) for d in in_zone]
                active = _motion(self._prev_points.get(sensor.id), cur_points,
                                 self.motion_threshold)
                self._prev_points[sensor.id] = cur_points
                raw_by_sensor[sensor.id] = RawObservation(
                    present=present, confidence=conf, count=len(in_zone), active=active)

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
                if s.kind in ("occupancy", "presence"):
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
) -> LiveRuntime:
    assets, sources = load_venue_config(db, venue_id)
    frame_sources = {}
    for src in sources:
        if src.uri:
            frame_sources[src.id] = source_factory(src)
    return LiveRuntime(venue_id, assets, sources, frame_sources, detector,
                       engine, sink, sampler)
