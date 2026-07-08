"""Person tracker for footfall — YOLO detection + ByteTrack association, giving
each person a persistent id across frames. Lazy import so the core stays light.

Needs CONTINUOUS frames (ByteTrack associates by frame-to-frame motion), so the
footfall camera runs on a dedicated persistent lane at several fps — NOT the
slow rotating scheduler used for the tables.
"""
from __future__ import annotations

from .footfall import Track

PERSON_CLASS = 0  # COCO 'person'


class YOLOByteTrackTracker:
    """Tracks people with Ultralytics' built-in ByteTrack. `model.track(persist=
    True)` keeps ids stable across calls. Low-light footage benefits from CLAHE,
    applied optionally before inference."""

    def __init__(self, model: str = "yolo11n.pt", conf: float = 0.25,
                 clahe: bool = False, tracker_cfg: str = "bytetrack.yaml"):
        from ultralytics import YOLO  # lazy
        self._model = YOLO(model)
        self._conf = conf
        self._clahe = clahe
        self._tracker_cfg = tracker_cfg

    def update(self, frame) -> list[Track]:
        if self._clahe:
            from .perception import apply_clahe
            frame = apply_clahe(frame)
        results = self._model.track(
            frame, persist=True, classes=[PERSON_CLASS], conf=self._conf,
            tracker=self._tracker_cfg, verbose=False,
        )[0]
        tracks: list[Track] = []
        if results.boxes is None or results.boxes.id is None:
            return tracks
        ids = results.boxes.id.int().tolist()
        for box, tid in zip(results.boxes, ids):
            xyxy = tuple(float(v) for v in box.xyxy[0].tolist())
            tracks.append(Track(id=int(tid), bbox=xyxy))
        return tracks
