"""Self-check / bring-up doctor. Run this ONCE on a new machine (especially the
Windows venue box) to prove the stack works before relying on it.

It checks, in order and without stopping at the first failure:
  1. Python version
  2. torch imports + which device it will use
  3. OpenCV imports
  4. the snooker model (best.pt) LOADS and RUNS one inference — this is the exact
     step that used to break on Windows, so a green here is the proof.
  5. (optional) a DVR/RTSP url decodes one frame — proves HEVC + connectivity.

Run:
    strikee-doctor
    strikee-doctor --model best.pt --rtsp "rtsp://user:pass@ip:554/..."

Exit code is 0 only if every non-optional check passes.
"""
import argparse
import platform
import sys

from .platform_env import harden

OK = "  [ OK ]"
FAIL = "  [FAIL]"
WARN = "  [WARN]"


def _check_python() -> bool:
    v = sys.version_info
    ok = (v.major, v.minor) >= (3, 11)
    print(f"{OK if ok else FAIL} Python {platform.python_version()} on {platform.system()} "
          f"({platform.machine()})" + ("" if ok else "  -> need 3.11+"))
    return ok


def _check_torch() -> bool:
    try:
        import torch
        dev = "cuda" if torch.cuda.is_available() else "cpu"
        extra = ""
        if dev == "cuda":
            extra = f" ({torch.cuda.get_device_name(0)})"
        print(f"{OK} torch {torch.__version__} -> device: {dev}{extra}")
        return True
    except Exception as exc:
        print(f"{FAIL} torch import failed: {exc}")
        return False


def _check_cv2() -> bool:
    try:
        import cv2
        print(f"{OK} OpenCV {cv2.__version__}")
        return True
    except Exception as exc:
        print(f"{FAIL} OpenCV import failed: {exc}")
        return False


def _check_model(model: str) -> bool:
    """Load best.pt and run one real inference on a synthetic frame. This is the
    step that historically broke on Windows (OpenMP/import) — proving it here is
    the whole point of the doctor."""
    try:
        import numpy as np
        from .pipeline.perception import SnookerDetector
        det = SnookerDetector(model)
        frame = np.zeros((640, 640, 3), dtype=np.uint8)  # black frame is enough
        dets = det.detect(frame)
        print(f"{OK} model '{model}' loaded and ran inference "
              f"({len(dets)} detections on a blank frame — 0 is fine)")
        return True
    except Exception as exc:
        print(f"{FAIL} model load/inference failed: {exc}")
        return False


def _check_rtsp(uri: str, label: str = "DVR/RTSP") -> bool:
    try:
        from .pipeline.capture import grab_once
        ok, frame = grab_once(uri)
        if ok and frame is not None:
            h, w = frame.shape[:2]
            print(f"{OK} {label}: grabbed a {w}x{h} frame (HEVC decode + network OK)")
            return True
        print(f"{FAIL} {label}: opened but no frame — check URL/credentials/codec")
        return False
    except Exception as exc:
        print(f"{FAIL} {label}: grab failed: {exc}")
        return False


def _check_turso_push() -> bool:
    """Push mode: local SQLite stays authoritative and rows go up over HTTP.

    The backend being sqlite3 is the whole point here, so this proves the
    remote end instead - that the endpoint answers, the token works, and we can
    create and write, which is what a push cycle actually does.
    """
    import os
    from .cloudsync import TursoPush

    url = os.environ.get("TURSO_DATABASE_URL")
    token = os.environ.get("TURSO_AUTH_TOKEN")
    if not (url and token):
        print(f"{FAIL} STRIKEE_SYNC_MODE=push but TURSO_DATABASE_URL/TOKEN are not set")
        return False
    host = url.replace("libsql://", "").replace("https://", "").rstrip("/")
    try:
        # db is unused by the transport - this only exercises the remote end.
        TursoPush(None, url, token)._pipeline([
            {"sql": "CREATE TABLE IF NOT EXISTS _doctor_push (id TEXT PRIMARY KEY)"},
            {"sql": "INSERT OR REPLACE INTO _doctor_push (id) VALUES (?)",
             "args": [{"type": "text", "value": "probe"}]},
            {"sql": "SELECT COUNT(*) FROM _doctor_push"},
            {"sql": "DROP TABLE _doctor_push"},
        ])
    except Exception as exc:
        print(f"{FAIL} Turso push: cannot write to {host}: {exc}")
        print("       Check it with: python tools/turso_check.py <url> <token>")
        return False
    print(f"{OK} Turso push: remote reachable and writable "
          f"(local SQLite stays the source of truth)")
    return True


