"""SQLite / Turso connection and schema management for the Local Core.

Single-connection-with-lock model: fine for MVP volume (config CRUD plus a
5–10s tick). Access always goes through Database.cursor(), which commits on
success and rolls back on error.

Two interchangeable backends, selected by environment:
  * stdlib **sqlite3** (default) — the local-first recorder; every write lands
    on disk instantly, internet or not. Used for all tests and local dev.
  * **Turso** (libSQL embedded replica) — when TURSO_DATABASE_URL +
    TURSO_AUTH_TOKEN are set. Reads/writes hit a LOCAL replica file (so the box
    keeps working offline); Database.sync() replicates to the Turso cloud so the
    data is queryable from anywhere. libSQL returns plain tuples and a
    cumulative rowcount, so a thin adapter makes it quack like sqlite3 (dict
    rows + correct per-statement rowcount).
"""
from __future__ import annotations

import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def _sqlite_connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    if path != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL")
    return conn


def _turso_env():
    """Credentials for the libsql EMBEDDED REPLICA backend.

    STRIKEE_SYNC_MODE=push means local SQLite stays the source of truth and
    app/cloudsync.py pushes rows up over HTTP instead - so the same
    TURSO_* variables must NOT also make this open a replica.
    """
    if os.environ.get("STRIKEE_SYNC_MODE", "").lower() in ("push", "off"):
        return None
    url = os.environ.get("TURSO_DATABASE_URL")
    tok = os.environ.get("TURSO_AUTH_TOKEN")
    return (url, tok) if url and tok else None


# --- libSQL adapter: make libsql tuples/rowcount behave like sqlite3 --------

class _Row:
    """sqlite3.Row-like: supports row[i], row['col'], dict(row), .get(), keys()."""
    __slots__ = ("_vals", "_map")

    def __init__(self, cols, vals):
        self._vals = vals
        self._map = {c: v for c, v in zip(cols, vals)}

    def keys(self):
        return list(self._map)

    def get(self, key, default=None):
        return self._map.get(key, default)

    def __getitem__(self, key):
        return self._vals[key] if isinstance(key, int) else self._map[key]

    def __iter__(self):
        return iter(self._vals)

    def __len__(self):
        return len(self._vals)


def _colnames(description):
    return [d[0] for d in description] if description else []


def _is_read(sql: str) -> bool:
    head = sql.lstrip().lower()
    return head.startswith(("select", "pragma", "explain", "with"))


class _LibsqlCursor:
    """Wraps a libsql cursor: dict rows + correct per-statement rowcount.

    libsql's own `rowcount` is cumulative total-changes (a no-match DELETE still
    reports the running total), which would break our `rowcount == 0` checks for
    404/not-found. So after each write we read SQLite's `changes()` for the real
    per-statement count.
    """

    def __init__(self, raw, conn):
        self._raw = raw
        self._conn = conn
        self._rowcount = -1

    def execute(self, sql, params=()):
        self._raw.execute(sql, params)
        if _is_read(sql):
            self._rowcount = -1
        else:
            try:
                c = self._conn.cursor()
                c.execute("SELECT changes()")
                self._rowcount = c.fetchone()[0]
            except Exception:
                self._rowcount = -1
        return self

    def executemany(self, sql, seq):
        self._raw.executemany(sql, seq)
        self._rowcount = -1
        return self

    @property
    def description(self):
        return self._raw.description

    @property
    def lastrowid(self):
        return self._raw.lastrowid

    @property
    def rowcount(self):
        return self._rowcount

    def fetchone(self):
        row = self._raw.fetchone()
        return None if row is None else _Row(_colnames(self._raw.description), row)

    def fetchall(self):
        cols = _colnames(self._raw.description)
        return [_Row(cols, r) for r in self._raw.fetchall()]

    def fetchmany(self, size=1):
        cols = _colnames(self._raw.description)
        return [_Row(cols, r) for r in self._raw.fetchmany(size)]

    def close(self):
        try:
            self._raw.close()
        except Exception:
            pass


class _LibsqlConn:
    """Wraps a libsql connection to expose the sqlite3-connection surface the
    Database uses, plus sync()."""

    def __init__(self, raw):
        self._raw = raw

    def cursor(self):
        return _LibsqlCursor(self._raw.cursor(), self._raw)

    def executescript(self, sql):
        self._raw.executescript(sql)
        return self

    def commit(self):
        self._raw.commit()

    def rollback(self):
        try:
            self._raw.rollback()
        except Exception:
            pass

    def sync(self):
        self._raw.sync()

    def close(self):
        self._raw.close()


