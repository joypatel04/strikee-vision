"""Diagnostics: what is *actually* in effect right now.

Every tunable is an environment variable, and on Windows `set VAR=x` applies
only to the window it was typed in — launch the app from a different shell, a
shortcut or Task Scheduler and it silently runs on defaults instead. Nothing on
screen would look wrong; the numbers would just be someone else's.

So this reports the effective value of every knob *and where it came from*,
alongside the things that make a setting meaningless if they are off: whether
the models are present, whether the perception stack imports, whether the
cameras are actually being grabbed, and what grace window each asset ended up
with once seconds were converted to reads.

`warnings()` is the part worth reading first — it names configurations that are
individually valid but wrong together.
"""
from __future__ import annotations

import os
import platform
import sys
from pathlib import Path
from typing import Any, Callable, Optional

from . import platform_env   # module, not names: ENV_FILE_PATH is rebound
                             # by load_env_file() after import time

# name, default, parser, group, one-line description
_KNOBS: list[tuple[str, Optional[str], Callable[[str], Any], str, str]] = [
    # capture
    ("STRIKEE_MAX_STREAMS", "3", int, "capture",
     "Concurrent DVR connections, shared across every running venue. 4 dropped streams on this DVR."),
    ("STRIKEE_RATE_TABLE", "13", float, "capture",
     "Seconds between grabs of a snooker table."),
    ("STRIKEE_RATE_GAMING", "5", float, "capture",
     "Seconds between grabs of a gaming/person camera."),
    ("STRIKEE_RATE_ENTRY", "3", float, "capture",
     "Seconds between grabs of an entry/footfall camera."),
    ("STRIKEE_SCHEDULER", "1", str, "capture",
     "1 = rotating scheduler (default). 0 = legacy loop holding every stream open at once."),
    ("STRIKEE_TICK_SEC", "7", float, "capture",
     "Legacy loop tick interval. Ignored by the scheduler."),
    # state
    ("STRIKEE_EXIT_SEC", None, float, "state",
     "No-activity window before an asset frees up, in SECONDS. Preferred over ticks."),
    ("STRIKEE_ENTER_SEC", None, float, "state",
     "How long presence must hold before an asset counts as occupied, in seconds."),
    ("STRIKEE_STILL_SEC", None, float, "state",
     "Stillness before Active drops to Idle, in seconds."),
    ("STRIKEE_EXIT_TICKS", "3", int, "state",
     "Same as EXIT_SEC but counted in reads — means different durations at different rates."),
    ("STRIKEE_ENTER_TICKS", "2", int, "state",
     "Reads of presence before an asset counts as occupied."),
    ("STRIKEE_STILL_TICKS", "3", int, "state",
     "Still reads before Active drops to Idle."),
    ("STRIKEE_MOTION_THRESHOLD", "8.0", float, "state",
     "Pixel movement that counts as play."),
    # snooker
    ("STRIKEE_RACK_REDS", "8", int, "snooker",
     "Reds that constitute a fresh rack."),
    ("STRIKEE_RERACK_JUMP", "6", int, "snooker",
     "Red-count jump treated as a mid-game re-rack."),
    ("STRIKEE_RERACK_LOW", "2", int, "snooker", "The 'clearly low' red band."),
    ("STRIKEE_RERACK_HIGH", "7", int, "snooker", "The 'clearly high' red band."),
    ("STRIKEE_MIN_GAME_MIN", "0", float, "snooker",
     "Minimum game length in minutes; suppresses spurious restarts."),
    ("STRIKEE_MAX_GAME_MIN", "120", float, "snooker",
     "Safety net that force-ends a stuck game."),
    # models / storage
    ("STRIKEE_SNOOKER_MODEL", "best.pt", str, "models", "Snooker model path."),
    ("STRIKEE_PERSON_MODEL", None, str, "models",
     "Person model path. yolo11x.pt is far better at difficult angles, and far slower."),
    ("STRIKEE_PERSON_CONF", "0.25", float, "models",
     "Person confidence threshold. Lower finds more, with more false positives."),
    ("STRIKEE_PERSON_IMGSZ", None, int, "models",
     "Inference size for people (default 640). 960/1280 finds people far down a room."),
    ("STRIKEE_PERSON_CLAHE", None, str, "models",
     "Set to 1 to normalise lighting before person detection. Helps in a dim room."),
    ("STRIKEE_PERSON_ASPECT", None, str, "models",
     "True scene aspect (e.g. 16:9) when a channel delivers a squeezed frame."),
    ("STRIKEE_DB", "strikee.db", str, "storage", "SQLite database path."),
    ("STRIKEE_SNAPSHOT_DIR", "snapshots", str, "storage", "Where evidence images are written."),
    ("STRIKEE_SNAPSHOT_QUALITY", "80", int, "storage",
     "JPEG quality for evidence images. 80 halves the size versus OpenCV's default 95."),
    ("STRIKEE_SNAPSHOT_KEEP_DAYS", "30", int, "storage",
     "Delete local snapshots older than this. 0 keeps everything (disk grows forever)."),
    ("STRIKEE_DEBUG", None, str, "storage",
     "Set to 1 to write debug_<venue>.csv — one row per read per asset."),
    # cloud
    ("TURSO_DATABASE_URL", None, str, "cloud", "Turso database URL. Enables cloud sync."),
    ("TURSO_AUTH_TOKEN", None, str, "cloud", "Turso auth token (value hidden here)."),
    ("STRIKEE_TURSO_SYNC_SEC", "15", float, "cloud", "Seconds between cloud syncs."),
    ("STRIKEE_SYNC_MODE", "replica", str, "cloud",
     "replica = libsql embedded replica. push = local SQLite plus HTTP push (use when "
     "the database has no replication endpoints). off = local only."),
    ("STRIKEE_SYNC_BATCH", "200", int, "cloud", "Rows per push request."),
    ("STRIKEE_SYNC_METRICS", None, str, "cloud",
     "Set to 1 to also push metric_samples (~2.4M rows/month). Off by default."),
    ("STRIKEE_BACKUP_BUCKET", None, str, "cloud",
     "Bucket for whole-database backups. Redundant if Turso sync is on."),
    ("STRIKEE_BACKUP_ENDPOINT", None, str, "cloud",
     "S3 endpoint for backups. Cloudflare R2: https://<account-id>.r2.cloudflarestorage.com"),
    ("STRIKEE_BACKUP_REGION", "auto", str, "cloud", "Bucket region. 'auto' is correct for R2."),
    ("STRIKEE_BACKUP_EVERY_MIN", None, float, "cloud",
     "Minutes between automatic database backups. Unset = no automatic backup."),
    ("STRIKEE_S3_BUCKET", None, str, "cloud", "Bucket for evidence snapshot images."),
    ("STRIKEE_S3_ENDPOINT", None, str, "cloud",
     "S3 endpoint for snapshots. Falls back to STRIKEE_BACKUP_ENDPOINT."),
    ("STRIKEE_S3_REGION", None, str, "cloud",
     "Region for snapshots. Falls back to STRIKEE_BACKUP_REGION, then 'auto'."),
    ("STRIKEE_AUTOSTART_VENUE", None, str, "runtime",
     "Venue id (or 'all') to start automatically on boot."),
    ("STRIKEE_HEADLESS", None, str, "runtime", "1 = server only, no desktop window."),
    ("STRIKEE_WATCHDOG_SEC", "60", float, "runtime",
     "Seconds between system health checks (cameras, cloud sync)."),
    ("STRIKEE_ENV_FILE", None, str, "runtime",
     "Path to the .env file. Defaults to ./.env, then the one beside the app."),
]

