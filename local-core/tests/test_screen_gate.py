"""A gaming station is in use only when someone is there AND the TV is on.

Somebody sitting on the sofa with the screen off is not playing, and billing
that time is exactly the leakage this system exists to measure. The gate must
also not be trigger-happy in the other direction: a dark loading screen or one
missed read cannot end a session on its own, because the exit window still
applies.
"""
import numpy as np
import pytest

from app.pipeline.observe import observe_screen
from app.pipeline.state import StateEngine
from app.pipeline.types import AssetRuntime, RawObservation, SensorRuntime


class FakeSensor:
    def __init__(self, polys, **params):
        self.zone_polygons = polys
        self.params = params
        self.conf_threshold = 0.3


ZONE = [[[10, 10], [90, 10], [90, 90], [10, 90]]]


def _frame(value, size=100):
    return np.full((size, size, 3), value, dtype="uint8")


# ------------------------------------------------------------------- observe


def test_dark_static_screen_reads_off():
    obs = observe_screen(_frame(20), FakeSensor(ZONE))
    assert obs["present"] is False


def test_bright_screen_reads_on():
    obs = observe_screen(_frame(200), FakeSensor(ZONE))
    assert obs["present"] is True
    assert obs["luminance"] > 90


def test_dim_but_changing_screen_reads_on():
    """A dark game scene is dimmer than the room; only the change gives it away."""
    sensor = FakeSensor(ZONE)
    first = observe_screen(_frame(40), sensor)
    assert first["present"] is False
    second = observe_screen(_frame(70), sensor, previous=first["crop"])
    assert second["change"] > 6
    assert second["present"] is True


def test_bright_but_static_screen_still_reads_on():
    """A paused game does not change at all - brightness has to carry it."""
    sensor = FakeSensor(ZONE)
    first = observe_screen(_frame(200), sensor)
    second = observe_screen(_frame(200), sensor, previous=first["crop"])
    assert second["change"] == 0
    assert second["present"] is True


def test_thresholds_are_tunable():
    dim = _frame(60)
    assert observe_screen(dim, FakeSensor(ZONE))["present"] is False
    assert observe_screen(dim, FakeSensor(ZONE, screen_lum=50))["present"] is True


def test_missing_zone_or_frame_is_not_a_crash():
    assert observe_screen(None, FakeSensor(ZONE))["present"] is False
    assert observe_screen(_frame(200), FakeSensor([]))["present"] is False


def test_zone_is_cropped_not_the_whole_frame():
    """A bright screen in a dark room must be judged on the screen."""
    frame = _frame(10, size=200)
    frame[20:80, 20:80] = 240                      # the panel
    dark = observe_screen(frame, FakeSensor([[[100, 100], [180, 100],
                                              [180, 180], [100, 180]]]))
    bright = observe_screen(frame, FakeSensor([[[20, 20], [80, 20],
                                                [80, 80], [20, 80]]]))
    assert dark["present"] is False
    assert bright["present"] is True


# ---------------------------------------------------------------------- gate


def _station(with_screen=True):
    sensors = [SensorRuntime(id="p1", asset_id="s1", source_id="cam", kind="occupancy")]
    if with_screen:
        sensors.append(SensorRuntime(id="tv1", asset_id="s1", source_id="cam",
                                     kind="screen"))
    return AssetRuntime(id="s1", name="Station 1", business_unit_id="gaming",
                        sensors=sensors)


def _drive(engine, asset, person, screen, ticks=4):
    raw = {"p1": RawObservation(person, 0.9 if person else 0.0)}
    if len(asset.sensors) > 1:
        raw["tv1"] = RawObservation(screen, 0.9 if screen else 0.0)
    snap = None
    for _ in range(ticks):
        snap, _ = engine.update(asset, raw, {"cam": True})
    return snap


def test_person_and_screen_on_is_in_use():
    engine = StateEngine(enter_ticks=2, exit_ticks=3)
    assert _drive(engine, _station(), person=True, screen=True).presence == "present"


def test_person_with_screen_off_is_not_in_use():
    engine = StateEngine(enter_ticks=2, exit_ticks=3)
    snap = _drive(engine, _station(), person=True, screen=False)
    assert snap.presence == "absent", "billing someone who is not playing"


def test_screen_on_with_nobody_there_is_not_in_use():
    """A TV left running after they walked out is the leakage, not a session."""
    engine = StateEngine(enter_ticks=2, exit_ticks=3)
    assert _drive(engine, _station(), person=False, screen=True).presence == "absent"


def test_a_single_screen_dropout_does_not_end_the_session():
    """The exit window still applies, so a loading screen cannot free a station."""
    engine = StateEngine(enter_ticks=2, exit_ticks=5)
    asset = _station()
    _drive(engine, asset, person=True, screen=True, ticks=4)
    snap = _drive(engine, asset, person=True, screen=False, ticks=2)
    assert snap.presence == "present", "one dark frame ended the session"
    snap = _drive(engine, asset, person=True, screen=False, ticks=4)
    assert snap.presence == "absent", "screen off for the whole window must end it"


def test_a_station_without_a_screen_sensor_is_unaffected():
    engine = StateEngine(enter_ticks=2, exit_ticks=3)
    snap = _drive(engine, _station(with_screen=False), person=True, screen=False)
    assert snap.presence == "present"


def test_thresholds_fall_back_to_environment(monkeypatch):
    """Documented in .env.example, so they have to actually be read."""
    monkeypatch.setenv("STRIKEE_SCREEN_LUM", "50")
    assert observe_screen(_frame(60), FakeSensor(ZONE))["present"] is True
    monkeypatch.setenv("STRIKEE_SCREEN_LUM", "200")
    assert observe_screen(_frame(60), FakeSensor(ZONE))["present"] is False


def test_per_sensor_params_beat_the_environment(monkeypatch):
    """One awkward TV must be tunable without moving the venue-wide default."""
    monkeypatch.setenv("STRIKEE_SCREEN_LUM", "200")
    assert observe_screen(_frame(60), FakeSensor(ZONE, screen_lum=50))["present"] is True
