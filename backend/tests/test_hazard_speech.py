"""Webcam = danger mode: distance estimates, beep levels and stress words."""
from unittest import mock

from app import hazards, narrator
from app.hazards import HazardMonitor, estimate_distance_m
from app.narrator import hazard_sentence, say_distance
from app.state import Mode, state_manager

H = 720  # frame height


def det(label, y1, y2):
    return {"label": label, "box": (100, y1, 300, y2), "side": "center"}


def test_distance_shrinks_as_box_grows():
    far = estimate_distance_m(det("chair", 300, 400), H)
    near = estimate_distance_m(det("chair", 100, 600), H)
    assert far is not None and near is not None
    assert near < far
    # A 0.9 m chair filling 500 of 720 px (50 deg FOV) is about 1 m away.
    assert 0.8 < near < 1.4


def test_distance_unknown_when_cut_off_or_unknown_label():
    assert estimate_distance_m(det("chair", 0, 500), H) is None      # top cut off
    assert estimate_distance_m(det("chair", 200, H), H) is None      # bottom cut off
    assert estimate_distance_m(det("spaceship", 200, 400), H) is None


def test_beep_level_by_distance():
    lvl = HazardMonitor._level_for_distance
    assert lvl(None) == 0
    assert lvl(4.0) == 0
    assert lvl(2.0) == 1
    assert lvl(1.2) == 2
    assert lvl(0.5) == 3


def test_spoken_distance():
    assert say_distance(None) == ""
    assert say_distance(0.5) == ""            # too close for a number: "very close"
    assert say_distance(1.0) == "about 1 metre"
    assert say_distance(1.3) == "about 1.5 metres"
    assert say_distance(2.1) == "about 2 metres"
    assert say_distance(4.4) == "about 4 metres"


def test_stress_words_rise_with_level():
    assert hazard_sentence("chair", "center", 1, 2.1) == "Chair ahead, about 2 metres."
    assert hazard_sentence("chair", "center", 2, 1.2) == "Careful! Chair ahead, about 1 metre."
    assert hazard_sentence("chair", "center", 3, 0.5) == "Stop! Chair right in front of you."
    assert hazard_sentence("person", "left", 3, None) == "Watch out! Person very close on your left."
    assert hazard_sentence("person", "right", 2, None) == "Careful! Person close on your right."


def test_joystick_answer_silences_beeps():
    with mock.patch.object(hazards.audio, "priority_speaking", return_value=False):
        state_manager.state.mode = Mode.DESCRIBING
        try:
            assert HazardMonitor._joystick_busy()
        finally:
            state_manager.state.mode = Mode.IDLE
        assert not HazardMonitor._joystick_busy()
    with mock.patch.object(hazards.audio, "priority_speaking", return_value=True):
        assert HazardMonitor._joystick_busy()  # answer still being spoken


def _run_ticks(n, nearest, priority=False):
    n_obj = narrator.Narrator()
    said, narrated = [], []
    with mock.patch.object(hazards.hazard_monitor, "nearest", nearest), \
         mock.patch.object(narrator.audio, "say", said.append), \
         mock.patch.object(narrator.audio, "narrate", lambda t: narrated.append(t) or True), \
         mock.patch.object(narrator.audio, "priority_speaking", return_value=priority):
        for _ in range(n):
            n_obj._tick_hazards()
    return said, narrated


def test_close_hazard_is_narrated_after_it_is_steady():
    h = {"label": "chair", "side": "center", "level": 1, "distance_m": 2.0}
    said, narrated = _run_ticks(1, h)
    assert narrated == []                      # one frame is not enough
    said, narrated = _run_ticks(3, h)
    assert narrated == ["Chair ahead, about 2 metres."]
    assert said == []


def test_mild_hazard_waits_for_joystick_answer():
    h = {"label": "chair", "side": "center", "level": 2, "distance_m": 1.2}
    said, narrated = _run_ticks(3, h, priority=True)
    assert narrated == [] and said == []


def test_danger_interrupts_even_during_joystick_answer():
    h = {"label": "chair", "side": "center", "level": 3, "distance_m": 0.5}
    said, narrated = _run_ticks(3, h, priority=True)
    assert said == ["Stop! Chair right in front of you."]


def test_no_hazard_means_silence():
    said, narrated = _run_ticks(5, None)
    assert said == [] and narrated == []


def test_beeps_need_a_steady_hazard():
    m = HazardMonitor()
    # one-frame flickers never beep
    assert [m._steady_level(v) for v in (2, 0, 1, 0, 0)] == [0, 0, 0, 0, 0]
    # a hazard held for 3 polls (~0.3 s) does
    m = HazardMonitor()
    assert [m._steady_level(v) for v in (2, 2, 2)] == [0, 0, 2]
    # a single dropout doesn't silence it
    assert m._steady_level(0) == 2


def test_small_tabletop_items_are_not_hazards():
    from app.config import DEFAULT_OBSTACLE_CLASSES
    for small in ("cup", "bottle", "book", "laptop", "cell phone"):
        assert small not in DEFAULT_OBSTACLE_CLASSES
    for big in ("person", "chair", "dining table", "bicycle", "dog"):
        assert big in DEFAULT_OBSTACLE_CLASSES
