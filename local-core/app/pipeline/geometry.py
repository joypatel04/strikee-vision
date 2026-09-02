"""Pure-Python geometry — no numpy/OpenCV, so the observation logic is testable
without heavy dependencies.
"""
from __future__ import annotations

from .types import Detection


def ground_point(bbox: tuple[float, float, float, float]) -> tuple[float, float]:
    """A person 'stands' at the bottom-centre of their box (their feet). This
    is the meaningful point for testing occupancy of a table/station."""
    x1, y1, x2, y2 = bbox
    return ((x1 + x2) / 2.0, y2)


def center_point(bbox: tuple[float, float, float, float]) -> tuple[float, float]:
    """The box centre — used for objects that sit on the surface (e.g. balls),
    where the whole object, not the feet, indicates the location."""
    x1, y1, x2, y2 = bbox
    return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)


def point_in_polygon(point: tuple[float, float], polygon: list) -> bool:
    """Ray-casting point-in-polygon test. `polygon` is a list of [x, y].
    Points on the boundary are treated as inside."""
    x, y = point
    n = len(polygon)
    if n < 3:
        return False
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i][0], polygon[i][1]
        xj, yj = polygon[j][0], polygon[j][1]
        # boundary check
        if _on_segment(x, y, xi, yi, xj, yj):
            return True
        intersects = ((yi > y) != (yj > y)) and (
            x < (xj - xi) * (y - yi) / (yj - yi) + xi
        )
        if intersects:
            inside = not inside
        j = i
    return inside


def _on_segment(px, py, ax, ay, bx, by) -> bool:
    """True if point P lies on segment AB (within a small epsilon)."""
    cross = (bx - ax) * (py - ay) - (by - ay) * (px - ax)
    if abs(cross) > 1e-9:
        return False
    if min(ax, bx) - 1e-9 <= px <= max(ax, bx) + 1e-9 and \
       min(ay, by) - 1e-9 <= py <= max(ay, by) + 1e-9:
        return True
    return False


# Which part of a person decides where they are. The right answer depends on
# the furniture, not on the model.
ANCHOR_FEET = "feet"
ANCHOR_CENTER = "center"
ANCHOR_BODY = "body"
ANCHORS = (ANCHOR_FEET, ANCHOR_CENTER, ANCHOR_BODY)


def anchor_points(bbox, anchor: str = ANCHOR_FEET) -> list:
    """The points that count as 'where this person is', for the given anchor.

    feet    bottom-centre. Correct for someone standing on a floor, and wrong
            for everyone on a sofa: with their legs hidden behind the seat back
            the box ends at their chest, so the point lands well above the
            cushion and outside a zone drawn around the floor. The person is
            detected and then discarded, which looks exactly like not being
            detected at all.
    center  the middle of the box. What you want when the zone is drawn around
            a seating area rather than a footprint.
    body    feet, middle and three-quarter height. Any one inside counts, so it
            holds for someone standing AND someone seated in the same view -
            at the cost of also counting somebody leaning over the back of the
            sofa from behind it.
    """
    x1, y1, x2, y2 = bbox
    mx = (x1 + x2) / 2.0
    if anchor == ANCHOR_CENTER:
        return [(mx, (y1 + y2) / 2.0)]
    if anchor == ANCHOR_BODY:
        return [(mx, y2), (mx, y1 + (y2 - y1) * 0.75), (mx, (y1 + y2) / 2.0)]
    return [(mx, y2)]


def detection_in_any_polygon(det: Detection, polygons: list,
                             anchor: str = ANCHOR_FEET) -> bool:
    """True if any of the detection's anchor points falls inside any polygon."""
    return any(point_in_polygon(pt, poly)
               for pt in anchor_points(det.bbox, anchor)
               for poly in polygons)


def detection_center_in_any_polygon(det: Detection, polygons: list) -> bool:
    """True if the detection's centre falls inside any polygon (for balls)."""
    cp = center_point(det.bbox)
    return any(point_in_polygon(cp, poly) for poly in polygons)


def overlapping_pairs(named_polygons) -> list:
    """Which of these zones share space, as (name_a, name_b) pairs.

    `named_polygons` is [(name, polygon), ...]. Only meaningful for zones on the
    SAME camera: the coordinates are pixels in that camera's picture, so two
    zones from different cameras "overlapping" means nothing at all.

    A person is placed at a point, so a point in the shared area marks BOTH
    stations occupied - one customer, two billed sessions, and nothing on the
    dashboard explains it. Vertex containment both ways, which catches every
    overlap a hand-drawn room zone realistically produces.
    """
    out = []
    items = list(named_polygons)
    for i, (name_a, poly_a) in enumerate(items):
        for name_b, poly_b in items[i + 1:]:
            if any(point_in_polygon(pt, poly_b) for pt in poly_a) or \
               any(point_in_polygon(pt, poly_a) for pt in poly_b):
                out.append((name_a, name_b))
    return out
