"""Interactively draw occupancy zones (polygons) on a reference frame.

Controls (in the image window):
    left click     add a point to the current polygon
    n              finish current polygon -> prompts for a name in the terminal
    u              undo last point
    s              save all zones to zones.json and quit
    q              quit without saving

Example:
    python draw_zones.py --frame frame.jpg --out zones.json
"""
from __future__ import annotations

import argparse

import cv2
import numpy as np

from common import save_zones

points: list[list[int]] = []
zones: list[dict] = []
frame = None
window = "Draw zones - click points, 'n' name/next, 'u' undo, 's' save, 'q' quit"


def redraw():
    canvas = frame.copy()
    # existing saved zones in green
    for z in zones:
        poly = np.array(z["polygon"], dtype=np.int32)
        cv2.polylines(canvas, [poly], True, (0, 200, 0), 2)
        cx, cy = poly.mean(axis=0).astype(int)
        cv2.putText(canvas, z["name"], (cx - 40, cy), cv2.FONT_HERSHEY_SIMPLEX,
                    0.6, (0, 200, 0), 2)
    # current polygon in yellow
    for i, p in enumerate(points):
        cv2.circle(canvas, tuple(p), 4, (0, 255, 255), -1)
        if i > 0:
            cv2.line(canvas, tuple(points[i - 1]), tuple(p), (0, 255, 255), 2)
    cv2.imshow(window, canvas)


def on_mouse(event, x, y, flags, param):
    if event == cv2.EVENT_LBUTTONDOWN:
        points.append([x, y])
        redraw()


def main():
    global frame
    ap = argparse.ArgumentParser()
    ap.add_argument("--frame", required=True, help="reference image (from snapshot.py)")
    ap.add_argument("--out", default="zones.json")
    args = ap.parse_args()

    frame = cv2.imread(args.frame)
    if frame is None:
        raise SystemExit(f"Could not read frame: {args.frame}")

    cv2.namedWindow(window)
    cv2.setMouseCallback(window, on_mouse)
    redraw()
    print("Draw a polygon by clicking. Press 'n' to name & finish it. 's' to save.")

    while True:
        key = cv2.waitKey(20) & 0xFF
        if key == ord("u") and points:
            points.pop()
            redraw()
        elif key == ord("n"):
            if len(points) >= 3:
                name = input("Zone name (e.g. 'Snooker Table 1'): ").strip() or f"Zone {len(zones)+1}"
                asset_type = input("Asset type [Snooker Table]: ").strip() or "Snooker Table"
                zones.append({
                    "name": name,
                    "asset_type": asset_type,
                    "polygon": list(points),
                    "conf": 0.35,
                    "min_start_ticks": 2,
                    "min_clear_ticks": 3,
                })
                points.clear()
                redraw()
                print(f"  added '{name}' ({len(zones)} zones total)")
            else:
                print("  need at least 3 points before naming a zone")
        elif key == ord("s"):
            if points and len(points) >= 3:
                print("  (you have an unfinished polygon; press 'n' first or 'u' to clear it)")
                continue
            save_zones(args.out, zones)
            print(f"Saved {len(zones)} zones -> {args.out}")
            break
        elif key == ord("q"):
            print("Quit without saving.")
            break

    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
