"""SnookerGameTracker state machine (ported from the deployed logic)."""
from datetime import datetime, timedelta, timezone

from app.pipeline.snooker_game import (
    SnookerGameTracker, SEARCH, IN_GAME, CHECK_END, WAIT_PLAYER,
)

BASE = datetime(2026, 7, 8, 14, 0, 0, tzinfo=timezone.utc)


def ts(sec):
    return (BASE + timedelta(seconds=sec)).isoformat()


def start_a_game(tr, t0=0):
    """Drive the tracker through a confirmed game_start."""
    tr.update(ts(t0), red_count=15, colored_present=True, game_start=True, player=False)
    ev = tr.update(ts(t0 + 10), red_count=15, colored_present=True,
                   game_start=True, player=False)
    return ev


def test_game_start_needs_confirmation():
    tr = SnookerGameTracker(confirm_ticks=2)
    assert tr.update(ts(0), 15, True, True, False) == []      # 1 tick, not yet
    ev = tr.update(ts(10), 15, True, True, False)             # 2nd consecutive
    assert len(ev) == 1 and ev[0].kind == "game_start"
    assert ev[0].game_number == 1
    assert tr.state == IN_GAME


def test_lingering_rack_does_not_double_count():
    """A rack that keeps being detected (slow break, balls in triangle) must
    NOT count more games while IN_GAME."""
    tr = SnookerGameTracker(confirm_ticks=2)
    start_a_game(tr)
    # game_start keeps firing for many ticks -> still one game
    for k in range(20):
        ev = tr.update(ts(30 + k * 10), red_count=15, colored_present=True,
                       game_start=True, player=False)
        assert ev == []
    assert tr.game_number == 1


def test_game_end_via_red_trajectory():
    tr = SnookerGameTracker(confirm_ticks=2, end_hold_ticks=2)
    start_a_game(tr)
    # end phase: few reds + colours on the table (reds potted), held
    tr.update(ts(600), 1, True, False, False)
    tr.update(ts(610), 1, True, False, False)     # -> CHECK_END
    assert tr.state == CHECK_END
    # table clears (colours potted): reds 0, held -> game end
    tr.update(ts(620), 0, False, False, False)
    ev = tr.update(ts(630), 0, False, False, False)
    assert len(ev) == 1 and ev[0].kind == "game_end"
    assert tr.state == WAIT_PLAYER


def test_mid_game_restart_counts_new_game():
    tr = SnookerGameTracker(confirm_ticks=2, end_hold_ticks=2, restart_confirm_ticks=2)
    start_a_game(tr)
    tr.update(ts(600), 1, True, False, False)
    tr.update(ts(610), 1, True, False, False)     # -> CHECK_END
    # a fresh rack appears (reds jump high) -> previous ends, new game starts
    tr.update(ts(620), 15, True, False, False)
    ev = tr.update(ts(630), 15, True, False, False)
    kinds = [e.kind for e in ev]
    assert kinds == ["game_end", "game_start"]
    assert tr.game_number == 2
    assert tr.state == IN_GAME


def test_wait_player_gates_next_game():
    tr = SnookerGameTracker(confirm_ticks=2, end_hold_ticks=2)
    start_a_game(tr)
    tr.update(ts(600), 1, True, False, False)
    tr.update(ts(610), 1, True, False, False)
    tr.update(ts(620), 0, False, False, False)
    tr.update(ts(630), 0, False, False, False)    # game_end -> WAIT_PLAYER
    assert tr.state == WAIT_PLAYER
    # leftover rack detected but no player -> NOT a new game
    tr.update(ts(640), 15, True, True, False)
    assert tr.game_number == 1
    # a player appears -> back to SEARCH; then a confirmed rack -> game 2
    tr.update(ts(650), 0, False, False, True)
    assert tr.state == SEARCH
    tr.update(ts(660), 15, True, True, False)
    ev = tr.update(ts(670), 15, True, True, False)
    assert ev and ev[0].kind == "game_start" and tr.game_number == 2


def test_min_game_window_suppresses_early_end():
    tr = SnookerGameTracker(min_game_sec=900)
    start_a_game(tr)
    # end-looking signal soon after start (within 15 min) is ignored
    tr.update(ts(60), 1, True, False, False)
    tr.update(ts(120), 1, True, False, False)
    assert tr.state == IN_GAME       # not ended — inside the min-game window
    assert tr.game_number == 1


