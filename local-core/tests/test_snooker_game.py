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
