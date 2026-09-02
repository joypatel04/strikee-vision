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


def draw_zones(frame, max_w: int = 1280, max_h: int = 720,
               aspect: float | None = None, paired: bool = False,
               existing: list | None = None) -> list[dict]:
    """Interactive polygon drawing. Returns [{name, polygon, kind}, ...].

    `paired` asks for TWO polygons per asset - the seating area, then that
    station's screen - naming it once. A gaming station needs both, and drawing
    them in separate passes means naming each screen to match its station
    exactly, from memory, six times. Doing it in one pass is half the work and
    removes the mismatch entirely.

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
    pending: str | None = None      # asset awaiting its screen polygon
    window = "Draw a zone per table — click, 'n' name, 'u' undo, 's' save, 'q' quit"

    h, w = frame.shape[:2]

    # Some DVR channels deliver an anamorphic frame - the picture is square but
    # the room is not, which is why it looks wrong here and right in DMSS. Draw
    # on a squeezed image and every polygon is guesswork, so unsqueeze for
    # DISPLAY and convert clicks back. Zones stay in native frame coordinates,
    # which is what the pipeline applies them to.
    unsqueezed_w = int(round(h * aspect)) if aspect else w
    fit = min(1.0, max_w / unsqueezed_w, max_h / h)
    disp_w, disp_h = max(1, int(unsqueezed_w * fit)), max(1, int(h * fit))
    display = (frame if (disp_w, disp_h) == (w, h)
               else cv2.resize(frame, (disp_w, disp_h), interpolation=cv2.INTER_AREA))

    sx, sy = disp_w / float(w), disp_h / float(h)
    if aspect:
        print(f"  unsqueezed for drawing: {w}x{h} shown as {disp_w}x{disp_h} "
              f"(aspect {aspect:.2f}) - zones are still saved against the real "
              f"{w}x{h} frame")
    elif (disp_w, disp_h) != (w, h):
        print(f"  window scaled to {disp_w}x{disp_h} to fit your screen - zones "
              f"are still saved at full {w}x{h} resolution")

    def to_disp(p):
        return (int(round(p[0] * sx)), int(round(p[1] * sy)))

    def redraw():
        canvas = display.copy()
        # What is already configured on this camera, dimmed. Redrawing a zone
        # blind - without seeing the one you are replacing - is how a small
        # improvement turns into a worse polygon.
        for old in (existing or []):
            pts = np.array([to_disp(pt) for pt in old["polygon"]], dtype=np.int32)
            cv2.polylines(canvas, [pts], True, (90, 90, 90), 1)
            ox, oy = pts.min(axis=0)
            cv2.putText(canvas, f"current: {old['name']}", (int(ox), max(12, int(oy) - 5)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.42, (120, 120, 120), 1)
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
            ox = min(w - 1, max(0, int(round(x / sx))))
            oy = min(h - 1, max(0, int(round(y / sy))))
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
                if pending is None:
                    name = input("Station/table name: ").strip() \
                        or f"Asset {len(zones)+1}"
                    zones.append({"name": name, "polygon": list(points),
                                  "kind": "asset"})
                    if paired:
                        pending = name
                        print(f"  added '{name}'. NOW DRAW ITS SCREEN "
                              f"(the panel only), then press 'n' again.")
                    else:
                        print(f"  added '{name}' ({len(zones)} total)")
                else:
                    # second polygon of a pair: the screen, same name, no prompt
                    zones.append({"name": pending, "polygon": list(points),
                                  "kind": "screen"})
                    print(f"  added screen for '{pending}'. Next station, or 's' "
                          f"to save.")
                    pending = None
                points.clear(); redraw()
            else:
                print("  need at least 3 points first")
        elif key == ord("s"):
            if len(points) >= 3:
                print("  finish the current polygon with 'n' first (or 'u' to clear)")
                continue
            if pending is not None:
                print(f"  '{pending}' has no screen yet - draw it and press 'n', "
                      f"or press 'q' to discard everything and start over")
                continue
            break
        elif key == ord("q"):
            zones = []
            break
    cv2.destroyAllWindows()
    return zones


def _mask_uri(uri: str) -> str:
    """Never print the DVR password - this output gets screenshotted."""
    import re
    return re.sub(r"//([^:/@]+):([^@]+)@", r"//\1:***@", uri or "")


def _overlapping_pairs(zones: list[dict]) -> list[tuple[str, str]]:
    """Zones that share space, which on a wide camera is easy to do by accident.

    A person is placed at one point, so if that point falls inside two station
    polygons BOTH stations read occupied - one customer, two billed sessions,
    and nothing on screen explains it. Checked by vertex containment both ways,
    which catches every overlap a hand-drawn room zone realistically produces.
    """
    from app.pipeline.geometry import overlapping_pairs

    return overlapping_pairs((z["name"], z["polygon"]) for z in zones)


def _find(repo, cur, **match):
    """First row whose fields all equal `match`, else None. The config tables hold
    a handful of rows, so scanning them is cheaper than adding query plumbing."""
    for row in repo.list(cur):
        if all(row.get(k) == v for k, v in match.items()):
            return row
    return None


class AmbiguousCamera(Exception):
    """More than one camera answers to this name."""

    def __init__(self, name, matches):
        self.name = name
        self.matches = matches
        super().__init__(f"{len(matches)} cameras are named {name!r}")


def source_uri_by_name(db_path, venue_name, source_name):
    """The RTSP url of a configured camera, so a command need not carry it.

    Putting the url on the command line means putting the DVR password into
    shell history, into any screenshot of the terminal, and over anyone's
    shoulder. For a camera that already exists, its name is enough.
    """
    repos = {s.name: Repository(s) for s in REGISTRY}
    db = Database(db_path)
    try:
        with db.cursor() as cur:
            venue = _find(repos["venue"], cur, name=venue_name)
            if venue is None:
                return None
            matches = [s for s in repos["video_source"].list(cur)
                       if s.get("venue_id") == venue["id"]
                       and s.get("name") == source_name]
            if len(matches) > 1:
                # Cameras are identified by url, so two can share a name - which
                # happens the moment a channel is set up with the wrong label.
                # Picking one silently would redraw zones on the wrong camera.
                raise AmbiguousCamera(source_name, matches)
            return matches[0]["uri"] if matches else None
    finally:
        db.close()


def existing_zones(db_path, venue_name, source_uri, mode=None) -> list[dict]:
    """Zones already configured on this camera, for drawing underneath."""
    repos = {s.name: Repository(s) for s in REGISTRY}
    db = Database(db_path)
    try:
        with db.cursor() as cur:
            venue = _find(repos["venue"], cur, name=venue_name)
            if venue is None:
                return []
            src = _find(repos["video_source"], cur, venue_id=venue["id"], uri=source_uri)
            if src is None:
                return []
            assets = {a["id"]: a["name"] for a in repos["asset"].list(cur)
                      if a.get("venue_id") == venue["id"]}
            zones = {z["id"]: z for z in repos["zone"].list(cur)}
            out = []
            for sensor in repos["sensor"].list(cur):
                if sensor.get("video_source_id") != src["id"]:
                    continue
                if mode and sensor.get("type") != mode:
                    continue
                zone = zones.get(sensor.get("zone_id")) or {}
                for poly in (zone.get("polygons") or []):
                    out.append({"name": assets.get(sensor["asset_id"], "?"),
                                "polygon": poly})
            return out
    finally:
        db.close()


def redraw_zones(db_path, source_uri, venue_name, zones, mode) -> tuple[int, list]:
    """Replace the polygons of existing sensors, in place.

    The asset keeps its id, so its sessions, games and any screen sensor are
    untouched - only the shape changes. Deleting and redrawing would lose the
    history, which is the thing you were trying to improve the accuracy of.
    """
    repos = {s.name: Repository(s) for s in REGISTRY}
    db = Database(db_path)
    updated, missing = 0, []
    try:
        with db.cursor() as cur:
            venue = _find(repos["venue"], cur, name=venue_name)
            src = _find(repos["video_source"], cur,
                        venue_id=venue["id"], uri=source_uri) if venue else None
            if venue is None or src is None:
                return 0, [z["name"] for z in zones]
            for z in zones:
                asset = _find(repos["asset"], cur, venue_id=venue["id"], name=z["name"])
                if asset is None:
                    missing.append(z["name"])
                    continue
                sensor = next(
                    (s for s in repos["sensor"].list(cur)
                     if s["asset_id"] == asset["id"]
                     and s.get("type") == mode
                     and s.get("video_source_id") == src["id"]), None)
                if sensor is None or not sensor.get("zone_id"):
                    missing.append(z["name"])
                    continue
                repos["zone"].update(cur, sensor["zone_id"],
                                     {"polygons": [z["polygon"]]})
                updated += 1
    finally:
        db.close()
    return updated, missing


def write_config(db_path, source, venue_name, source_name, bu_name,
                 asset_type_name, zones, mode="snooker_game",
                 attach=False, role=None) -> str:
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

        # `attach` adds a sensor to an EXISTING asset matched by name instead of
        # creating one. A TV is not an asset - it is evidence about one - and the
        # same is true of a second view: a pool table watched for balls AND for
        # people is one table with two sensors, not two tables.
        if attach or mode == "screen":
            sensor_role = role or ("supporting" if attach else "supporting")
            attached, missing = 0, []
            for z in zones:
                asset = _find(repos["asset"], cur, venue_id=venue["id"], name=z["name"])
                if asset is None:
                    missing.append(z["name"])
                    continue
                zone = repos["zone"].create(cur, {
                    "space_id": asset["space_id"] or space["id"],
                    "name": f"{z['name']} {mode}",
                    "polygons": [z["polygon"]]})
                repos["sensor"].create(cur, {
                    "asset_id": asset["id"], "video_source_id": src["id"],
                    "zone_id": zone["id"], "type": mode, "role": sensor_role})
                attached += 1
            if missing:
                # Say what DOES exist. The match is exact, and the failure is
                # almost always a name typed slightly differently at the prompt
                # ("Table 4" vs "Snooker Table 4") - which is impossible to spot
                # without seeing the list.
                existing = sorted(a["name"] for a in
                                  repos["asset"].list(cur)
                                  if a.get("venue_id") == venue["id"])
                print(f"\n  NO ASSET NAMED: {', '.join(missing)}")
                print("  Attaching matches an existing asset by name, exactly.")
                print(f"  This venue has: {', '.join(existing) or '(none yet)'}")
                print("  Re-run and name the polygon to match one of those.")
            print(f"  attached {attached} {mode} sensor(s) to existing asset(s)")
            zones = []          # nothing left to create; fall through to the exit

        # A paired run carries both kinds. Assets first, then their screens
        # attach to what was just created - one pass, no name to retype.
        screens = [z for z in zones if z.get("kind") == "screen"]
        zones = [z for z in zones if z.get("kind") != "screen"]

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
        for z in screens:
            asset = _find(repos["asset"], cur, venue_id=venue["id"], name=z["name"])
            if asset is None:
                print(f"  screen for '{z['name']}' skipped - no such asset")
                continue
            zone = repos["zone"].create(cur, {
                "space_id": asset["space_id"] or space["id"],
                "name": f"{z['name']} screen", "polygons": [z["polygon"]]})
            repos["sensor"].create(cur, {
                "asset_id": asset["id"], "video_source_id": src["id"],
                "zone_id": zone["id"], "type": "screen", "role": "supporting"})
        if screens:
            print(f"  attached {len(screens)} screen zone(s)")

    db.close()
    return venue["id"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", help="RTSP url, file path, or webcam index. Not "
                                     "needed with --redraw if --source-name names "
                                     "a camera that already exists.")
    ap.add_argument("--venue", default="Strikee Club")
    ap.add_argument("--source-name", default="Camera 1")
    ap.add_argument("--business-unit", default="Snooker")
    ap.add_argument("--asset-type", default="Snooker Table")
    ap.add_argument("--mode", default="snooker_game",
                    choices=["snooker_game", "occupancy", "screen"],
                    help="snooker_game (balls, for tables), occupancy (people), or "
                         "screen (a TV zone ATTACHED to an existing asset - name "
                         "each polygon exactly like the station it belongs to)")
    ap.add_argument("--db", default=os.environ.get("STRIKEE_DB", "strikee.db"))
    ap.add_argument("--redraw", action="store_true",
                    help="REPLACE the polygons of existing assets of the same "
                         "name on this camera, instead of creating anything. The "
                         "assets keep their id, so sessions, games and screen "
                         "sensors survive - only the shape changes.")
    ap.add_argument("--with-screen", action="store_true",
                    help="draw TWO polygons per station in one pass - the seating "
                         "area, then that station's screen - naming it once. Saves "
                         "a second run and removes the exact-name match.")
    ap.add_argument("--attach", action="store_true",
                    help="add these zones as extra sensors on EXISTING assets of "
                         "the same name, instead of creating new assets. Use it to "
                         "watch one table both ways, or to add a second camera "
                         "angle. (--mode screen always attaches.)")
    ap.add_argument("--role", default=None, choices=["primary", "supporting"],
                    help="sensor role when attaching (default supporting)")
    ap.add_argument("--aspect", default=os.environ.get("STRIKEE_PERSON_ASPECT"),
                    help="true scene aspect (e.g. 16:9) for channels that deliver "
                         "a squeezed frame - the editor unsqueezes it for drawing "
                         "while still saving zones against the real frame")
    ap.add_argument("--max-window", default="1280x720",
                    help="largest on-screen size for the editor, WxH (default "
                         "1280x720). Zones are always saved at full resolution.")
    args = ap.parse_args()

    if not args.source:
        # Redrawing an existing camera: look its url up rather than making
        # someone paste a password into their shell history.
        try:
            looked_up = source_uri_by_name(args.db, args.venue, args.source_name)
        except AmbiguousCamera as exc:
            print(f"{len(exc.matches)} cameras are named {exc.name!r}, so this "
                  f"would redraw the wrong one:")
            for m in exc.matches:
                print(f"    {m['id'][:8]}  {_mask_uri(m.get('uri'))}")
            print("\n  Give them distinct names first:")
            print(f"    python tools/rename_cameras.py --auto")
            print("  or rename one by id:")
            print(f"    python tools/rename_cameras.py --set {exc.matches[-1]['id'][:8]} "
                  f"\"Gaming Camera D\"")
            sys.exit(2)
        if looked_up is None:
            print(f"No camera named {args.source_name!r} in {args.venue!r}. "
                  f"Pass --source with its url, or check "
                  f"tools/show_config.py for the names.")
            sys.exit(2)
        args.source = looked_up
        print(f"Using the configured camera {args.source_name!r}.")

    print(f"Grabbing a frame from {_mask_uri(args.source)} ...")
    frame = grab_frame(args.source)
    h, w = frame.shape[:2]
    print(f"Got a {w}x{h} frame. Opening the zone editor...")
    if args.mode == "snooker_game":
        print("Mode: snooker_game — draw the zone around the TABLE surface "
              "(where the balls are).")
    elif args.mode == "screen":
        print("Mode: screen — draw the zone around each TV SCREEN ONLY (just the "
              "panel, no wall or reflections). Name each one EXACTLY like the "
              "station it belongs to; it attaches to that asset rather than "
              "creating a new one.")
    else:
        # People are located by their FEET (the bottom edge of the detection
        # box), so a zone drawn tightly around a seat or a screen misses a
        # player whose feet fall outside it.
        print("Mode: occupancy — a person is placed at the BOTTOM-CENTRE of their "
              "box, so cover where that lands: for someone standing that is the "
              "floor at their feet; for someone SEATED it is the seat or their "
              "legs, not the floor in front. Include the whole seating area, and "
              "keep neighbouring stations from overlapping.")

    try:
        max_w, max_h = (int(v) for v in args.max_window.lower().split("x"))
    except ValueError:
        print(f"--max-window must look like 1280x720, got {args.max_window!r}")
        sys.exit(2)
    aspect = None
    if args.aspect:
        try:
            aspect = (float(args.aspect.split(":")[0]) / float(args.aspect.split(":")[1])
                      if ":" in args.aspect else float(args.aspect))
        except (ValueError, ZeroDivisionError):
            print(f"--aspect must look like 16:9 or 1.78, got {args.aspect!r}")
            sys.exit(2)
    # With --with-screen both zones are being replaced, so show both underneath.
    prior_mode = None if (args.with_screen or not args.redraw) else args.mode
    prior = existing_zones(args.db, args.venue, args.source, mode=prior_mode)
    if args.redraw:
        if not prior:
            print(f"Nothing to redraw: no {args.mode} zones on this camera in "
                  f"'{args.venue}'.")
            sys.exit(2)
        print(f"REDRAW - the current zones are outlined in grey. Draw the "
              f"replacement for each and name it the same:")
        for z in prior:
            print(f"    {z['name']}")
    zones = draw_zones(frame, max_w=max_w, max_h=max_h, aspect=aspect,
                       paired=args.with_screen, existing=prior)
    if not zones:
        print("No zones drawn — nothing written."); return

    if args.redraw:
        # A paired run carries both kinds; each replaces the zone of its own
        # sensor, so one pass fixes the seating area and the screen together.
        groups = [(args.mode, [z for z in zones if z.get("kind") != "screen"]),
                  ("screen", [z for z in zones if z.get("kind") == "screen"])]
        total, missing = 0, []
        for mode, group in groups:
            if not group:
                continue
            updated, gone = redraw_zones(args.db, args.source, args.venue,
                                         group, mode)
            if updated:
                print(f"  updated {updated} {mode} zone(s)")
            total += updated
            missing.extend(f"{n} ({mode})" for n in gone)
        print(f"\n  {total} zone(s) replaced in place")
        if missing:
            print(f"  NOT FOUND: {', '.join(missing)}")
            print("  A redraw replaces an existing zone on THIS camera, matched "
                  "by asset name and mode. Nothing was created.")
        print("  Restart strikee-core to pick up the new shapes.")
        return

    for a, b in _overlapping_pairs([z for z in zones if z.get("kind") != "screen"]):
        print(f"  WARNING: '{a}' and '{b}' overlap. A person standing in the shared "
              f"area will mark BOTH occupied, so one customer becomes two sessions. "
              f"Re-run and keep them apart if that area is reachable.")

    venue_id = write_config(args.db, args.source, args.venue, args.source_name,
                            args.business_unit, args.asset_type, zones,
                            mode=args.mode, attach=args.attach, role=args.role)
    print(f"\nConfigured venue '{args.venue}' with {len(zones)} asset(s) in {args.db}")
    print(f"venue id: {venue_id}")
    print("\nNext: run  strikee-core  (or: python run_desktop.py), pick the venue,")
    print("and press 'Start pipeline'.")


if __name__ == "__main__":
    main()
