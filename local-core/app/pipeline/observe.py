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

    No model - four cheap statistics over the zone's pixels.

    Brightness alone cannot do this, and the field data says so plainly: a dark
    panel reflecting room lights reads 92-97, while a night level or a loading
    screen on a TV that is genuinely ON can read below that. The two ranges
    OVERLAP, so no threshold on mean brightness separates them - raise it and you
    lose dark games, lower it and every off TV reads as on.

    What does separate them is the character of the picture, not its level:

      luminance   mean grey. Settles the easy case, a bright screen.
      change      mean absolute difference from the last look. A TV playing
                  anything moves; a reflection of a still room does not.
      contrast    standard deviation across the zone. Content has structure -
                  bright HUD on a dark scene, subtitles, edges. A reflection is
                  a smooth wash of ambient light.
      saturation  mean channel spread. Games are coloured; reflected room light
                  is very nearly grey.

    So a dim, still, but structured and colourful zone reads ON, and a bright,
    smooth, grey one reads OFF - which is the pair brightness alone got backwards.

    `previous` is the same zone's grey pixels from the last sample; without one
    there is no change signal. Returns the crop so the caller can pass it back.
    """
    import os

    import numpy as np

    crop = _zone_crop(frame, sensor)
    if crop is None or crop.size == 0:
        return {"present": False, "count": 0, "confidence": 0.0, "points": [],
                "luminance": 0.0, "change": 0.0, "contrast": 0.0,
                "saturation": 0.0, "reason": "no zone", "crop": None}

    grey = crop.mean(axis=2) if crop.ndim == 3 else crop
    luminance = float(grey.mean())
    contrast = float(grey.std())

    if crop.ndim == 3:
        as_f = crop.astype("float32")
        saturation = float((as_f.max(axis=2) - as_f.min(axis=2)).mean())
    else:
        saturation = 0.0        # a mono frame cannot tell us about colour

    change = 0.0
    if previous is not None and getattr(previous, "shape", None) == grey.shape:
        change = float(np.abs(grey.astype("float32") - previous.astype("float32")).mean())

    # Per-sensor params win, so one awkward TV can be tuned on its own; the env
    # vars are the venue-wide default.
    params = getattr(sensor, "params", None) or {}

    def _p(key, env, default):
        return float(params.get(key, os.environ.get(env, default)))

    # 120, not 90: an off panel reflecting room lighting measured 92-97 at the
    # venue, so 90 called every dark TV "on" all evening.
    lum_on = _p("screen_lum", "STRIKEE_SCREEN_LUM", 120.0)
    change_on = _p("screen_change", "STRIKEE_SCREEN_CHANGE", 6.0)
    contrast_on = _p("screen_contrast", "STRIKEE_SCREEN_CONTRAST", 28.0)
    sat_on = _p("screen_sat", "STRIKEE_SCREEN_SAT", 14.0)

    # Any ONE of these is enough, except the last, which needs both halves:
    # structure without colour is a window reflection, and colour without
    # structure is a wall. Together they are a picture.
    signals = [
        ("bright", luminance >= lum_on, luminance / max(lum_on, 1.0)),
        ("moving", change >= change_on, change / max(change_on, 1.0)),
        ("picture", contrast >= contrast_on and saturation >= sat_on,
         min(contrast / max(contrast_on, 1.0), saturation / max(sat_on, 1.0))),
    ]
    fired = [(name, ratio) for name, ok, ratio in signals if ok]
    on = bool(fired)

    # Confidence follows whichever signal is carrying the decision, so a
    # borderline screen does not look as certain as an obvious one.
    confidence = min(1.0, max(r for _, r in fired) / 2.0) if on else 0.0
    reason = "+".join(name for name, _ in fired) if on else "off"

    return {"present": on, "count": 1 if on else 0, "confidence": confidence,
            "points": [], "luminance": round(luminance, 1),
            "change": round(change, 2), "contrast": round(contrast, 1),
            "saturation": round(saturation, 1), "reason": reason, "crop": grey}


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
