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

## Windows venue box — bring-up (one-time)

The code is cross-platform; the two historical "works on Linux, breaks on
Windows" traps are handled for you: the OpenMP `libiomp5md.dll` clash (auto-set
`KMP_DUPLICATE_LIB_OK`) and flaky HEVC/RTSP (forced TCP transport + an ffmpeg
fallback in the frame grabber). Steps on the Windows box:

```
python --version                 # need 3.11+  (install from python.org / winget)
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[perception,desktop]"

REM prove the stack — especially the model, which is what broke before:
strikee-doctor --model best.pt --rtsp "rtsp://USER:PASS@DVR_IP:554/cam/realmonitor?channel=1&subtype=0"
```

`strikee-doctor` checks Python, torch (+ CPU/GPU), OpenCV, **loads best.pt and
runs one real inference**, and (with `--rtsp`) decodes one DVR frame. All green =
safe to run `strikee-core`. If the model line ever fails, that output is the
exact error to send me. (For the ffmpeg fallback, install ffmpeg and put it on
PATH — optional, only used if OpenCV can't decode the HEVC stream itself.)

## Remote access + backup (view from anywhere, keep it safe)

One database (local SQLite), viewed live off-box and backed up to the cloud — no
Google Sheets, no second datastore.

### View the dashboard from anywhere — Cloudflare Tunnel (free)

The box already serves the full live dashboard on `127.0.0.1:8760`. A tunnel
makes it reachable from your phone/laptop without opening any ports.

- **Quick try (no account):** on the box, `cloudflared tunnel --url http://127.0.0.1:8760`
  prints a temporary `https://….trycloudflare.com` URL. Good for a first look;
  it changes each run and is unprotected.
- **Real use:** a **named tunnel** on your Cloudflare account routed to a
  subdomain, run as a Windows service, and gated with **Cloudflare Access**
  (email one-time-code) so only you can open it. Then the dashboard is at a
  stable, private URL. The box stays the source of truth; nothing syncs.

### Back up the DB to Cloudflare R2 (free tier, no egress fees)

A consistent snapshot (`VACUUM INTO`, safe while the pipeline writes) is uploaded
on a schedule, so a dead box loses nothing.

```
pip install -e ".[cloud]"          # boto3

REM env on the box (R2 example):
set STRIKEE_BACKUP_BUCKET=strikee
set STRIKEE_BACKUP_ENDPOINT=https://<ACCOUNT_ID>.r2.cloudflarestorage.com
set AWS_ACCESS_KEY_ID=<r2 token key>
set AWS_SECRET_ACCESS_KEY=<r2 token secret>
set STRIKEE_BACKUP_EVERY_MIN=10     REM app backs up every 10 min automatically

strikee-backup                      REM or run once manually / from Task Scheduler
```

Uploads `strikee-<timestamp>.db` plus a stable `strikee-latest.db`. To read the
data, pull `strikee-latest.db` and open it in any SQLite tool. Backup is
best-effort — a failed upload never affects the venue. (S3 works too: set the
same vars, drop the R2 endpoint, use a real region.)

### Option: Turso (cloud-synced database) instead of tunnel+R2

If you'd rather have ONE system — a SQLite you query from anywhere, always
available — use the **Turso** backend. The box writes to a **local replica**
(so it keeps recording offline), and syncs to the Turso cloud so the data is
queryable remotely. Free tier is plenty.

```
pip install -e ".[turso]"          # native libsql client

REM 1) verify the native client works on THIS box FIRST, no cloud needed:
set STRIKEE_LIBSQL_LOCAL=1
strikee-doctor --model best.pt     REM Turso line should say libsql loads/runs

REM 2) then point at your Turso DB:
set TURSO_DATABASE_URL=libsql://<your-db>.turso.io
set TURSO_AUTH_TOKEN=<token>
set STRIKEE_TURSO_SYNC_SEC=15       REM push local changes to cloud every 15s
strikee-doctor --model best.pt     REM Turso line should say "synced to cloud"
strikee-core
```

**Sync health is visible.** The dashboard header shows a badge — **`☁ synced 12s ago`** (green) when tracking data is reaching the cloud, or **`⚠ NOT syncing`** (red) if it stalls — so you'd notice immediately if data stopped flowing. Also at `GET /api/sync-health`. (Hidden entirely on local-only sqlite3.)

**Verify offline writes before you trust it (important):** with Turso set,
start `strikee-core`, **disconnect the internet**, and confirm games still get
recorded (the local replica should accept writes). Reconnect and confirm they
appear in Turso. If writes fail while offline, stay on the local-first SQLite +
tunnel/R2 setup instead — the box must never miss a rack because the wifi
blipped. (`strikee-doctor` with `STRIKEE_LIBSQL_LOCAL=1` isolates the native-
client question from the network question.)

## Run unattended on Windows (PC on → it just works, staff do nothing)

By default the app needs someone to launch it and click **Start pipeline**. To
make it turnkey, two things: auto-start the pipeline, and auto-launch on boot.

**One-time setup (during install):** configure the venue and draw the zones with
`field_setup.py` first — auto-start only works once a venue exists.

**1) Make the app auto-start the pipeline + run windowless.** Set these as
*system* environment variables (so they apply at boot):

