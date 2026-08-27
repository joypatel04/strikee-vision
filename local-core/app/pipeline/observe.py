"""Observation strategies: turn a frame's detections into a per-sensor raw
observation, according to the sensor's kind (observation mode).

  - person       : a person's feet in the zone -> occupied
  - snooker_game : balls on the table (in the zone) -> a game in progress
  - screen       : a TV/monitor inside the zone is switched on

Both are 'occupancy-like' (they drive the presence/activity facets). The state
engine's smoothing + multi-camera fusion provide the persistence that makes this
robust to a model that intermittently misses.
"""
from __future__ import annotations

from .geometry import detection_in_any_polygon, detection_center_in_any_polygon
from .types import Detection

PERSON_KINDS = {"occupancy", "presence", "person"}
SNOOKER_KIND = "snooker_game"
SCREEN_KIND = "screen"

BALL_LABELS = {
    "red_ball", "black_ball", "blue_ball", "brown_ball",
    "green_ball", "white_ball", "yellow_ball",
}
# non-red, non-cue colours — their presence with few reds signals the end phase
COLORED_LABELS = {"black_ball", "blue_ball", "brown_ball", "green_ball", "yellow_ball"}


def observe_person(detections: list[Detection], sensor) -> dict:
    """present when >=1 person's feet are in the zone."""
    in_zone = [d for d in detections
               if d.label == "person"
               and d.confidence >= sensor.conf_threshold
               and detection_in_any_polygon(d, sensor.zone_polygons)]
    return {
        "present": len(in_zone) > 0,
        "count": len(in_zone),
        "confidence": max((d.confidence for d in in_zone), default=0.0),
        "points": [_ground(d) for d in in_zone],
    }


def observe_snooker_game(detections: list[Detection], sensor) -> dict:
    """present when at least `min_balls` balls sit on the table (in the zone).
    Also surfaces game_start (rack) and player presence for corroboration."""
    params = getattr(sensor, "zone_polygons", None)
    min_balls = 3
    if getattr(sensor, "params", None):
        min_balls = sensor.params.get("min_balls", 3)

    balls = [d for d in detections
             if d.label in BALL_LABELS
             and d.confidence >= sensor.conf_threshold
             and detection_center_in_any_polygon(d, sensor.zone_polygons)]
    red_count = sum(1 for d in balls if d.label == "red_ball")
    colored_present = any(d.label in COLORED_LABELS for d in balls)
    game_start = any(d.label == "game_start"
                     and detection_center_in_any_polygon(d, sensor.zone_polygons)
                     for d in detections)
    player = any(d.label == "snooker_player"
                 and detection_in_any_polygon(d, sensor.zone_polygons)
                 for d in detections)
    return {
        "present": len(balls) >= min_balls,
        "count": len(balls),
        "confidence": max((d.confidence for d in balls), default=0.0),
        "points": [_center(d) for d in balls],
        "game_start": game_start,
        "player": player,
        "red_count": red_count,
        "colored_present": colored_present,
    }


def observe_screen(frame, sensor, previous=None) -> dict:
    """present when the screen inside the zone is on.

    No model: a display that is on is either bright or changing, usually both.
    Brightness alone is not enough - a dark game scene is dimmer than the room -
    and change alone is not enough either, because a paused game is perfectly
    still. Taking either signal covers both, and the state engine's smoothing
    absorbs the rest.

    `previous` is the same zone's pixels from the last sample; without one we
    have no change signal and fall back to brightness. Returns the crop so the
    caller can pass it back next time.
    """
    import numpy as np

    crop = _zone_crop(frame, sensor)
    if crop is None or crop.size == 0:
        return {"present": False, "count": 0, "confidence": 0.0, "points": [],
                "luminance": 0.0, "change": 0.0, "crop": None}

    grey = crop.mean(axis=2) if crop.ndim == 3 else crop
    luminance = float(grey.mean())

    change = 0.0
    if previous is not None and getattr(previous, "shape", None) == grey.shape:
        change = float(np.abs(grey.astype("float32") - previous.astype("float32")).mean())

    # Per-sensor params win, so one awkward TV can be tuned on its own; the env
    # vars are the venue-wide default.
    import os
    params = getattr(sensor, "params", None) or {}
    lum_on = float(params.get("screen_lum",
                              os.environ.get("STRIKEE_SCREEN_LUM", 90.0)))
    change_on = float(params.get("screen_change",
                                 os.environ.get("STRIKEE_SCREEN_CHANGE", 6.0)))

    on = luminance >= lum_on or change >= change_on
    # Confidence rises with whichever signal is carrying the decision, so a
    # borderline screen does not look as certain as an obvious one.
    confidence = min(1.0, max(luminance / max(lum_on, 1.0),
                              change / max(change_on, 1.0)) / 2.0) if on else 0.0
    return {"present": on, "count": 1 if on else 0, "confidence": confidence,
            "points": [], "luminance": round(luminance, 1),
            "change": round(change, 2), "crop": grey}


def _zone_crop(frame, sensor):
    """The bounding box of the sensor's polygons, clipped to the frame."""
    polys = getattr(sensor, "zone_polygons", None)
    if frame is None or not polys:
        return None
    xs = [p[0] for poly in polys for p in poly]
    ys = [p[1] for poly in polys for p in poly]
    if not xs or not ys:
        return None
    h, w = frame.shape[:2]
    x1 = max(0, int(min(xs)));  x2 = min(w, int(max(xs)) + 1)
    y1 = max(0, int(min(ys)));  y2 = min(h, int(max(ys)) + 1)
    if x2 <= x1 or y2 <= y1:
        return None
    return frame[y1:y2, x1:x2]


def observe(kind: str, detections: list[Detection], sensor) -> dict:
    if kind == SNOOKER_KIND:
        return observe_snooker_game(detections, sensor)
    return observe_person(detections, sensor)


def _ground(d: Detection):
    x1, y1, x2, y2 = d.bbox
    return ((x1 + x2) / 2.0, y2)


def _center(d: Detection):
    x1, y1, x2, y2 = d.bbox
    return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)
