# Field Test Runbook (MacBook)

Everything runs on the MacBook. The Windows PC is not needed for this test.

## Done already (tonight, on wifi)

- ✅ Perception stack installed into `local-core/.venv` (torch, YOLO, OpenCV).
- ✅ Your custom snooker model (`best.pt`) is in `local-core/` and wired in.
- ✅ **Game-tracking mode** verified end-to-end on your real footage: it detects
  balls on the table (`best.pt` + lighting normalization), tracks a **game in
  progress**, and opens/closes a **session per game** (18 balls → game on;
  cleared table → game over).

So at the club you need **no internet** — only the camera.

## What it tracks (snooker game mode)

- **In use vs Available = actual play (motion).** A table is **in use** only when
  someone is playing (movement on the table). Balls left sitting after a game do
  **not** count as in use — after a short no-play window the table reads
  **Available** (players leave balls/lights between games). "Active" = a shot
  happening; "Occupied – Idle" = a brief pause mid-game.
- **Games are counted by a state machine** (ported from your deployed snooker-ai
  logic): a game starts on a **`game_start` (rack) detection OR a confirmed full
  rack of reds** (so it still counts when the model misses the rack — verified on
  your `test_videos`, where `game_start` never fired but games were detected). A
  **lingering rack is not double-counted** (while a game is running, new rack
  detections are ignored). A game **ends** from the red-ball trajectory (reds
  clear to colours, then to none), then it waits for a player before the next
  game. A **re-rack** (a new game is set up mid-play — e.g. a player concedes and all
  balls are brought back) is counted as a new game, detected by **two
  independent checks**: (A) reds **jump up** clearly from the game's low point,
  and (B) the game reached a **clear low** then reds are **clearly high** again.
  Either one flags it — so an undercounted tight triangle still counts. Normal
  detection wobble (a frame misses a few balls, the next re-finds them) and
  single-frame dropouts are ignored so they don't fake a re-rack. Each game is
  logged with a **snapshot + start/end time + duration** for staff reconciliation.

> ⚠️ **Most important lesson from testing:** ball detection needs a
> **good-quality stream**. Heavy compression destroys the small balls. Use the
> camera's **main/high-res RTSP stream**, not a compressed sub-stream.

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

- Defaults to **snooker game mode**. It grabs a frame and opens a window. **Click
  the corners of the TABLE surface** (the green, where the balls are — *not* where
  people stand), press **`n`** to name it, repeat per table, then **`s`** to save.
- It writes the full venue config to `strikee.db`.
- Tip: try one table first to validate, then add the rest.
- For a people-watching camera instead (passage/reception), add `--mode occupancy`.

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

### Games log + evidence snapshots (staff reconciliation)

Every game start saves a **labelled, timestamped snapshot** (e.g. "Table 1
2026-07-08 14:23:05") to `snapshots/<venue>/<date>/`. See the **"Games today"**
panel on the dashboard, or the report:

```
GET /api/venues/{venue_id}/games?date=2026-07-08
```

Each entry has the table, start/end time, duration, and a link to the snapshot —
so you can compare the system's game log against what staff recorded and spot
discrepancies. Snapshots are stored **locally** (works offline). To auto-delete
after a week, run cleanup (e.g. a nightly/weekly scheduled task):

```python
from app.snapshots import SnapshotStore
SnapshotStore().cleanup(keep_days=7)
```

Optional cloud backup: set `STRIKEE_S3_BUCKET` (needs `boto3` + AWS creds) to
best-effort upload each snapshot to S3.

## Tuning (no code edits — set env vars, then restart `strikee-core`)

| Symptom | Knob | Try |
|---|---|---|
| Balls not detected / table shows Available during a game | **stream quality** | use the **main/high-res** RTSP stream, not a sub-stream |
| Misses some balls | sensor confidence | lower it: `PATCH /api/sensors/{id}` `{"conf_threshold": 0.15}` via `/docs` |
| Needs fewer balls to count as a game | sensor `params.min_balls` | set `{"params": {"min_balls": 2}}` |
| Table goes Available during a long player pause | `STRIKEE_EXIT_TICKS` | raise it — this is the **no-play window** before a table frees up (e.g. 8–20 ≈ 1–2 min at a 7s tick) |
| Table stays "in use" too long after players leave | `STRIKEE_EXIT_TICKS` | lower it |
| Games over/under-counted | `STRIKEE_RACK_REDS` | reds needed to treat as a new rack (default 10; raise to be stricter) |
| Re-rack (Check A) missed / false | `STRIKEE_RERACK_JUMP` | how big a red-count jump = a re-rack (default 6; raise to be stricter) |
| Re-rack (Check B) bands | `STRIKEE_RERACK_LOW` / `STRIKEE_RERACK_HIGH` | the "clearly low" and "clearly high" red counts for the second check (defaults 2 / 7 — set HIGH to what a fresh rack actually detects as) |
| Two quick frames merged into one game | `STRIKEE_MIN_GAME_MIN` | the min game window — raise to suppress spurious quick restarts (your 15-min idea) |
| A stuck/abandoned game never ends | `STRIKEE_MAX_GAME_MIN` | pure safety net — force-end after this many minutes (default **120**, well beyond any real frame, so a long game is never cut short). Raise if you ever have longer sessions. |
| Missed racks | sensor confidence | lower `conf_threshold`; use the main stream |
| "Active" vs "Idle" wrong | `STRIKEE_MOTION_THRESHOLD`, `STRIKEE_STILL_TICKS` | tune threshold / still ticks |
| Sampling too slow/fast | `STRIKEE_TICK_SEC` | 5–10 |
| Use a different snooker model | `STRIKEE_SNOOKER_MODEL` | path to a `.pt` |

Example: `STRIKEE_EXIT_TICKS=10 STRIKEE_TICK_SEC=6 strikee-core`

To re-draw zones or add tables, re-run `field_setup.py` (it creates a fresh
venue; pick the newest one in the dashboard).

## Troubleshooting

- **Stream won't open** — verify the RTSP URL in VLC first (File → Open Network).
  If VLC can't play it, the app can't either.
- **Everything Unknown/grey** — the camera feed isn't being read (offline). Check
  the URL/network; the pipeline retries automatically when it recovers.
- **No ball detections** — first suspect **stream quality** (use the main stream).
  Then check the zone actually covers the table surface, and lower the sensor
  confidence to 0.15.
- **No detections at all (people mode)** — the zone may not cover where people
  actually stand, or the angle is too steep. Re-draw the zone lower/wider.
- **Window doesn't appear** — the launcher falls back to the browser; open the
  printed `http://127.0.0.1:8760/` URL.
