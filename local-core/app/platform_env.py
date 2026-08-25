"""Cross-platform runtime hardening — must run BEFORE torch/ultralytics/cv2 are
imported. Neutralises the classic 'works on Linux, breaks on Windows' failures:

  * The OpenMP duplicate-runtime clash. torch and numpy/MKL each bundle their own
    OpenMP DLL; Windows refuses to load both and aborts on import with
    "OMP: Error #15: Initializing libiomp5md.dll, but found libiomp5md.dll
    already initialized". KMP_DUPLICATE_LIB_OK=TRUE tells it to proceed. This is
    the single most common reason a YOLO model that runs on Linux crashes on
    Windows.
  * Flaky HEVC-over-RTSP. Forcing the ffmpeg TCP transport makes the DVR's H.265
    streams decode reliably through OpenCV on Windows.
  * Legacy console code pages. A Windows console defaults to cp1252/cp437, which
    cannot render the em-dashes in our own status output - so a purely cosmetic
    character raises UnicodeEncodeError ("charmap codec can't encode/decode") and
    kills an otherwise healthy run. We reconfigure stdout/stderr to UTF-8 and
    never fail on an unmappable character.

It also loads a `.env` file, because every tunable here is an environment
variable and on Windows `set VAR=x` lives only in the window it was typed in.
A venue box started from a shortcut or Task Scheduler would otherwise always
run on defaults, silently.

All values use setdefault, so an explicit environment override always wins and
calling harden() more than once is safe.
"""
import os
import sys
from pathlib import Path

_DEFAULTS = {
    "KMP_DUPLICATE_LIB_OK": "TRUE",                       # torch+MKL OpenMP clash (Windows)
    "OPENCV_FFMPEG_CAPTURE_OPTIONS": "rtsp_transport;tcp",  # stable HEVC/RTSP decode
}


def _force_utf8_console() -> None:
    """Make our own output survive a legacy Windows code page. Best-effort: under
    pytest capture or a plain pipe the streams may not be reconfigurable, and that
    is fine - there is nothing to fix in those cases."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass


# Which keys came from the .env file, so diagnostics can show where a setting
# actually came from rather than just its value.
ENV_FILE_KEYS: set[str] = set()
ENV_FILE_PATH: str | None = None


def _parse_env_file(text: str) -> dict:
    """Minimal KEY=VALUE parser - no dependency, and the file is ours.

    Skips blanks and # comments, tolerates `export KEY=value`, strips one layer
    of matching quotes. An unquoted trailing comment is stripped; a quoted value
    keeps everything inside the quotes, so passwords containing # survive.
    """
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, _, value = line.partition("=")
        key = key.strip()
        if not key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        else:
            value = value.split(" #", 1)[0].rstrip()
        out[key] = value
    return out


def load_env_file(path: str | None = None) -> int:
    """Load `.env` into the environment. Returns how many keys it set.

    A real environment variable always wins - so a one-off `set VAR=x` still
    overrides the file for that run, which is what you want while tuning.
    Looks at STRIKEE_ENV_FILE, then ./.env, then the file beside the package -
    so a shortcut or scheduled task that starts in some other directory still
    finds it.
    """
    global ENV_FILE_PATH
    candidates = []
    if path:
        candidates.append(Path(path))
    else:
        env_override = os.environ.get("STRIKEE_ENV_FILE")
        if env_override:
            candidates.append(Path(env_override))
        candidates.append(Path.cwd() / ".env")
        candidates.append(Path(__file__).resolve().parent.parent / ".env")

    for candidate in candidates:
        try:
            if not candidate.is_file():
                continue
            values = _parse_env_file(candidate.read_text(encoding="utf-8"))
        except OSError:
            continue
        applied = 0
        for key, value in values.items():
            if key not in os.environ:          # real env wins
                os.environ[key] = value
                ENV_FILE_KEYS.add(key)
                applied += 1
        ENV_FILE_PATH = str(candidate)
        return applied
    return 0


def harden() -> None:
    # .env first: it must be in place before anything reads a setting.
    load_env_file()
    for key, value in _DEFAULTS.items():
        os.environ.setdefault(key, value)
    _force_utf8_console()
