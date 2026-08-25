"""The 'local state is incorrect' trap.

An embedded replica will not adopt a database plain SQLite created, which is
exactly what running field_setup.py before configuring Turso produces. libsql's
own message does not suggest a fix and there is no repair, so the app has to
say what to do.
"""
import pytest

from app.db import Database


def test_non_replica_file_gets_an_actionable_error(monkeypatch, tmp_path):
    db_file = tmp_path / "strikee.db"
    db_file.write_bytes(b"SQLite format 3\x00")

    monkeypatch.setenv("TURSO_DATABASE_URL", "libsql://x.turso.io")
    monkeypatch.setenv("TURSO_AUTH_TOKEN", "ey.token")

    class FakeLibsql:
        @staticmethod
        def connect(*a, **k):
            raise Exception("local state is incorrect. db file exists but "
                            "metadata file does not")

    import sys
    monkeypatch.setitem(sys.modules, "libsql", FakeLibsql)

    with pytest.raises(RuntimeError) as excinfo:
        Database(str(db_file))

    msg = str(excinfo.value)
    assert "fresh_start.py" in msg, "error does not tell the user how to fix it"
    assert "BEFORE running" in msg, "error does not warn about the ordering that caused it"


def test_other_libsql_errors_are_not_swallowed(monkeypatch, tmp_path):
    """Only this specific trap gets rewritten; everything else must surface as-is."""
    db_file = tmp_path / "strikee.db"
    db_file.write_bytes(b"x")
    monkeypatch.setenv("TURSO_DATABASE_URL", "libsql://x.turso.io")
    monkeypatch.setenv("TURSO_AUTH_TOKEN", "ey.token")

    class FakeLibsql:
        @staticmethod
        def connect(*a, **k):
            raise ValueError("some unrelated failure")

    import sys
    monkeypatch.setitem(sys.modules, "libsql", FakeLibsql)

    with pytest.raises(ValueError, match="some unrelated failure"):
        Database(str(db_file))
