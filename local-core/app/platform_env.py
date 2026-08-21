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

All values use setdefault, so an explicit environment override always wins and
calling harden() more than once is safe.
"""
import os
import sys

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


def harden() -> None:
    for key, value in _DEFAULTS.items():
        os.environ.setdefault(key, value)
    _force_utf8_console()
