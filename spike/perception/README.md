# Strikee Vision — Perception Spike

Goal: **de-risk the single biggest technical unknown** before building the full
product — *can local YOLO reliably tell "occupied vs available" on a snooker
table at the club's real camera angles and lighting?*

This spike mirrors the product's real pipeline so it validates the actual
approach, not a toy:

```
frame  →  YOLO person detection  →  person-in-zone  →  presence
       →  smoothed state (min start / min clear ticks)  →  table-usage session
```

It samples **every 5–10 seconds** (not continuously) to match the product's
periodic, low-cost local model. No video is stored — only annotated keyframes
on state changes, plus CSV logs.

## What it is NOT

Not the product. It's a throwaway validation harness. The real system reuses
the *idea* (and YOLO), not this code.

## Setup

```bash
cd spike/perception
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

First run downloads the YOLO weights (`yolo11n.pt`, a few MB) automatically.

## Using it at the club (live stream, 3–4 hour test)

**1. Confirm the stream connects and grab a reference frame:**

```bash
python snapshot.py --source "rtsp://USER:PASS@CAM_IP:554/stream1"
```
Find the exact RTSP URL in the DVR/NVR or camera settings. Saves `frame.jpg`.

**2. Draw occupancy zones on that frame (one polygon per table):**

```bash
python draw_zones.py --frame frame.jpg --out zones.json
```
Click the corners of each table's play area, press `n` to name it, `s` to save.
Draw the polygon around **where players stand/lean**, not just the cloth — the
spike tests the player's *feet* (bottom-centre of their box) against the zone.

**3. Run the logic against the live stream for a few hours:**

```bash
python run_spike.py --source "rtsp://USER:PASS@CAM_IP:554/stream1" \
    --zones zones.json --interval 7 --hours 4
```

Leave it running while the club operates. Ctrl-C stops it early.

## Dev run (no club needed — validate the pipeline first)

Against a video file or your webcam:

```bash
python run_spike.py --source clip.mp4 --zones zones.json --interval 7
python run_spike.py --source 0 --zones zones.json --interval 5     # webcam
```

## Reading the results

Everything lands in `runs/<timestamp>/`:

| File | What to check |
|---|---|
| `sessions.csv` | Did detected table-usage sessions match reality (roughly right start/end)? |
| `observations.csv` | Per-tick truth: how many persons in each zone, confidence, raw vs smoothed state |
| `events.csv` | Every state change (became_occupied / became_available / session_ended) |
| `frames/` | Annotated keyframes saved on each state change — eyeball for false hits/misses |
| `health.csv` | Camera offline/recovered transitions |

**The key question to answer at the club:** scrub `frames/` and compare
`observations.csv` against what actually happened. Count false "occupied" (empty
table flagged busy) and false "available" (busy table flagged free). That tells
us if the angle/model is good enough, or if we need a better model, better zones,
or a different mounting.

## Tuning knobs

| Flag / field | Effect |
|---|---|
| `--interval` | seconds between samples (5–10 recommended) |
| `--model` | `yolo11n.pt` (fast) → `yolo11s.pt` / `yolo11m.pt` (more accurate, slower) |
| `--conf` | global detection confidence floor |
| zone `conf` | per-zone confidence threshold |
| zone `min_start_ticks` | how many present-ticks before flipping to OCCUPIED (debounce) |
| zone `min_clear_ticks` | how many empty-ticks before flipping to AVAILABLE (grace window) |

With `--interval 7`, `min_start_ticks 2` ≈ 14s of presence to open, and
`min_clear_ticks 3` ≈ 21s clear to close — a sensible starting point for tables.

## Notes / caveats

- The spike decides occupancy from **person presence in the zone**, which is the
  MVP signal for a snooker table. It does not judge "are they actually playing"
  (activity) — that's the separate activity facet in the full design.
- Runs on CPU fine at this sample rate. GPU (CUDA/Apple Silicon) is auto-used if
  available and speeds up per-frame inference.
- Final performance numbers should be confirmed on the **target Windows box**;
  the logic is identical cross-platform.
