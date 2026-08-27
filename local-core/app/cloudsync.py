"""Push local rows to Turso over HTTP, keeping SQLite as the source of truth.

Turso's embedded replica would have been the neat answer - write locally, sync
transparently - but the replication endpoints are not available on every
database, and without them libsql cannot sync at all. Remote-only mode is the
obvious fallback and the wrong one: it turns every read and write into a network
call, so the dashboard slows down and a wifi blip loses a game instead of
delaying it. The venue box must never miss a rack because the internet hiccupped.

So: local SQLite stays authoritative and unchanged, and this pushes new and
changed rows up on a timer through the Hrana HTTP API - the same `/v2/pipeline`
endpoint that plain queries use, which works everywhere. Writes are upserts
keyed on each row's id, so re-sending is harmless and a failed cycle simply
retries next time.

Progress is a keyset cursor per table, (timestamp, id), stored locally in
`sync_state`. A plain "rows newer than T" watermark cannot make progress when a
batch fills with identical timestamps; the id breaks that tie.

No libsql dependency: this is urllib and JSON, which also keeps the native
client off a venue box that struggled to load one.
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# (table, column to order by). Parents first: the remote enforces the same
# foreign keys, so a child row must never arrive before its parent.
# Rows here are edited after insert (renames, review decisions), so the forward
# scan alone can miss a change - see _push_recent.
MUTABLE = {"organizations", "venues", "business_units", "spaces", "video_sources",
           "asset_types", "assets", "zones", "sensors", "rules", "sessions",
           "notifications"}

CONFIG_TABLES = [
    ("organizations", "updated_at"),
    ("venues", "updated_at"),
    ("business_units", "updated_at"),
    ("spaces", "updated_at"),
    ("video_sources", "updated_at"),
    ("asset_types", "updated_at"),
    ("assets", "updated_at"),
    ("zones", "updated_at"),
    ("sensors", "updated_at"),
    ("rules", "updated_at"),
]

# The history the reconciliation app actually reads.
HISTORY_TABLES = [
    ("events", "created_at"),        # append-only, so created_at is enough
    ("sessions", "updated_at"),      # reopened and re-statused, so updated_at
    ("notifications", "updated_at"),
]

# Several rows per asset per evaluation - roughly 2.4M rows a month at four
# tables. Nothing downstream reads them today, so they are opt-in.
OPTIONAL_TABLES = [("metric_samples", "ts")]

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _hrana_value(v):
    """Python value -> Hrana typed argument."""
    if v is None:
        return {"type": "null"}
    if isinstance(v, bool):
        return {"type": "integer", "value": str(int(v))}
    if isinstance(v, int):
        return {"type": "integer", "value": str(v)}
    if isinstance(v, float):
        return {"type": "float", "value": v}
    if isinstance(v, (bytes, bytearray)):
        import base64
        return {"type": "blob", "base64": base64.b64encode(bytes(v)).decode()}
    return {"type": "text", "value": str(v)}


def _minus_seconds(iso: str, seconds: float) -> str:
    """`iso` shifted back, or "" if it cannot be parsed (which widens the sweep,
    never narrows it - erring toward re-sending rather than losing)."""
    try:
        from datetime import timedelta
        dt = datetime.fromisoformat(iso)
        return (dt - timedelta(seconds=seconds)).isoformat(timespec="seconds")
    except (ValueError, TypeError):
        return ""


def _split_statements(sql: str) -> list[str]:
    """Split a .sql file into statements.

    Comments are stripped BEFORE splitting, because schema.sql contains prose
    like "children of Venue; a Sensor is owned by..." - splitting on ";" first
    tears those comments into fragments that then get sent to the server as if
    they were SQL.
    """
    lines = []
    for line in sql.splitlines():
        stripped = line.strip()
        if stripped.startswith("--"):
            continue
        if "--" in line:                      # trailing comment on a real line
            line = line.split("--", 1)[0]
        lines.append(line)
    return [s.strip() for s in "\n".join(lines).split(";") if s.strip()]


class CloudSyncError(RuntimeError):
    pass


class TursoPush:
    """Pushes local rows to a Turso database over the Hrana HTTP API."""

    def __init__(self, db, url: str, token: str, *, batch: int = 200,
                 include_metrics: bool = False, timeout: float = 20.0,
                 overlap_sec: float = 120.0, clock=time.monotonic):
        host = url.replace("libsql://", "").replace("https://", "").rstrip("/")
        self._endpoint = f"https://{host}/v2/pipeline"
        self._token = token
        self._db = db
        self._batch = max(1, batch)
        self._timeout = timeout
        self._overlap = overlap_sec
        self._clock = clock
        self._lock = threading.Lock()
        self._schema_done = False

        self.tables = CONFIG_TABLES + HISTORY_TABLES + (
            OPTIONAL_TABLES if include_metrics else [])

        self.host = host
        self.last_success: Optional[float] = None
        self.last_success_iso: Optional[str] = None
        self.last_error: Optional[str] = None
        self.rows_pushed = 0
        self.cycles = 0

    # --- transport --------------------------------------------------------

    def _pipeline(self, statements: list[dict]) -> list[dict]:
        """Run statements in one request. Raises on the first one that fails."""
        requests = [{"type": "execute", "stmt": s} for s in statements]
        requests.append({"type": "close"})
        body = json.dumps({"requests": requests}).encode()
        req = urllib.request.Request(self._endpoint, data=body, headers={
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        })
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                payload = json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:200]
            raise CloudSyncError(f"HTTP {exc.code}: {detail}") from exc
        except Exception as exc:
            raise CloudSyncError(f"{type(exc).__name__}: {exc}") from exc

        results = payload.get("results", [])
        for result in results:
            if result.get("type") == "error":
                message = (result.get("error") or {}).get("message", "unknown")
                raise CloudSyncError(message[:200])
        return results

    def ensure_schema(self) -> None:
        """Create the tables on the remote. Every statement is IF NOT EXISTS, so
        this is safe to repeat and cheap after the first run."""
        if self._schema_done:
            return
        statements = _split_statements(_SCHEMA_PATH.read_text(encoding="utf-8"))
        for i in range(0, len(statements), 20):
            self._pipeline([{"sql": s} for s in statements[i:i + 20]])
        self._schema_done = True

    # --- cursor -----------------------------------------------------------

    def _read_cursor(self, key: str) -> tuple:
        with self._db.cursor() as cur:
            cur.execute("SELECT cursor FROM sync_state WHERE table_name = ?", (key,))
            row = cur.fetchone()
        if not row or not row[0]:
            return {}
        try:
            return json.loads(row[0]) or {}
        except (ValueError, TypeError):
            return {}

    def _write_cursor(self, key: str, data: dict, pushed: int) -> None:
        with self._db.cursor() as cur:
            cur.execute(
                "INSERT INTO sync_state (table_name, cursor, rows_pushed, updated_at) "
                "VALUES (?,?,?,?) ON CONFLICT(table_name) DO UPDATE SET "
                "cursor=excluded.cursor, "
                "rows_pushed=sync_state.rows_pushed+excluded.rows_pushed, "
                "updated_at=excluded.updated_at",
                (key, json.dumps(data), pushed, _now_iso()),
            )

    # --- push -------------------------------------------------------------

    def _send_rows(self, table: str, columns: list[str], rows: list) -> None:
        placeholders = ", ".join(["?"] * len(columns))
        col_list = ", ".join(columns)
        self._pipeline([{
            # Upsert by id: re-sending after a failed cycle, or a session whose
            # status changed, must not duplicate or fail.
            "sql": f"INSERT OR REPLACE INTO {table} ({col_list}) VALUES ({placeholders})",
            "args": [_hrana_value(v) for v in row],
        } for row in rows])

    def _push_inserts(self, table: str) -> int:
        """Every row not yet sent, in true insertion order.

        Ordered by rowid, not (timestamp, id). Timestamps have one-second
        resolution and ids are random UUIDs, so several rows written in the same
        second sort in an order unrelated to when they arrived - advance a
        (ts, id) cursor over that and any row whose id happens to sort lower is
        skipped for good. On `events` that loses games silently. rowid is
        monotonic per insert, so it cannot.
        """
        key = f"{table}:rowid"
        sent = 0
        while True:
            after = int(self._read_cursor(key).get("rowid", 0))
            with self._db.cursor() as cur:
                cur.execute(
                    f"SELECT rowid, * FROM {table} WHERE rowid > ? "
                    f"ORDER BY rowid LIMIT ?", (after, self._batch))
                rows = cur.fetchall()
                columns = [d[0] for d in cur.description]
            if not rows:
                return sent
            last_rowid = rows[-1][0]
            self._send_rows(table, columns[1:], [list(r)[1:] for r in rows])
            self._write_cursor(key, {"rowid": last_rowid}, len(rows))
            sent += len(rows)
            if len(rows) < self._batch:
                return sent

    def _push_updates(self, table: str, order_col: str) -> int:
        """Rows changed since last time, for tables that are edited after insert.

        rowid never moves on an UPDATE, so the insert scan cannot see a session
        being closed or a booking voided. This scans by timestamp instead, and
        rewinds `overlap_sec` first: timestamps are second-resolution, so a row
        updated in the same second the scan last stopped sits exactly on the
        cursor and would be missed. Rewinding also covers an outage - the cursor
        stays where it was, so the whole gap is re-scanned when sync resumes.
        """
        if table not in MUTABLE:
            return 0                       # append-only; inserts are the whole story
        key = f"{table}:changed"
        cursor = self._read_cursor(key)
        ts = _minus_seconds(cursor.get("ts", ""), self._overlap) if cursor.get("ts") else ""
        last_id = ""
        sent = 0
        while True:
            with self._db.cursor() as cur:
                cur.execute(
                    f"SELECT * FROM {table} "
                    f"WHERE ({order_col} > ?) OR ({order_col} = ? AND id > ?) "
                    f"ORDER BY {order_col}, id LIMIT ?",
                    (ts, ts, last_id, self._batch))
                rows = cur.fetchall()
                columns = [d[0] for d in cur.description]
            if not rows:
                self._write_cursor(key, {"ts": ts}, 0)
                return sent
            index = {c: i for i, c in enumerate(columns)}
            self._send_rows(table, columns, [list(r) for r in rows])
            ts = str(rows[-1][index[order_col]])
            last_id = str(rows[-1][index["id"]])
            sent += len(rows)
            if len(rows) < self._batch:
                self._write_cursor(key, {"ts": ts}, sent)
                return sent

    def _heartbeat(self) -> None:
        """One row, rewritten each cycle, saying "sync is alive".

        The web app judges freshness with MAX(ts) FROM metric_samples, falling
        back to events. Neither works here: metric_samples is opt-in because it
        is ~2.4M rows a month, and on a quiet night events do not move either -
        so a perfectly healthy box would show as stale. A single row upserted
        under a fixed id gives an honest signal at a cost of one write.
        """
        with self._db.cursor() as cur:
            cur.execute("SELECT id FROM venues ORDER BY created_at LIMIT 1")
            row = cur.fetchone()
        if row is None:
            return
        self._pipeline([{
            "sql": "INSERT OR REPLACE INTO metric_samples "
                   "(id, venue_id, asset_id, business_unit_id, ts, metric, value) "
                   "VALUES (?, ?, NULL, NULL, ?, ?, ?)",
            "args": [_hrana_value("sync-heartbeat"), _hrana_value(row[0]),
                     _hrana_value(_now_iso()), _hrana_value("sync_heartbeat"),
                     _hrana_value(1.0)],
        }])

    def push_once(self) -> dict:
        """One full cycle across every table. Never raises."""
        with self._lock:
            stats: dict[str, int] = {}
            try:
                self.ensure_schema()
                for table, order_col in self.tables:
                    pushed = self._push_inserts(table)
                    pushed += self._push_updates(table, order_col)
                    if pushed:
                        stats[table] = pushed
                self._heartbeat()
                total = sum(stats.values())
                self.rows_pushed += total
                self.cycles += 1
                self.last_success = self._clock()
                self.last_success_iso = _now_iso()
                self.last_error = None
                return {"ok": True, "rows": total, "tables": stats}
            except Exception as exc:
                self.last_error = str(exc)[:300]
                return {"ok": False, "error": self.last_error, "tables": stats}

    # --- health -----------------------------------------------------------

    def status(self) -> dict:
        """Same shape the dashboard badge and watchdog already consume."""
        period = float(os.environ.get("STRIKEE_TURSO_SYNC_SEC", "15"))
        stale_after = max(60.0, period * 4)
        age = None if self.last_success is None else self._clock() - self.last_success
        healthy = age is not None and age <= stale_after and self.last_error is None
        return {
            "backend": "turso-push",
            "sync_enabled": True,
            "healthy": healthy,
            "seconds_since_sync": None if age is None else round(age, 1),
            "stale_after_sec": stale_after,
            "last_sync_at": self.last_success_iso,
            "rows_pushed": self.rows_pushed,
            "cycles": self.cycles,
            "host": self.host,
            "error": self.last_error,
            "message": self.last_error or (
                "pushing local rows to Turso" if healthy else "not synced yet"),
        }


def from_env(db) -> Optional[TursoPush]:
    """Build a pusher if STRIKEE_SYNC_MODE=push and credentials are present."""
    if os.environ.get("STRIKEE_SYNC_MODE", "").lower() != "push":
        return None
    url = os.environ.get("TURSO_DATABASE_URL")
    token = os.environ.get("TURSO_AUTH_TOKEN")
    if not (url and token):
        return None
    return TursoPush(
        db, url, token,
        batch=int(os.environ.get("STRIKEE_SYNC_BATCH", "200")),
        include_metrics=bool(os.environ.get("STRIKEE_SYNC_METRICS")),
    )
