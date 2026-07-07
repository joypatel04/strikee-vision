# Field Test Runbook (MacBook)

Everything runs on the MacBook. The Windows PC is not needed for this test.

## Done already (tonight, on wifi)

- ✅ Perception stack installed into `local-core/.venv` (torch, YOLO, OpenCV).
- ✅ YOLO model (`yolo11n.pt`) downloaded and cached in `local-core/`.
- ✅ Full pipeline verified end-to-end with real YOLO.

So at the club you need **no internet** — only the camera.

> Run everything from the `local-core/` directory so the setup script and the
> app share the same database (`strikee.db`).

## Before you leave: find the camera's RTSP URL

Get the RTSP stream URL + login from the venue's DVR/NVR or camera app. It looks
like:  `rtsp://username:password@192.168.1.50:554/stream1`
(the exact path varies by brand — check the camera/NVR manual or its web UI).

## At the club

### 1. Sanity check the environment

```bash
cd "/Users/joypatel/Documents/Strikee Vision/local-core"
source .venv/bin/activate
python -c "import torch, cv2, ultralytics; print('ok')"
```

### 2. Point at the camera, draw table zones, write the config

```bash
python field_setup.py --source "rtsp://USER:PASS@CAM_IP:554/stream1" --venue "Strikee Club"
```

- It grabs a frame and opens a window. **Click** the corners of each table's play
  area (where players stand/lean, not just the cloth), press **`n`** to name it,
  repeat for each table, then **`s`** to save.
- It writes the full venue config to `strikee.db`.
- Tip: try one or two tables first to validate, then add the rest.

If the stream won't open, the script tells you — double-check the URL, the
password, and that the MacBook is on the same network as the camera.

### 3. Launch the app

```bash
strikee-core
```

A window opens with the live dashboard (or your browser, if pywebview isn't
available). Pick the venue and press **Start pipeline**.

Optional: sample faster/slower with `STRIKEE_TICK_SEC=5 strikee-core` (default 7).

### 4. Watch it work

The asset grid should track reality within ~15s:

- **Available** (green) — empty table
- **Occupied** — someone there, not moving much
- **Active (In Use)** — movement detected
- **Occupied – Idle** — present but still for a while
- **Unknown / Degraded** (grey/orange) — camera issue or unclear view

Sessions accrue in the Sessions panel; events stream in; the analytics strip
shows counts by business unit.

### 5. Let it run, then judge it

Leave it running during normal operation (a couple of hours is ideal). Then:

- Compare the grid against what actually happened. Count **false Occupied**
  (empty table shown busy) and **false Available** (busy table shown free).
- Check the **Sessions** panel — do start/end times roughly match reality?
- Use ✓ / ✕ on sessions to confirm or void; that's the review workflow.

That comparison is the go/no-go answer on camera angle + detection quality.

## Tuning (no code edits — set env vars, then restart `strikee-core`)

| Symptom | Knob | Try |
|---|---|---|
| Misses people / too many Unknown | sensor confidence | lower it: `PATCH /api/sensors/{id}` `{"conf_threshold": 0.25}` via `/docs` |
| Flips busy/free too fast | `STRIKEE_ENTER_TICKS` / `STRIKEE_EXIT_TICKS` | raise (e.g. 3 / 4) |
| Shows "Active" when still / never idle | `STRIKEE_MOTION_THRESHOLD`, `STRIKEE_STILL_TICKS` | raise threshold (12–20), raise still ticks (4–6) |
| Sampling too slow/fast | `STRIKEE_TICK_SEC` | 5–10 |

Example: `STRIKEE_MOTION_THRESHOLD=15 STRIKEE_EXIT_TICKS=4 strikee-core`

To re-draw zones or add tables, re-run `field_setup.py` (it creates a fresh
venue; pick the newest one in the dashboard).

## Troubleshooting

- **Stream won't open** — verify the RTSP URL in VLC first (File → Open Network).
  If VLC can't play it, the app can't either.
- **Everything Unknown/grey** — the camera feed isn't being read (offline). Check
  the URL/network; the pipeline retries automatically when it recovers.
- **No detections at all** — the zone may not cover where people actually stand,
  or the angle is too steep. Re-draw the zone lower/wider.
- **Window doesn't appear** — the launcher falls back to the browser; open the
  printed `http://127.0.0.1:8760/` URL.