_SECRET = ("TOKEN", "SECRET", "PASSWORD", "KEY")


def _mask(name: str, value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    if any(word in name.upper() for word in _SECRET):
        return f"set ({len(value)} chars)"
    return value


def config_report() -> list[dict]:
    """Every knob with its effective value and whether it came from the
    environment or fell back to a default."""
    out = []
    for name, default, parse, group, desc in _KNOBS:
        raw = os.environ.get(name)
        from_env = raw is not None
        # A key loaded from .env lands in os.environ too, so distinguish them -
        # "did my .env get picked up?" is the question this panel exists for.
        if from_env:
            source = "env file" if name in platform_env.ENV_FILE_KEYS else "environment"
        else:
            source = "default" if default is not None else "unset"
        effective_raw = raw if from_env else default
        effective: Any = None
        error = None
        if effective_raw is not None:
            try:
                effective = parse(effective_raw)
            except (TypeError, ValueError):
                error = f"cannot read {effective_raw!r} as {parse.__name__}"
        out.append({
            "name": name,
            "group": group,
            "value": _mask(name, effective_raw),
            "source": source,
            "default": default,
            "effective": None if error else effective,
            "error": error,
            "description": desc,
        })
    return out


def _module_version(mod: str) -> Optional[str]:
    try:
        __import__(mod)
        return getattr(sys.modules[mod], "__version__", "unknown")
    except Exception:
        return None


def perception_report() -> dict:
    """Whether the heavy stack can actually load. Imports torch first — on
    Windows, loading OpenCV's OpenMP runtime before torch's aborts the process."""
    torch_v = _module_version("torch")
    return {
        "torch": torch_v,
        "numpy": _module_version("numpy"),
        "opencv": _module_version("cv2"),
        "ultralytics": _module_version("ultralytics"),
        "libsql": _module_version("libsql"),
        "ready": bool(torch_v and _module_version("cv2")),
    }


def model_report() -> list[dict]:
    snooker = os.environ.get("STRIKEE_SNOOKER_MODEL", "best.pt")
    person = os.environ.get("STRIKEE_PERSON_MODEL", "yolo11n.pt")
    out = []
    for role, path in (("snooker", snooker), ("person", person)):
        p = Path(path)
        out.append({
            "role": role,
            "path": path,
            "exists": p.is_file(),
            "size_mb": round(p.stat().st_size / 1e6, 1) if p.is_file() else None,
        })
    return out


def asset_windows(runtime) -> list[dict]:
    """The grace window each asset actually ended up with.

    This is where a seconds setting proves itself: the same 120s is 9 reads on
    a table sampled every 13s and 24 on a station sampled every 5s.
    """
    engine = getattr(runtime, "engine", None)
    if engine is None:
        return []
    out = []
    for asset in getattr(runtime, "assets", []):
        try:
            enter, leave, still = engine._thresholds(asset)
            interval = engine.interval_for(asset) if engine.interval_for else None
        except Exception:
            continue
        out.append({
            "asset": asset.name,
            "kinds": sorted({s.kind for s in asset.sensors}),
            "interval_sec": interval,
            "enter_reads": enter,
            "exit_reads": leave,
            "still_reads": still,
            "exit_window_sec": round(leave * interval, 1) if interval else None,
            "enter_window_sec": round(enter * interval, 1) if interval else None,
        })
    return out


def warnings(cfg: list[dict], perception: dict, models: list[dict]) -> list[dict]:
    """Configurations that are individually valid but wrong together."""
    by_name = {c["name"]: c for c in cfg}
    out: list[dict] = []

    def warn(level, text):
        out.append({"level": level, "text": text})

    for c in cfg:
        if c["error"]:
            warn("error", f"{c['name']}: {c['error']}")

    k = by_name["STRIKEE_MAX_STREAMS"]["effective"]
    if isinstance(k, int) and k > 3:
        warn("error", f"STRIKEE_MAX_STREAMS={k} — 4 concurrent streams were measured "
                      "to drop on this DVR. Use 3 or fewer.")

    if by_name["STRIKEE_SCHEDULER"]["effective"] == "0":
        warn("warn", "STRIKEE_SCHEDULER=0 holds every camera open at once. Only safe "
                     "when the camera count is at or below STRIKEE_MAX_STREAMS.")

    for sec, ticks in (("STRIKEE_EXIT_SEC", "STRIKEE_EXIT_TICKS"),
                       ("STRIKEE_ENTER_SEC", "STRIKEE_ENTER_TICKS"),
                       ("STRIKEE_STILL_SEC", "STRIKEE_STILL_TICKS")):
        if by_name[sec]["source"] in ("environment", "env file") and \
                by_name[ticks]["source"] in ("environment", "env file"):
            warn("warn", f"{sec} and {ticks} are both set — {sec} wins and {ticks} is ignored.")

    if not perception["ready"]:
        missing = [m for m in ("torch", "opencv") if not perception[m]]
        warn("error", "Perception stack not loadable (" + ", ".join(missing) +
                      "). The pipeline cannot detect anything. Run: "
                      'pip install -e ".[perception]"')

    for m in models:
        if not m["exists"]:
            warn("error", f"{m['role']} model missing at {m['path']} — *.pt is gitignored, "
                          "so copy it across rather than expecting a clone to have it.")

    def _is_set(knob):
        return by_name[knob]["source"] in ("environment", "env file")

    if _is_set("TURSO_DATABASE_URL"):
        if not _is_set("TURSO_AUTH_TOKEN"):
            warn("error", "TURSO_DATABASE_URL is set but TURSO_AUTH_TOKEN is not — sync will fail.")
        if perception["libsql"] is None:
            warn("error", 'Turso is configured but the libsql client is not installed. '
                          'Run: pip install -e ".[turso]"')

    # --- object storage: the endpoint is what makes R2 work ---------------
    for bucket_knob, endpoint_knob, what in (
        ("STRIKEE_S3_BUCKET", "STRIKEE_S3_ENDPOINT", "snapshot images"),
        ("STRIKEE_BACKUP_BUCKET", "STRIKEE_BACKUP_ENDPOINT", "database backups"),
    ):
        if not _is_set(bucket_knob):
            continue
        if _module_version("boto3") is None:
            warn("error", f"{bucket_knob} is set but boto3 is not installed, so {what} "
                          'are not being uploaded. Run: pip install -e ".[cloud]"')
        endpoint_set = _is_set(endpoint_knob)
        if bucket_knob == "STRIKEE_S3_BUCKET" and not endpoint_set:
            endpoint_set = _is_set("STRIKEE_BACKUP_ENDPOINT")
        if not endpoint_set:
            # Going to Amazon is a legitimate choice, so this is a note, not a
            # complaint - but someone who meant R2 and forgot the endpoint would
            # otherwise get no hint at all.
            warn("info", f"{bucket_knob} has no endpoint set, so {what} go to Amazon "
                         f"S3. For Cloudflare R2 instead, set {endpoint_knob} to "
                         "https://<account-id>.r2.cloudflarestorage.com")
            # Real AWS needs a real region - "auto" is an R2 convention and
            # resolves to nothing on AWS.
            region_knob = ("STRIKEE_S3_REGION" if bucket_knob == "STRIKEE_S3_BUCKET"
                           else "STRIKEE_BACKUP_REGION")
            has_region = (_is_set(region_knob)
                          or os.environ.get("AWS_DEFAULT_REGION")
                          or os.environ.get("AWS_REGION"))
            if not has_region:
                warn("warn", f"{bucket_knob} is set for Amazon S3 but no region is "
                             f"configured. Set AWS_DEFAULT_REGION (e.g. ap-south-1) "
                             f"or {region_knob}, or uploads will fail to resolve.")
            if not (os.environ.get("AWS_ACCESS_KEY_ID")
                    or os.environ.get("AWS_PROFILE")):
                warn("warn", f"{bucket_knob} is set but no AWS credentials are in the "
                             "environment. Set AWS_ACCESS_KEY_ID and "
                             "AWS_SECRET_ACCESS_KEY in .env.")

    if _is_set("TURSO_DATABASE_URL") and _is_set("STRIKEE_BACKUP_BUCKET"):
        warn("info", "Turso sync and database backups are both on. Turso already keeps "
                     "a cloud copy, so the backup bucket is belt-and-braces - fine, "
                     "but not required.")

    if by_name["STRIKEE_DEBUG"]["source"] in ("environment", "env file"):
        warn("info", "STRIKEE_DEBUG is on — debug_<venue>.csv is being written. "
                     "Useful during a field test, worth turning off for a long run.")

    if not out:
        warn("info", "No configuration problems detected.")
    return out


def build(db, runtime_manager, version: str) -> dict:
    cfg = config_report()
    perception = perception_report()
    models = model_report()

    venues = []
    for venue_id in runtime_manager.running_venues():
        rt = runtime_manager.runtime_for(venue_id)
        venues.append({
            "venue_id": venue_id,
            "cameras": runtime_manager.capture_status(venue_id),
            "assets": asset_windows(rt) if rt is not None else [],
        })

    try:
        sync = db.sync_status()
    except Exception:
        sync = None

    return {
        "version": version,
        "env_file": {"path": platform_env.ENV_FILE_PATH,
                     "keys": len(platform_env.ENV_FILE_KEYS)},
        "host": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "machine": platform.machine(),
        },
        "perception": perception,
        "models": models,
        "database": {"path": getattr(db, "path", None), "sync": sync},
        "config": cfg,
        "running": venues,
        "warnings": warnings(cfg, perception, models),
    }
