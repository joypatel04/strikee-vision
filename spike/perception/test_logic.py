"""Synthetic self-test for the spike's core logic — no model or footage needed.

Validates:
  1. point-in-polygon using a person's ground point
  2. the smoothing state machine (min_start / min_clear hysteresis)
  3. session open/close semantics

Run:  python test_logic.py
"""
from common import Zone, ZoneState, point_in_poly, person_ground_point
import numpy as np


def test_point_in_poly():
    # square 0,0 -> 100,100
    poly = np.array([[0, 0], [100, 0], [100, 100], [0, 100]], dtype=np.int32)
    assert point_in_poly((50, 50), poly) is True
    assert point_in_poly((150, 50), poly) is False
    # a person box whose feet (bottom-centre) land inside
    box = [40, 10, 60, 90]           # x1,y1,x2,y2
    gp = person_ground_point(box)    # (50, 90)
    assert gp == (50.0, 90.0)
    assert point_in_poly(gp, poly) is True
    print("ok  point-in-polygon + ground point")


def drive(states_input, min_start=2, min_clear=3):
    """Feed a list of raw-present booleans; return (state_trace, changes)."""
    z = Zone(name="T1", asset_type="Snooker Table", polygon=[[0, 0]],
             min_start_ticks=min_start, min_clear_ticks=min_clear)
    st = ZoneState(zone=z)
    trace, changes = [], []
    for i, present in enumerate(states_input):
        ch = st.update(present, ts=f"2026-07-07T10:00:{i:02d}+00:00")
        trace.append(st.state)
        if ch:
            changes.append((i, ch, st.state))
    return trace, changes


def test_debounce_open():
    # single stray detection should NOT open (needs 2 consecutive)
    trace, changes = drive([True, False, False])
    assert "OCCUPIED" not in trace, trace
    print("ok  single stray tick does not open a session")


def test_open_and_close():
    # present x3 opens, empty x3 closes
    raw = [True, True, True, False, False, False]
    trace, changes = drive(raw)
    assert trace[1] == "OCCUPIED", trace          # opens on 2nd present tick
    assert trace[-1] == "AVAILABLE", trace         # closes after 3 empty
    kinds = [c[1] for c in changes]
    assert "became_occupied" in kinds
    assert "session_ended" in kinds
    print("ok  session opens after min_start and closes after min_clear")


def test_grace_window_absorbs_blip():
    # occupied, then ONE empty tick (blip), then present again -> stays occupied,
    # no session close (min_clear=3 not reached)
    raw = [True, True, False, True, True]
    trace, changes = drive(raw)
    assert trace[-1] == "OCCUPIED", trace
    assert all(c[1] != "session_ended" for c in changes), changes
    print("ok  grace window absorbs a single empty blip (no false session end)")


if __name__ == "__main__":
    test_point_in_poly()
    test_debounce_open()
    test_open_and_close()
    test_grace_window_absorbs_blip()
    print("\nALL LOGIC TESTS PASSED")
