"""Windows/cross-platform hardening + doctor self-check failure paths."""
import os

from app.platform_env import harden
from app import doctor
from app.pipeline.capture import _grab_ffmpeg, grab_once


def test_harden_sets_openmp_flag():
    harden()
    assert os.environ["KMP_DUPLICATE_LIB_OK"] == "TRUE"
    assert "rtsp_transport" in os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"]


def test_harden_respects_existing_override():
    os.environ["KMP_DUPLICATE_LIB_OK"] = "CUSTOM"
    try:
        harden()
        assert os.environ["KMP_DUPLICATE_LIB_OK"] == "CUSTOM"   # setdefault, not clobber
    finally:
        os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"


def test_ffmpeg_fallback_handles_bad_uri_gracefully():
    # malformed uri fails fast -> (False, None), never raises
    ok, frame = _grab_ffmpeg("notaprotocol://x", timeout=3.0)
    assert ok is False and frame is None


def test_grab_once_bad_uri_returns_false():
    ok, frame = grab_once("notaprotocol://x")
    assert ok is False and frame is None


def test_doctor_model_check_reports_failure_not_crash():
    # a nonexistent model path -> [FAIL], returns False, no exception
    assert doctor._check_model("/no/such/model.pt") is False


def test_doctor_rtsp_check_reports_failure_not_crash():
    assert doctor._check_rtsp("notaprotocol://x") is False


def test_doctor_python_check_passes_here():
    assert doctor._check_python() is True
