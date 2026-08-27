"""Look at every DVR channel and report what the models can see there.

Run this BEFORE drawing zones. Two questions it answers that guesswork cannot:

  * Which channel is which? Twelve channels, and the useful ones are not in an
    obvious order. The saved frames tell you at a glance.
  * Does the model actually see anything there? A camera angle that defeats
    detection looks perfectly fine to a human - the overhead table cameras here
    show people clearly and yield zero person detections, because the model was
    never trained looking straight down at heads. Drawing six station zones
    against such a camera produces a system that reports an empty room all
    evening and gives no clue why.

    python tools/survey_cameras.py --url "rtsp://user:pass@192.168.0.108:554/cam/realmonitor?channel={ch}&subtype=0" --channels 1-12

Writes an annotated JPEG per channel to survey/ and prints a summary. Channels
are visited one at a time, so it never troubles the DVR's concurrent-stream
limit.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.platform_env import harden

harden()   # torch before cv2, UTF-8 console, forced TCP for RTSP


def parse_channels(spec: str) -> list[int]:
    """'1-6', '1,4,6' or '1-4,7,9-12' -> [1, 2, ...]"""
    out: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            lo, hi = part.split("-", 1)
            out.extend(range(int(lo), int(hi) + 1))
        elif part:
            out.append(int(part))
    return out


def _sweep(frame, args):
    """Try a handful of settings on one frame and keep whichever found most.

    Worth doing once per difficult camera: the difference between zero and a
    working detection is usually one of these, and which one is not guessable
    from looking at the picture.
    """
    from app.pipeline.perception import YOLODetector

    trials = [
        ("default", dict(conf=0.25)),
        ("conf 0.15", dict(conf=0.15)),
        ("imgsz 960", dict(conf=0.25, imgsz=960)),
        ("imgsz 1280", dict(conf=0.20, imgsz=1280)),
        ("clahe", dict(conf=0.20, clahe=True)),
        ("imgsz 1280 + clahe", dict(conf=0.20, imgsz=1280, clahe=True)),
        ("aspect 16:9", dict(conf=0.20, aspect=16 / 9)),
        ("aspect 16:9 + imgsz 1280", dict(conf=0.20, aspect=16 / 9, imgsz=1280)),
    ]
    best_label, best_dets = "none", []
    for label, kwargs in trials:
        try:
            dets = YOLODetector(args.person_model, **kwargs).detect(frame)
        except Exception:
            continue
        if len(dets) > len(best_dets):
            best_label, best_dets = label, dets
    return (best_label if best_dets else None), best_dets


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", required=True,
                    help="RTSP template containing {ch}, e.g. "
                         '"rtsp://u:p@ip:554/cam/realmonitor?channel={ch}&subtype=0"')
    ap.add_argument("--channels", default="1-12")
    ap.add_argument("--out", default="survey")
    ap.add_argument("--person-model", default=os.environ.get("STRIKEE_PERSON_MODEL",
                                                             "yolo11n.pt"))
    ap.add_argument("--snooker-model", default=os.environ.get("STRIKEE_SNOOKER_MODEL",
                                                              "best.pt"))
    ap.add_argument("--no-snooker", action="store_true",
                    help="skip ball detection (faster; use when surveying people cameras)")
    ap.add_argument("--conf", type=float, default=0.25,
                    help="person confidence threshold (default 0.25; try 0.15)")
    ap.add_argument("--imgsz", type=int, default=None,
                    help="inference size (default 640). 960 or 1280 finds people "
                         "far down a room who are only a few dozen pixels tall")
    ap.add_argument("--clahe", action="store_true",
                    help="normalise lighting before detection - try this in a dim room")
    ap.add_argument("--aspect", default=None,
                    help="true scene aspect, e.g. 16:9, when a channel delivers a "
                         "squeezed frame. People stop looking like people when the "
                         "picture is anamorphic")
    ap.add_argument("--sweep", action="store_true",
                    help="try several settings on each channel and report which "
                         "found the most people")
    args = ap.parse_args()

    if "{ch}" not in args.url:
        print("--url must contain {ch} so each channel can be substituted.", file=sys.stderr)
        return 2

    import cv2
    from app.pipeline.capture import grab_once
    from app.pipeline.perception import SnookerDetector, YOLODetector

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    def parse_aspect(raw):
        if not raw:
            return None
        if ":" in raw:
            w, h = raw.split(":", 1)
            return float(w) / float(h)
        return float(raw)

    aspect = parse_aspect(args.aspect)

    print("Loading models...")
    person = YOLODetector(args.person_model, conf=args.conf, imgsz=args.imgsz,
                          clahe=args.clahe, aspect=aspect)
    snooker = None if args.no_snooker else SnookerDetector(args.snooker_model, conf=0.20)

    channels = parse_channels(args.channels)
    rows = []
    print(f"Surveying {len(channels)} channels, one at a time.\n")

    for ch in channels:
        uri = args.url.replace("{ch}", str(ch))
        started = time.perf_counter()
        try:
            ok, frame = grab_once(uri)
        except Exception as exc:
            ok, frame = False, None
            note = f"{type(exc).__name__}"
        else:
            note = ""
        elapsed = time.perf_counter() - started

        if not ok or frame is None:
            print(f"  ch{ch:<3} OFFLINE  ({elapsed:.1f}s) {note}")
            rows.append((ch, None, 0, 0, elapsed, "offline"))
            continue

        h, w = frame.shape[:2]
        if args.sweep:
            best_label, people = _sweep(frame, args)
        else:
            best_label, people = None, person.detect(frame)
        balls = snooker.detect(frame) if snooker is not None else []
        reds = [d for d in balls if d.label == "red_ball"]

        canvas = frame.copy()
        for d in people:
            x1, y1, x2, y2 = (int(v) for v in d.bbox)
            cv2.rectangle(canvas, (x1, y1), (x2, y2), (0, 220, 0), 2)
            cv2.circle(canvas, ((x1 + x2) // 2, y2), 4, (0, 220, 0), -1)  # feet
        for d in balls:
            x1, y1, x2, y2 = (int(v) for v in d.bbox)
            cv2.rectangle(canvas, (x1, y1), (x2, y2), (0, 165, 255), 2)

        caption = (f"ch{ch}  {w}x{h}  people={len(people)}  "
                   f"balls={len(balls)} (red={len(reds)})")
        if best_label:
            caption += f"  best: {best_label}"
        cv2.rectangle(canvas, (0, 0), (canvas.shape[1], 30), (0, 0, 0), -1)
        cv2.putText(canvas, caption, (8, 21), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                    (255, 255, 255), 2)
        if aspect:
            # Save it the shape the room actually is. Detection already ran on an
            # unsqueezed copy; this is so the picture you inspect matches what
            # DMSS shows you, rather than the squeezed frame off the wire.
            canvas = cv2.resize(canvas, (int(round(h * aspect)), h),
                                interpolation=cv2.INTER_LINEAR)
        path = out_dir / f"ch{ch:02d}.jpg"
        cv2.imwrite(str(path), canvas, [cv2.IMWRITE_JPEG_QUALITY, 85])

        extra = f"  best: {best_label}" if best_label else ""
        print(f"  ch{ch:<3} {w}x{h}  people={len(people):<3} balls={len(balls):<3} "
              f"({elapsed:.1f}s){extra}  -> {path}")
        rows.append((ch, f"{w}x{h}", len(people), len(balls), elapsed, "ok"))

    # --- summary ---------------------------------------------------------
    live = [r for r in rows if r[5] == "ok"]
    print(f"\n{'-' * 68}")
    print(f"{len(live)} of {len(rows)} channels responded. Frames in {out_dir}/\n")

    people_cams = [r[0] for r in live if r[2] > 0]
    ball_cams = [r[0] for r in live if r[3] >= 5]
    dead = [r[0] for r in rows if r[5] == "offline"]

    print(f"  People detected on : {people_cams or 'none'}")
    print(f"  Balls detected on  : {ball_cams or 'none'}")
    if dead:
        print(f"  Did not respond    : {dead}")

    print("""
Now OPEN THE IMAGES. The counts alone will mislead you:

  * A gaming camera showing people in the picture but people=0 cannot drive
    occupancy. That is the angle defeating the model, not a zone problem, and
    no amount of zone drawing fixes it. Check whether a lower or wider-angle
    camera covers the same stations before committing.
  * people=0 on an empty room says nothing. Re-run while someone stands there.
  * Balls on a channel you thought was a people camera means you have the
    channel numbers crossed.

Then draw zones only on the channels that actually detected what you need.

If a gaming camera shows people but detects none, try:

    --sweep                     try several settings and report the best
    --imgsz 1280                people far down a room are tiny at the default 640
    --clahe                     normalise lighting in a dim lounge
    --aspect 16:9               unsqueeze an anamorphic channel
    --person-model yolo11x.pt   a much larger model; slower, far better at angles

Whatever wins, put it in .env as STRIKEE_PERSON_IMGSZ / _CLAHE / _ASPECT /
_CONF / STRIKEE_PERSON_MODEL and the pipeline will use it.""")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
