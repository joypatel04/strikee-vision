"""Grab one frame from a source and save it as a still image.

Use this first at the club to (1) confirm the stream connects, and
(2) get a reference frame to draw zones on.

Examples:
    python snapshot.py --source "rtsp://user:pass@192.168.1.50:554/stream1"
    python snapshot.py --source video.mp4
    python snapshot.py --source 0            # webcam
"""
from __future__ import annotations

import argparse
import sys

import cv2

from common import open_source, grab_recent_frame


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True, help="RTSP url, file path, or webcam index")
    ap.add_argument("--out", default="frame.jpg", help="output image path")
    args = ap.parse_args()

    cap = open_source(args.source)
    if not cap.isOpened():
        print(f"ERROR: could not open source: {args.source}", file=sys.stderr)
        print("If RTSP: check the URL, credentials, and that you're on the venue network.", file=sys.stderr)
        sys.exit(1)

    ok, frame = grab_recent_frame(cap)
    cap.release()
    if not ok or frame is None:
        print("ERROR: opened the source but could not read a frame.", file=sys.stderr)
        sys.exit(2)

    cv2.imwrite(args.out, frame)
    h, w = frame.shape[:2]
    print(f"Saved {args.out}  ({w}x{h})")
    print("Next: python draw_zones.py --frame", args.out)


if __name__ == "__main__":
    main()
