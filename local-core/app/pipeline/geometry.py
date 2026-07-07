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


def detection_in_any_polygon(det: Detection, polygons: list) -> bool:
    """True if the detection's ground point falls inside any of the polygons."""
    gp = ground_point(det.bbox)
    return any(point_in_polygon(gp, poly) for poly in polygons)
