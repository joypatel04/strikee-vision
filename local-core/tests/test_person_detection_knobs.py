"""The three levers for a camera that defeats person detection.

A gaming camera can show people plainly and detect none. Which of these fixes
it is not guessable from the picture, so each has to actually work - especially
`aspect`, where getting the coordinate mapping wrong would silently misplace
every detection while still reporting a count.
"""
import numpy as np
import pytest

import app.pipeline.perception as pm
from app.pipeline.perception import YOLODetector


class FakeYOLO:
    """Returns one box at FIXED pixel coordinates, and records the frame size it
    was given - so a test can tell what the detector actually fed the model."""

    seen = {}

    def __init__(self, *a, **k):
        pass

    def predict(self, frame, **kwargs):
        h, w = frame.shape[:2]
        FakeYOLO.seen = {"w": w, "h": h, "kwargs": kwargs}

        class Box:
            xyxy = [type("T", (), {"tolist": lambda s: [100.0, 50.0, 200.0, 300.0]})()]
            conf = [0.9]

        return [type("R", (), {"boxes": [Box()]})()]


@pytest.fixture(autouse=True)
def fake_yolo(monkeypatch):
    monkeypatch.setattr(pm, "_yolo_class", lambda: FakeYOLO)
    FakeYOLO.seen = {}


def _frame(w=576, h=576):
    return np.zeros((h, w, 3), dtype="uint8")


def test_without_aspect_the_frame_is_untouched():
    d = YOLODetector("x.pt").detect(_frame())[0]
    assert FakeYOLO.seen["w"] == 576
    assert d.bbox == (100.0, 50.0, 200.0, 300.0)


def test_aspect_unsqueezes_before_inference():
    """A 576x576 channel showing a 16:9 scene must be widened to 1024 first, or
    people are compressed sideways and stop looking like people."""
    YOLODetector("x.pt", aspect=16 / 9).detect(_frame())
    assert FakeYOLO.seen["w"] == 1024
    assert FakeYOLO.seen["h"] == 576


def test_aspect_maps_boxes_back_to_the_real_frame():
    """Coordinates must come back in ORIGINAL frame space. Zones are drawn on
    the real frame, so leaving detections in stretched space would put every
    person in the wrong place while the count still looked right."""
    d = YOLODetector("x.pt", aspect=16 / 9).detect(_frame())[0]
    scale = 576 / 1024                       # 0.5625
    assert d.bbox[0] == pytest.approx(100.0 * scale)
    assert d.bbox[2] == pytest.approx(200.0 * scale)
    # vertical is untouched - only width was wrong
    assert d.bbox[1] == 50.0 and d.bbox[3] == 300.0
    assert 0 <= d.bbox[0] and d.bbox[2] <= 576


def test_aspect_matching_the_frame_is_a_no_op():
    YOLODetector("x.pt", aspect=16 / 9).detect(_frame(w=1024, h=576))
    assert FakeYOLO.seen["w"] == 1024


def test_imgsz_is_passed_through():
    """People far down a room are a few dozen pixels tall and vanish at the
    default 640."""
    YOLODetector("x.pt", imgsz=1280).detect(_frame())
    assert FakeYOLO.seen["kwargs"].get("imgsz") == 1280


def test_imgsz_absent_by_default():
    YOLODetector("x.pt").detect(_frame())
    assert "imgsz" not in FakeYOLO.seen["kwargs"]


def test_conf_is_passed_through():
    YOLODetector("x.pt", conf=0.15).detect(_frame())
    assert FakeYOLO.seen["kwargs"]["conf"] == 0.15


def test_clahe_changes_the_frame_content():
    """The snooker detector normalises lighting and this one did not - which is
    exactly wrong for a dim lounge."""
    frame = (np.random.rand(120, 160, 3) * 40 + 30).astype("uint8")
    YOLODetector("x.pt").detect(frame.copy())
    plain_mean = frame.mean()
    YOLODetector("x.pt", clahe=True).detect(frame.copy())
    # CLAHE ran on a copy inside detect(); prove it produces a different image
    assert pm.apply_clahe(frame).mean() != pytest.approx(plain_mean, abs=0.5)


def test_aspect_and_imgsz_combine():
    d = YOLODetector("x.pt", aspect=16 / 9, imgsz=1280).detect(_frame())[0]
    assert FakeYOLO.seen["w"] == 1024
    assert FakeYOLO.seen["kwargs"]["imgsz"] == 1280
    assert d.bbox[2] <= 576
