"""Telling a TV that is on from a dark panel reflecting the room.

Measured at the venue: an OFF screen reads 92-97 mean brightness because it
reflects the room lighting, while a night level or loading screen on a TV that
is genuinely ON can read below that. The ranges overlap, so these tests exist to
pin the thing that does separate them - structure and colour - and to stop
anyone "simplifying" the observer back to a brightness threshold.
"""
import numpy as np

from app.pipeline.observe import observe_screen

H, W = 60, 100


class Sensor:
    zone_polygons = [[[0, 0], [W, 0], [W, H], [0, H]]]
    conf_threshold = 0.35
    params = {}


def _uniform(level, jitter=1.0, seed=0):
    """A smooth, grey wash - what an off panel reflecting the room looks like."""
    rng = np.random.default_rng(seed)
    base = rng.normal(level, jitter, (H, W))
    return np.clip(np.stack([base] * 3, axis=2), 0, 255).astype(np.uint8)


def _picture(mean_level, seed=0):
    """Structured and coloured - a game scene, dim or otherwise."""
    rng = np.random.default_rng(seed)
    img = np.zeros((H, W, 3), dtype=np.uint8)
    # dark ground with a bright, saturated region: a lit HUD over a night level
    img[:, :] = (int(mean_level * 0.45), int(mean_level * 0.3), int(mean_level * 0.7))
    img[8:28, 10:70] = (40, 220, 255)
    img[38:52, 20:80] = (210, 40, 90)
    img = np.clip(img.astype("float32") + rng.normal(0, 6, img.shape), 0, 255)
    return img.astype(np.uint8)


def _obs(frame, previous=None, **env):
    return observe_screen(frame, Sensor(), previous)


# ------------------------------------------------------- the regression


def test_off_panel_reflecting_the_room_is_not_on(monkeypatch):
    """The measured failure: 92-97 mean, and the old default was 90."""
    monkeypatch.delenv("STRIKEE_SCREEN_LUM", raising=False)
    for level in (92, 95, 97):
        obs = _obs(_uniform(level))
        assert obs["present"] is False, (
            f"reflection at lum {level} read as a TV that is on: {obs['reason']}")
        assert obs["luminance"] > 90, "test frame is not in the measured range"


def test_a_dim_game_scene_is_on_despite_being_darker_than_the_reflection():
    """The other half of the overlap - and the reason a threshold cannot work."""
    dim = _obs(_picture(70))
    assert dim["present"] is True, "a dark game scene read as off"
    assert "picture" in dim["reason"]
    # the point of the pair: the ON frame is DIMMER than the OFF one above
    assert dim["luminance"] < _obs(_uniform(95))["luminance"]


def test_a_bright_screen_is_on_on_brightness_alone():
    obs = _obs(_uniform(180))
    assert obs["present"] is True
    assert "bright" in obs["reason"]


def test_a_changing_zone_is_on_even_when_dim_and_grey():
    first = _uniform(60, seed=1)
    second = _uniform(60, seed=2)
    grey_first = observe_screen(first, Sensor())["crop"]
    obs = observe_screen(second + 40, Sensor(), previous=grey_first)
    assert obs["present"] is True
    assert "moving" in obs["reason"]


# --------------------------------------------------------- the signals


def test_structure_without_colour_is_not_a_picture():
    """A window reflected in a dark panel has edges but no colour."""
    frame = _uniform(80)
    frame[:, 40:60] = 200          # a bright grey stripe: high contrast, no hue
    obs = _obs(frame)
    assert obs["contrast"] > 28, "test frame lacks the structure it claims"
    assert obs["saturation"] < 14
    assert obs["present"] is False, "a grey reflection read as content"


def test_colour_without_structure_is_not_a_picture():
    """A flat coloured wall inside the zone is not a screen."""
    frame = np.zeros((H, W, 3), dtype=np.uint8)
    frame[:, :] = (30, 20, 90)     # uniform, saturated, dim
    obs = _obs(frame)
    assert obs["saturation"] > 14
    assert obs["contrast"] < 28
    assert obs["present"] is False


def test_reason_names_what_decided_it():
    """The reason is what turns a wrong verdict into a fixable one."""
    assert _obs(_uniform(95))["reason"] == "off"
    assert "bright" in _obs(_uniform(200))["reason"]


def test_thresholds_are_tunable_per_sensor(monkeypatch):
    """One awkward TV must be fixable without moving the venue-wide default."""
    frame = _uniform(95)
    assert _obs(frame)["present"] is False

    class Tuned(Sensor):
        params = {"screen_lum": 90.0}

    assert observe_screen(frame, Tuned())["present"] is True


def test_env_overrides_the_default(monkeypatch):
    monkeypatch.setenv("STRIKEE_SCREEN_LUM", "90")
    assert _obs(_uniform(95))["present"] is True
    monkeypatch.setenv("STRIKEE_SCREEN_LUM", "150")
    assert _obs(_uniform(95))["present"] is False