def _check_turso() -> bool:
    """If Turso env is configured, prove the whole round-trip on THIS machine:
    the libsql client imports (native dep — the Windows risk), an embedded
    replica connects, a write lands locally, sync() reaches the cloud, and it
    reads back. Skipped (as a pass) when Turso isn't configured."""
    import os
    mode = os.environ.get("STRIKEE_SYNC_MODE", "").lower()
    if mode == "off":
        print(f"{WARN} skipped Turso check (STRIKEE_SYNC_MODE=off)")
        return True
    if mode == "push":
        # Not a libsql replica at all, so none of the checks below apply: the
        # backend is sqlite3 by design and libsql need not even be installed.
        return _check_turso_push()
    if not (os.environ.get("TURSO_DATABASE_URL") and os.environ.get("TURSO_AUTH_TOKEN")):
        print(f"{WARN} skipped Turso check (TURSO_DATABASE_URL/TOKEN not set)")
        return True
    try:
        import libsql  # noqa: F401  (native client — verifies Windows install)
    except Exception as exc:
        print(f"{FAIL} libsql import failed (Turso client): {exc}")
        return False
    try:
        import tempfile
        from .db import Database
        tmp = os.path.join(tempfile.gettempdir(), "strikee-doctor-turso.db")
        for suffix in ("", "-wal", "-shm"):
            try:
                os.remove(tmp + suffix)
            except OSError:
                pass
        db = Database(tmp)
        if db.backend != "turso":
            print(f"{FAIL} Turso env set but backend is '{db.backend}'. If this "
                  f"database has no /v1 replication endpoints, set "
                  f"STRIKEE_SYNC_MODE=push instead.")
            return False
        with db.cursor() as cur:
            cur.execute("CREATE TABLE IF NOT EXISTS _doctor (v TEXT)")
            cur.execute("INSERT INTO _doctor (v) VALUES (?)", ("ok",))
        synced = db.sync()
        with db.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM _doctor")
            n = cur.fetchone()[0]
        db.close()
        note = "synced to cloud" if synced else "local write OK but sync did NOT reach cloud (check network/token)"
        print(f"{OK if synced else WARN} Turso: connected, wrote+read locally (n={n}), {note}")
        return True
    except Exception as exc:
        print(f"{FAIL} Turso round-trip failed: {exc}")
        return False


def _check_env_file() -> bool:
    """Say where settings came from. On Windows `set` dies with its window, so a
    box can look configured and be running entirely on defaults."""
    from . import platform_env
    if platform_env.ENV_FILE_PATH:
        print(f"{OK} settings: {len(platform_env.ENV_FILE_KEYS)} from "
              f"{platform_env.ENV_FILE_PATH}")
    else:
        print(f"{WARN} no .env found - everything is running on defaults or on "
              f"variables set in THIS window only")
    return True


def _check_disk(path: str = ".") -> bool:
    """Snapshots are written continuously; a full disk stops tracking."""
    import shutil
    try:
        free_gb = shutil.disk_usage(path).free / 1e9
    except Exception as exc:
        print(f"{WARN} could not read free disk space: {exc}")
        return True
    if free_gb < 1:
        print(f"{FAIL} only {free_gb:.1f} GB free - snapshots will fill this shortly")
        return False
    note = "" if free_gb > 5 else "  (getting low)"
    print(f"{OK} disk: {free_gb:.1f} GB free{note}")
    return True


