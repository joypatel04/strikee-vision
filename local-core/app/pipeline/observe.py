"""Observation strategies: turn a frame's detections into a per-sensor raw
observation, according to the sensor's kind (observation mode).

  - person       : a person's feet in the zone -> occupied
  - snooker_game : balls on the table (in the zone) -> a game in progress

Both are 'occupancy-like' (they drive the presence/activity facets). The state
engine's smoothing + multi-camera fusion provide the persistence that makes this
robust to a model that intermittently misses.
"""
from __future__ import annotations

from .geometry import detection_in_any_polygon, detection_center_in_any_polygon
from .types import Detection

PERSON_KINDS = {"occupancy", "presence", "person"}
SNOOKER_KIND = "snooker_game"

BALL_LABELS = {
    "red_ball", "black_ball", "blue_ball", "brown_ball",
    "green_ball", "white_ball", "yellow_ball",
}


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
    }


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