```
STRIKEE_AUTOSTART_VENUE = <your venue id>     (or "all" for every venue)
STRIKEE_HEADLESS        = 1                    (server only, no window)
STRIKEE_MAX_STREAMS     = 3
# + your DB choice: STRIKEE_DB=... or the TURSO_* vars
```

Now `strikee-core` boots straight into running the venue — no clicks. Staff open
the dashboard at `http://127.0.0.1:8760/` (or the tunnel URL) only when they want
to *look*; they never have to start anything.

**2) Launch it on boot.** Simplest reliable path for a club PC:

- Enable **Windows auto-login** for the club user.
- Put a shortcut to `strikee-core` (the venv's `Scripts\strikee-core.exe`) in the
  **Startup folder** (`Win+R` → `shell:startup`).

More robust (survives crashes, runs without login) — Task Scheduler:

```
schtasks /Create /TN "StrikeeVision" /SC ONSTART /RL HIGHEST /RU SYSTEM ^
  /TR "C:\path\to\.venv\Scripts\strikee-core.exe" /F
# then, in Task Scheduler UI: Properties → Settings →
#   "If the task fails, restart every 1 minute, up to 3 times"
```

**3) Stop the PC from sleeping** (or it stops processing when idle):

```
powercfg /change standby-timeout-ac 0
powercfg /change monitor-timeout-ac 0
```

**Recovery:** on a power cut / reboot, the PC powers on → the task relaunches
`strikee-core` → auto-start begins the pipeline again. If the DVR is slow to come
up, the capture scheduler retries offline cameras automatically. So a rebooted
club PC returns to tracking on its own, hands-off.

## Gaming lounge (a second business unit in the SAME venue)

Snooker and the gaming lounge belong in **one venue** as two **business units** —
not two venues. The stream budget is process-wide but analytics, the games log
and the reconciliation app are all per venue, so splitting them means joining
the club back together by hand. Business Unit is already the analytics
dimension.

Draw stations exactly like tables, changing three flags:

```bash
python field_setup.py --source "rtsp://USER:PASS@DVR_IP:554/cam/realmonitor?channel=9&subtype=0" \
    --venue "Strikee Club" \
    --business-unit "Gaming Lounge" --asset-type "Gaming Station" \
    --mode occupancy --source-name "Gaming Camera A"
```

Keep `--venue` **identical** to the snooker runs — that is what puts them in the
same venue. You should see `reusing existing venue 'Strikee Club'`.

- **Draw around where a person is, feet included.** People are placed by the
  bottom of their detection box, so a zone hugging a seat or a screen misses a
  player whose feet fall outside it.
- **Check the model actually sees people at that angle first.** The overhead
  table cameras defeated person detection entirely; there is no point drawing
  six zones until one works. Run the pipeline with a single station drawn and
  watch it before doing the rest.
