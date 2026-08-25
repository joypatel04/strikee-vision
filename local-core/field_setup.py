"""Guided venue setup for a field test.

One command that: (1) grabs a frame from the camera, (2) lets you draw a zone
around each table/station, and (3) writes the full venue config (org → venue →
space → video source → asset type → assets → zones → sensors) into the local
database. Afterwards, launch `strikee-core` and press "Start pipeline".

Needs the perception extra (OpenCV):  pip install -e ".[perception]"

Examples:
    python field_setup.py --source "rtsp://user:pass@CAM_IP:554/stream1" --venue "Strikee Club"

    # a second business unit in the SAME venue (snooker + gaming side by side):
    python field_setup.py --source "rtsp://...channel=9..." --venue "Strikee Club" \
        --business-unit "Gaming Lounge" --asset-type "Gaming Station" \
        --mode occupancy --source-name "Gaming Camera A"
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


def draw_zones(frame, max_w: int = 1280, max_h: int = 720) -> list[dict]:
    """Interactive polygon drawing. Returns [{name, polygon}, ...].

    The DVR's main stream is 960x1080 - taller than most screens once the title
    bar and taskbar are accounted for - so at native size the bottom of the table
    is off-screen and unclickable. We shrink the *display* to fit and convert
    every click back, so polygons are always stored in ORIGINAL frame
    coordinates. That matters: the pipeline applies these zones to full-size
    frames, so display-space points would silently mis-place every zone.
    """
    import cv2
    import numpy as np

    zones: list[dict] = []
    points: list[list[int]] = []
    window = "Draw a zone per table — click, 'n' name, 'u' undo, 's' save, 'q' quit"

    h, w = frame.shape[:2]
    scale = min(1.0, max_w / w, max_h / h)
    display = (frame if scale == 1.0
               else cv2.resize(frame, (int(w * scale), int(h * scale)),
                               interpolation=cv2.INTER_AREA))
    if scale < 1.0:
        print(f"  window scaled to {int(w*scale)}x{int(h*scale)} "
              f"({scale*100:.0f}%) to fit your screen - zones are still saved at "
              f"full {w}x{h} resolution")

    def to_disp(p):
        return (int(round(p[0] * scale)), int(round(p[1] * scale)))

    def redraw():
        canvas = display.copy()
        for z in zones:
            poly = np.array([to_disp(pt) for pt in z["polygon"]], dtype=np.int32)
            cv2.polylines(canvas, [poly], True, (0, 200, 0), 2)
            cx, cy = poly.mean(axis=0).astype(int)
            cv2.putText(canvas, z["name"], (cx - 40, cy),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 200, 0), 2)
        for i, p in enumerate(points):
            cv2.circle(canvas, to_disp(p), 4, (0, 255, 255), -1)
            if i:
                cv2.line(canvas, to_disp(points[i - 1]), to_disp(p), (0, 255, 255), 2)
        cv2.imshow(window, canvas)

    def on_mouse(event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            # back to original-frame coordinates, clamped inside the image
            ox = min(w - 1, max(0, int(round(x / scale))))
            oy = min(h - 1, max(0, int(round(y / scale))))
            points.append([ox, oy])
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
    ap.add_argument("--max-window", default="1280x720",
                    help="largest on-screen size for the editor, WxH (default "
                         "1280x720). Zones are always saved at full resolution.")
    args = ap.parse_args()

    print(f"Grabbing a frame from {args.source} ...")
    frame = grab_frame(args.source)
    h, w = frame.shape[:2]
    print(f"Got a {w}x{h} frame. Opening the zone editor...")
    if args.mode == "snooker_game":
        print("Mode: snooker_game — draw the zone around the TABLE surface "
              "(where the balls are).")
    else:
        # People are located by their FEET (the bottom edge of the detection
        # box), so a zone drawn tightly around a seat or a screen misses a
        # player whose feet fall outside it.
        print("Mode: occupancy — draw the zone around where a PERSON is, "
              "including the floor at their feet (people are placed by their "
              "feet, not their head).")

    try:
        max_w, max_h = (int(v) for v in args.max_window.lower().split("x"))
    except ValueError:
        print(f"--max-window must look like 1280x720, got {args.max_window!r}")
        sys.exit(2)
    zones = draw_zones(frame, max_w=max_w, max_h=max_h)
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
