"""Frame sources. The OpenCV source lazily imports cv2 so the core stays light.

A FrameSource yields (ok, frame). `ok=False` means the source is currently
unhealthy (offline/degraded) — the runtime maps that to the health facet.
"""
from __future__ import annotations

from typing import Protocol

from .types import Frame


class FrameSource(Protocol):
    id: str

    def read(self) -> tuple[bool, Frame]:
        """Return (ok, frame). ok=False when no usable frame is available."""
        ...

    def release(self) -> None:
        ...


class FakeFrameSource:
    """Scripted source for tests. Feed it a list of (ok, frame) or default to
    always-ok with a token frame."""

    def __init__(self, id: str, script: list | None = None, token: object = "FRAME"):
        self.id = id
        self._script = list(script) if script else None
        self._token = token
        self._i = 0

    def read(self) -> tuple[bool, Frame]:
        if self._script is None:
            return True, self._token
        if self._i < len(self._script):
            item = self._script[self._i]
            self._i += 1
            return item
        # exhausted -> behave as offline
        return False, None

    def release(self) -> None:
        pass


class OpenCVFrameSource:
    """RTSP url / file path / webcam index via OpenCV. Lazy cv2 import."""

    def __init__(self, id: str, uri: str):
        self.id = id
        self.uri = uri
        self._cap = None
        self._open()

    def _open(self) -> None:
        import cv2  # lazy

        if str(self.uri).isdigit():
            self._cap = cv2.VideoCapture(int(self.uri))
        else:
            self._cap = cv2.VideoCapture(self.uri, cv2.CAP_FFMPEG)
        try:
            self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass

    def read(self) -> tuple[bool, Frame]:
        if self._cap is None or not self._cap.isOpened():
            self._reopen()
            if self._cap is None or not self._cap.isOpened():
                return False, None
        # flush a couple of buffered frames so we act on 'now' for live streams
        for _ in range(4):
            self._cap.grab()
        ok, frame = self._cap.read()
        if not ok:
            self._reopen()
        return ok, frame

    def _reopen(self) -> None:
        try:
            if self._cap is not None:
                self._cap.release()
        except Exception:
            pass
        try:
            self._open()
        except Exception:
            self._cap = None

    def release(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None


def grab_once(uri: str, flush: int = 4, max_reads: int = 60) -> tuple[bool, Frame]:
    """Open a stream, pull one fresh frame, and close it — a short-lived
    'rotating' grab. Used by the capture scheduler so that only K connections
    are ever open at once (each worker holds one for ~1.7s, then releases it).

    Tries OpenCV first; if that can't decode the stream (some Windows OpenCV
    builds struggle with HEVC/H.265 RTSP), falls back to an ffmpeg subprocess.
    Returns (ok, frame). ok=False if neither path yields a frame.
    """
    ok, frame = _grab_cv2(uri, flush, max_reads)
    if ok:
        return ok, frame
    return _grab_ffmpeg(uri)


def _grab_cv2(uri: str, flush: int, max_reads: int) -> tuple[bool, Frame]:
    import cv2  # lazy

    cap = None
    try:
        if str(uri).isdigit():
            cap = cv2.VideoCapture(int(uri))
        else:
            cap = cv2.VideoCapture(uri, cv2.CAP_FFMPEG)
        try:
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass
        if not cap.isOpened():
            return False, None
        # HEVC RTSP needs a keyframe before it decodes; pull until a real frame.
        for _ in range(max_reads):
            ok, frame = cap.read()
            if ok and frame is not None:
                for _ in range(flush):        # drop buffered/stale frames
                    cap.grab()
                ok2, fresh = cap.retrieve()
                return (True, fresh) if ok2 and fresh is not None else (True, frame)
        return False, None
    except Exception:
        return False, None
    finally:
        if cap is not None:
            try:
                cap.release()
            except Exception:
                pass


def _grab_ffmpeg(uri: str, timeout: float = 20.0) -> tuple[bool, Frame]:
    """Fallback grab via a one-shot ffmpeg subprocess (writes a single JPEG,
    then we read it back). Needs ffmpeg on PATH; if it's absent this simply
    returns (False, None). Proven on the club DVR's HEVC streams."""
    import os
    import subprocess
    import tempfile

    if str(uri).isdigit():
        return False, None                     # webcams: cv2 only
    fd, path = tempfile.mkstemp(suffix=".jpg")
    os.close(fd)
    try:
        r = subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-rtsp_transport", "tcp",
             "-i", uri, "-frames:v", "1", path],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout)
        if r.returncode == 0 and os.path.exists(path) and os.path.getsize(path) > 0:
            import cv2
            frame = cv2.imread(path)
            return (frame is not None), frame
        return False, None
    except Exception:
        return False, None
    finally:
        try:
            os.remove(path)
        except Exception:
            pass
