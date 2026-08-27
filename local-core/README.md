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
| `STRIKEE_SCREEN_LUM` | `90` | Brightness in a screen zone counting as "on". |
| `STRIKEE_SCREEN_CHANGE` | `6` | Frame-to-frame change counting as "on". |

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

Faults appear as a banner naming what broke and which adapter to check. The box
has two networks and either can fail alone: losing the cameras stops tracking
while the dashboard still loads over the other, and losing the internet stops
sync while every table keeps updating. Both look fine from the wrong angle.

**System check** at the bottom shows every setting with where it came from
(`env file` versus `default`), the installed library versions, model files, live
per-camera capture health, and the grace window each asset actually ended up
with.

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
