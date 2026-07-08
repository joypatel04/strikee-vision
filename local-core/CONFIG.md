# Strikee Vision — Environment Configuration Reference

Every runtime knob is an **environment variable**, so you tune the system at the
venue without editing code — set them, then (re)start `strikee-core`. This is the
complete list, grouped by purpose, with the default, what it does, and when to
reach for it.

Nothing here is required to *run* — all have sensible defaults. You only set what
you want to change or enable (Turso, backup, unattended mode, tuning).

---

## 1. Core / server

| Variable | Default | What it does · when to use |
|---|---|---|
| `STRIKEE_DB` | `strikee.db` | Path to the local SQLite database file. Set to a fixed absolute path on the venue PC so the app and any tools share one DB. `:memory:` = throwaway (tests). |
| `STRIKEE_PORT` | `8760` | Port the dashboard/API listens on (`http://127.0.0.1:<port>/`). Change only if 8760 is taken. |
| `STRIKEE_SNAPSHOT_DIR` | `snapshots` | Folder where per-game evidence images are saved. Point at a bigger drive if space is tight. |
| `STRIKEE_TICK_SEC` | `7` | Loop interval in seconds. Only used by the **legacy** capture loop (`STRIKEE_SCHEDULER=0`); the scheduler uses the per-camera rates below instead. |

## 2. Unattended / turnkey (Windows deployment)

| Variable | Default | What it does · when to use |
|---|---|---|
| `STRIKEE_AUTOSTART_VENUE` | *(unset)* | Auto-start the pipeline on boot so **no one clicks "Start pipeline."** Set to a venue id, or `all` for every venue. Requires the venue + zones to already be configured. |
| `STRIKEE_HEADLESS` | *(unset)* | `1` = run the server with **no window** (for boot / no logged-in desktop). Staff open the dashboard URL only when they want to look. |

> Turnkey recipe: set both above (`STRIKEE_AUTOSTART_VENUE=<id>`, `STRIKEE_HEADLESS=1`)
> as *system* env vars + launch `strikee-core` on boot (Task Scheduler / Startup
> folder). See FIELD-TEST.md → "Run unattended on Windows."

## 3. Capture scheduler & camera rates

| Variable | Default | What it does · when to use |
|---|---|---|
| `STRIKEE_SCHEDULER` | `1` | `1` = K-slot rotating scheduler (default, respects the DVR limit). `0` = legacy "read all cameras at once" loop — only safe when #cameras ≤ the DVR's concurrent limit. |
| `STRIKEE_MAX_STREAMS` | `3` | **K** — max simultaneous DVR connections. Measured safe = 3 on the club Dahua (4 dropped). Raise only if you confirm the DVR tolerates more. |
| `STRIKEE_RATE_TABLE` | `13` | Seconds between grabs for each **snooker table** camera. Lower = fresher (more load), higher = lighter. |
| `STRIKEE_RATE_GAMING` | `5` | Seconds between grabs for each **gaming-zone / person** camera. |
| `STRIKEE_RATE_ENTRY` | `3` | Seconds between grabs for each **entry / footfall** camera. |

> These rates are per **sensor kind** — tables use `snooker_game`, entries use
> `footfall`, others are person cameras. Budget check: at ~1.7s/grab, 3 slots ≈
> 106 grabs/min; keep the sum of (cameras ÷ rate) under that.

## 4. Snooker game tracking (tuning)

Set these only if the Games log over/under-counts. Use `STRIKEE_DEBUG=1` to see
why before changing anything.

| Variable | Default | What it does · when to use |
|---|---|---|
| `STRIKEE_RACK_REDS` | `8` | Reds detected that counts as a fresh **rack** (new game). Raise to be stricter about what starts a game. |
| `STRIKEE_RERACK_JUMP` | `6` | Re-rack **Check A**: a sudden red-count jump this large = a new game mid-play. Raise if you get spurious extra games. |
| `STRIKEE_RERACK_LOW` | `2` | Re-rack **Check B**: the "clearly low" red count (near end of a frame). |
| `STRIKEE_RERACK_HIGH` | `7` | Re-rack **Check B**: the "clearly high" red count = a new rack. Set to what a real fresh rack actually *detects* as. |
| `STRIKEE_MIN_GAME_MIN` | `0` | Minimum game length (minutes). Raise to suppress two quick detections merging into spurious restarts. |
| `STRIKEE_MAX_GAME_MIN` | `120` | Safety net: force-end a stuck/abandoned game after this long. Set well beyond any real frame (default 2h) so a long game is never cut short. |

## 5. State / activity (presence smoothing)

| Variable | Default | What it does · when to use |
|---|---|---|
| `STRIKEE_ENTER_TICKS` | `2` | Consecutive positive reads before an asset flips to occupied/in-use (debounce). |
| `STRIKEE_EXIT_TICKS` | `3` | Consecutive no-play reads before a table frees up. Units are **camera samples**, so at a 13s table rate, 3 ≈ 40s. Raise if tables free too eagerly during a pause. |
| `STRIKEE_STILL_TICKS` | `3` | Reads of no motion before "Active" → "Occupied – Idle". |
| `STRIKEE_MOTION_THRESHOLD` | `8.0` | Pixel-movement threshold that counts as play/motion. Lower = more sensitive. |

