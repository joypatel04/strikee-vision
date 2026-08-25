"""Wipe local state so the box can be set up from scratch.

The usual reason: an embedded replica cannot adopt a database that plain SQLite
created. Run field_setup.py before configuring Turso and you get a strikee.db
with no replica metadata beside it, and libsql then refuses it with "local state
is incorrect - db file exists but metadata file does not". There is no repair;
the file has to go and be recreated by libsql itself.

    python tools/fresh_start.py            # show what would be removed
    python tools/fresh_start.py --yes      # actually remove it

Nothing here touches the cloud. A Turso database keeps whatever it already has,
and uploaded snapshots stay in their bucket - this only clears the local box.

ORDER MATTERS afterwards: put the Turso settings in .env BEFORE running
field_setup.py. The first process to create strikee.db decides what kind of
database it is, and if that is plain SQLite you are straight back here.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path


def _size(path: Path) -> int:
    try:
        if path.is_file():
            return path.stat().st_size
        return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    except OSError:
        return 0


def _human(n: int) -> str:
    return f"{n/1e6:.1f} MB" if n >= 1e6 else f"{n/1e3:.1f} KB"


def targets(db_path: str, snapshot_dir: str) -> list[tuple[Path, str]]:
    """Everything a fresh start removes, with why."""
    db = Path(db_path)
    out: list[tuple[Path, str]] = []

    # The database and every sidecar libsql/sqlite keeps beside it: -wal, -shm,
    # -info, -client_wal_index. Leaving one behind reproduces the same error.
    if db.parent.exists():
        for f in sorted(db.parent.glob(db.name + "*")):
            out.append((f, "database" if f.name == db.name else "database sidecar"))

    snaps = Path(snapshot_dir)
    if snaps.exists():
        out.append((snaps, "evidence snapshots"))

    for f in sorted(Path(".").glob("debug_*.csv")):
        out.append((f, "debug log"))

    return out


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Remove local database, snapshots and debug logs for a clean setup.")
    ap.add_argument("--yes", action="store_true", help="actually delete (default: dry run)")
    ap.add_argument("--db", default=os.environ.get("STRIKEE_DB", "strikee.db"))
    ap.add_argument("--snapshots", default=os.environ.get("STRIKEE_SNAPSHOT_DIR", "snapshots"))
    ap.add_argument("--keep-snapshots", action="store_true",
                    help="keep evidence images (they are not what breaks a replica)")
    args = ap.parse_args()

    if not Path("pyproject.toml").is_file():
        print("Run this from the local-core directory.", file=sys.stderr)
        return 2

    items = [(p, why) for p, why in targets(args.db, args.snapshots)
             if not (args.keep_snapshots and why == "evidence snapshots")]

    if not items:
        print("Nothing to remove - this box is already clean.")
        return 0

    total = 0
    print("Would remove:" if not args.yes else "Removing:")
    for path, why in items:
        n = _size(path)
        total += n
        kind = "dir " if path.is_dir() else "file"
        print(f"  {kind} {str(path):40} {_human(n):>10}   {why}")
    print(f"  {'':45} {_human(total):>10}   total")

    if not args.yes:
        print("\nDry run. Re-run with --yes to delete.")
        print("Stop strikee-core first, or the files will be recreated as you delete them.")
        return 0

    failed = []
    for path, _ in items:
        try:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
        except OSError as exc:
            failed.append((path, exc))

    if failed:
        print("\nCould not remove:")
        for path, exc in failed:
            print(f"  {path}: {exc}")
        print("\nUsually means strikee-core is still running and holding the file.")
        return 1

    print("""
Done. Set up in THIS order - it matters:

  1. Put your settings in .env FIRST, including the Turso ones. The first
     process to create strikee.db decides what kind of database it is, and a
     plain SQLite file is what caused this.

  2. Confirm they are live:
       .venv\\Scripts\\strikee-core.exe
     Dashboard -> System check -> every setting should read "env file", the
     database row should say the cloud backend, and there should be no red
     warnings. Stop it again once that looks right.

  3. Draw the zones:
       .venv\\Scripts\\python.exe field_setup.py --source "<rtsp url>" --venue "Strikee Club" --source-name "Channel 1"
     Repeat for each channel, same --venue every time.

  4. Start it and check the banner is clear.
""")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
