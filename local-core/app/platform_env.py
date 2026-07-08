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

All values use setdefault, so an explicit environment override always wins and
calling harden() more than once is safe.
"""
import os

_DEFAULTS = {
    "KMP_DUPLICATE_LIB_OK": "TRUE",                       # torch+MKL OpenMP clash (Windows)
    "OPENCV_FFMPEG_CAPTURE_OPTIONS": "rtsp_transport;tcp",  # stable HEVC/RTSP decode
}


def harden() -> None:
    for key, value in _DEFAULTS.items():
        os.environ.setdefault(key, value)