def _check_object_storage() -> bool:
    """Round-trip a tiny object through each configured bucket.

    Uploads are best-effort by design - a failed snapshot upload must never
    stall the pipeline - which also means bad credentials fail silently forever.
    The only honest test is to actually write, read and delete something.
    """
    import os

    targets = []
    if os.environ.get("STRIKEE_S3_BUCKET"):
        from .snapshots import SnapshotStore
        st = SnapshotStore(os.environ.get("STRIKEE_SNAPSHOT_DIR", "snapshots"))
        targets.append(("snapshots", st.s3_bucket, "_doctor/", st._client))
    if os.environ.get("STRIKEE_BACKUP_BUCKET"):
        from .backup import BackupConfig, _client as backup_client
        cfg = BackupConfig.from_env()
        targets.append(("db backup", cfg.bucket, f"{cfg.prefix}/_doctor/",
                        lambda: backup_client(cfg)))

    if not targets:
        print(f"{WARN} skipped object storage (no STRIKEE_S3_BUCKET / "
              f"STRIKEE_BACKUP_BUCKET set)")
        return True

    ok = True
    for label, bucket, prefix, make_client in targets:
        key = f"{prefix}write-test.txt"
        try:
            client = make_client()
            client.put_object(Bucket=bucket, Key=key, Body=b"strikee-doctor")
            body = client.get_object(Bucket=bucket, Key=key)["Body"].read()
            client.delete_object(Bucket=bucket, Key=key)
            if body != b"strikee-doctor":
                raise RuntimeError("read back the wrong content")
            print(f"{OK} {label}: wrote, read and deleted s3://{bucket}/{key}")
        except Exception as exc:
            ok = False
            print(f"{FAIL} {label}: cannot write to {bucket}: "
                  f"{type(exc).__name__}: {str(exc)[:120]}")
            print(f"       Check the bucket name, the region, and that the key "
                  f"has s3:PutObject/GetObject/DeleteObject on it.")
    return ok


def run(model: str = "best.pt", rtsp: str | None = None,
        channels: list | None = None) -> int:
    harden()
    print("Strikee Vision — self check\n" + "-" * 40)
    results = [
        _check_env_file(),
        _check_python(),
        _check_torch(),
        _check_cv2(),
        _check_model(model),
        _check_disk(),
        _check_turso(),
        _check_object_storage(),
    ]
    if rtsp:
        # A template with {ch} tests every channel you will actually use, which
        # is the difference between "a camera works" and "my cameras work".
        if "{ch}" in rtsp:
            for ch in channels or [1]:
                results.append(_check_rtsp(rtsp.replace("{ch}", str(ch)), label=f"ch{ch}"))
        else:
            results.append(_check_rtsp(rtsp))
    else:
        print(f"{WARN} skipped DVR/RTSP check (pass --rtsp <url> to test the camera)")
    print("-" * 40)
    ok = all(results)
    print("ALL GOOD — safe to run `strikee-core`." if ok
          else "SOME CHECKS FAILED — see [FAIL] lines above.")
    return 0 if ok else 1


def main() -> None:
    ap = argparse.ArgumentParser(description="Strikee Vision bring-up self-check")
    ap.add_argument("--model", default="best.pt", help="path to the snooker model")
    ap.add_argument("--rtsp", default=None,
                    help="DVR/RTSP url to test. May contain {ch}, in which case "
                         "--channels decides which channels are tried")
    ap.add_argument("--channels", default=None,
                    help="channels to test with a {ch} url, e.g. 1,4,6")
    args = ap.parse_args()
    chans = None
    if args.channels:
        chans = [int(c) for c in args.channels.replace(" ", "").split(",") if c]
    sys.exit(run(model=args.model, rtsp=args.rtsp, channels=chans))


if __name__ == "__main__":
    main()
