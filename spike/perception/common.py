"""Shared helpers for the Strikee Vision perception spike.

Kept dependency-light on purpose: OpenCV + numpy only (no shapely).
Point-in-polygon uses cv2.pointPolygonTest.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

import cv2
import numpy as np


# ---- Video source handling ------------------------------------------------

def open_source(source: str):
    """Open an RTSP url, a video file path, or a webcam index.

    Returns an opened cv2.VideoCapture (caller must check .isOpened()).
    Buffer size is minimised so periodic sampling reads a *recent* frame,
    not a stale buffered one (important for live RTSP).
    """
    # Webcam if the source is a bare integer like "0".
    if source.isdigit():
        cap = cv2.VideoCapture(int(source))
    else:
        # CAP_FFMPEG is the most reliable backend for RTSP.
        cap = cv2.VideoCapture(source, cv2.CAP_FFMPEG)
    try:
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    except Exception:
        pass
    return cap


def grab_recent_frame(cap):
    """Read one recent frame. Flushes a couple of buffered frames first so
    that on a live stream we act on 'now', not on a backlog. Returns
    (ok, frame)."""
    # Flush stale frames cheaply.
    for _ in range(4):
        cap.grab()
    return cap.read()


# ---- Zone config ----------------------------------------------------------

@dataclass
class Zone:
    name: str
    asset_type: str            # e.g. "Snooker Table" (label only, for the spike)
    polygon: list              # list of [x, y] pixel coords
    conf: float = 0.35         # detection confidence threshold for this zone
    min_start_ticks: int = 2   # ticks present -> becomes OCCUPIED (hysteresis)
    min_clear_ticks: int = 3   # ticks empty  -> becomes AVAILABLE (grace window)

    def np_poly(self) -> np.ndarray:
        return np.array(self.polygon, dtype=np.int32)


def load_zones(path: str) -> list[Zone]:
    with open(path, "r") as f:
        data = json.load(f)
    zones = []
    for z in data["zones"]:
        zones.append(Zone(
            name=z["name"],
            asset_type=z.get("asset_type", "Asset"),
            polygon=z["polygon"],
            conf=z.get("conf", 0.35),
            min_start_ticks=z.get("min_start_ticks", 2),
            min_clear_ticks=z.get("min_clear_ticks", 3),
        ))
    return zones


def save_zones(path: str, zones: list[dict]):
    with open(path, "w") as f:
        json.dump({"zones": zones}, f, indent=2)


def point_in_poly(pt, poly_np) -> bool:
    """True if point (x, y) is inside polygon. Boundary counts as inside."""
    return cv2.pointPolygonTest(poly_np, (float(pt[0]), float(pt[1])), False) >= 0


def person_ground_point(box):
    """A person 'stands' at the bottom-centre of their bounding box (their
    feet). That ground point is the most meaningful test for occupancy of a
    table/station, so we use it instead of the box centre."""
    x1, y1, x2, y2 = box
    return ((x1 + x2) / 2.0, y2)


# ---- State smoothing (mirrors G03 presence facet + G05/G06 hysteresis) ----

@dataclass
class ZoneState:
    """Tracks smoothed occupancy for one zone across ticks."""
    zone: Zone
    state: str = "UNKNOWN"            # UNKNOWN | AVAILABLE | OCCUPIED
    _present_streak: int = 0
    _empty_streak: int = 0
    # session tracking
    session_open: bool = False
    session_start_ts: str | None = field(default=None)

    def update(self, present: bool, ts: str):
        """Feed this tick's raw presence; return a dict describing any change."""
        change = None
        if present:
            self._present_streak += 1
            self._empty_streak = 0
        else:
            self._empty_streak += 1
            self._present_streak = 0

        if self.state != "OCCUPIED" and self._present_streak >= self.zone.min_start_ticks:
            self.state = "OCCUPIED"
            change = "became_occupied"
            if not self.session_open:
                self.session_open = True
                self.session_start_ts = ts
        elif self.state != "AVAILABLE" and self._empty_streak >= self.zone.min_clear_ticks:
            was_open = self.session_open
            self.state = "AVAILABLE"
            change = "became_available"
            if was_open:
                self.session_open = False
                change = "session_ended"  # signal caller to close the session
        return change
