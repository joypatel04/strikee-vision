# Strikee Vision — Local Core

On-site operations intelligence for a snooker club and gaming lounge. Watches the
venue's existing DVR cameras, works out which tables and stations are actually in
use, counts snooker games from the balls on the table, and keeps an evidence
snapshot of each one so the numbers can be reconciled against the till.

Everything runs **on a PC at the venue**. Cloud storage and the web dashboard are
additions, never dependencies: pull the internet out and the box keeps recording.

**Where to look**

| Document | For |
|---|---|
| **This file** | How it works, every setting, every tool |
| **[PREFLIGHT.md](PREFLIGHT.md)** | Setting up a box from scratch, in order |
| **[FIELD-TEST.md](FIELD-TEST.md)** | Running it at the venue and tuning what it gets wrong |
| **[CONFIG.md](CONFIG.md)** | The config API in detail |

---

## How it fits together

```
DVR (12 channels)
   |  RTSP, main stream, at most STRIKEE_MAX_STREAMS at once
   v
Capture scheduler  --> grabs the most-overdue camera, one frame, then closes
   |
   v
Detectors          --> best.pt (balls) and/or yolo11n (people), per camera
   |
   v
Observations       --> per sensor: is my zone occupied?
   |
   v
State engine       --> presence / activity / health, smoothed, per asset
   |
   +--> Sessions   (occupancy periods)      --> SQLite
   +--> Games      (racks, with snapshots)  --> SQLite + JPEG
   +--> Events     (every state change)     --> SQLite
                                                  |
                        +-------------------------+------------------------+
                        v                         v                        v
                  Dashboard                Turso (push)              S3 / R2
                127.0.0.1:8760         live data for the web app   snapshots + db backup
```

### The vocabulary

- **Venue** — the club. **One venue** holds everything.
- **Business Unit** — Snooker, Gaming Lounge. The analytics dimension; keep both
  in the one venue or you spend forever joining the club back together.
- **Asset** — a table or a station. What gets tracked and billed.
- **Zone** — the polygon on the camera image belonging to an asset.
- **Sensor** — a zone + a camera + a mode. An asset can have several.

Sensor modes:

| Mode | Detects | Produces |
|---|---|---|
| `snooker_game` | balls with `best.pt` | sessions **and** games |
| `occupancy` | people with `yolo11n` | sessions |
| `screen` | brightness/change in a zone | gates whether its asset counts as in use |
| `footfall` | *(built, not wired)* | line-crossing counts |

### Sessions versus games — they are not the same number

A **session** is an occupancy period: it opens when presence begins and closes
after `STRIKEE_EXIT_SEC` of absence. It knows nothing about snooker.

A **game** is a rack, counted by the snooker state machine, with a timestamped
evidence snapshot.

**Reconcile against games**, because that is what the club bills. Sessions are
the context: a table occupied for two hours with no games counted is exactly the
discrepancy worth looking at.

Sessions carry a status — `detected`, `confirmed`, `corrected`, `voided` — and
review actions append immutable correction events rather than overwriting what
the camera saw. The audit trail is the point.

---

## Setting up