def test_an_empty_zone_reports_off_not_a_crash():
    class NoZone:
        zone_polygons = []
        params = {}
    obs = observe_screen(np.zeros((H, W, 3), np.uint8), NoZone())
    assert obs["present"] is False and obs["crop"] is None


# ----------------------------------------------- the threshold recommender


def _load_recommender():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
    from debug_frame import _recommend
    return _recommend


def _report(asset="Station 3", **metrics):
    return {"s1": {"asset": asset, "camera": "Gaming Camera B",
                   "samples": 40,
                   "stats": {k: {"min": v[0], "median": v[1], "max": v[2]}
                             for k, v in metrics.items()}}}


def test_recommender_rejects_the_signal_that_overlaps(capsys):
    """The venue's real numbers: brightness overlaps, colour and structure do not.

    Reporting the overlap is the point - it is what stops someone tuning
    STRIKEE_SCREEN_LUM forever on a signal that cannot work.
    """
    _load_recommender()(
        _report(luminance=(74, 138, 213), contrast=(41, 58, 77),
                saturation=(22, 38, 61), change=(3, 17, 44)),
        _report(luminance=(92, 94, 97), contrast=(6, 9, 13),
                saturation=(2, 4, 7), change=(0, 1, 3)))
    out = capsys.readouterr().out

    assert "luminance" in out and "overlaps" in out
    assert "STRIKEE_SCREEN_LUM=" not in out, "recommended an overlapping signal"
    assert "STRIKEE_SCREEN_CONTRAST=" in out
    assert "STRIKEE_SCREEN_SAT=" in out


def test_recommended_threshold_sits_between_the_two_ranges(capsys):
    _load_recommender()(_report(contrast=(40, 50, 60)),
                        _report(contrast=(6, 9, 10)))
    out = capsys.readouterr().out
    picked = int(out.split("STRIKEE_SCREEN_CONTRAST=")[1].split()[0])
    assert 10 < picked < 40, f"threshold {picked} is not in the gap"


def test_no_separation_points_at_the_zone_not_the_numbers(capsys):
    """If every signal overlaps, the zone takes in more than the panel."""
    _load_recommender()(_report(luminance=(80, 95, 110), contrast=(5, 9, 14)),
                        _report(luminance=(78, 96, 112), contrast=(4, 10, 15)))
    out = capsys.readouterr().out
    assert "No signal separated" in out
    assert "--redraw" in out, "did not say what to actually do about it"


# ------------------------------------- comparing stations in a single pass


def _load_across():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
    from debug_frame import _recommend_across
    return _recommend_across


def _group(**stations):
    return {name: {"asset": name, "camera": "Gaming Camera B", "samples": 30,
                   "stats": {m: {"min": v[0], "median": v[1], "max": v[2]}
                             for m, v in stats.items()}}
            for name, stats in stations.items()}


def test_stations_on_versus_stations_off_in_one_pass(capsys):
    """A venue mid-evening already contains both states - some playing, some
    idle - so a threshold can be had without switching off a customer's TV."""
    _load_across()(
        _group(**{"Station 1": {"luminance": (74, 130, 205),
                                "contrast": (44, 60, 78),
                                "saturation": (25, 40, 58)},
                  "Station 2": {"luminance": (96, 150, 198),
                                "contrast": (41, 57, 69),
                                "saturation": (23, 39, 55)}}),
        _group(**{"Station 5": {"luminance": (92, 94, 97),
                                "contrast": (6, 9, 13),
                                "saturation": (2, 4, 7)},
                  "Station 6": {"luminance": (90, 95, 99),
                                "contrast": (7, 10, 15),
                                "saturation": (2, 5, 9)}}))
    out = capsys.readouterr().out

    assert "overlaps" in out.split("luminance")[1].split("\n")[0]
    assert "STRIKEE_SCREEN_LUM=" not in out
    assert "STRIKEE_SCREEN_CONTRAST=" in out
    assert "STRIKEE_SCREEN_SAT=" in out


def test_pooling_uses_the_worst_station_not_the_average(capsys):
    """One dim screen in the ON group must drag the threshold down with it, or
    the recommendation works for five stations and fails on the sixth."""
    _load_across()(
        _group(**{"Bright": {"contrast": (60, 70, 80)},
                  "Dim":    {"contrast": (30, 35, 40)}}),
        _group(**{"Off": {"contrast": (5, 8, 12)}}))
    out = capsys.readouterr().out
    picked = int(out.split("STRIKEE_SCREEN_CONTRAST=")[1].split()[0])
    assert picked < 30, f"threshold {picked} excludes the dim station"


def test_it_says_the_evidence_is_weaker_than_a_two_state_run(capsys):
    """Different televisions in different corners: a gap could be a difference
    between the sets rather than between on and off."""
    _load_across()(_group(**{"On": {"contrast": (40, 50, 60)}}),
                   _group(**{"Off": {"contrast": (5, 8, 12)}}))
    out = capsys.readouterr().out
    assert "different televisions" in out
    assert "--state on" in out, "did not say how to confirm it properly"
