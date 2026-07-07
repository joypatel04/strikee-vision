"""Person detectors. The YOLO detector lazily imports ultralytics.

A Detector turns a frame into a list of person Detections. Fakes let the whole
pipeline run in tests with no model.
"""
from __future__ import annotations

from typing import Callable, Protocol

from .types import Detection, Frame

PERSON_CLASS = 0  # COCO 'person'


class Detector(Protocol):
    def detect_persons(self, frame: Frame) -> list[Detection]:
        ...


class FakeDetector:
    """Returns scripted detections. Pass a list of detection-lists (consumed one
    per call) or a callable(frame) -> list[Detection]."""

    def __init__(self, script: list | Callable | None = None):
        self._callable = script if callable(script) else None
        self._script = None if callable(script) else (list(script) if script else None)
        self._i = 0

    def detect_persons(self, frame: Frame) -> list[Detection]:
        if self._callable is not None:
            return self._callable(frame)
        if self._script is None:
            return []
        if self._i < len(self._script):
            item = self._script[self._i]
            self._i += 1
            return item
        return []


class YOLODetector:
    """Ultralytics YOLO person detector. Lazy import so core installs stay light."""

    def __init__(self, model: str = "yolo11n.pt", conf: float = 0.25):
        from ultralytics import YOLO  # lazy

        self._model = YOLO(model)
        self._conf = conf

    def detect_persons(self, frame: Frame) -> list[Detection]:
        results = self._model.predict(
            frame, classes=[PERSON_CLASS], conf=self._conf, verbose=False
        )[0]
        dets: list[Detection] = []
        for b in results.boxes:
            xyxy = tuple(float(v) for v in b.xyxy[0].tolist())
            dets.append(Detection(bbox=xyxy, confidence=float(b.conf[0])))
        return dets