Full walkthrough in **[PREFLIGHT.md](PREFLIGHT.md)**. In short:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[perception,desktop]"
.venv\Scripts\python.exe -m pip install --force-reinstall "torch==2.0.1" "torchvision==0.15.2" --index-url https://download.pytorch.org/whl/cpu
.venv\Scripts\python.exe -m pip install "numpy<2" boto3
copy .env.example .env          # then edit
.venv\Scripts\strikee-doctor.exe --model best.pt --rtsp "rtsp://USER:PASS@DVR/cam/realmonitor?channel={ch}&subtype=0" --channels 1,4,6
.venv\Scripts\python.exe field_setup.py --source "..." --venue "Strikee Club" ...
.venv\Scripts\strikee-core.exe
```

**Python 3.11 and `torch==2.0.1` are not preferences.** The venue box is a 2011
Sandy Bridge CPU with no AVX2; modern PyTorch aborts on import with a native
crash and no traceback, and no torch with 3.12 wheels avoids it.

**Always `.venv\Scripts\python.exe -m pip`, never bare `pip`** — bare `pip`
resolves to system Python and installs where the app never looks.

---

## Settings

Put them in **`.env`** beside `strikee.db`. It is read on every start, from any
shell, shortcut or scheduled task. On Windows `set VAR=x` applies only to the
window you typed it in, which is how a box ends up silently running on defaults.

A real environment variable still overrides the file, so `set` remains a one-off
override while tuning.

**Confirm anything took:** dashboard → **System check** → the **From** column
reads `env file`, not `default`.

### Capture

| Setting | Default | What it does |
|---|---|---|
| `STRIKEE_MAX_STREAMS` | `3` | Concurrent DVR connections, **shared across all venues**. 4 was measured to drop streams on this DVR. |
| `STRIKEE_RATE_TABLE` | `13` | Seconds between grabs of a snooker table. |
| `STRIKEE_RATE_GAMING` | `5` | Seconds between grabs of a person/screen camera. |
| `STRIKEE_RATE_ENTRY` | `3` | Seconds between grabs of an entry/footfall camera. |
| `STRIKEE_SCHEDULER` | `1` | `0` reverts to the legacy loop that holds every stream open at once. |
| `STRIKEE_TICK_SEC` | `7` | Legacy loop interval. Ignored by the scheduler. |

A camera that fails backs off automatically — each consecutive failure doubles
its next wait, capped at 120s, cleared by one success. A dead camera therefore
stops costing a lane every rotation, and the working ones keep their rate.

### Occupancy timing

| Setting | Default | What it does |
|---|---|---|
| `STRIKEE_EXIT_SEC` | — | **Seconds** of no activity before an asset frees up. |
| `STRIKEE_ENTER_SEC` | — | Seconds of presence before it counts as occupied. |
| `STRIKEE_STILL_SEC` | — | Stillness before Active drops to Idle. |
| `STRIKEE_EXIT_TICKS` | `3` | The same in *reads*. |
| `STRIKEE_ENTER_TICKS` | `2` | |
| `STRIKEE_STILL_TICKS` | `3` | |
| `STRIKEE_MOTION_THRESHOLD` | `8.0` | Pixel movement counting as play. |

**Prefer the `_SEC` forms.** A tick is not a duration: tables are grabbed every
13s and stations every 5s, so `EXIT_TICKS=3` frees a table after 39 seconds and a
station after 15. Seconds are converted per asset from its own rate, so 120 means
120 everywhere. If one evening fragments into five sessions, this is the knob.

### Screens (gaming stations)

| Setting | Default | What it does |
|---|---|---|
| `STRIKEE_SCREEN_LUM` | `120` | Brightness counting as "on". Not `90`: an off panel reflecting room lights measured 92–97 at the venue. |
| `STRIKEE_SCREEN_CONTRAST` | `off` | Spread of brightness across the zone. Off by default: measured at the venue it runs **backwards**, because these zones take in bezel and wall. Enable only if `--watch` says it separates. |
| `STRIKEE_SCREEN_SAT` | `off` | Colour in the zone. Off by default for the same reason — a lamp reflected in a dark panel is colourful. |

Any of these accepts `off` (or `none`) to disable that signal entirely. A screen reads on if **any** signal fires, so every enabled threshold must sit clear of what that zone reads while off — one that does not will hold a station open all night by itself. Per-sensor overrides live in the sensor's `params` (`{"screen_lum": 160}`) and beat the environment, which is how one awkward camera gets tightened without desensitising the rest.
| `STRIKEE_SCREEN_CHANGE` | `6` | Frame-to-frame change counting as "on". |
| `STRIKEE_SCREEN_HOLD_TICKS` | `2` | Consecutive dark reads forgiven before the screen closes the station. A screen never yet seen on gets no hold. |

A station with a screen zone is in use only when someone is there **and** the TV
is on. Either signal suffices: a paused game is bright and still, a dark game
scene is dim and moving. Per-sensor `params` override these for one awkward TV.

### Game counting

| Setting | Default | What it does |
|---|---|---|
| `STRIKEE_RACK_REDS` | `8` | Reds constituting a fresh rack. |
| `STRIKEE_RERACK_JUMP` | `6` | Red-count jump treated as a mid-game re-rack. |
| `STRIKEE_RERACK_LOW` / `STRIKEE_RERACK_HIGH` | `2` / `7` | The "clearly low" and "clearly high" bands. |
| `STRIKEE_MIN_GAME_MIN` | `0` | Minimum game length; suppresses spurious restarts. |
| `STRIKEE_MAX_GAME_MIN` | `120` | Safety net that force-ends a stuck game. |

### Models

| Setting | Default | What it does |
|---|---|---|
| `STRIKEE_SNOOKER_MODEL` | `best.pt` | The custom snooker model. **Irreplaceable** — `*.pt` is gitignored, so a clone never has it. |
| `STRIKEE_PERSON_MODEL` | `yolo11n.pt` | `yolo11x.pt` is far better at hard angles and far slower. |
| `STRIKEE_PERSON_CONF` | `0.25` | Lower finds more, with more false positives. |
| `STRIKEE_PERSON_IMGSZ` | `640` | People far down a room are a few dozen pixels tall and vanish at 640. Try `1280`. |
| `STRIKEE_PERSON_CLAHE` | off | Normalise lighting first. For a dim room. |
| `STRIKEE_PERSON_ASPECT` | — | e.g. `16:9`, when a channel delivers a squeezed frame. |

If a camera shows people and detects none, `tools/survey_cameras.py --sweep`
tries these combinations and reports which found the most.

### Storage

| Setting | Default | What it does |
|---|---|---|
| `STRIKEE_DB` | `strikee.db` | Database path. |
| `STRIKEE_SNAPSHOT_DIR` | `snapshots` | Where evidence images go. |
| `STRIKEE_SNAPSHOT_QUALITY` | `80` | ~75 KB per image; OpenCV's default 95 is ~160 KB for no visible gain. |
| `STRIKEE_SNAPSHOT_KEEP_DAYS` | `30` | Local images older than this are deleted four times a day. `0` keeps everything and the disk fills. |
| `STRIKEE_SNAPSHOT_MAX_MB` | `2000` | Disk budget for local evidence images. Once over, the oldest are deleted until under. `0` = no cap. Age alone is not a bound: a busy weekend writes more than a quiet fortnight. |
| `STRIKEE_S3_UPLOAD` | `all` | Which evidence images reach the bucket. `none` keeps the local archive and uploads nothing. Live frames are never uploaded under any setting. |
| `STRIKEE_LIVE_FRAMES` | `1` | Save each camera's last frame, annotated with zones and detections, for the dashboard. `0` disables. |
| `STRIKEE_LIVE_FRAME_WIDTH` | `960` | Downscale live frames to this width before saving. |
| `STRIKEE_LIVE_FRAME_QUALITY` | `70` | JPEG quality for live frames. |
| `STRIKEE_DEBUG` | off | `1` writes `debug_<venue>.csv`, one row per read per asset. |

Three snapshots per game (session start, game start, game end) at roughly 60
games a day is about **13 MB/day**, or 4.6 GB a year.

### Cloud sync

| Setting | Default | What it does |
|---|---|---|
| `STRIKEE_SYNC_MODE` | `replica` | `push` \| `replica` \| `off` — see below. |
| `TURSO_DATABASE_URL` | — | `libsql://your-db-org.turso.io` |
| `TURSO_AUTH_TOKEN` | — | A **database** token, not a platform API token. |
| `STRIKEE_TURSO_SYNC_SEC` | `15` | Seconds between pushes. |
| `STRIKEE_SYNC_BATCH` | `200` | Rows per request. |
| `STRIKEE_SYNC_METRICS` | off | Also push `metric_samples` (~2.4M rows/month). |

