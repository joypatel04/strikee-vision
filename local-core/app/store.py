"""Persistence for runtime facts: append-only Events and materialized Sessions.

Both stores manage their own transactions via Database.cursor().
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from .repository import new_id, now_iso

# columns copied from a state snapshot into a state_change event
_EVENT_COLS = [
    "venue_id", "asset_id", "business_unit_id", "type", "ts",
    "presence", "activity", "health", "label", "prev_label",
    "confidence", "origin", "actor", "reason", "correlation_id",
]


def _duration_sec(start_ts: str, end_ts: str) -> int:
    return int((datetime.fromisoformat(end_ts) - datetime.fromisoformat(start_ts)).total_seconds())


class EventStore:
    """Append-only. No update or delete."""

    def __init__(self, db):
        self.db = db

    def append(self, event: dict) -> dict:
        rec_id = new_id()
        created = now_iso()
        cols = [c for c in _EVENT_COLS if c in event]
        col_names = ", ".join(["id", *cols, "created_at"])
        placeholders = ", ".join(["?"] * (len(cols) + 2))
        values = [rec_id, *[event[c] for c in cols], created]
        with self.db.cursor() as cur:
            cur.execute(
                f"INSERT INTO events ({col_names}) VALUES ({placeholders})", values
            )
            cur.execute("SELECT * FROM events WHERE id = ?", (rec_id,))
            return dict(cur.fetchone())

    def list(self, venue_id: str, asset_id: Optional[str] = None,
             limit: int = 100) -> list[dict]:
        sql = "SELECT * FROM events WHERE venue_id = ?"
        args: list = [venue_id]
        if asset_id:
            sql += " AND asset_id = ?"
            args.append(asset_id)
        sql += " ORDER BY ts DESC, created_at DESC LIMIT ?"
        args.append(limit)
        with self.db.cursor() as cur:
            cur.execute(sql, args)
            return [dict(r) for r in cur.fetchall()]


class SessionStore:
    """Materialized sessions. Open on presence-present, close on presence-absent."""

    def __init__(self, db):
        self.db = db

    # -- reads -------------------------------------------------------------

    def get(self, session_id: str) -> Optional[dict]:
        with self.db.cursor() as cur:
            cur.execute("SELECT * FROM sessions WHERE id = ?", (session_id,))
            row = cur.fetchone()
            return dict(row) if row else None

    def get_open_for_asset(self, asset_id: str) -> Optional[dict]:
        with self.db.cursor() as cur:
            cur.execute(
                "SELECT * FROM sessions WHERE asset_id = ? AND end_ts IS NULL "
                "AND status != 'voided' ORDER BY start_ts DESC LIMIT 1",
                (asset_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def list(self, venue_id: str, asset_id: Optional[str] = None,
             business_unit_id: Optional[str] = None, limit: int = 100) -> list[dict]:
        sql = "SELECT * FROM sessions WHERE venue_id = ?"
        args: list = [venue_id]
        if asset_id:
            sql += " AND asset_id = ?"
            args.append(asset_id)
        if business_unit_id:
            sql += " AND business_unit_id = ?"
            args.append(business_unit_id)
        sql += " ORDER BY start_ts DESC LIMIT ?"
        args.append(limit)
        with self.db.cursor() as cur:
            cur.execute(sql, args)
            return [dict(r) for r in cur.fetchall()]

    # -- lifecycle ---------------------------------------------------------

    def open(self, venue_id: str, asset_id: str, business_unit_id: Optional[str],
             start_ts: str, confidence: float = 0.0,
             start_event_id: Optional[str] = None,
             start_snapshot: Optional[str] = None) -> dict:
        rec_id = new_id()
        ts = now_iso()
        with self.db.cursor() as cur:
            cur.execute(
                """INSERT INTO sessions
                   (id, venue_id, asset_id, business_unit_id, type, start_ts,
                    status, confidence, start_event_id, start_snapshot,
                    created_at, updated_at)
                   VALUES (?, ?, ?, ?, 'usage', ?, 'detected', ?, ?, ?, ?, ?)""",
                (rec_id, venue_id, asset_id, business_unit_id, start_ts,
                 confidence, start_event_id, start_snapshot, ts, ts),
            )
            cur.execute("SELECT * FROM sessions WHERE id = ?", (rec_id,))
            return dict(cur.fetchone())

    def close(self, session_id: str, end_ts: str,
              end_event_id: Optional[str] = None) -> Optional[dict]:
        with self.db.cursor() as cur:
            cur.execute("SELECT * FROM sessions WHERE id = ?", (session_id,))
            row = cur.fetchone()
            if row is None:
                return None
            duration = _duration_sec(row["start_ts"], end_ts)
            cur.execute(
                "UPDATE sessions SET end_ts = ?, duration_sec = ?, end_event_id = ?, "
                "updated_at = ? WHERE id = ?",
                (end_ts, duration, end_event_id, now_iso(), session_id),
            )
            cur.execute("SELECT * FROM sessions WHERE id = ?", (session_id,))
            return dict(cur.fetchone())

    # -- review ------------------------------------------------------------

    def set_status(self, session_id: str, status: str) -> Optional[dict]:
        with self.db.cursor() as cur:
            cur.execute(
                "UPDATE sessions SET status = ?, updated_at = ? WHERE id = ?",
                (status, now_iso(), session_id),
            )
            if cur.rowcount == 0:
                return None
            cur.execute("SELECT * FROM sessions WHERE id = ?", (session_id,))
            return dict(cur.fetchone())

    def correct_times(self, session_id: str, start_ts: Optional[str],
                      end_ts: Optional[str]) -> Optional[dict]:
        with self.db.cursor() as cur:
            cur.execute("SELECT * FROM sessions WHERE id = ?", (session_id,))
            row = cur.fetchone()
            if row is None:
                return None
            row = dict(row)
            # preserve originals once
            orig_start = row["orig_start_ts"] or row["start_ts"]
            orig_end = row["orig_end_ts"] or row["end_ts"]
            new_start = start_ts or row["start_ts"]
            new_end = end_ts if end_ts is not None else row["end_ts"]
            duration = _duration_sec(new_start, new_end) if new_end else None
            cur.execute(
                """UPDATE sessions SET start_ts = ?, end_ts = ?, duration_sec = ?,
                   orig_start_ts = ?, orig_end_ts = ?, status = 'corrected',
                   updated_at = ? WHERE id = ?""",
                (new_start, new_end, duration, orig_start, orig_end,
                 now_iso(), session_id),
            )
            cur.execute("SELECT * FROM sessions WHERE id = ?", (session_id,))
            return dict(cur.fetchone())


class MetricStore:
    """Writes periodic scalar samples (one row per asset per metric per tick).
    Doubles as the runtime's sampler: it exposes record(venue_id, ts, samples)."""

    def __init__(self, db):
        self.db = db

    def record(self, venue_id: str, ts: str, samples: list[dict]) -> None:
        """samples: [{asset_id, business_unit_id, metric, value}, ...]"""
        if not samples:
            return
        with self.db.cursor() as cur:
            cur.executemany(
                """INSERT INTO metric_samples
                   (id, venue_id, asset_id, business_unit_id, ts, metric, value)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                [(new_id(), venue_id, s.get("asset_id"), s.get("business_unit_id"),
                  ts, s["metric"], float(s["value"])) for s in samples],
            )

    def list(self, venue_id: str, asset_id: Optional[str] = None,
             metric: Optional[str] = None, limit: int = 500) -> list[dict]:
        sql = "SELECT * FROM metric_samples WHERE venue_id = ?"
        args: list = [venue_id]
        if asset_id:
            sql += " AND asset_id = ?"
            args.append(asset_id)
        if metric:
            sql += " AND metric = ?"
            args.append(metric)
        sql += " ORDER BY ts DESC LIMIT ?"
        args.append(limit)
        with self.db.cursor() as cur:
            cur.execute(sql, args)
            return [dict(r) for r in cur.fetchall()]


class RuleStore:
    def __init__(self, db):
        self.db = db

    def list_enabled(self, venue_id: str) -> list[dict]:
        import json
        with self.db.cursor() as cur:
            cur.execute(
                "SELECT * FROM rules WHERE venue_id = ? AND enabled = 1", (venue_id,)
            )
            rows = [dict(r) for r in cur.fetchall()]
        for r in rows:
            r["params"] = json.loads(r["params"]) if r.get("params") else {}
        return rows


class NotificationStore:
    def __init__(self, db):
        self.db = db

    def create(self, n: dict) -> dict:
        rec_id = new_id()
        ts = now_iso()
        cols = ["venue_id", "rule_id", "event_id", "asset_id", "business_unit_id",
                "severity", "status", "channel", "title", "message"]
        present = [c for c in cols if c in n]
        col_names = ", ".join(["id", *present, "created_at", "updated_at"])
        placeholders = ", ".join(["?"] * (len(present) + 3))
        values = [rec_id, *[n[c] for c in present], ts, ts]
        with self.db.cursor() as cur:
            cur.execute(
                f"INSERT INTO notifications ({col_names}) VALUES ({placeholders})",
                values,
            )
            cur.execute("SELECT * FROM notifications WHERE id = ?", (rec_id,))
            return dict(cur.fetchone())

    def get(self, notif_id: str) -> Optional[dict]:
        with self.db.cursor() as cur:
            cur.execute("SELECT * FROM notifications WHERE id = ?", (notif_id,))
            row = cur.fetchone()
            return dict(row) if row else None

    def list(self, venue_id: str, status: Optional[str] = None,
             limit: int = 100) -> list[dict]:
        sql = "SELECT * FROM notifications WHERE venue_id = ?"
        args: list = [venue_id]
        if status:
            sql += " AND status = ?"
            args.append(status)
        sql += " ORDER BY created_at DESC LIMIT ?"
        args.append(limit)
        with self.db.cursor() as cur:
            cur.execute(sql, args)
            return [dict(r) for r in cur.fetchall()]

    def last_created_at(self, rule_id: str, asset_id: Optional[str]) -> Optional[str]:
        with self.db.cursor() as cur:
            cur.execute(
                "SELECT created_at FROM notifications WHERE rule_id = ? "
                "AND (asset_id = ? OR (? IS NULL AND asset_id IS NULL)) "
                "ORDER BY created_at DESC LIMIT 1",
                (rule_id, asset_id, asset_id),
            )
            row = cur.fetchone()
            return row["created_at"] if row else None

    def acknowledge(self, notif_id: str, actor: Optional[str]) -> Optional[dict]:
        return self._transition(notif_id, "acknowledged",
                                {"acknowledged_by": actor, "acknowledged_at": now_iso()})

    def resolve(self, notif_id: str, actor: Optional[str],
                reason: Optional[str] = None) -> Optional[dict]:
        return self._transition(notif_id, "resolved",
                                {"resolved_by": actor, "resolved_at": now_iso(),
                                 "reason": reason})

    def _transition(self, notif_id: str, status: str, extra: dict) -> Optional[dict]:
        sets = ["status = ?", "updated_at = ?"] + [f"{k} = ?" for k in extra]
        values = [status, now_iso(), *extra.values(), notif_id]
        with self.db.cursor() as cur:
            cur.execute(
                f"UPDATE notifications SET {', '.join(sets)} WHERE id = ?", values
            )
            if cur.rowcount == 0:
                return None
            cur.execute("SELECT * FROM notifications WHERE id = ?", (notif_id,))
            return dict(cur.fetchone())
