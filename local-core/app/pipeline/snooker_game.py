"""SnookerGameTracker — per-table game state machine.

Ported from the deployed snooker-ai production logic (run_analysis.py) and
adapted from its batch, variable-frame-skip form to our fixed live tick. It
counts games robustly despite a model that re-detects the rack (game_start)
many times, by keying game counting on STATE rather than on every game_start:

    SEARCH  --game_start(confirmed)-->  IN_GAME
    IN_GAME --reds<2 & colours (held)-->  CHECK_END        (game_start ignored here)
    CHECK_END --reds==0 (held)-->  WAIT_PLAYER  (game end)
    CHECK_END --reds>8 (confirmed)-->  IN_GAME  (mid-game re-rack = new game)
    CHECK_END --reds 1..8-->  IN_GAME  (not ended)
    WAIT_PLAYER --player-->  SEARCH

Key properties (matching the venue's real behaviour):
  - game_start only starts a game in SEARCH, so a rack that lingers (slow break,
    balls left in a triangle) is NOT counted repeatedly.
  - end is detected from the red-ball trajectory (snooker clears reds first,
    then colours), not from "balls gone".
  - a minimum game window suppresses spurious quick end/restart; a maximum window
    force-ends a stuck game.

Multi-frame `slow_verify` is replaced by requiring a condition on N consecutive
ticks (our tick is already several seconds).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

SEARCH = "SEARCH"
IN_GAME = "IN_GAME"
CHECK_END = "CHECK_END"
WAIT_PLAYER = "WAIT_PLAYER"


def _secs(a_iso: str, b_iso: str) -> float:
    return (datetime.fromisoformat(b_iso) - datetime.fromisoformat(a_iso)).total_seconds()


@dataclass
class GameEvent:
    kind: str          # "game_start" | "game_end"
    ts: str
    game_number: int


class SnookerGameTracker:
    def __init__(self, confirm_ticks: int = 2, end_hold_ticks: int = 2,
                 restart_confirm_ticks: int = 2, rack_red_threshold: int = 10,
                 min_game_sec: float = 0.0, max_game_sec: float = 2700.0):
        self.confirm_ticks = confirm_ticks
        self.end_hold_ticks = end_hold_ticks
        self.restart_confirm_ticks = restart_confirm_ticks
        # a game also starts on a confirmed full rack (many reds), so we still
        # count games when the model never fires the game_start class.
        self.rack_red_threshold = rack_red_threshold
        self.min_game_sec = min_game_sec        # ignore end signals before this
        self.max_game_sec = max_game_sec        # force-end after this
        self.state = SEARCH
        self.game_number = 0
        self.game_start_ts: Optional[str] = None
        # streak counters
        self._start_streak = 0
        self._low_red_streak = 0
        self._no_red_streak = 0
        self._high_red_streak = 0

    def update(self, ts: str, red_count: int, colored_present: bool,
               game_start: bool, player: bool) -> list[GameEvent]:
        """Feed one tick's observation. Returns any game events emitted."""
        events: list[GameEvent] = []
        elapsed = _secs(self.game_start_ts, ts) if self.game_start_ts else 0.0

        if self.state == SEARCH:
            # a new game = a detected rack (game_start) OR a confirmed full rack
            # of reds (fallback for when the model misses the game_start class)
            is_rack = game_start or red_count >= self.rack_red_threshold
            self._start_streak = self._start_streak + 1 if is_rack else 0
            if self._start_streak >= self.confirm_ticks:
                events.append(self._begin_game(ts))

        elif self.state == IN_GAME:
            if elapsed >= self.max_game_sec:
                events.append(self._end_game(ts))
                self.state = WAIT_PLAYER
            elif elapsed >= self.min_game_sec and red_count < 2 and colored_present \
                    and not game_start:
                self._low_red_streak += 1
                if self._low_red_streak >= self.end_hold_ticks:
                    self.state = CHECK_END
                    self._low_red_streak = 0
                    self._no_red_streak = 0
                    self._high_red_streak = 0
            else:
                self._low_red_streak = 0
            # game_start is intentionally ignored while IN_GAME

        elif self.state == CHECK_END:
            if red_count > 8:
                self._high_red_streak += 1
                if self._high_red_streak >= self.restart_confirm_ticks:
                    # a fresh rack mid-way -> the previous game ended, a new one began
                    events.append(self._end_game(ts))
                    events.append(self._begin_game(ts))
                    self._high_red_streak = 0
            elif red_count > 0:
                self.state = IN_GAME               # balls still in play; not ended
                self._no_red_streak = 0
                self._high_red_streak = 0
            else:  # red_count == 0
                self._high_red_streak = 0
                self._no_red_streak += 1
                if self._no_red_streak >= self.end_hold_ticks:
                    events.append(self._end_game(ts))
                    self.state = WAIT_PLAYER
                    self._no_red_streak = 0

        elif self.state == WAIT_PLAYER:
            if player:
                self.state = SEARCH
                self._start_streak = 0

        return events

    # -- helpers -----------------------------------------------------------

    def _begin_game(self, ts: str) -> GameEvent:
        self.game_number += 1
        self.game_start_ts = ts
        self.state = IN_GAME
        self._start_streak = 0
        self._low_red_streak = self._no_red_streak = self._high_red_streak = 0
        return GameEvent("game_start", ts, self.game_number)

    def _end_game(self, ts: str) -> GameEvent:
        n = self.game_number
        self.game_start_ts = None
        return GameEvent("game_end", ts, n)