- **`push`** — local SQLite stays authoritative; new and changed rows go up over
  HTTP. Works against any Turso database, needs no `libsql` client, and the box
  records through an outage and resends afterwards. **Use this** unless you know
  embedded replicas work for your database.
- **`replica`** — libsql embedded replica. Neater when available, but needs the
  `/v1` replication endpoints, which many databases do not serve. The symptom is
  `failed to pull db export status 404`. Check with `tools/turso_check.py`.

### Object storage

| Setting | Default | What it does |
|---|---|---|
| `STRIKEE_S3_BUCKET` | — | Bucket for evidence snapshots. |
| `STRIKEE_S3_ENDPOINT` | — | Only for R2 or another S3-compatible store. Falls back to the backup endpoint. |
| `STRIKEE_S3_REGION` | — | Falls back to the backup region, then `auto` behind an endpoint. |
| `STRIKEE_BACKUP_BUCKET` | — | Bucket for whole-database backups. |
| `STRIKEE_BACKUP_PREFIX` | `strikee` | Folder inside it, e.g. `db-backup`, so backups can share the snapshot bucket. |
| `STRIKEE_BACKUP_ENDPOINT` / `STRIKEE_BACKUP_REGION` | — | As above. |
| `STRIKEE_BACKUP_EVERY_MIN` | — | Minutes between backups. Unset means none. |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | — | Credentials for both. |
| `AWS_DEFAULT_REGION` | — | e.g. `ap-south-1`. **Required on AWS** — `auto` is an R2 convention and resolves to nothing on Amazon. |

