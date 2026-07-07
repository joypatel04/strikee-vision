"""Generic CRUD repository over SQLite, driven by an EntitySpec.

Handles id/timestamp generation, JSON (de)serialization for JSON columns, and
bool<->int for bool columns. Returns plain dicts.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from .entities import EntitySpec


def new_id() -> str:
    return uuid.uuid4().hex


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Repository:
    def __init__(self, spec: EntitySpec):
        self.spec = spec

    # -- serialization helpers ---------------------------------------------

    def _encode(self, col: str, value: Any) -> Any:
        if value is None:
            return None
        if col in self.spec.json_columns:
            return json.dumps(value)
        if col in self.spec.bool_columns:
            return 1 if value else 0
        return value

    def _row_to_dict(self, row: sqlite3.Row) -> dict:
        out = dict(row)
        for col in self.spec.json_columns:
            if out.get(col) is not None:
                out[col] = json.loads(out[col])
        for col in self.spec.bool_columns:
            if out.get(col) is not None:
                out[col] = bool(out[col])
        return out

    # -- CRUD --------------------------------------------------------------

    def create(self, cur: sqlite3.Cursor, data: dict) -> dict:
        rec_id = new_id()
        ts = now_iso()
        # Only insert columns the caller actually provided, so omitted columns
        # fall back to their DB defaults (e.g. timezone, role, conf_threshold).
        cols = [c for c in self.spec.columns if c in data]
        placeholders = ", ".join(["?"] * (len(cols) + 3))
        col_names = ", ".join(["id", *cols, "created_at", "updated_at"])
        values = [rec_id]
        values += [self._encode(c, data[c]) for c in cols]
        values += [ts, ts]
        cur.execute(
            f"INSERT INTO {self.spec.table} ({col_names}) VALUES ({placeholders})",
            values,
        )
        return self.get(cur, rec_id)  # type: ignore[return-value]

    def get(self, cur: sqlite3.Cursor, rec_id: str) -> Optional[dict]:
        cur.execute(f"SELECT * FROM {self.spec.table} WHERE id = ?", (rec_id,))
        row = cur.fetchone()
        return self._row_to_dict(row) if row else None

    def list(self, cur: sqlite3.Cursor, filters: Optional[dict] = None) -> list[dict]:
        where, values = "", []
        if filters:
            clauses = []
            for param, col in self.spec.parents.items():
                if filters.get(param) is not None:
                    clauses.append(f"{col} = ?")
                    values.append(filters[param])
            if clauses:
                where = " WHERE " + " AND ".join(clauses)
        cur.execute(
            f"SELECT * FROM {self.spec.table}{where} ORDER BY created_at", values
        )
        return [self._row_to_dict(r) for r in cur.fetchall()]

    def update(self, cur: sqlite3.Cursor, rec_id: str, data: dict) -> Optional[dict]:
        fields = {k: v for k, v in data.items() if k in self.spec.columns}
        if not fields:
            return self.get(cur, rec_id)
        sets = ", ".join([f"{c} = ?" for c in fields] + ["updated_at = ?"])
        values = [self._encode(c, v) for c, v in fields.items()]
        values.append(now_iso())
        values.append(rec_id)
        cur.execute(
            f"UPDATE {self.spec.table} SET {sets} WHERE id = ?", values
        )
        if cur.rowcount == 0:
            return None
        return self.get(cur, rec_id)

    def delete(self, cur: sqlite3.Cursor, rec_id: str) -> bool:
        cur.execute(f"DELETE FROM {self.spec.table} WHERE id = ?", (rec_id,))
        return cur.rowcount > 0
