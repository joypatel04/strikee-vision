"""Which part of a person decides whether they are in the zone.

Sofa seating breaks the default. A standing person's box ends at their feet, on
the floor, where the zone is drawn. A person sunk into a sofa has their legs
hidden behind the seat back, so the box ends at their chest - and with the feet
anchor the deciding point lands above the cushion, outside the zone. They are
detected and then discarded, which from the dashboard is indistinguishable from
never being detected at all.
"""
from app.pipeline.geometry import (ANCHOR_BODY, ANCHOR_CENTER, ANCHOR_FEET,
                                   anchor_points, detection_in_any_polygon)
from app.pipeline.observe import observe_person, person_anchor
from app.pipeline.types import Detection

# A sofa seating area as drawn on the picture: the cushions and the people on
# them, roughly y 300-500.
SEAT = [[100, 300], [500, 300], [500, 500], [100, 500]]


class Sensor:
    zone_polygons = [SEAT]
    conf_threshold = 0.35
    params = {}


def _sensor(**params):
    class S(Sensor):
        pass
    S.params = params
    return S()


# A seated player: head and torso visible above the seat back, legs hidden.
# The box therefore ENDS at y=380, well inside the seat area but not at its foot.
SEATED = Detection(bbox=(280, 250, 360, 380), confidence=0.9, label="person")

# Someone standing on the floor in front of the sofa; feet at y=470.
STANDING = Detection(bbox=(200, 150, 280, 470), confidence=0.9, label="person")

# Someone standing BEHIND the sofa, leaning over it. Their feet are past the
# zone (y=560) but their upper body crosses it.
BEHIND = Detection(bbox=(300, 200, 380, 560), confidence=0.9, label="person")


def test_feet_anchor_loses_someone_whose_box_runs_past_the_zone():
    """The direction an anchor CAN fix.

    Someone near the camera, or standing at the front edge of the seating area,
    has a box that extends below the zone. Their feet land past it, so the feet
    anchor discards them while their body is plainly inside.
    """
    tall = Detection(bbox=(280, 320, 360, 620), confidence=0.9, label="person")
    assert detection_in_any_polygon(tall, [SEAT], ANCHOR_FEET) is False
    assert detection_in_any_polygon(tall, [SEAT], ANCHOR_CENTER) is True
    assert detection_in_any_polygon(tall, [SEAT], ANCHOR_BODY) is True


def test_no_anchor_rescues_a_box_that_ends_above_the_zone():
    """The direction an anchor CANNOT fix, recorded so nobody goes looking.

    Every anchor point lies between the middle of the box and its bottom edge,
    and in image coordinates both are ABOVE a zone the box never reaches. When
    only a head clears the seat back and the zone is drawn around the floor in
    front of the sofa, the answer is to redraw the zone over the seating area -
    no setting substitutes for that.
    """
    head_only = Detection(bbox=(280, 150, 360, 290), confidence=0.9, label="person")
    for anchor in (ANCHOR_FEET, ANCHOR_CENTER, ANCHOR_BODY):
        assert detection_in_any_polygon(head_only, [SEAT], anchor) is False


def test_center_anchor_holds_a_head_and_shoulders_detection():
    """When only the head clears the seat back, the box is small and high; its
    centre is what sits in the seating area, not its bottom edge."""
    head = Detection(bbox=(300, 310, 340, 360), confidence=0.9, label="person")
    assert detection_in_any_polygon(head, [SEAT], ANCHOR_CENTER) is True


def test_body_anchor_holds_both_seated_and_standing():
    for det in (SEATED, STANDING):
        assert detection_in_any_polygon(det, [SEAT], ANCHOR_BODY) is True


def test_body_anchor_also_counts_someone_leaning_over_the_back():
    """The cost of the permissive anchor, stated so nobody is surprised by it."""
    assert detection_in_any_polygon(BEHIND, [SEAT], ANCHOR_FEET) is False
    assert detection_in_any_polygon(BEHIND, [SEAT], ANCHOR_BODY) is True


def test_anchor_points_are_ordered_feet_first():
    """observe_person reports points[0] for the motion signal, so the first point
    must be stable across anchors that share it."""
    pts = anchor_points((0, 0, 100, 200), ANCHOR_BODY)
    assert pts[0] == (50.0, 200.0)
    assert anchor_points((0, 0, 100, 200), ANCHOR_FEET) == [(50.0, 200.0)]
    assert anchor_points((0, 0, 100, 200), ANCHOR_CENTER) == [(50.0, 100.0)]


# ------------------------------------------------------------ configuration


def test_default_is_unchanged():
    assert person_anchor(_sensor()) == ANCHOR_FEET


def test_per_sensor_beats_the_venue_default(monkeypatch):
    """A room has both kinds of seating, so this cannot be one global switch."""
    monkeypatch.setenv("STRIKEE_PERSON_ANCHOR", "feet")
    assert person_anchor(_sensor(anchor="body")) == ANCHOR_BODY


def test_env_sets_the_venue_default(monkeypatch):
    monkeypatch.setenv("STRIKEE_PERSON_ANCHOR", "center")
    assert person_anchor(_sensor()) == ANCHOR_CENTER


def test_a_typo_falls_back_rather_than_crashing(monkeypatch):
    monkeypatch.setenv("STRIKEE_PERSON_ANCHOR", "middle")
    assert person_anchor(_sensor()) == ANCHOR_FEET


def test_observe_person_uses_and_reports_the_anchor():
    tall = Detection(bbox=(280, 320, 360, 620), confidence=0.9, label="person")
    assert observe_person([tall], _sensor())["present"] is False
    seen = observe_person([tall], _sensor(anchor="center"))
    assert seen["present"] is True and seen["anchor"] == "center"


def test_reported_point_follows_the_anchor():
    """The motion signal diffs these between reads; mixing a feet point one tick
    with a centre point the next would read as movement that never happened."""
    obs = observe_person([SEATED], _sensor(anchor="center"))
    assert obs["points"] == [anchor_points(SEATED.bbox, ANCHOR_CENTER)[0]]