**Set a lifecycle rule scoped to a prefix.** An expiry on the whole bucket
deletes your database backups along with old snapshots.

### Unattended running

| Setting | Default | What it does |
|---|---|---|
| `STRIKEE_AUTOSTART_VENUE` | — | Venue id, or `all`, to start tracking on boot. |
| `STRIKEE_HEADLESS` | — | `1` for server only, no desktop window. |
| `STRIKEE_WATCHDOG_SEC` | `60` | Seconds between system health checks. |
| `STRIKEE_ENV_FILE` | — | Explicit path to the `.env`. |

---

## Tools

| Command | What it is for |
|---|---|
| `strikee-doctor --model best.pt --rtsp "...{ch}..." --channels 1,4,6` | The gate. Proves Python, torch, OpenCV, the model, disk, cloud sync, both buckets and every camera. Run before anything else. |
| `python field_setup.py --source ... --venue ...` | Draw zones. See below. |
| `strikee-core` | Run the pipeline and serve the dashboard on `127.0.0.1:8760`. |
| `python tools/survey_cameras.py --url "...{ch}..." --channels 1-12 [--sweep]` | Look at every channel and report what the models see. Run before drawing zones. |
| `python tools/turso_check.py <url> <token>` | Prove a Turso database is reachable, writable, and which sync mode to use. |
| `python tools/restore.py [--list \| --verify \| --yes]` | List, verify or restore a database backup. |
| `python tools/show_config.py [--venue "..."]` | The whole configuration as a tree - assets, their sensors, cameras - plus the exact redraw command for each. Start here before changing anything. |
| `python tools/debug_frame.py --venue "..." [--source "..."]` | Render one live frame per camera with its zones, detections and each sensor's verdict. The tool for "why will this asset not go occupied". |
| `python tools/rename_cameras.py [--auto]` | List cameras and what each watches; rename them from the channel in their URL. |
| `python tools/fresh_start.py [--yes]` | Wipe local database, snapshots and debug logs for a clean setup. |
| `strikee-backup` | Run one backup now. |

### Drawing zones

```powershell
.venv\Scripts\python.exe field_setup.py `
  --source "rtsp://USER:PASS@DVR:554/cam/realmonitor?channel=1&subtype=0" `
  --venue "Strikee Club" --business-unit "Snooker" `
  --asset-type "Snooker Table" --mode snooker_game `
  --source-name "Channel 1" --aspect 16:9
```

- **`--source-name` names the CAMERA, not the table.** Easy to get wrong when
  one camera covers two tables. Nothing tracks by it - a camera is matched by
  its RTSP URL - so fix it later with `tools/rename_cameras.py --auto`.
- **The same `--venue` every time.** Runs after the first must print
  `reusing existing venue` — one that does not has just made a second venue.
- **Controls:** click corners → click the image window → **`n`** → **type the
  name in the terminal**, Enter (the window freezes until you do; that is the
  prompt waiting) → repeat → **`s`** to save. **`q` discards everything.**