- Stations get **occupancy sessions** but **no game counting** — correct, there
  are no racks. `best.pt` is never loaded for them; they use `yolo11n.pt`.
- Stations are sampled every 5s (`STRIKEE_RATE_GAMING`) against a table's 13s,
  which is why the grace window belongs in `STRIKEE_EXIT_SEC`, not ticks.

## Footfall (Channel 7 — club entrance)

Footfall is counted by **directional line-crossing**: people are tracked
frame-to-frame (ByteTrack — a temporary id while on screen, no face/identity)
and a virtual **line** across the entrance counts each passage `in` / `out`.
Footfall = `in` crossings; **occupancy = in − out** (self-corrects when someone
steps out for a call and returns). It's a **trend** tool — a consistent daily
proxy, not an exact headcount (a re-entering regular counts twice; we can't
re-identify without faces). All traffic is on the **left** of the ch7 frame
(main door bottom-left, gaming-lounge entrance mid-left; the centre pillar hides
only a railing/stairwell with no traffic — so we ignore the centre/right).

Footfall needs a **dedicated continuous lane** (several fps), unlike the slow
rotating table cameras — tracking needs consecutive frames.

**Probe it on-site (see what the model picks up before committing):**

```
# in the scratchpad dir, with the venue network reachable:
# 1) LOOK at detection first (the make-or-break in low light):
python footfall_test.py --channel 7 --minutes 10 --fps 4 --clahe

# 2) once you can see where people walk, add the two left-side lines
#    (x1,y1,x2,y2; 'inside' = LEFT of a->b; add --flip-* if it counts backwards)
python footfall_test.py --channel 7 --minutes 20 --fps 5 --clahe \
    --club-line 250,300,250,760 --gaming-line 120,150,120,520 \
    --roi-right 900        # ignore everything right of x=900 (pillar/door)
```

It draws boxes + track ids + feet points + the lines + live counts, saves
annotated frames to `footfall_out/frames/`, and logs `footfall_out/footfall.csv`.
**Validate after the lighting upgrade** — night detection at that dark corner is
the limiting factor, not the counting logic.

## Validating a LIVE run (no video to re-watch)

You can't rewind a live stream, so validate three ways together:

1. **Ground truth (do this).** While it runs, jot down the real games on one
   table — rough start/end times, or just a tally. This is your reference.
2. **Compare the Games log.** Open the dashboard "Games today" panel (or
   `GET /api/venues/{id}/games`). Compare count + times against your notes, and
   **open each game's snapshot** to confirm it was a real rack / a real end.
3. **Debug log — to understand *why*.** Run with debug on:

   ```bash
   STRIKEE_DEBUG=1 strikee-core
   ```

   This writes `debug_<venue>.csv` — one row per tick per table with what the
   model saw (`red`, `game_start`, `player`, motion) and what the tracker decided
   (`state`, `red_floor`, `event`). When a game is missed or false, this shows
   exactly why, and which knob to turn. Examples:
   - games **missed** and `red` peaks at ~6 on a fresh rack → lower
     `STRIKEE_RACK_REDS` / `STRIKEE_RERACK_HIGH` to ~6.
   - **extra** games and `red` swings a lot → raise `STRIKEE_RERACK_JUMP`.
   - a real game ended late → check the `red`→0 tail; adjust nothing or lower
     the end hold.

**Tune → restart → re-observe.** All thresholds are env vars, so you iterate
without touching code.

**Optional — record for later review.** If you want to double-check a
discrepancy against footage, record the stream to a file during the test (in a
separate terminal), then delete it after:

```bash
ffmpeg -i "rtsp://USER:PASS@CAM_IP:554/stream1" -c copy -t 7200 test_recording.mp4
```

## Tuning (no code edits — set env vars, then restart `strikee-core`)

