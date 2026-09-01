"""Print everything configured, so you can see what to change before changing it.

Zones, cameras and assets are drawn once and then referred to by name for the
rest of their life - by --attach, by --redraw, by the screen pairing. Getting a
name slightly wrong is the commonest way to waste a redraw, and there was no way
to see the list.

    python tools/show_config.py
    python tools/show_config.py --venue "Strikee Club"

Prints the venue as a tree - business unit, asset, and the sensors watching it -
and ends with the exact command to redraw each camera.
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

from app.db import Database          # noqa: E402
from app.entities import REGISTRY    # noqa: E402
from app.repository import Repository  # noqa: E402


def _mask(uri: str) -> str:
    return re.sub(r"//([^:/@]+):([^@]+)@", r"//\1:***@", uri or "")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--venue", help="venue name (default: all)")
    ap.add_argument("--db", default=os.environ.get("STRIKEE_DB", "strikee.db"))
    ap.add_argument("--ids", action="store_true", help="show full ids, not short ones")
    args = ap.parse_args()

    if not Path(args.db).exists():
        print(f"{args.db} not found - run this from the local-core directory.")
        return 2

    repos = {s.name: Repository(s) for s in REGISTRY}
    db = Database(args.db)
    try:
        with db.cursor() as cur:
            venues = repos["venue"].list(cur)
            units = {u["id"]: u for u in repos["business_unit"].list(cur)}
            sources = {s["id"]: s for s in repos["video_source"].list(cur)}
            zones = {z["id"]: z for z in repos["zone"].list(cur)}
            assets = repos["asset"].list(cur)
            sensors = repos["sensor"].list(cur)
    finally:
        db.close()

    if args.venue:
        venues = [v for v in venues if v["name"] == args.venue]
        if not venues:
            print(f"No venue named {args.venue!r}.")
            return 2
    if not venues:
        print("Nothing configured yet. Run field_setup.py to draw some zones.")
        return 0

    def short(i):
        return i if args.ids else i[:8]

    by_asset = {}
    for s in sensors:
        by_asset.setdefault(s["asset_id"], []).append(s)

    for venue in venues:
        print(f"\n{venue['name']}   venue {short(venue['id'])}")
        mine = [a for a in assets if a["venue_id"] == venue["id"]]
        if not mine:
            print("  (no assets yet)")
            continue

        grouped = {}
        for a in mine:
            grouped.setdefault(a.get("business_unit_id"), []).append(a)

        for bu_id in sorted(grouped, key=lambda b: (units.get(b) or {}).get("name", "zz")):
            bu = units.get(bu_id) or {"name": "Unassigned"}
            print(f"\n  {bu['name']}")
            for asset in sorted(grouped[bu_id], key=lambda a: a["name"]):
                print(f"    {asset['name']:<20} asset {short(asset['id'])}")
                for sensor in sorted(by_asset.get(asset["id"], []),
                                     key=lambda s: s.get("type") or ""):
                    src = sources.get(sensor.get("video_source_id")) or {}
                    zone = zones.get(sensor.get("zone_id")) or {}
                    points = sum(len(p) for p in (zone.get("polygons") or []))
                    print(f"        {sensor.get('type',''):<13} "
                          f"{sensor.get('role',''):<11} "
                          f"{src.get('name','?'):<18} {points}-point zone")
                if not by_asset.get(asset["id"]):
                    print("        (no sensors - this asset is never observed)")

    used = {s.get("video_source_id") for s in sensors}
    # Two cameras with one name is easy to create - the name is a label, the url
    # is the identity - and it makes every by-name lookup ambiguous.
    seen_names = {}
    for src in sources.values():
        seen_names.setdefault(src["name"], []).append(src)
    dupes = {n: v for n, v in seen_names.items() if len(v) > 1}

    print("\n  Cameras")
    for src in sources.values():
        if args.venue and src["venue_id"] not in {v["id"] for v in venues}:
            continue
        watching = sorted({a["name"] for a in assets for s in by_asset.get(a["id"], [])
                           if s.get("video_source_id") == src["id"]})
        mark = "" if src["id"] in used else "   (nothing uses this camera)"
        print(f"    {src['name']:<20} {short(src['id'])}{mark}")
        print(f"        {_mask(src.get('uri'))}")
        print(f"        watches: {', '.join(watching) or 'nothing'}")

    if dupes:
        print("\n  DUPLICATE NAMES - by-name lookups cannot tell these apart:")
        for name, group in dupes.items():
            print(f"    {len(group)} cameras named {name!r}:")
            for src in group:
                ch = re.search(r"[?&]channel=(\d+)", src.get("uri") or "")
                where = f"channel {ch.group(1)}" if ch else _mask(src.get("uri"))
                print(f"        {short(src['id'])}  {where}")
        print("    Fix with: python tools/rename_cameras.py --auto")
        print("    (tracking is unaffected - a camera is identified by its url)")

    # The point of the listing: knowing what to type next.
    print("""
To improve a zone, redraw it in place - the asset keeps its id, so its
sessions, games and any screen sensor survive:""")
    for src in sources.values():
        if args.venue and src["venue_id"] not in {v["id"] for v in venues}:
            continue
        modes = sorted({s.get("type") for s in sensors
                        if s.get("video_source_id") == src["id"]} - {None})
        if not modes:
            continue
        venue_name = next(v["name"] for v in venues if v["id"] == src["venue_id"])
        base = (f'python field_setup.py --redraw --venue "{venue_name}" '
                f'--source-name "{src["name"]}"')

        # A camera carrying both a person zone and a screen zone is redrawn in
        # ONE pass: --with-screen asks for the seating area and then that
        # station's TV, so the name is typed once and cannot mismatch.
        person_mode = next((m for m in modes if m in ("occupancy", "presence",
                                                      "person")), None)
        if person_mode and "screen" in modes:
            print(f"\n  {src['name']}  (stations and their screens, one pass):")
            print(f"    {base} --with-screen --mode {person_mode}")
            leftover = [m for m in modes if m not in (person_mode, "screen")]
        else:
            leftover = modes

        for mode in leftover:
            print(f"\n  {src['name']}  ({mode}):")
            print(f"    {base} --mode {mode}")

    print("\n  Name each replacement polygon exactly as listed above.")
    print("  The camera is looked up by name, so no url or password is typed -")
    print("  which also keeps it out of your shell history and any screenshot.")
    print("  Add --aspect only if STRIKEE_PERSON_ASPECT is not in your .env.")
    print("  --business-unit and --asset-type are NOT needed: a redraw creates")
    print("  nothing, so it has no use for them.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