- **Draw around:** the table surface for `snooker_game`; where a **person** is
  for `occupancy`, remembering people are placed at the *bottom-centre* of their
  box — for someone seated that is the seat, not the floor in front; the **panel
  only** for `screen`.
- `--redraw` **replaces** the polygons of existing assets of the same name on
  this camera. The current shapes are outlined in grey while you draw, and the
  assets keep their ids - so sessions, games and screen sensors all survive and
  only the shape changes. Restart `strikee-core` afterwards.
- `--with-screen` draws **two polygons per station in one pass** - the seating
  area, then that station's screen - naming it once. For a gaming lounge this
  halves the runs and removes the exact-name match between a screen and its
  station.
- `--attach` adds the zones as **extra sensors on existing assets** of the same
  name, rather than creating assets. Use it to watch one table both ways (balls
  *and* people), or to add a second camera angle. `--mode screen` always
  attaches. `--role` sets primary or supporting; the default is supporting, and
  presence is *primary OR a confident supporting sensor*.
- Overlapping zones are reported by name: a person is one point, so if it falls
  in two polygons both read occupied.
- `--aspect 16:9` unsqueezes an anamorphic channel for drawing while still
  storing zones against the real frame.

---

## Operating it

### The dashboard — `http://127.0.0.1:8760/`

Faults appear as a banner naming what broke and which adapter to check. The two
networks are tested **directly**, not inferred from camera behaviour, so this is
right even with the pipeline stopped:

| Banner | Meaning |
|---|---|
| **Cannot reach the cameras** | The DVR does not answer *but this PC has internet* — so the box is online and the camera-side adapter is the problem. |
| **No network at all** | Neither answers. |
| **No internet** | Cameras fine, recording continues. Sync and uploads pause and catch up — nothing is lost. |
| **N of M cameras not responding** | Network is fine; those channels are not. |

Only one fault is raised per cause: a dead camera network does not also produce
a camera-failure alarm and a stalled-sync alarm, because three alarms for one
unplugged dongle teaches people to ignore alarms.

**System check** at the bottom shows every setting with where it came from
(`env file` versus `default`), the installed library versions, model files, live
per-camera capture health, and the grace window each asset actually ended up
with.

### When an asset will not go occupied

Four different causes look identical from the dashboard: the person is not
detected; they are detected but their point falls outside the zone; the zone is
on the wrong camera; or a `screen` sensor is holding the asset shut because the
TV reads as off. `tools/debug_frame.py` renders all four onto one image using
the same detectors and observers the pipeline uses, and prints a verdict per
sensor:

```
IN USE  RED   occupancy   1 in zone
closed  RED   screen      [off] lum=94.2/120 contrast=9.1/28 sat=4.0/14 change=1.10/6
```

That pair says the person is seen and inside the zone, and the screen gate is
what is closing the station - so the fix is `STRIKEE_SCREEN_LUM`, not the zone.

Two more things it can tell you:

```
.venv\Scripts\python.exe tools\debug_frame.py --venue "Strikee Club" --watch 60
```

samples every screen zone for a minute. To turn that into a threshold you need
both states, and there are two ways to get them.

**During service**, name the stations whose TVs are on right now — the room
already contains both states, so one pass is enough and nobody has to switch off
a customer's TV:

```
... --watch 60 --on "Station 1,Station 2,Station 3"
```

**When the room is empty**, measure the same screens twice, which is the
stronger evidence because it compares each television against itself:

```
... --watch 60 --state on        then        ... --watch 60 --state off
```

Either way it prints the thresholds that separate on from off, and marks any
signal whose ranges overlap as unusable.

### Why brightness alone cannot decide a screen

Measured at the venue: an **off** panel reads 92-97, because it reflects the room
lighting. A night level or loading screen on a TV that is **on** can read below
that. The two ranges overlap, so no brightness threshold works - raise it and you
lose dark games, lower it and every off TV reads as on.

Four statistics are taken over the zone instead, and any one is enough:

