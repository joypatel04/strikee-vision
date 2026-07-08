"""SQLite → object-storage backup: consistent snapshot + best-effort upload."""
import os
import sqlite3

from app.backup import BackupConfig, snapshot_db, run_once


def _make_db(path):
    con = sqlite3.connect(path)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("CREATE TABLE games (id INTEGER, table_name TEXT)")
    con.executemany("INSERT INTO games VALUES (?, ?)",
                    [(1, "Table 1"), (2, "Table 2"), (3, "Table 3")])
    con.commit()
    con.close()


def test_snapshot_produces_queryable_copy(tmp_path):
    src = str(tmp_path / "strikee.db")
    dest = str(tmp_path / "snap.db")
    _make_db(src)
    snapshot_db(src, dest)
    assert os.path.exists(dest)
    con = sqlite3.connect(dest)
    rows = con.execute("SELECT COUNT(*) FROM games").fetchone()[0]
    names = [r[0] for r in con.execute("SELECT table_name FROM games ORDER BY id")]
    con.close()
    assert rows == 3
    assert names == ["Table 1", "Table 2", "Table 3"]


def test_snapshot_consistent_while_source_open(tmp_path):
    """Taking a snapshot while a writer connection is open (WAL) still yields a
    consistent copy — the real pipeline is always writing."""
    src = str(tmp_path / "strikee.db")
    dest = str(tmp_path / "snap.db")
    _make_db(src)
    writer = sqlite3.connect(src)
    writer.execute("INSERT INTO games VALUES (4, 'Table 4')")
    writer.commit()
    snapshot_db(src, dest)
    writer.close()
    con = sqlite3.connect(dest)
    assert con.execute("SELECT COUNT(*) FROM games").fetchone()[0] == 4
    con.close()


def test_run_once_noop_when_disabled(tmp_path):
    src = str(tmp_path / "strikee.db")
    _make_db(src)
    # no bucket configured -> disabled -> returns None, never raises
    assert run_once(src, BackupConfig()) is None


def test_run_once_missing_db_is_safe(tmp_path):
    cfg = BackupConfig(bucket="b", endpoint="https://x", prefix="p")
    assert run_once(str(tmp_path / "nope.db"), cfg) is None


def test_config_from_env(monkeypatch):
    monkeypatch.setenv("STRIKEE_BACKUP_BUCKET", "mybucket")
    monkeypatch.setenv("STRIKEE_BACKUP_ENDPOINT", "https://acct.r2.cloudflarestorage.com")
    monkeypatch.setenv("STRIKEE_BACKUP_PREFIX", "venue1")
    cfg = BackupConfig.from_env()
    assert cfg.enabled and cfg.bucket == "mybucket" and cfg.prefix == "venue1"
    assert cfg.region == "auto"
