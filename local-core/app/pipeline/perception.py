"""Object detectors. Heavy models (YOLO) are imported lazily.

A Detector turns a frame into a list of labelled Detections. Two concrete
detectors:
  - YOLODetector: general model, returns 'person' detections (passage/reception)
  - SnookerDetector: the custom best.pt, returns balls / game_start / player,
    with CLAHE lighting normalisation for robustness to lighting changes

Fakes let the whole pipeline run in tests with no model.
"""
from __future__ import annotations

from typing import Callable, Protocol

from .types import Detection, Frame

PERSON_CLASS = 0  # COCO 'person'


class Detector(Protocol):
    def detect(self, frame: Frame) -> list[Detection]:
        ...


class FakeDetector:
    """Returns scripted labelled detections. Pass a list of detection-lists
    (consumed one per call) or a callable(frame) -> list[Detection]."""

    def __init__(self, script: list | Callable | None = None):
        self._callable = script if callable(script) else None
        self._script = None if callable(script) else (list(script) if script else None)
        self._i = 0

    def detect(self, frame: Frame) -> list[Detection]:
        if self._callable is not None:
            return self._callable(frame)
        if self._script is None:
            return []
        if self._i < len(self._script):
            item = self._script[self._i]
            self._i += 1
            return item
        return []


def _yolo_class():
    """Import Ultralytics' YOLO with torch loaded FIRST.

    On Windows, torch and OpenCV each ship their own OpenMP runtime, and
    whichever loads first wins. Ultralytics imports cv2 before torch, so going
    straight to `from ultralytics import YOLO` loads OpenCV's runtime first and
    torch aborts the process during import - a C++ throw ending in terminate(),
    with no Python traceback to explain it. strikee-doctor never hit this only
    because it happens to import torch before cv2.

    Importing torch here first makes that ordering explicit rather than
    accidental. KMP_DUPLICATE_LIB_OK (set in platform_env) suppresses the
    specific OMP Error #15 abort but does not fix the ordering itself.
    """
    import torch  # noqa: F401  - MUST precede cv2/ultralytics; see above
    from ultralytics import YOLO
    return YOLO


class YOLODetector:
    """General YOLO person detector. Lazy import. Model configurable (nano is
    fast; yolo11x is more accurate for people at difficult angles)."""

    def __init__(self, model: str = "yolo11n.pt", conf: float = 0.25):
        YOLO = _yolo_class()  # lazy; torch before cv2
        self._model = YOLO(model)
        self._conf = conf

    def detect(self, frame: Frame) -> list[Detection]:
        results = self._model.predict(
            frame, classes=[PERSON_CLASS], conf=self._conf, verbose=False
        )[0]
        dets: list[Detection] = []
        for b in results.boxes:
            xyxy = tuple(float(v) for v in b.xyxy[0].tolist())
            dets.append(Detection(bbox=xyxy, confidence=float(b.conf[0]), label="person"))
        return dets


def apply_clahe(frame):
    """CLAHE lighting normalisation on the luminance channel. Makes detection
    more robust to lighting differences without retraining."""
    import cv2
    lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    l = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8)).apply(l)
    return cv2.cvtColor(cv2.merge((l, a, b)), cv2.COLOR_LAB2BGR)


class SnookerDetector:
    """Custom snooker model (best.pt). Returns balls / game_start / player.
    Applies CLAHE before inference. Low default conf + downstream smoothing =
    robust to intermittent misses."""

    def __init__(self, model: str = "best.pt", conf: float = 0.20, clahe: bool = True):
        YOLO = _yolo_class()  # lazy; torch before cv2
        self._model = YOLO(model)
        self._names = self._model.names
        self._conf = conf
        self._clahe = clahe

    def detect(self, frame: Frame) -> list[Detection]:
        if self._clahe:
            frame = apply_clahe(frame)
        results = self._model.predict(frame, conf=self._conf, verbose=False)[0]
        dets: list[Detection] = []
        for b in results.boxes:
            xyxy = tuple(float(v) for v in b.xyxy[0].tolist())
            label = self._names[int(b.cls[0])]
            dets.append(Detection(bbox=xyxy, confidence=float(b.conf[0]), label=label))
        return dets