def test_midgame_concession_rerack_counts_new_game():
    """A player concedes mid-game (reds still ~5, not potted down), balls are
    re-racked -> reds jump back up -> old game ends, new game starts, WITHOUT
    ever reaching the normal end phase."""
    tr = SnookerGameTracker(confirm_ticks=2, restart_confirm_ticks=2,
                            rack_red_threshold=10, rerack_jump=6)
    start_a_game(tr)                                  # game 1, ~15 reds
    # game progresses, reds fall to ~5 (mid-game)
    for t, r in [(30, 12), (40, 9), (50, 7), (60, 5)]:
        ev = tr.update(ts(t), r, True, False, False)
        assert ev == [] and tr.game_number == 1
    # concession + re-rack: reds jump back to a full rack
    tr.update(ts(70), 15, True, False, False)         # 1st high tick
    ev = tr.update(ts(80), 15, True, False, False)    # confirmed -> restart
    assert [e.kind for e in ev] == ["game_end", "game_start"]
    assert tr.game_number == 2
    assert tr.state == IN_GAME


def test_normal_potting_is_not_a_rerack():
    """Reds only falling (normal play) must never trigger a re-rack; a small
    detection wobble up must not either."""
    tr = SnookerGameTracker(confirm_ticks=2, rack_red_threshold=10, rerack_jump=6)
    start_a_game(tr)
    # decline with a small +2 wobble (missed red re-detected) — not a re-rack
    for t, r in [(30, 14), (40, 11), (50, 9), (60, 11), (70, 8), (80, 6)]:
        tr.update(ts(t), r, True, False, False)
    assert tr.game_number == 1
    assert tr.state == IN_GAME


def test_missed_ball_wobble_is_not_a_rerack():
    """Your concern: a frame misses a few balls (low red), the next frame
    re-detects them (higher red). This wobble must NOT look like a re-rack."""
    tr = SnookerGameTracker(confirm_ticks=2, rack_red_threshold=8, rerack_jump=6,
                            floor_confirm_ticks=2)
    start_a_game(tr)                                   # ~15 reds
    seq = [(30, 10), (40, 10),
           (50, 4), (60, 10),                          # single-frame miss to 4
           (70, 10), (80, 5), (90, 5), (100, 10)]      # two-frame miss to 5, recover
    for t, r in seq:
        assert tr.update(ts(t), r, True, False, False) == [], f"false event at red={r}"
    assert tr.game_number == 1                         # still one game


def test_clear_low_to_full_rack_is_a_rerack():
    """A genuine end→re-rack (reds fall to ~2, then a full rack returns) IS a
    new game — caught by Check A (sudden rise)."""
    tr = SnookerGameTracker(confirm_ticks=2, rack_red_threshold=8, rerack_jump=6,
                            restart_confirm_ticks=2)
    start_a_game(tr)
    for t, r in [(30, 10), (40, 6), (50, 3), (60, 2)]:  # play down to ~2 reds
        tr.update(ts(t), r, True, False, False)
    tr.update(ts(70), 13, True, False, False)           # full rack back
    ev = tr.update(ts(80), 13, True, False, False)
    assert [e.kind for e in ev] == ["game_end", "game_start"]
    assert tr.game_number == 2


def test_check_B_catches_undercounted_rack_that_check_A_misses():
    """Two-check payoff: after a confirmed low, a tight fresh rack detected as
    only 7 reds is a new game via Check B (low->high bands) even though Check A
    (needs >= 8 reds) would miss it."""
    tr = SnookerGameTracker(confirm_ticks=2, rack_red_threshold=8, rerack_jump=6,
                            rerack_low_band=2, rerack_high_band=7,
                            floor_confirm_ticks=2, restart_confirm_ticks=2)
    start_a_game(tr)
    for t, r in [(30, 6), (40, 3), (50, 2), (60, 2)]:   # reach a CONFIRMED low
        tr.update(ts(t), r, True, False, False)
    # a tight rack undercounted to just 7 reds (< Check A's 8) comes back
    tr.update(ts(70), 7, True, False, False)
    ev = tr.update(ts(80), 7, True, False, False)
    assert [e.kind for e in ev] == ["game_end", "game_start"]   # via Check B
    assert tr.game_number == 2


def test_full_rack_starts_game_without_game_start_class():
    """When the model never fires game_start, a confirmed full rack of reds
    still starts a game (the camera1.mp4 case: game_start=0 but 16 reds)."""
    tr = SnookerGameTracker(confirm_ticks=2, rack_red_threshold=10)
    assert tr.update(ts(0), 16, True, False, False) == []       # 1 tick
    ev = tr.update(ts(10), 16, True, False, False)              # 2nd -> game
    assert ev and ev[0].kind == "game_start"
    assert tr.state == IN_GAME


def test_max_game_window_force_ends():
    tr = SnookerGameTracker(max_game_sec=100)
    start_a_game(tr)
    ev = tr.update(ts(200), 10, True, False, False)   # elapsed 190 > 100
    assert ev and ev[0].kind == "game_end"
    assert tr.state == WAIT_PLAYER
