"""Turso/libSQL backend: the adapter that makes libsql behave like sqlite3
(dict rows + correct per-statement rowcount), and backend selection.

The adapter tests use libsql in LOCAL-FILE mode (no cloud token needed), which
exercises the exact wrapper the Turso path uses."""
import pytest

from app.db import Database, _LibsqlConn


def test_default_backend_is_sqlite3():
    db = Database(":memory:")
    assert db.backend == "sqlite3"
    assert db.sync() is False          # no-op on sqlite3
    db.close()


def test_memory_stays_sqlite3_even_with_turso_env(monkeypatch):
    monkeypatch.setenv("TURSO_DATABASE_URL", "libsql://example.turso.io")
    monkeypatch.setenv("TURSO_AUTH_TOKEN", "tok")
    db = Database(":memory:")            # :memory: never uses the replica
    assert db.backend == "sqlite3"
    db.close()


# --- the libsql adapter (local-file mode, no cloud) -------------------------

libsql = pytest.importorskip("libsql")


@pytest.fixture
def lconn(tmp_path):
    raw = libsql.connect(str(tmp_path / "t.db"))
    conn = _LibsqlConn(raw)
    conn.executescript(
        "CREATE TABLE games (id INTEGER PRIMARY KEY, name TEXT, reds INTEGER);")
    conn.commit()
    yield conn
    conn.close()


def test_rows_behave_like_sqlite3_row(lconn):
    cur = lconn.cursor()
    cur.executemany("INSERT INTO games (id, name, reds) VALUES (?, ?, ?)",
                    [(1, "Table 1", 15), (2, "Table 2", 7)])
    lconn.commit()
    cur = lconn.cursor()
    cur.execute("SELECT * FROM games ORDER BY id")
    rows = cur.fetchall()
    r = rows[0]
    assert r["name"] == "Table 1"          # by column name
    assert r[0] == 1                        # by index
    assert dict(r) == {"id": 1, "name": "Table 1", "reds": 15}   # dict(row)
    assert r.get("missing", "d") == "d"     # .get with default
    assert sorted(r.keys()) == ["id", "name", "reds"]


def test_rowcount_is_per_statement_not_cumulative(lconn):
    cur = lconn.cursor()
    cur.executemany("INSERT INTO games (id, name) VALUES (?, ?)",
                    [(1, "a"), (2, "b"), (3, "c")])
    lconn.commit()
    cur = lconn.cursor()
    cur.execute("DELETE FROM games WHERE id = ?", (2,))
    assert cur.rowcount == 1                # matched one row
    cur.execute("DELETE FROM games WHERE id = ?", (99,))
    assert cur.rowcount == 0                # <-- the fix: NOT the running total
    cur.execute("UPDATE games SET name = ? WHERE id = ?", ("x", 1))
    assert cur.rowcount == 1
    cur.execute("UPDATE games SET name = ? WHERE id = ?", ("x", 77))
    assert cur.rowcount == 0
    lconn.commit()


def test_fetchone_returns_dict_row(lconn):
    cur = lconn.cursor()
    cur.execute("INSERT INTO games (id, name) VALUES (?, ?)", (1, "Table 1"))
    lconn.commit()
    cur = lconn.cursor()
    cur.execute("SELECT * FROM games WHERE id = ?", (1,))
    row = cur.fetchone()
    assert row["name"] == "Table 1"
    cur.execute("SELECT * FROM games WHERE id = ?", (999,))
    assert cur.fetchone() is None