| | on | off |
|---|---|---|
| `luminance` | bright screen | *also* a lit reflection |
| `change` | anything playing | a still room |
| `contrast` | HUD, subtitles, edges | a smooth wash of ambient light |
| `saturation` | games are coloured | reflected light is nearly grey |

Structure and colour are required *together*: structure without colour is a
window reflection, colour without structure is a wall. The verdict names which
signal fired, so `[picture]` and `[bright]` are distinguishable at a glance and
`[off]` tells you none of them did.

If `--state` reports that **every** signal overlaps, the zone is taking in more
than the panel - wall, bezel or a window dilutes every statistic toward the
room - and the fix is a tighter redraw, not a number.

### Camera frames in the dashboard

**Camera frames** at the bottom of the dashboard shows the last frame each
camera produced, with its zones, detections and verdicts drawn on. Click one to
enlarge, or **Download** to send it on when asking for help.

These are written by the pipeline itself, so they are the exact picture the
state engine acted on - grabbing a fresh frame to look at would show a different
moment than the one that produced the verdict you are questioning.

They cost nothing to keep: one file per camera, overwritten in place, so ten
cameras is ten files today and in a year. They are **never uploaded** - an
evidence image is written three times a game and is worth cloud storage, a live
frame is worthless ten seconds later. `STRIKEE_LIVE_FRAMES=0` turns them off.

The section only polls while it is open, so a closed panel costs nothing.

### Judging whether it is right

Camera counts are not evidence. **Write down the real games on one table by
hand**, then compare against the Games panel and open the snapshots. Count false
Occupied and false Available. `debug_<venue>.csv` (with `STRIKEE_DEBUG=1`) has
one row per read per asset showing what the model saw and what the tracker
decided — that is what tells you which knob to turn.

### If the PC dies

```powershell
# rebuild the stack, restore the same .env, then:
.venv\Scripts\python.exe tools\restore.py --verify
.venv\Scripts\python.exe tools\restore.py --yes
```

Venue, zones, stations and history come back in one step. **Verify a backup now,
while nothing is wrong** — a backup nobody has restored is a hope, not a backup.

---

## Development

```bash
python -m pytest            # ~300 tests, no cameras or models needed
```

Tests use fakes throughout, so the perception extra is not required to run them.

### Layout

```
app/
  main.py           FastAPI app, routes, background tasks
  api.py            generic CRUD router built from the entity registry
  entities.py       the config model (organization -> venue -> ... -> sensor)
  db.py             SQLite / libsql adapter
  store.py          events, sessions, metrics, rules, notifications
  admin.py          venue rename and delete-for-real
  diagnostics.py    what is actually in effect
  watchdog.py       system faults, in plain language
  cloudsync.py      push rows to Turso over HTTP
  backup.py         database snapshot -> S3/R2
  snapshots.py      evidence images
  doctor.py         the bring-up self-check
  pipeline/
    scheduler.py    K-slot rotating capture with per-camera backoff
    capture.py      RTSP grab, forced TCP, ffmpeg fallback
    perception.py   YOLO detectors
    observe.py      detections -> per-sensor observations
    state.py        presence / activity / health, smoothing, screen gate
    snooker_game.py the game state machine
    runtime.py      ties a venue's sources, sensors and assets together
    manager.py      per-venue lifecycle, shared stream budget
web/index.html      the dashboard, entirely self-contained
tools/              survey, turso_check, restore, fresh_start
```

### Things that have already cost an evening

- **Bare `pip`** installs into system Python, not the venv.
- **Python 3.12** cannot run torch on this CPU, and downgrading torch does not
  help — 3.11 is required.
- **`set VAR=x`** dies with the window. Use `.env`.
- **LAN 1 on the Airtel router** serves no DHCP.
- **`nslookup` on a Turso host** always succeeds — `*.turso.io` is wildcard DNS.
  It proves nothing.
- **Drawing zones before configuring an embedded replica** makes a database the
  replica cannot adopt. (Irrelevant in `push` mode.)
- **`region=auto`** is R2-only and resolves to nothing on AWS.
- **A missing `s3:PutObject`** fails silently forever, because uploads are
  best-effort by design. `strikee-doctor` now round-trips a real object.
