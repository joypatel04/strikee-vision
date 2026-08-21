"""Guided venue setup for a field test.

One command that: (1) grabs a frame from the camera, (2) lets you draw a zone
around each table/station, and (3) writes the full venue config (org → venue →
space → video source → asset type → assets → zones → sensors) into the local
database. Afterwards, launch `strikee-core` and press "Start pipeline".

Needs the perception extra (OpenCV):  pip install -e ".[perception]"

Examples:
    python field_setup.py --source "rtsp://user:pass@CAM_IP:554/stream1" --venue "Strikee Club"
    python field_setup.py --source clip.mp4 --venue "Test"     # dry run on a file
    python field_setup.py --source 0 --venue "Webcam test"     # webcam

Controls while drawing:
    left click   add a point       n   finish + name this table
    u   undo last point            s   save all + write config
    q   quit without saving
"""
from __future__ import annotations

import argparse
import os
import sys

from app.db import Database
from app.entities import REGISTRY
from app.platform_env import harden
from app.repository import Repository

# Windows: legacy console code page + OpenCV/HEVC RTSP quirks, before we print
# anything or open a stream.
harden()


def open_source(source: str):
    import cv2
    cap = cv2.VideoCapture(int(source)) if source.isdigit() \
        else cv2.VideoCapture(source, cv2.CAP_FFMPEG)
    try:
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    except Exception:
        pass
    return cap


def grab_frame(source: str):
    cap = open_source(source)
    if not cap.isOpened():
        print(f"ERROR: could not open source: {source}", file=sys.stderr)
        print("  RTSP? check the URL/credentials and that you're on the venue network.",
              file=sys.stderr)
        sys.exit(1)
    for _ in range(5):
        cap.grab()
    ok, frame = cap.read()
    cap.release()
    if not ok or frame is None:
        print("ERROR: opened the source but could not read a frame.", file=sys.stderr)
        sys.exit(2)
    return frame


