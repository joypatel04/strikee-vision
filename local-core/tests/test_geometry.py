from app.pipeline.geometry import (
    ground_point, point_in_polygon, detection_in_any_polygon,
)
from app.pipeline.types import Detection

SQUARE = [[0, 0], [100, 0], [100, 100], [0, 100]]


def test_ground_point_is_bottom_centre():
    assert ground_point((40, 10, 60, 90)) == (50.0, 90.0)


def test_point_inside_and_outside():
    assert point_in_polygon((50, 50), SQUARE) is True
    assert point_in_polygon((150, 50), SQUARE) is False
    assert point_in_polygon((-1, -1), SQUARE) is False


def test_point_on_boundary_is_inside():
    assert point_in_polygon((0, 50), SQUARE) is True
    assert point_in_polygon((100, 100), SQUARE) is True


def test_degenerate_polygon_is_never_inside():
    assert point_in_polygon((0, 0), [[0, 0], [1, 1]]) is False


def test_detection_feet_in_zone():
    # person box whose feet (bottom-centre) land at (50, 90) -> inside
    det = Detection(bbox=(40, 10, 60, 90), confidence=0.9)
    assert detection_in_any_polygon(det, [SQUARE]) is True
    # a person standing to the right of the zone
    det2 = Detection(bbox=(140, 10, 160, 90), confidence=0.9)
    assert detection_in_any_polygon(det2, [SQUARE]) is False


def test_concave_polygon():
    # L-shape
    L = [[0, 0], [100, 0], [100, 40], [40, 40], [40, 100], [0, 100]]
    assert point_in_polygon((20, 80), L) is True     # in the tall part
    assert point_in_polygon((80, 80), L) is False    # in the notch
