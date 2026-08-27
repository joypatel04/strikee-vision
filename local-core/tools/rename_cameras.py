"""List and rename the video sources (cameras) in the local database.

`--source-name` in field_setup names the CAMERA, not the table, and it is easy
to type the table's name there - especially when one camera covers two tables
and neither name is right. Nothing tracks by that name, so a wrong one is
cosmetic, but it makes the config confusing to read later.

    python tools/rename_cameras.py                 show them
    python tools/rename_cameras.py --auto          rename to "Channel N" from the URI
    python tools/rename_cameras.py --set <id> "Gaming Camera A"

Only the display name changes. Zones, sensors and history are untouched: a
camera is matched by its RTSP URL, never by its name.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.platform_env import load_env_file

load_env_file()

from app.db import Database  # noqa: E402
from app.entities import REGISTRY  # noqa: E402
from app.repository import Repository  # noqa: E402

CHANNEL = re.compile(r"[?&]channel=(\d+)")


def _mask(uri: str) -> str:
    """Hide the password when printing a URL."""
    return re.sub(r"//([^:/@]+):([^@]+)@", r"//\1:***@", uri or "")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--auto", action="store_true",
                    help='rename each to "Channel N" using the channel in its URL')
    ap.add_argument("--set", nargs=2, metavar=("ID", "NAME"),
                    help="rename one source by id")
    ap.add_argument("--db", default=os.environ.get("STRIKEE_DB", "strikee.db"))
    args = ap.parse_args()

    if not Path(args.db).exists():
        print(f"{args.db} not found. Run this from the local-core directory.")
        return 2

    repos = {s.name: Repository(s) for s in REGISTRY}
    db = Database(args.db)
    try:
        with db.cursor() as cur:
            sources = repos["video_source"].list(cur)
            if not sources:
                print("No cameras configured yet.")
                return 0

            # How many assets each camera actually watches - useful context when
            # deciding what to call it.
            sensors = repos["sensor"].list(cur)
            assets = {a["id"]: a["name"] for a in repos["asset"].list(cur)}
            watching = {}
            for s in sensors:
                if s.get("video_source_id"):
                    watching.setdefault(s["video_source_id"], set()).add(
                        assets.get(s["asset_id"], "?"))

            if args.set:
                sid, new_name = args.set
                match = next((s for s in sources if s["id"].startswith(sid)), None)
                if match is None:
                    print(f"No camera whose id starts with {sid!r}.")
                    return 1
                repos["video_source"].update(cur, match["id"], {"name": new_name})
                print(f"  {match['name']!r} -> {new_name!r}")
                return 0

            renamed = 0
            for s in sources:
                ch = CHANNEL.search(s.get("uri") or "")
                suggested = f"Channel {ch.group(1)}" if ch else None
                seen = ", ".join(sorted(watching.get(s["id"], []))) or "nothing yet"

                if args.auto and suggested and suggested != s["name"]:
                    repos["video_source"].update(cur, s["id"], {"name": suggested})
                    print(f"  {s['name']!r} -> {suggested!r}   watches: {seen}")
                    renamed += 1
                elif args.auto:
                    why = "already correct" if suggested else "no channel in its URL"
                    print(f"  {s['name']!r} left alone ({why})   watches: {seen}")
                else:
                    hint = ""
                    if suggested and suggested != s["name"]:
                        hint = f"   --auto would call it {suggested!r}"
                    print(f"  {s['id'][:8]}  {s['name']!r}{hint}")
                    print(f"            {_mask(s.get('uri'))}")
                    print(f"            watches: {seen}")

            if args.auto:
                print(f"\n  renamed {renamed}")
            else:
                print("\n  Nothing changed. Add --auto to rename them from their URLs,")
                print('  or --set <id> "Some Name" for one.')
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
