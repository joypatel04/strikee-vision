"""Field debug log: a per-tick CSV of what the model saw and what the game
tracker decided. Enabled with STRIKEE_DEBUG=1. Lets you validate/tune a live
run without the raw video — you can see exactly why a game was (or wasn't)
counted, and which threshold to adjust.
"""
from __future__ import annotations

import csv

COLUMNS = [
    "ts", "table", "red", "colored", "game_start", "player",
    "state", "red_floor", "label", "activity", "event",
]


class DebugLog:
    def __init__(self, path: str):
        new = True
        try:
            with open(path, "r", encoding="utf-8"):
                new = False
        except OSError:
            new = True
        self._f = open(path, "a", newline="", encoding="utf-8")
        self._w = csv.writer(self._f)
        if new:
            self._w.writerow(COLUMNS)
            self._f.flush()

    def row(self, data: dict) -> None:
        self._w.writerow([data.get(c, "") for c in COLUMNS])
        self._f.flush()

    def close(self) -> None:
        try:
            self._f.close()
        except Exception:
            pass
