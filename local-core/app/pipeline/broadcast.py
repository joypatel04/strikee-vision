"""WebSocket broadcaster: tracks connections per venue and pushes state
snapshots. Kept transport-agnostic enough to unit-test with a fake socket
(anything with an async send_json)."""
from __future__ import annotations

from typing import Iterable

from .types import AssetSnapshot


def _payload(venue_id: str, snapshots: Iterable[AssetSnapshot]) -> dict:
    return {
        "type": "state",
        "venue_id": venue_id,
        "assets": [s.to_dict() for s in snapshots],
    }


class Broadcaster:
    def __init__(self):
        self._conns: dict[str, set] = {}

    def add(self, venue_id: str, ws) -> None:
        self._conns.setdefault(venue_id, set()).add(ws)

    def remove(self, venue_id: str, ws) -> None:
        self._conns.get(venue_id, set()).discard(ws)

    def count(self, venue_id: str) -> int:
        return len(self._conns.get(venue_id, set()))

    async def send_to(self, ws, venue_id: str, snapshots: Iterable[AssetSnapshot]) -> None:
        await ws.send_json(_payload(venue_id, snapshots))

    async def broadcast(self, venue_id: str, snapshots: Iterable[AssetSnapshot]) -> None:
        snaps = list(snapshots)
        dead = []
        for ws in list(self._conns.get(venue_id, set())):
            try:
                await ws.send_json(_payload(venue_id, snaps))
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.remove(venue_id, ws)
