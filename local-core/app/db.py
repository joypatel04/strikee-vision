"""SQLite connection and schema management for the Local Core.

Single-connection-with-lock model: fine for MVP volume (config CRUD plus a
5–10s tick). Access always goes through Database.cursor(), which commits on
success and rolls back on error.
"""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def _connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    if path != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL")
    return conn


class Database:
    def __init__(self, path: str = ":memory:"):
        self.path = path
        self._conn = _connect(path)
        self._lock = threading.Lock()
        self.init_schema()

    def init_schema(self) -> None:
        with self._lock:
            self._conn.executescript(SCHEMA_PATH.read_text())
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

    def close(self) -> None:
        self._conn.close()
