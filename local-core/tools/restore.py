"""List, verify and restore the database backups in S3/R2.

A backup you have never restored is a hope, not a backup. `--verify` downloads
the latest one and checks it can actually be opened and contains the config you
would need - do that once now, while nothing is wrong, rather than finding out
on the evening the PC dies.

    python tools/restore.py --list       what backups exist
    python tools/restore.py --verify     download the latest and check it opens
    python tools/restore.py --yes        restore it over the local database

Restoring brings back everything in one step: the venue, the zones you drew, the
sensors, and all recorded history. It is the difference between "the box died"
and "the box died and I have to redraw twelve polygons".

Reads the same STRIKEE_BACKUP_* settings the uploader uses, so if backups are
being written this can read them.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.platform_env import load_env_file

load_env_file()

from app.backup import BackupConfig, _client  # noqa: E402

# Tables whose emptiness means the restore is not usable. History being empty is
# fine on a fresh venue; config being empty means there is nothing to restore.
CONFIG_TABLES = ("venues", "assets", "zones", "sensors", "video_sources")
HISTORY_TABLES = ("events", "sessions")


def _human(n):
    return f"{n/1e6:.1f} MB" if n >= 1e6 else f"{n/1e3:.1f} KB"


def list_backups(cfg):
    client = _client(cfg)
    resp = client.list_objects_v2(Bucket=cfg.bucket, Prefix=f"{cfg.prefix}/")
    items = [o for o in resp.get("Contents", []) if o["Key"].endswith(".db")]
    items.sort(key=lambda o: o["LastModified"], reverse=True)
    return items


def inspect(path):
    """What is actually inside a downloaded backup."""
    out = {"ok": False, "integrity": None, "counts": {}, "error": None}
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            out["integrity"] = conn.execute("PRAGMA integrity_check").fetchone()[0]
            for table in CONFIG_TABLES + HISTORY_TABLES:
                try:
                    out["counts"][table] = conn.execute(
                        f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                except sqlite3.Error:
                    out["counts"][table] = None      # table absent entirely
        finally:
            conn.close()
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
        return out
    out["ok"] = (out["integrity"] == "ok"
                 and all(out["counts"].get(t) for t in CONFIG_TABLES))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", action="store_true", help="show available backups")
    ap.add_argument("--verify", action="store_true",
                    help="download the latest and check it is restorable")
    ap.add_argument("--yes", action="store_true",
                    help="restore over the local database")
    ap.add_argument("--key", help="restore a specific key instead of the latest")
    ap.add_argument("--db", default=os.environ.get("STRIKEE_DB", "strikee.db"))
    args = ap.parse_args()

    cfg = BackupConfig.from_env()
    if not cfg.enabled:
        print("STRIKEE_BACKUP_BUCKET is not set, so there are no backups to read.")
        print("Set it (plus credentials) in .env and restart to start writing them.")
        return 2

    where = cfg.endpoint or "Amazon S3"
    print(f"bucket : {cfg.bucket}/{cfg.prefix}  ({where})\n")

    try:
        items = list_backups(cfg)
    except Exception as exc:
        print(f"Could not list the bucket: {type(exc).__name__}: {exc}")
        print("Check the bucket name, credentials and region.")
        return 1

    if not items:
        print("No backups found. Either none has run yet (the first is written")
        print("about 90 seconds after startup) or STRIKEE_BACKUP_EVERY_MIN is unset.")
        return 1

    if args.list or not (args.verify or args.yes):
        print(f"{len(items)} backup(s), newest first:\n")
        for o in items[:20]:
            age = datetime.now(timezone.utc) - o["LastModified"].astimezone(timezone.utc)
            hours = age.total_seconds() / 3600
            when = f"{hours:.1f}h ago" if hours < 48 else f"{hours/24:.0f}d ago"
            print(f"  {o['Key']:52} {_human(o['Size']):>10}  {when}")
        if not (args.verify or args.yes):
            print("\nRe-run with --verify to prove the latest one is restorable.")
        return 0

    key = args.key or f"{cfg.prefix}/strikee-latest.db"
    tmp = Path(tempfile.gettempdir()) / "strikee-restore-check.db"
    print(f"downloading {key} ...")
    try:
        _client(cfg).download_file(cfg.bucket, key, str(tmp))
    except Exception as exc:
        print(f"  FAILED: {type(exc).__name__}: {exc}")
        return 1
    print(f"  {_human(tmp.stat().st_size)}\n")

    report = inspect(tmp)
    if report["error"]:
        print(f"NOT RESTORABLE - could not open it: {report['error']}")
        return 1

    print(f"integrity_check: {report['integrity']}")
    for table in CONFIG_TABLES:
        n = report["counts"].get(table)
        mark = "ok " if n else "!! "
        print(f"  {mark}{table:16} {'missing' if n is None else n}")
    for table in HISTORY_TABLES:
        print(f"      {table:16} {report['counts'].get(table)}")

    if not report["ok"]:
        print("\nNOT RESTORABLE. The file opens but has no venue configuration in it,")
        print("so restoring would leave you redrawing zones anyway. Check that the")
        print("box writing these backups is the configured one.")
        return 1

    print("\nRESTORABLE - this backup contains a complete venue configuration.")

    if not args.yes:
        print("\nNothing was changed. Re-run with --yes to restore it over "
              f"{args.db}.")
        tmp.unlink(missing_ok=True)
        return 0

    target = Path(args.db)
    if target.exists():
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        aside = target.with_name(f"{target.name}.before-restore-{stamp}")
        shutil.move(str(target), str(aside))
        print(f"\nexisting database moved aside -> {aside.name}")
        for suffix in ("-wal", "-shm"):
            extra = Path(str(target) + suffix)
            if extra.exists():
                extra.unlink()
    shutil.move(str(tmp), str(target))
    print(f"restored {key} -> {target}")
    print("\nStart strikee-core and check the dashboard: the venue, its tables and "
          "stations should all be there.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