def draw_zones(frame) -> list[dict]:
    """Interactive polygon drawing. Returns [{name, polygon}, ...]."""
    import cv2
    import numpy as np

    zones: list[dict] = []
    points: list[list[int]] = []
    window = "Draw a zone per table — click, 'n' name, 'u' undo, 's' save, 'q' quit"

    def redraw():
        canvas = frame.copy()
        for z in zones:
            poly = np.array(z["polygon"], dtype=np.int32)
            cv2.polylines(canvas, [poly], True, (0, 200, 0), 2)
            cx, cy = poly.mean(axis=0).astype(int)
            cv2.putText(canvas, z["name"], (cx - 40, cy),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 200, 0), 2)
        for i, p in enumerate(points):
            cv2.circle(canvas, tuple(p), 4, (0, 255, 255), -1)
            if i:
                cv2.line(canvas, tuple(points[i - 1]), tuple(p), (0, 255, 255), 2)
        cv2.imshow(window, canvas)

    def on_mouse(event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            points.append([x, y])
            redraw()

    cv2.namedWindow(window)
    cv2.setMouseCallback(window, on_mouse)
    redraw()
    print("Draw a polygon around each table's play area (where players stand).")

    while True:
        key = cv2.waitKey(20) & 0xFF
        if key == ord("u") and points:
            points.pop(); redraw()
        elif key == ord("n"):
            if len(points) >= 3:
                name = input("Table/station name (e.g. 'Snooker Table 1'): ").strip() \
                    or f"Asset {len(zones)+1}"
                zones.append({"name": name, "polygon": list(points)})
                points.clear(); redraw()
                print(f"  added '{name}' ({len(zones)} total)")
            else:
                print("  need at least 3 points first")
        elif key == ord("s"):
            if len(points) >= 3:
                print("  finish the current polygon with 'n' first (or 'u' to clear)")
                continue
            break
        elif key == ord("q"):
            zones = []
            break
    cv2.destroyAllWindows()
    return zones


def _find(repo, cur, **match):
    """First row whose fields all equal `match`, else None. The config tables hold
    a handful of rows, so scanning them is cheaper than adding query plumbing."""
    for row in repo.list(cur):
        if all(row.get(k) == v for k, v in match.items()):
            return row
    return None


def write_config(db_path, source, venue_name, source_name, bu_name,
                 asset_type_name, zones, mode="snooker_game") -> str:
    """Write (or extend) a venue config.

    A venue usually has several cameras, and you draw one channel per run - so
    everything above the camera is reused when it already exists. Creating a
    fresh venue per run (the old behaviour) scattered one channel into each of
    several venues, and the dashboard could then only ever track one of them.
    """
    repos = {s.name: Repository(s) for s in REGISTRY}
    db = Database(db_path)
    with db.cursor() as cur:
        venue = _find(repos["venue"], cur, name=venue_name)
        if venue is None:
            org = repos["organization"].create(cur, {"name": venue_name})
            venue = repos["venue"].create(cur, {"organization_id": org["id"],
                                                "name": venue_name})
        else:
            print(f"  reusing existing venue '{venue_name}'")

        bu = _find(repos["business_unit"], cur, venue_id=venue["id"], name=bu_name)
        if bu is None:
            bu = repos["business_unit"].create(cur, {"venue_id": venue["id"],
                                                     "name": bu_name,
                                                     "kind": bu_name.lower()})

        space = _find(repos["space"], cur, venue_id=venue["id"], name=f"{bu_name} Area")
        if space is None:
            space = repos["space"].create(cur, {"venue_id": venue["id"],
                                                "name": f"{bu_name} Area"})

        at = _find(repos["asset_type"], cur, venue_id=venue["id"], name=asset_type_name)
        if at is None:
            at = repos["asset_type"].create(cur, {"venue_id": venue["id"],
                                                  "name": asset_type_name})

        src = _find(repos["video_source"], cur, venue_id=venue["id"], uri=source)
        if src is None:
            src = repos["video_source"].create(cur, {"venue_id": venue["id"],
                                                     "space_id": space["id"],
                                                     "name": source_name, "uri": source})
        else:
            print(f"  camera already configured as '{src['name']}' - adding these "
                  f"zones to it (re-running the same channel adds duplicates)")

        for z in zones:
            asset = repos["asset"].create(cur, {
                "venue_id": venue["id"], "space_id": space["id"],
                "business_unit_id": bu["id"], "asset_type_id": at["id"], "name": z["name"]})
            zone = repos["zone"].create(cur, {"space_id": space["id"],
                                              "name": f"{z['name']} Zone",
                                              "polygons": [z["polygon"]]})
            repos["sensor"].create(cur, {
                "asset_id": asset["id"], "video_source_id": src["id"],
                "zone_id": zone["id"], "type": mode, "role": "primary"})
    db.close()
    return venue["id"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True, help="RTSP url, file path, or webcam index")
    ap.add_argument("--venue", default="Strikee Club")
    ap.add_argument("--source-name", default="Camera 1")
    ap.add_argument("--business-unit", default="Snooker")
    ap.add_argument("--asset-type", default="Snooker Table")
    ap.add_argument("--mode", default="snooker_game",
                    choices=["snooker_game", "occupancy"],
                    help="sensor mode: snooker_game (balls, for tables) or occupancy (people)")
    ap.add_argument("--db", default=os.environ.get("STRIKEE_DB", "strikee.db"))
    args = ap.parse_args()

    print(f"Grabbing a frame from {args.source} ...")
    frame = grab_frame(args.source)
    h, w = frame.shape[:2]
    print(f"Got a {w}x{h} frame. Opening the zone editor...")
    if args.mode == "snooker_game":
        print("Mode: snooker_game — draw the zone around the TABLE surface "
              "(where the balls are).")

    zones = draw_zones(frame)
    if not zones:
        print("No zones drawn — nothing written."); return

    venue_id = write_config(args.db, args.source, args.venue, args.source_name,
                            args.business_unit, args.asset_type, zones, mode=args.mode)
    print(f"\nConfigured venue '{args.venue}' with {len(zones)} asset(s) in {args.db}")
    print(f"venue id: {venue_id}")
    print("\nNext: run  strikee-core  (or: python run_desktop.py), pick the venue,")
    print("and press 'Start pipeline'.")


if __name__ == "__main__":
    main()
