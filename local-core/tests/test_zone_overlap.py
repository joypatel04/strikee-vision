"""Overlapping station zones.

A person is reduced to a single point, so if that point sits inside two station
polygons both read occupied - one customer, two billed sessions, and nothing on
screen explaining it. Easy to do by accident on a wide-angle camera covering
several stations, so the editor warns at save time.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from field_setup import _overlapping_pairs


def _z(name, poly):
    return {"name": name, "polygon": poly}


def test_separate_zones_do_not_warn():
    zones = [_z("Station 1", [[0, 0], [40, 0], [40, 40], [0, 40]]),
             _z("Station 2", [[60, 0], [100, 0], [100, 40], [60, 40]])]
    assert _overlapping_pairs(zones) == []


def test_partial_overlap_is_reported():
    zones = [_z("Station 1", [[0, 0], [50, 0], [50, 40], [0, 40]]),
             _z("Station 2", [[30, 0], [100, 0], [100, 40], [30, 40]])]
    assert _overlapping_pairs(zones) == [("Station 1", "Station 2")]


def test_one_zone_inside_another_is_reported():
    """Vertex containment has to be checked both ways or a fully-enclosed zone
    is missed - none of the outer polygon's corners are inside the inner one."""
    zones = [_z("Sofa", [[0, 0], [100, 0], [100, 100], [0, 100]]),
             _z("Seat", [[20, 20], [40, 20], [40, 40], [20, 40]])]
    assert _overlapping_pairs(zones) == [("Sofa", "Seat")]


def test_irregular_shapes_that_interlock_without_containing_a_corner():
    """Awkward room shapes still get caught when they genuinely share space."""
    zones = [_z("A", [[0, 0], [60, 0], [60, 20], [20, 20], [20, 60], [0, 60]]),
             _z("B", [[10, 10], [50, 10], [50, 50], [10, 50]])]
    assert _overlapping_pairs(zones) == [("A", "B")]


def test_adjacent_but_not_overlapping_shares_an_edge_only():
    """Zones that merely touch along an edge are reported, because a point on
    the boundary counts as inside both - so a shared edge really is ambiguous."""
    zones = [_z("A", [[0, 0], [50, 0], [50, 40], [0, 40]]),
             _z("B", [[50, 0], [100, 0], [100, 40], [50, 40]])]
    assert _overlapping_pairs(zones) == [("A", "B")]


def test_three_zones_report_every_offending_pair():
    zones = [_z("A", [[0, 0], [50, 0], [50, 50], [0, 50]]),
             _z("B", [[25, 25], [75, 25], [75, 75], [25, 75]]),
             _z("C", [[200, 200], [250, 200], [250, 250], [200, 250]])]
    pairs = _overlapping_pairs(zones)
    assert ("A", "B") in pairs
    assert not any("C" in p for p in pairs)


def test_a_single_zone_cannot_overlap_itself():
    assert _overlapping_pairs([_z("Only", [[0, 0], [10, 0], [10, 10]])]) == []
