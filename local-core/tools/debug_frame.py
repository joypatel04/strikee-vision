"""See exactly what each sensor sees, on a real frame, right now.

When an asset will not go occupied there are four different things it could be,
and they are indistinguishable from the dashboard:

  * the model does not detect the person at all
  * it detects them, but their point falls outside the zone
  * the zone is on the wrong camera or the wrong part of the picture
  * everything is fine and a SCREEN sensor is holding the asset closed, because
    the TV reads as off

This renders all four onto one image, using the same detectors and the same
observation functions the pipeline uses - so what you see here is what it sees.

    python tools/debug_frame.py --venue "Strikee Club"
    python tools/debug_frame.py --venue "Strikee Club" --source "Gaming Camera A"

Writes an annotated frame per camera to debug_frames/ and prints a verdict per
sensor. Green means that sensor currently reads occupied.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.platform_env import harden

harden()

from app.db import Database                      # noqa: E402
from app.entities import REGISTRY                # noqa: E402
from app.pipeline.geometry import ground_point, point_in_polygon  # noqa: E402
from app.repository import Repository            # noqa: E402

GREEN, RED, AMBER, GREY, WHITE = ((0, 220, 0), (60, 60, 240), (0, 190, 240),
                                  (150, 150, 150), (255, 255, 255))


def _aspect(raw):
    if not raw:
        return None
    try:
        return (float(raw.split(":")[0]) / float(raw.split(":")[1])
                if ":" in raw else float(raw))
    except (ValueError, ZeroDivisionError):
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--venue", help="venue name (default: the only one)")
    ap.add_argument("--source", help="only this camera, by name")
    ap.add_argument("--db", default=os.environ.get("STRIKEE_DB", "strikee.db"))
    ap.add_argument("--out", default="debug_frames")
    ap.add_argument("--aspect", default=os.environ.get("STRIKEE_PERSON_ASPECT"))
    args = ap.parse_args()

    if not Path(args.db).exists():
        print(f"{args.db} not found - run this from the local-core directory.")
        return 2

    import cv2
    from app.pipeline.capture import grab_once
    from app.pipeline.observe import (PERSON_KINDS, SCREEN_KIND, SNOOKER_KIND,
                                      observe, observe_screen)
    from app.pipeline.perception import SnookerDetector, YOLODetector

    repos = {s.name: Repository(s) for s in REGISTRY}
    db = Database(args.db)
    with db.cursor() as cur:
        venues = repos["venue"].list(cur)
        venue = next((v for v in venues if v["name"] == args.venue), None) \
            if args.venue else (venues[0] if len(venues) == 1 else None)
        if venue is None:
            print("Pick a venue with --venue. Available: "
                  + ", ".join(repr(v["name"]) for v in venues))
            return 2
        sources = [s for s in repos["video_source"].list(cur)
                   if s["venue_id"] == venue["id"]]
        assets = {a["id"]: a for a in repos["asset"].list(cur)
                  if a["venue_id"] == venue["id"]}
        zones = {z["id"]: z for z in repos["zone"].list(cur)}
        sensors = [s for s in repos["sensor"].list(cur) if s["asset_id"] in assets]
    db.close()

    if args.source:
        sources = [s for s in sources if s["name"] == args.source]
        if not sources:
            print(f"No camera named {args.source!r}.")
            return 2

    by_source = {}
    for s in sensors:
        by_source.setdefault(s["video_source_id"], []).append(s)

    kinds = {s["type"] for s in sensors}
    person_det = snooker_det = None
    print("Loading models...")
    if kinds & PERSON_KINDS:
        person_det = YOLODetector(
            os.environ.get("STRIKEE_PERSON_MODEL", "yolo11n.pt"),
            conf=float(os.environ.get("STRIKEE_PERSON_CONF", "0.25")),
            imgsz=int(os.environ.get("STRIKEE_PERSON_IMGSZ", "0")) or None,
            clahe=bool(os.environ.get("STRIKEE_PERSON_CLAHE")),
            aspect=_aspect(os.environ.get("STRIKEE_PERSON_ASPECT")))
    if SNOOKER_KIND in kinds:
        snooker_det = SnookerDetector(
            os.environ.get("STRIKEE_SNOOKER_MODEL", "best.pt"))

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    aspect = _aspect(args.aspect)
    any_problem = False

    for src in sources:
        mine = by_source.get(src["id"], [])
        if not mine:
            continue
        print(f"\n=== {src['name']} ===")
        ok, frame = grab_once(src["uri"])
        if not ok or frame is None:
            print("  OFFLINE - could not grab a frame")
            any_problem = True
            continue

        people = person_det.detect(frame) if person_det else []
        balls = snooker_det.detect(frame) if snooker_det else []
        canvas = frame.copy()

        # Every detected person, with the point that actually decides occupancy.
        for d in people:
            x1, y1, x2, y2 = (int(v) for v in d.bbox)
            cv2.rectangle(canvas, (x1, y1), (x2, y2), GREY, 1)
        for d in balls:
            x1, y1, x2, y2 = (int(v) for v in d.bbox)
            cv2.rectangle(canvas, (x1, y1), (x2, y2), AMBER, 1)

        import numpy as np
        for sensor in mine:
            zone = zones.get(sensor["zone_id"]) or {}
            polys = zone.get("polygons") or []
            asset_name = assets[sensor["asset_id"]]["name"]
            kind = sensor["type"]

            class S:      # what observe() expects
                zone_polygons = polys
                conf_threshold = sensor.get("conf_threshold") or 0.35
                params = sensor.get("params") or {}

            if kind == SCREEN_KIND:
                obs = observe_screen(frame, S())
                verdict = obs["present"]
                detail = (f"lum={obs['luminance']} (on at >= "
                          f"{S.params.get('screen_lum', os.environ.get('STRIKEE_SCREEN_LUM', 90))})")
            else:
                dets = balls if kind == SNOOKER_KIND else people
                obs = observe(kind, dets, S())
                verdict = obs["present"]
                detail = f"{obs['count']} in zone"

            colour = GREEN if verdict else RED
            for poly in polys:
                pts = np.array(poly, dtype=np.int32)
                cv2.polylines(canvas, [pts], True, colour, 2)
                x, y = pts.min(axis=0)
                cv2.putText(canvas, f"{asset_name} [{kind}] {detail}",
                            (int(x), max(14, int(y) - 6)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.45, colour, 1)

            mark = "IN USE " if verdict else "closed "
            print(f"  {mark} {asset_name:14} {kind:13} {detail}")
            if not verdict:
                any_problem = True

        # The deciding point for each person, coloured by whether ANY zone holds it.
        person_polys = [p for s in mine if s["type"] in PERSON_KINDS
                        for p in ((zones.get(s["zone_id"]) or {}).get("polygons") or [])]
        for d in people:
            gx, gy = ground_point(d.bbox)
            inside = any(point_in_polygon((gx, gy), p) for p in person_polys)
            cv2.circle(canvas, (int(gx), int(gy)), 7, GREEN if inside else RED, -1)
            cv2.circle(canvas, (int(gx), int(gy)), 7, WHITE, 1)
        if people and person_polys:
            outside = sum(1 for d in people
                          if not any(point_in_polygon(ground_point(d.bbox), p)
                                     for p in person_polys))
            if outside:
                print(f"  NOTE: {outside} of {len(people)} detected people stand "
                      f"OUTSIDE every zone on this camera (red dots)")

        if aspect:
            h = canvas.shape[0]
            canvas = cv2.resize(canvas, (int(round(h * aspect)), h))
        path = out_dir / f"{src['name'].replace(' ', '_')}.jpg"
        cv2.imwrite(str(path), canvas, [cv2.IMWRITE_JPEG_QUALITY, 88])
        print(f"  -> {path}")

    print("""
Reading the images: GREY boxes are detected people, AMBER are balls, and the
DOT on each person is the point that decides occupancy - green if it is inside
a zone, red if not. Zone outlines are green when that sensor currently reads
occupied and red when it does not.

  people detected but their dots are RED   -> the zone is in the wrong place, or
                                              drawn around the floor when they
                                              are seated (the dot lands on the seat)
  no grey boxes at all                     -> detection, not zones. Try
                                              tools/survey_cameras.py --sweep
  person dot GREEN but the asset is closed -> its SCREEN sensor is holding it
                                              shut; look at the lum= reading""")
    return 1 if any_problem else 0


if __name__ == "__main__":
    raise SystemExit(main())
