"""Venue administration: rename, and delete-for-real.

Deleting a venue is not one DELETE. The *config* tree (business units, spaces,
video sources, asset types, assets, zones, sensors) cascades from `venues` via
foreign keys, but the *history* tables — events, sessions, metric samples,
rules, notifications — only carry a bare `venue_id TEXT` with no reference, so
a plain delete leaves every one of their rows behind.

That matters more than tidiness: those orphans still answer venue-scoped
queries. Analytics, the games log and the reconciliation web app would keep
counting sessions belonging to a venue that no longer exists, and the numbers
would be wrong in a way nothing on screen explains.

So `purge_venue` removes the history first, then the venue, then the evidence
snapshots on disk, and reports exactly what it removed.
"""
from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def _now() -> str:
    """Match Repository's stamp format exactly - SQLite's datetime('now') writes
    'YYYY-MM-DD HH:MM:SS', which sorts differently from the ISO-8601 strings
    every other row carries."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# History tables keyed by a bare venue_id (no FK, so no cascade). Order is not
# significant - nothing here references anything else here.
_HISTORY_TABLES = ("notifications", "rules", "metric_samples", "sessions", "events")


def _venue_row(cur, venue_id: str) -> Optional[dict]:
    cur.execute("SELECT id, name FROM venues WHERE id = ?", (venue_id,))
    row = cur.fetchone()
    return {"id": row[0], "name": row[1]} if row else None


def venue_contents(db, venue_id: str, snapshot_dir: str = "snapshots") -> Optional[dict]:
    """What a purge would remove, without removing it. Powers the confirm step —
    'delete Strikee Club?' is a very different question from 'delete Strikee
    Club, 4 tables and 1,182 events?'"""
    with db.cursor() as cur:
        venue = _venue_row(cur, venue_id)
        if venue is None:
            return None
        counts: dict[str, int] = {}
        for table in ("assets", "video_sources", "business_units") + _HISTORY_TABLES:
            cur.execute(f"SELECT COUNT(*) FROM {table} WHERE venue_id = ?", (venue_id,))
            counts[table] = int(cur.fetchone()[0])
    snap = Path(snapshot_dir) / venue_id
    counts["snapshots"] = sum(1 for _ in snap.rglob("*.jpg")) if snap.is_dir() else 0
    return {"venue": venue, "counts": counts}


def purge_venue(db, venue_id: str, snapshot_dir: str = "snapshots") -> Optional[dict]:
    """Delete a venue, everything it owns, and its evidence snapshots.

    Returns the removed counts, or None if the venue does not exist. History is
    deleted before the venue row so that a failure part-way leaves a venue whose
    history is short - recoverable and visible - rather than an invisible venue
    whose history still skews every query.
    """
    with db.cursor() as cur:
        venue = _venue_row(cur, venue_id)
        if venue is None:
            return None

        removed: dict[str, int] = {}
        for table in _HISTORY_TABLES:
            cur.execute(f"DELETE FROM {table} WHERE venue_id = ?", (venue_id,))
            removed[table] = cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0

        # Config tree goes with the venue row via ON DELETE CASCADE (db.py sets
        # PRAGMA foreign_keys = ON, without which SQLite would silently skip it).
        cur.execute("DELETE FROM venues WHERE id = ?", (venue_id,))
        removed["venues"] = 1

    snap = Path(snapshot_dir) / venue_id
    if snap.is_dir():
        removed["snapshots"] = sum(1 for _ in snap.rglob("*.jpg"))
        shutil.rmtree(snap, ignore_errors=True)
    else:
        removed["snapshots"] = 0

    return {"venue": venue, "removed": removed}


def rename_venue(db, venue_id: str, name: str, rename_org: bool = True) -> Optional[dict]:
    """Rename a venue, and by default its organization with it.

    field_setup.py creates the organization with the same name as the venue, so
    renaming only the venue leaves an organization still called 'Strikee Club
    Test' behind the scenes - and that stale name is what a fresh venue would
    later be matched against.
    """
    name = (name or "").strip()
    if not name:
        raise ValueError("name must not be empty")

    with db.cursor() as cur:
        cur.execute("SELECT id, name, organization_id FROM venues WHERE id = ?", (venue_id,))
        row = cur.fetchone()
        if row is None:
            return None
        old_name, org_id = row[1], row[2]

        now = _now()
        cur.execute(
            "UPDATE venues SET name = ?, updated_at = ? WHERE id = ?",
            (name, now, venue_id),
        )
        renamed_org = False
        if rename_org and org_id:
            cur.execute("SELECT name FROM organizations WHERE id = ?", (org_id,))
            org = cur.fetchone()
            if org and org[0] == old_name:
                cur.execute(
                    "UPDATE organizations SET name = ?, updated_at = ? WHERE id = ?",
                    (name, now, org_id),
                )
                renamed_org = True

    return {"id": venue_id, "name": name, "previous_name": old_name,
            "organization_renamed": renamed_org}
