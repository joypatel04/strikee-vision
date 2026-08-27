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
    args = ap.parse_args()

    if "{ch}" not in args.url:
        print("--url must contain {ch} so each channel can be substituted.", file=sys.stderr)
        return 2

    import cv2
    from app.pipeline.capture import grab_once
    from app.pipeline.perception import SnookerDetector, YOLODetector

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("Loading models...")
    person = YOLODetector(args.person_model, conf=0.25)
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
        people = person.detect(frame)
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

        caption = f"ch{ch}  {w}x{h}  people={len(people)}  balls={len(balls)} (red={len(reds)})"
        cv2.rectangle(canvas, (0, 0), (canvas.shape[1], 30), (0, 0, 0), -1)
        cv2.putText(canvas, caption, (8, 21), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                    (255, 255, 255), 2)
        path = out_dir / f"ch{ch:02d}.jpg"
        cv2.imwrite(str(path), canvas, [cv2.IMWRITE_JPEG_QUALITY, 85])

        print(f"  ch{ch:<3} {w}x{h}  people={len(people):<3} balls={len(balls):<3} "
              f"({elapsed:.1f}s)  -> {path}")
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

Then draw zones only on the channels that actually detected what you need.""")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
