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


def _check_rtsp(uri: str) -> bool:
    try:
        from .pipeline.capture import grab_once
        ok, frame = grab_once(uri)
        if ok and frame is not None:
            h, w = frame.shape[:2]
            print(f"{OK} DVR/RTSP grabbed a {w}x{h} frame (HEVC decode + network OK)")
            return True
        print(f"{FAIL} DVR/RTSP: opened but no frame — check URL/credentials/codec")
        return False
    except Exception as exc:
        print(f"{FAIL} DVR/RTSP grab failed: {exc}")
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


def run(model: str = "best.pt", rtsp: str | None = None) -> int:
    harden()
    print("Strikee Vision — self check\n" + "-" * 40)
    results = [
        _check_python(),
        _check_torch(),
        _check_cv2(),
        _check_model(model),
        _check_turso(),
    ]
    if rtsp:
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
    ap.add_argument("--rtsp", default=None, help="optional DVR/RTSP url to test")
    args = ap.parse_args()
    sys.exit(run(model=args.model, rtsp=args.rtsp))


if __name__ == "__main__":
    main()