## 6. Models

| Variable | Default | What it does · when to use |
|---|---|---|
| `STRIKEE_SNOOKER_MODEL` | `best.pt` | Path to the custom snooker YOLO model. Point at a newer `.pt` if you retrain. |
| `STRIKEE_PERSON_MODEL` | `yolo11n.pt` | General person model (occupancy / footfall). Use `yolo11x.pt` for better accuracy at hard angles/light (slower). |

## 7. Database backend — Turso (cloud-synced) / libSQL

| Variable | Default | What it does · when to use |
|---|---|---|
| `TURSO_DATABASE_URL` | *(unset)* | Set (with the token) to switch the DB to **Turso** — a local replica that syncs to the cloud, queryable from anywhere. `libsql://<db>.turso.io`. Needs `pip install -e ".[turso]"`. |
| `TURSO_AUTH_TOKEN` | *(unset)* | Turso auth token. Required alongside the URL. |
| `STRIKEE_TURSO_SYNC_SEC` | `15` | How often (seconds) local changes are pushed to the Turso cloud. Also drives the dashboard sync-health "stale" threshold. |
| `STRIKEE_LIBSQL_LOCAL` | *(unset)* | `1` = use the libSQL client against a **local file, no cloud**. For verifying the native client works (esp. on Windows) *before* adding cloud credentials. |

> Without any of these, the DB is plain local SQLite (the default, fully offline).

## 8. Cloud backup — SQLite → R2 / S3

Currently **off** by design (Turso covers durability). Set the bucket to enable.

| Variable | Default | What it does · when to use |
|---|---|---|
| `STRIKEE_BACKUP_BUCKET` | *(unset)* | Bucket name — **setting this enables backup**. Needs `pip install -e ".[cloud]"`. |
| `STRIKEE_BACKUP_ENDPOINT` | *(unset)* | S3-compatible endpoint. For Cloudflare R2: `https://<accountid>.r2.cloudflarestorage.com`. Omit for real AWS S3. |
| `STRIKEE_BACKUP_PREFIX` | `strikee` | Key prefix for uploaded snapshots (`<prefix>/strikee-<timestamp>.db` + `<prefix>/strikee-latest.db`). |
| `STRIKEE_BACKUP_REGION` | `auto` | Region. `auto` is correct for R2; use the real region for S3. |
| `STRIKEE_BACKUP_EVERY_MIN` | *(unset)* | If set, the app backs up automatically every N minutes. Otherwise run `strikee-backup` from a scheduled task. |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | *(unset)* | Credentials (R2 token key/secret, or AWS keys). Read by boto3. |
| `STRIKEE_S3_BUCKET` | *(unset)* | Separate, optional: best-effort upload of **game snapshot images** to S3 (needs boto3 + AWS creds). |

## 9. Debug / diagnostics

| Variable | Default | What it does · when to use |
|---|---|---|
| `STRIKEE_DEBUG` | *(unset)* | `1` = write a per-tick CSV (per table: red count, game_start, player, motion, tracker state, event). The first thing to turn on when a game is missed/false — it shows *why* and which knob to turn. |
| `STRIKEE_DEBUG_FILE` | `debug_<venue>.csv` | Where the debug CSV is written. |

## 10. Platform hardening (auto-set — usually leave alone)

Set automatically by `platform_env.harden()` at startup; listed for awareness.

| Variable | Auto value | What it does |
|---|---|---|
| `KMP_DUPLICATE_LIB_OK` | `TRUE` | Prevents the OpenMP `libiomp5md.dll` clash that crashes torch on Windows. |
| `OPENCV_FFMPEG_CAPTURE_OPTIONS` | `rtsp_transport;tcp` | Forces TCP transport for stable HEVC/RTSP decoding. |

> These use *setdefault*, so an explicit value you set always wins.

---

## Common recipes

**Turnkey Windows venue box** (runs on boot, staff do nothing):
```
STRIKEE_AUTOSTART_VENUE=<venue-id>
STRIKEE_HEADLESS=1
STRIKEE_MAX_STREAMS=3
STRIKEE_DB=C:\Strikee\strikee.db
```

**Enable Turso (cloud-synced, queryable) DB:**
```
STRIKEE_LIBSQL_LOCAL=1     # step 1: prove the native client works, then remove
TURSO_DATABASE_URL=libsql://<db>.turso.io
TURSO_AUTH_TOKEN=<token>
STRIKEE_TURSO_SYNC_SEC=15
```

**Enable R2 backup (optional safety net):**
```
STRIKEE_BACKUP_BUCKET=strikee
STRIKEE_BACKUP_ENDPOINT=https://<accountid>.r2.cloudflarestorage.com
STRIKEE_BACKUP_EVERY_MIN=10
AWS_ACCESS_KEY_ID=<key>
AWS_SECRET_ACCESS_KEY=<secret>
```

**Diagnose game counting on-site:**
```
STRIKEE_DEBUG=1            # then read debug_<venue>.csv to see why
```

> **Windows note:** set persistent vars with `setx NAME value` (system-wide needs
> an admin shell: `setx /M NAME value`), then restart `strikee-core`. On macOS/
> Linux, `export NAME=value` before launching, or prefix the command.
