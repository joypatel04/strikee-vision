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
import time
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


SCREEN_KNOBS = (
    ("lum", "screen_lum", "STRIKEE_SCREEN_LUM", 120.0),
    ("change", "screen_change", "STRIKEE_SCREEN_CHANGE", 6.0),
    ("contrast", "screen_contrast", "STRIKEE_SCREEN_CONTRAST", 28.0),
    ("sat", "screen_sat", "STRIKEE_SCREEN_SAT", 14.0),
)


def _screen_thresholds(params) -> dict:
    """Same precedence the observer uses: per-sensor params, then env, then default."""
    params = params or {}
    return {short: float(params.get(key, os.environ.get(env, default)))
            for short, key, env, default in SCREEN_KNOBS}


def watch_screens(sources, by_source, zones, assets, seconds: float,
                  gap: float, state: str | None, out_dir: str,
                  on_names: str | None = None) -> int:
    """Measure what the screen zones actually read, instead of guessing.

    A threshold picked from one reading is a coin flip: the number you happen to
    see may be the brightest frame of a dark game or the dimmest frame of a
    bright one. And at this venue brightness alone cannot do it at all - an OFF
    panel reflecting room lights measured 92-97, overlapping what a dark game
    scene reads when the TV is ON.

    So measure both states and compare. Run it once with the TVs on and once
    with them off, passing --state each time; the second run has the first to
    compare against and prints the thresholds that separate them.
    """
    import json

    from app.pipeline.capture import grab_once
    from app.pipeline.observe import SCREEN_KIND, observe_screen

    targets = [(src, s) for src in sources
               for s in by_source.get(src["id"], [])
               if s["type"] == SCREEN_KIND]
    if not targets:
        print("No screen sensors configured - nothing to watch.")
        return 2

    samples: dict = {}
    prev: dict = {}
    label = f" with the TVs {state.upper()}" if state else ""
    print(f"Sampling {len(targets)} screen zone(s) for {seconds:g}s{label}. "
          f"Leave them exactly as they are.\n")

    deadline = time.time() + seconds
    while time.time() < deadline:
        for src, sensor in targets:
            ok, frame = grab_once(src["uri"])
            if not ok or frame is None:
                continue

            class S:
                zone_polygons = (zones.get(sensor["zone_id"]) or {}).get("polygons") or []
                conf_threshold = sensor.get("conf_threshold") or 0.35
                params = sensor.get("params") or {}

            had_prev = prev.get(sensor["id"]) is not None
            obs = observe_screen(frame, S(), previous=prev.get(sensor["id"]))
            prev[sensor["id"]] = obs.get("crop")
            row = {k: obs[k] for k in ("luminance", "contrast", "saturation")}
            if had_prev:
                row["change"] = obs["change"]
            samples.setdefault(sensor["id"], []).append(row)
            print(".", end="", flush=True)
        if gap:
            time.sleep(gap)
    print("\n")

    def span(rows, key):
        vals = sorted(r[key] for r in rows if key in r)
        if not vals:
            return None
        return {"min": vals[0], "median": vals[len(vals) // 2], "max": vals[-1]}

    METRICS = (("luminance", "lum"), ("contrast", "contrast"),
               ("saturation", "sat"), ("change", "change"))

    report = {}
    for src, sensor in targets:
        rows = samples.get(sensor["id"], [])
        name = assets[sensor["asset_id"]]["name"]
        thresholds = _screen_thresholds(sensor.get("params"))
        print(f"{name}  ({src['name']})   {len(rows)} samples")
        stats = {}
        for metric, short in METRICS:
            sp = span(rows, metric)
            stats[metric] = sp
            if sp is None:
                print(f"    {metric:<11} no samples")
                continue
            print(f"    {metric:<11} min {sp['min']:>7.1f}   "
                  f"median {sp['median']:>7.1f}   max {sp['max']:>7.1f}"
                  f"      threshold {thresholds[short]:g}")
        report[sensor["id"]] = {"asset": name, "camera": src["name"],
                                "samples": len(rows), "stats": stats}
        print()

    # A venue mid-evening already contains both states: some stations playing,
    # some idle. Naming the ones that are on turns a single pass into the same
    # comparison, without asking anyone to switch off a customer's TV.
    if on_names:
        wanted = {n.strip().lower() for n in on_names.split(",") if n.strip()}
        known = {r["asset"].lower(): sid for sid, r in report.items()}
        unknown = sorted(n for n in wanted if n not in known)
        if unknown:
            print(f"Not a station on a screen sensor: {', '.join(unknown)}")
            print(f"Known: {', '.join(sorted(r['asset'] for r in report.values()))}")
            return 2
        on_report = {sid: r for sid, r in report.items()
                     if r["asset"].lower() in wanted}
        off_report = {sid: r for sid, r in report.items()
                      if r["asset"].lower() not in wanted}
        if not off_report:
            print("Every station was named as on - nothing to compare against.")
            return 2
        _recommend_across(on_report, off_report)
        return 0

    if not state:
        print("""Compare two states to get a threshold. Either name the stations
whose TVs are on right now, in one pass:

    --watch 60 --on "Station 1,Station 2,Station 3"

or, when the room is empty, measure the same screens twice:

    --watch 60 --state on       (TVs on)
    --watch 60 --state off      (TVs off)

The first needs no one to touch a TV, so it works during service.""")
        return 0

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"screen-{state}.json").write_text(json.dumps(report, indent=2),
                                              encoding="utf-8")
    other_state = "off" if state == "on" else "on"
    other_path = out / f"screen-{other_state}.json"
    if not other_path.exists():
        print(f"Saved. Now run it again with --state {other_state}:\n")
        print(f"    ... --watch {seconds:g} --state {other_state}\n")
        return 0

    other = json.loads(other_path.read_text(encoding="utf-8"))
    on_report, off_report = ((report, other) if state == "on"
                             else (other, report))
    _recommend(on_report, off_report)
    return 0


METRIC_ENVS = (("luminance", "STRIKEE_SCREEN_LUM"),
               ("contrast", "STRIKEE_SCREEN_CONTRAST"),
               ("saturation", "STRIKEE_SCREEN_SAT"),
               ("change", "STRIKEE_SCREEN_CHANGE"))


def _pool(report: dict, metric: str):
    """Widest range this metric took across every station in the group."""
    spans = [r["stats"].get(metric) for r in report.values()
             if r["stats"].get(metric)]
    if not spans:
        return None
    return {"min": min(s["min"] for s in spans),
            "max": max(s["max"] for s in spans)}


def _as_list(v):
    return v if isinstance(v, list) else [v]


def _print_picks(usable: dict, inverted: dict | None = None,
                 safety: dict | None = None) -> None:
    inverted, safety = inverted or {}, safety or {}
    if usable or inverted or safety:
        print("Put ALL of these in .env - the ones set to 'off' matter as much "
              "as the\nthresholds, because a signal left at a default that sits "
              "inside the off\nrange announces an idle screen as playing:\n")
        for env, picks in usable.items():
            print(f"    {env}={max(_as_list(picks))}")
        for env, picks in safety.items():
            print(f"    {env}={max(_as_list(picks))}")
        for env, metric in inverted.items():
            print(f"    {env}=off")
        print("""
A screen reads on if ANY signal fires, so every threshold has to be clear of the
off range - one that is not will hold stations open all night on its own.""")

    if not usable:
        print("""
WARNING: no signal cleanly separated on from off. The settings above keep an
idle screen from reading as playing, but nothing reliably recognises a screen
that IS on, so stations will under-report.

That usually means the zone takes in more than the panel: wall, bezel, or a
window dilutes every statistic toward the room. Redraw it tight to the screen:

    python field_setup.py --redraw --venue "..." --source-name "..." --mode screen""")


def _verdict(on_span, off_span, env):
    """How a signal behaves between the two groups, and what to set it to.

    Three outcomes, and the middle one is the trap. A signal whose ranges
    overlap cannot decide on its own - but leaving it at a default that sits
    INSIDE the off range is not neutral, it is a false positive generator: an
    off screen measured change 8.2 against a threshold of 6, so it announced
    itself as playing. Overlapping signals therefore get a threshold above
    everything seen while off, which makes them a safety net instead.

    Inversion earns its own answer because the fix is the opposite of the
    obvious one - not a different threshold, but switching the signal off.
    """
    if on_span["min"] > off_span["max"]:
        gap = on_span["min"] - off_span["max"]
        return "separates", round(off_span["max"] + gap / 2)
    if off_span["min"] > on_span["max"]:
        return "inverted", None
    if on_span["max"] > off_span["max"]:
        # Still worth keeping: it fires only above anything an idle screen did.
        return "overlaps", round(off_span["max"]) + 2
    return "useless", None


def _recommend_across(on_report: dict, off_report: dict) -> None:
    """Compare stations that are on against stations that are off, one pass.

    Weaker evidence than measuring one screen in both states, and worth saying
    so: these are different televisions in different corners, so a gap could be
    a difference between the sets rather than between on and off. With a few
    screens on each side it is still the right call, and it is the only version
    of this measurement that can be taken during service.
    """
    on_names = ", ".join(sorted(r["asset"] for r in on_report.values()))
    off_names = ", ".join(sorted(r["asset"] for r in off_report.values()))
    print("=" * 68)
    print(f"ON  ({len(on_report)}): {on_names}")
    print(f"OFF ({len(off_report)}): {off_names}")
    print("=" * 68 + "\n")

    usable: dict = {}
    inverted: dict = {}
    safety: dict = {}
    for metric, env in METRIC_ENVS:
        a, b = _pool(on_report, metric), _pool(off_report, metric)
        if not a or not b:
            print(f"    {metric:<11} not measured in both groups")
            continue
        how, pick = _verdict(a, b, env)
        ranges = (f"    {metric:<11} on {a['min']:.0f}-{a['max']:.0f}  "
                  f"off {b['min']:.0f}-{b['max']:.0f}   ")
        if how == "separates":
            usable[env] = [pick]
            print(ranges + f"SEPARATES -> {env}={pick}")
        elif how == "inverted":
            inverted[env] = metric
            print(ranges + f"BACKWARDS - off scores higher -> {env}=off")
        elif how == "overlaps":
            safety[env] = pick
            print(ranges + f"overlaps -> {env}={pick} (above the off range)")
        else:
            inverted[env] = metric
            print(ranges + f"never exceeds off -> {env}=off")

    print("\n" + "=" * 68)
    _print_picks(usable, inverted, safety)
    print("""
Measured across different televisions, so confirm it when the room is empty:

    --watch 60 --state on     then     --watch 60 --state off""")


def _recommend(on_report: dict, off_report: dict) -> None:
    """Print the threshold for each signal, from the gap between on and off.

    A signal is only usable if its two ranges do not overlap. Reporting which
    ones overlap matters as much as the numbers: at this venue brightness does
    overlap, and knowing that is what stops someone tuning it forever.
    """
    print("=" * 68)
    print("ON vs OFF")
    print("=" * 68)
    usable: dict = {}
    inverted: dict = {}
    safety: dict = {}
    for sensor_id, on in on_report.items():
        off = off_report.get(sensor_id)
        if not off:
            continue
        print(f"\n{on['asset']}  ({on['camera']})")
        for metric, env in METRIC_ENVS:
            a, b = on["stats"].get(metric), off["stats"].get(metric)
            if not a or not b:
                print(f"    {metric:<11} not measured in both runs")
                continue
            how, pick = _verdict(a, b, env)
            ranges = (f"    {metric:<11} on {a['min']:.0f}-{a['max']:.0f}  "
                      f"off {b['min']:.0f}-{b['max']:.0f}   ")
            if how == "separates":
                usable.setdefault(env, []).append(pick)
                print(ranges + f"SEPARATES -> {env}={pick}")
            elif how == "inverted":
                inverted[env] = metric
                print(ranges + f"BACKWARDS - off scores higher -> {env}=off")
            elif how == "overlaps":
                safety.setdefault(env, []).append(pick)
                print(ranges + f"overlaps -> {env}={pick} (above the off range)")
            else:
                inverted[env] = metric
                print(ranges + f"never exceeds off -> {env}=off")

    print("\n" + "=" * 68)
    _print_picks(usable, inverted, safety)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--venue", help="venue name (default: the only one)")
    ap.add_argument("--source", help="only this camera, by name")
    ap.add_argument("--db", default=os.environ.get("STRIKEE_DB", "strikee.db"))
    ap.add_argument("--out", default="debug_frames")
    ap.add_argument("--gap", type=float, default=1.5,
                    help="seconds between the two frames used to measure "
                         "screen change (default 1.5)")
    ap.add_argument("--watch", type=float, metavar="SECONDS",
                    help="instead of rendering, sample every screen zone for "
                         "this long and report the range of lum/change - run "
                         "it once with the TVs on and once with them off to "
                         "pick a threshold from data")
    ap.add_argument("--on", dest="on_names", metavar="NAMES",
                    help="comma-separated stations whose TVs are ON right now. "
                         "Compares them against the rest in a single pass, so "
                         "no one has to switch off a customer's TV")
    ap.add_argument("--state", choices=("on", "off"),
                    help="what the TVs were doing during a --watch run. Do one "
                         "of each and the second prints the thresholds that "
                         "separate them")
    ap.add_argument("--aspect", default=os.environ.get("STRIKEE_PERSON_ASPECT"))
    args = ap.parse_args()

    if not Path(args.db).exists():
        print(f"{args.db} not found - run this from the local-core directory.")
        return 2

    import cv2
    from app.pipeline.capture import grab_once
    from app.pipeline.observe import (PERSON_KINDS, SCREEN_KIND, SNOOKER_KIND,
                                      observe, observe_screen, person_anchor)
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

    # Measuring screens needs no model at all, so branch before loading one -
    # on this hardware that import alone costs more than the whole measurement.
    if args.watch:
        return watch_screens(sources, by_source, zones, assets,
                             args.watch, args.gap, args.state, args.out,
                             args.on_names)

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

        # A screen is called on when it is bright OR when it changed since the
        # last look. One frame can only answer the first half, so this tool used
        # to report change=0 for every TV and judge them on brightness alone -
        # strictly harsher than the pipeline, which does have a previous frame.
        # Grab an earlier frame first so both halves are real.
        prev_frame = None
        if any(s["type"] == SCREEN_KIND for s in mine):
            okp, prev_frame = grab_once(src["uri"])
            if not okp:
                prev_frame = None
            else:
                time.sleep(args.gap)

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
                before = (observe_screen(prev_frame, S())["crop"]
                          if prev_frame is not None else None)
                obs = observe_screen(frame, S(), previous=before)
                verdict = obs["present"]
                t = _screen_thresholds(S.params)
                detail = (f"[{obs['reason']}] lum={obs['luminance']}/{t['lum']:g} "
                          f"contrast={obs['contrast']}/{t['contrast']:g} "
                          f"sat={obs['saturation']}/{t['sat']:g} ")
                detail += ("change=UNMEASURED" if before is None
                           else f"change={obs['change']}/{t['change']:g}")
            else:
                dets = balls if kind == SNOOKER_KIND else people
                obs = observe(kind, dets, S())
                verdict = obs["present"]
                detail = f"{obs['count']} in zone"
                if kind in PERSON_KINDS:
                    # Which part of a person decides where they are is the
                    # commonest silent mistake on sofa seating, and the counts
                    # side by side make it obvious which anchor this zone wants.
                    from app.pipeline.geometry import (ANCHORS,
                                                       detection_in_any_polygon)
                    counts = {
                        a: sum(1 for d in dets
                               if d.confidence >= S.conf_threshold
                               and detection_in_any_polygon(d, polys, a))
                        for a in ANCHORS}
                    detail += ("   by anchor: "
                               + "  ".join(f"{a}={n}" for a, n in counts.items()))
                    detail += f"   (using {person_anchor(S())})"

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
