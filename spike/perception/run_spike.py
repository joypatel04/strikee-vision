"""Strikee Vision perception spike.

Samples a video source every N seconds (NOT continuously), runs YOLO person
detection, decides per-zone occupancy, smooths it into a stable state, and
derives table-usage sessions. Logs everything for later review.

This mirrors the product's real pipeline so the spike validates the actual
approach:  frame -> detections -> person-in-zone -> presence -> smoothed
state (min start/clear) -> session.

Run at the club against the live stream:
    python run_spike.py --source "rtsp://user:pass@CAM_IP:554/stream1" \
        --zones zones.json --interval 7 --hours 4

Dev run against a file or webcam:
    python run_spike.py --source clip.mp4 --zones zones.json --interval 7
    python run_spike.py --source 0 --zones zones.json --interval 5

Outputs (under ./runs/<timestamp>/):
    observations.csv   one row per zone per tick (raw + smoothed)
    sessions.csv       detected table-usage sessions (start, end, duration)
    events.csv         state-change events (became_occupied / available / etc.)
    frames/            annotated keyframe saved on every state change
    health.csv         camera online/offline transitions
    run.log            console mirror
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from datetime import datetime, timezone

import cv2

from common import (
    open_source, grab_recent_frame, load_zones,
    point_in_poly, person_ground_point, ZoneState,
)

PERSON_CLASS = 0  # COCO class id for 'person'


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def ts_slug() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


class CsvLog:
    def __init__(self, path, header):
        self.f = open(path, "w", newline="")
        self.w = csv.writer(self.f)
        self.w.writerow(header)
        self.f.flush()

    def row(self, *vals):
        self.w.writerow(vals)
        self.f.flush()

    def close(self):
        self.f.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True, help="RTSP url, file path, or webcam index")
    ap.add_argument("--zones", required=True, help="zones.json from draw_zones.py")
    ap.add_argument("--interval", type=float, default=7.0, help="seconds between samples (5-10 recommended)")
    ap.add_argument("--hours", type=float, default=0.0, help="stop after N hours (0 = run until source ends / Ctrl-C)")
    ap.add_argument("--model", default="yolo11n.pt", help="YOLO weights (nano is fast on CPU)")
    ap.add_argument("--conf", type=float, default=0.35, help="global fallback detection confidence")
    ap.add_argument("--out", default=None, help="output dir (default runs/<timestamp>)")
    ap.add_argument("--no-frames", action="store_true", help="don't save annotated keyframes")
    args = ap.parse_args()

    # Lazy import so --help works without ultralytics installed.
    from ultralytics import YOLO

    zones = load_zones(args.zones)
    if not zones:
        raise SystemExit("No zones in config. Run draw_zones.py first.")
    states = {z.name: ZoneState(zone=z) for z in zones}

    out = args.out or os.path.join("runs", ts_slug())
    os.makedirs(out, exist_ok=True)
    frames_dir = os.path.join(out, "frames")
    if not args.no_frames:
        os.makedirs(frames_dir, exist_ok=True)

    obs_log = CsvLog(os.path.join(out, "observations.csv"),
                     ["ts", "zone", "asset_type", "persons_in_zone", "max_conf", "raw_present", "smoothed_state"])
    evt_log = CsvLog(os.path.join(out, "events.csv"), ["ts", "zone", "event", "smoothed_state"])
    ses_log = CsvLog(os.path.join(out, "sessions.csv"), ["zone", "asset_type", "start_ts", "end_ts", "duration_sec"])
    hlt_log = CsvLog(os.path.join(out, "health.csv"), ["ts", "event"])

    def log(msg):
        line = f"{now_iso()}  {msg}"
        print(line, flush=True)
        with open(os.path.join(out, "run.log"), "a") as f:
            f.write(line + "\n")

    log(f"Loading model {args.model} ...")
    model = YOLO(args.model)
    log(f"Model ready. Zones: {[z.name for z in zones]}")
    log(f"Sampling every {args.interval}s. Output -> {out}")

    cap = open_source(args.source)
    camera_online = cap.isOpened()
    if not camera_online:
        log("WARNING: source not open at start; will keep retrying (health=offline).")
        hlt_log.row(now_iso(), "offline")

    start_time = time.time()
    tick = 0
    try:
        while True:
            if args.hours and (time.time() - start_time) >= args.hours * 3600:
                log(f"Reached --hours {args.hours}; stopping.")
                break

            loop_start = time.time()

            if not cap.isOpened():
                cap.release()
                cap = open_source(args.source)
                if cap.isOpened():
                    if not camera_online:
                        camera_online = True
                        hlt_log.row(now_iso(), "recovered")
                        log("Camera recovered.")
                else:
                    if camera_online:
                        camera_online = False
                        hlt_log.row(now_iso(), "offline")
                        log("Camera offline; retrying...")
                    time.sleep(args.interval)
                    continue

            ok, frame = grab_recent_frame(cap)
            if not ok or frame is None:
                # File source ends -> stop. Live source -> mark offline & retry.
                if args.source.isdigit() or "://" in args.source:
                    if camera_online:
                        camera_online = False
                        hlt_log.row(now_iso(), "offline")
                        log("Lost frames; camera offline. Retrying...")
                    cap.release()
                    cap = open_source(args.source)
                    time.sleep(args.interval)
                    continue
                else:
                    log("End of file reached; stopping.")
                    break

            if not camera_online:
                camera_online = True
                hlt_log.row(now_iso(), "recovered")
                log("Camera recovered.")

            tick += 1
            ts = now_iso()

            # --- Detection (persons only) ---
            results = model.predict(frame, classes=[PERSON_CLASS], conf=args.conf,
                                     verbose=False)[0]
            persons = []  # (ground_point, conf)
            for b in results.boxes:
                xyxy = b.xyxy[0].tolist()
                conf = float(b.conf[0])
                persons.append((person_ground_point(xyxy), conf, xyxy))

            annotated = frame.copy()
            any_change = False

            # --- Per-zone occupancy ---
            for z in zones:
                poly = z.np_poly()
                in_zone = [(gp, c, box) for (gp, c, box) in persons
                           if c >= z.conf and point_in_poly(gp, poly)]
                count = len(in_zone)
                max_conf = max([c for _, c, _ in in_zone], default=0.0)
                raw_present = count > 0

                st = states[z.name]
                change = st.update(raw_present, ts)

                obs_log.row(ts, z.name, z.asset_type, count, f"{max_conf:.2f}",
                            int(raw_present), st.state)

                if change:
                    any_change = True
                    evt_log.row(ts, z.name, change, st.state)
                    log(f"[{z.name}] {change} -> {st.state}")
                    if change == "session_ended" and st.session_start_ts:
                        # session just closed in update(); compute duration
                        start_dt = datetime.fromisoformat(st.session_start_ts)
                        end_dt = datetime.fromisoformat(ts)
                        dur = int((end_dt - start_dt).total_seconds())
                        ses_log.row(z.name, z.asset_type, st.session_start_ts, ts, dur)
                        st.session_start_ts = None

                # draw zone
                color = {"OCCUPIED": (0, 0, 255), "AVAILABLE": (0, 200, 0)}.get(st.state, (160, 160, 160))
                cv2.polylines(annotated, [poly], True, color, 2)
                cx, cy = poly.mean(axis=0).astype(int)
                cv2.putText(annotated, f"{z.name}: {st.state} ({count})",
                            (cx - 60, cy), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)

            # draw person ground points
            for gp, c, box in persons:
                x1, y1, x2, y2 = [int(v) for v in box]
                cv2.rectangle(annotated, (x1, y1), (x2, y2), (255, 200, 0), 1)
                cv2.circle(annotated, (int(gp[0]), int(gp[1])), 4, (255, 0, 255), -1)

            if not args.no_frames and (any_change or tick == 1):
                fn = os.path.join(frames_dir, f"tick{tick:05d}-{ts_slug()}.jpg")
                cv2.imwrite(fn, annotated)

            if tick % 10 == 0:
                summary = "  ".join(f"{z.name}={states[z.name].state}" for z in zones)
                log(f"tick {tick} | {summary}")

            # pace to the interval
            elapsed = time.time() - loop_start
            if elapsed < args.interval:
                time.sleep(args.interval - elapsed)

    except KeyboardInterrupt:
        log("Interrupted by user (Ctrl-C).")
    finally:
        # close any still-open sessions
        for z in zones:
            st = states[z.name]
            if st.session_open and st.session_start_ts:
                ts = now_iso()
                dur = int((datetime.fromisoformat(ts) - datetime.fromisoformat(st.session_start_ts)).total_seconds())
                ses_log.row(z.name, z.asset_type, st.session_start_ts, ts, dur)
        cap.release()
        for lg in (obs_log, evt_log, ses_log, hlt_log):
            lg.close()
        log(f"Done. {tick} ticks. Results in {out}")


if __name__ == "__main__":
    main()
