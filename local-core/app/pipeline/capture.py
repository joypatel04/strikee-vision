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
