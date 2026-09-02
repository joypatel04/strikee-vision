"""Draw what the pipeline saw onto a frame.

The dashboard can say a station is closed, but not why. The four reasons look
identical from outside: nobody was detected, someone was detected outside the
zone, the zone is on the wrong part of the picture, or the screen gate is
holding it shut. One annotated frame answers all four at a glance, which is why
these are worth rendering at all.

Kept separate from both callers so the live view and tools/debug_frame.py
cannot drift into disagreeing about what green means.
"""
from __future__ import annotations

from .geometry import ANCHOR_FEET, anchor_points, point_in_polygon

# BGR. Zone outlines carry the verdict, so they are the only saturated colours;
# detections stay neutral so they never read as a verdict of their own.
GREEN = (0, 200, 0)
RED = (60, 60, 235)
AMBER = (0, 190, 240)
GREY = (155, 155, 155)
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)


def annotate(frame, zones=(), boxes=(), caption: str | None = None,
             max_width: int | None = None, anchor: str = ANCHOR_FEET):
    """Return an annotated copy of `frame`.

    zones  - (polygons, label, present, is_person) per sensor
    boxes  - (bbox, kind) per detection, kind "person" or "ball"
    anchor - which part of a person decides where they are; the drawn dots must
             match it, or the picture explains a decision nobody made
    """
    import cv2
    import numpy as np

    canvas = frame.copy()

    for bbox, kind in boxes:
        x1, y1, x2, y2 = (int(v) for v in bbox)
        cv2.rectangle(canvas, (x1, y1), (x2, y2),
                      AMBER if kind == "ball" else GREY, 1)

    person_polys = [p for polys, _, _, is_person in zones if is_person
                    for p in polys]

    for polys, label, present, _ in zones:
        colour = GREEN if present else RED
        for poly in polys:
            pts = np.array(poly, dtype=np.int32)
            cv2.polylines(canvas, [pts], True, colour, 2)
            if label:
                x, y = pts.min(axis=0)
                _text(cv2, canvas, label, (int(x), max(16, int(y) - 6)), colour)

    # The deciding points for each person, coloured by whether any zone holds
    # them. This is what explains "detected but not counted": with the feet
    # anchor, a seated player's box ends at their chest, so the dot lands above
    # the cushion and outside a zone drawn around the floor.
    for bbox, kind in boxes:
        if kind != "person":
            continue
        for gx, gy in anchor_points(bbox, anchor):
            inside = any(point_in_polygon((gx, gy), p) for p in person_polys)
            cv2.circle(canvas, (int(gx), int(gy)), 6, GREEN if inside else RED, -1)
            cv2.circle(canvas, (int(gx), int(gy)), 6, WHITE, 1)

    if caption:
        cv2.rectangle(canvas, (0, 0), (canvas.shape[1], 30), BLACK, -1)
        cv2.putText(canvas, caption, (8, 21), cv2.FONT_HERSHEY_SIMPLEX,
                    0.6, WHITE, 1, cv2.LINE_AA)

    # Downscale last, so the text above is drawn at a legible size first and
    # then shrinks with the picture rather than being drawn tiny.
    if max_width and canvas.shape[1] > max_width:
        scale = max_width / canvas.shape[1]
        canvas = cv2.resize(canvas, (max_width, int(canvas.shape[0] * scale)),
                            interpolation=cv2.INTER_AREA)
    return canvas


def _text(cv2, canvas, text, org, colour):
    """Outlined, so a label stays readable over both a bright TV and a dark floor."""
    cv2.putText(canvas, text, org, cv2.FONT_HERSHEY_SIMPLEX, 0.45, BLACK, 3,
                cv2.LINE_AA)
    cv2.putText(canvas, text, org, cv2.FONT_HERSHEY_SIMPLEX, 0.45, colour, 1,
                cv2.LINE_AA)