| Symptom | Knob | Try |
|---|---|---|
| Balls not detected / table shows Available during a game | **stream quality** | use the **main/high-res** RTSP stream, not a sub-stream |
| Misses some balls | sensor confidence | lower it: `PATCH /api/sensors/{id}` `{"conf_threshold": 0.15}` via `/docs` |
| Needs fewer balls to count as a game | sensor `params.min_balls` | set `{"params": {"min_balls": 2}}` |
| Table goes Available during a long player pause | **`STRIKEE_EXIT_SEC`** | the no-play window in **seconds** before an asset frees up (e.g. `120`). Prefer this over `STRIKEE_EXIT_TICKS`: tables are grabbed every ~13s and gaming stations every ~5s, so one tick count means 39s on a table and 15s on a station. Seconds are converted per asset from its own rate. `STRIKEE_ENTER_SEC` / `STRIKEE_STILL_SEC` work the same way. |
| Table stays "in use" too long after players leave | `STRIKEE_EXIT_TICKS` | lower it |
| Games over/under-counted | `STRIKEE_RACK_REDS` | reds needed to treat as a new rack (default 10; raise to be stricter) |
| Re-rack (Check A) missed / false | `STRIKEE_RERACK_JUMP` | how big a red-count jump = a re-rack (default 6; raise to be stricter) |
| Re-rack (Check B) bands | `STRIKEE_RERACK_LOW` / `STRIKEE_RERACK_HIGH` | the "clearly low" and "clearly high" red counts for the second check (defaults 2 / 7 — set HIGH to what a fresh rack actually detects as) |
| Two quick frames merged into one game | `STRIKEE_MIN_GAME_MIN` | the min game window — raise to suppress spurious quick restarts (your 15-min idea) |
| A stuck/abandoned game never ends | `STRIKEE_MAX_GAME_MIN` | pure safety net — force-end after this many minutes (default **120**, well beyond any real frame, so a long game is never cut short). Raise if you ever have longer sessions. |
| Missed racks | sensor confidence | lower `conf_threshold`; use the main stream |
| "Active" vs "Idle" wrong | `STRIKEE_MOTION_THRESHOLD`, `STRIKEE_STILL_TICKS` | tune threshold / still ticks |
| Sampling too slow/fast | `STRIKEE_TICK_SEC` | 5–10 (legacy tick loop only) |
| Use a different snooker model | `STRIKEE_SNOOKER_MODEL` | path to a `.pt` |
| DVR drops streams under load | `STRIKEE_MAX_STREAMS` | max concurrent connections (default **3** — measured safe on the club Dahua; 4 dropped). This is now a **process-wide** budget shared by every running venue, not a per-venue cap. |
| A dead camera slows the working ones | *(automatic)* | a source that fails backs off exponentially (interval x2 per failure, capped 120s) and returns to its normal rate after one success — so an unplugged camera stops costing a lane every rotation |
| Snooker tables sampled too slow/fast | `STRIKEE_RATE_TABLE` | seconds between grabs per table (default **13**) |
| Gaming-zone cameras sampled too slow/fast | `STRIKEE_RATE_GAMING` | seconds per grab (default **5**) |
| Entry/footfall cameras sampled too slow/fast | `STRIKEE_RATE_ENTRY` | seconds per grab (default **3**) |
| Force the old all-streams-at-once loop | `STRIKEE_SCHEDULER=0` | only safe when #cameras ≤ DVR limit |

### Capture scheduler (default)

The pipeline now captures through a **K-slot rotating scheduler**: it holds at
most `STRIKEE_MAX_STREAMS` (default 3) connections open and grabs each camera at
its own target rate (entries every 3s, gaming every 5s, tables every 13s),
always servicing the most-overdue camera first. This runs all the venue's
cameras through the DVR's small concurrent-stream budget **without ever
exceeding it** — no dropped streams. Validated live on the club DVR: max 3
concurrent, entries grabbed ~4× more often than tables. Rates are per **sensor
kind**, so once the gaming/entry cameras are configured they get the right
cadence automatically. Snooker tables use the `snooker_game` kind; entry cameras
use the `footfall` kind (add it when you draw those zones).

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
