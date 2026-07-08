"""Unattended auto-start: which venues to start, and that they get started."""
import asyncio

import pytest

from app.db import Database
from app.main import _autostart_targets, _run_autostart


def _db_with_venues(ids):
    db = Database(":memory:")
    with db.cursor() as cur:
        cur.execute("INSERT INTO organizations (id, name, created_at, updated_at) "
                    "VALUES ('o1','Org','t','t')")
        for vid in ids:
            cur.execute(
                "INSERT INTO venues (id, organization_id, name, created_at, updated_at) "
                "VALUES (?, 'o1', ?, 't', 't')", (vid, vid))
    return db


def test_targets_all_returns_every_venue():
    db = _db_with_venues(["v1", "v2", "v3"])
    assert sorted(_autostart_targets(db, "all")) == ["v1", "v2", "v3"]
    db.close()


def test_targets_specific_venue():
    db = _db_with_venues(["v1"])
    assert _autostart_targets(db, "v1") == ["v1"]
    db.close()


class _FakeRuntime:
    def __init__(self, fail_on=None):
        self.started = []
        self._fail_on = fail_on or set()

    async def start(self, venue_id):
        if venue_id in self._fail_on:
            raise RuntimeError("perception not installed")
        self.started.append(venue_id)


def test_run_autostart_starts_all_targets():
    rt = _FakeRuntime()
    asyncio.run(_run_autostart(rt, ["v1", "v2"]))
    assert rt.started == ["v1", "v2"]


def test_run_autostart_skips_failures():
    # one venue can't start (e.g. no perception) -> others still start, no crash
    rt = _FakeRuntime(fail_on={"v2"})
    asyncio.run(_run_autostart(rt, ["v1", "v2", "v3"]))
    assert rt.started == ["v1", "v3"]