class Database:
    def __init__(self, path: str = ":memory:"):
        self.path = path
        self._lock = threading.Lock()
        self.backend = "sqlite3"

        # sync-health bookkeeping (used by sync_status() so the dashboard can
        # show "last synced Xs ago" and warn if tracking stops reaching cloud)
        self._sync_success_ts: float | None = None
        self._sync_attempt_ts: float | None = None
        self._sync_fail_streak = 0
        self._sync_ok_count = 0
        self._sync_last_error: str | None = None

        turso = _turso_env()
        # STRIKEE_LIBSQL_LOCAL runs the libsql backend against a LOCAL file with
        # NO cloud sync — same client + adapter as Turso, minus the network. Use
        # it to verify the native client works (esp. on Windows) before adding
        # cloud credentials.
        local_libsql = os.environ.get("STRIKEE_LIBSQL_LOCAL")
        if path != ":memory:" and (turso or local_libsql):
            import libsql  # lazy, optional dependency
            try:
                if turso:
                    url, token = turso
                    raw = libsql.connect(path, sync_url=url, auth_token=token)
                    self.backend = "turso"
                else:
                    raw = libsql.connect(path)
                    self.backend = "libsql-local"
            except Exception as exc:
                # An embedded replica keeps metadata beside the database file and
                # will not adopt one that plain SQLite created - which is what you
                # get by running field_setup.py before configuring Turso. libsql
                # reports this as "local state is incorrect", which does not
                # suggest the fix, and there is no repair: the file must be
                # recreated by libsql itself.
                text = str(exc).lower()
                if "local state" in text or "metadata file" in text:
                    raise RuntimeError(
                        f"{path} was created by plain SQLite, so it cannot be used "
                        f"as a Turso replica ({exc}).\n"
                        f"Clear the local database and let libsql recreate it:\n"
                        f"    python tools/fresh_start.py --yes\n"
                        f"Then set the Turso values in .env BEFORE running "
                        f"field_setup.py - whatever creates the file first decides "
                        f"what kind of database it is."
                    ) from exc
                raise
            try:
                raw.execute("PRAGMA foreign_keys = ON")   # match sqlite3: enforce FKs/cascade
            except Exception:
                pass
            self._conn = _LibsqlConn(raw)
            if self.backend == "turso":
                self.sync()             # pull remote state first (best-effort)
        else:
            self._conn = _sqlite_connect(path)

        self.init_schema()
        if self.backend == "turso":
            self.sync()                 # push local schema up (best-effort)

    def init_schema(self) -> None:
        with self._lock:
            self._conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
            self._conn.commit()

    @contextmanager
    def cursor(self):
        """Yield a cursor inside a locked transaction."""
        with self._lock:
            cur = self._conn.cursor()
            try:
                yield cur
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
            finally:
                cur.close()

    def sync(self) -> bool:
        """Replicate the local Turso replica to the cloud. Best-effort — returns
        True on success, False if offline/unconfigured. No-op for sqlite3.
        Records health so sync_status() can report it."""
        fn = getattr(self._conn, "sync", None)
        if fn is None:
            return False
        self._sync_attempt_ts = time.time()
        try:
            fn()
            self._sync_success_ts = time.time()
            self._sync_fail_streak = 0
            self._sync_ok_count += 1
            self._sync_last_error = None
            return True
        except Exception as exc:
            self._sync_fail_streak += 1
            self._sync_last_error = str(exc)[:200]
            return False

    def sync_status(self) -> dict:
        """Health of the cloud sync, for the dashboard. For sqlite3 (no cloud)
        `sync_enabled` is False. `healthy` means a sync succeeded recently — if
        it goes False, tracking data has stopped reaching the cloud."""
        if getattr(self._conn, "sync", None) is None:
            return {"backend": self.backend, "sync_enabled": False,
                    "healthy": True, "message": "local only (no cloud sync)"}
        now = time.time()
        period = float(os.environ.get("STRIKEE_TURSO_SYNC_SEC", "15"))
        stale_after = max(60.0, period * 4)      # a few missed cycles = a problem
        age = (now - self._sync_success_ts) if self._sync_success_ts else None
        healthy = age is not None and age <= stale_after and self._sync_fail_streak == 0

        def _iso(ts):
            return datetime.fromtimestamp(ts, timezone.utc).astimezone().isoformat(
                timespec="seconds") if ts else None

        return {
            "backend": self.backend,
            "sync_enabled": True,
            "healthy": healthy,
            "seconds_since_sync": round(age, 1) if age is not None else None,
            "stale_after_sec": stale_after,
            "last_success_at": _iso(self._sync_success_ts),
            "last_attempt_at": _iso(self._sync_attempt_ts),
            "consecutive_failures": self._sync_fail_streak,
            "sync_count": self._sync_ok_count,
            "last_error": self._sync_last_error,
        }

    def close(self) -> None:
        self._conn.close()
