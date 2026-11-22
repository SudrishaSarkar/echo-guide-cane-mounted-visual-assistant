import time

import pytest

from app import controls, describer, reader
from app.state import Mode, state_manager


@pytest.fixture
def env(monkeypatch):
    said, focuses, emitted = [], [], []

    def describe(focus):
        focuses.append(focus)
        return f"A chair on the {focus}"

    real_emit = state_manager.emit_event

    def emit(name, **payload):
        emitted.append(name)
        real_emit(name, **payload)

    monkeypatch.setattr(controls.audio, "say", said.append)
    monkeypatch.setattr(describer, "describe", describe)
    monkeypatch.setattr(reader, "read_text", lambda: "Aspirin 500 mg")
    monkeypatch.setattr(state_manager, "emit_event", emit)
    monkeypatch.setattr(controls, "SOS_COUNTDOWN_S", 1)
    monkeypatch.setattr(controls, "_last_spoken", "")
    monkeypatch.setattr(controls, "_countdown_cancel", None)
    s = state_manager.state
    monkeypatch.setattr(s, "sos_active", False)
    monkeypatch.setattr(s, "cane_drop_prompt", False)
    monkeypatch.setattr(s, "mode", Mode.IDLE)
    return dict(said=said, focuses=focuses, emitted=emitted, s=s)


def wait_for(cond, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


def test_registered_for_hardware_and_action_events():
    handlers = state_manager._event_handlers
    for name in ("joy_up", "joy_down", "joy_left", "joy_right", "joy_press", "tap",
                 "hold_start", "hold_release", "button_hold",
                 "describe", "read_text", "focus_left", "focus_right", "repeat"):
        assert name in handlers, name


@pytest.mark.parametrize("hw,rest", [("joy_up", "describe"), ("joy_left", "focus_left"),
                                     ("joy_right", "focus_right")])
def test_hardware_and_button_share_handlers(env, hw, rest):
    state_manager.emit_event(hw)
    assert wait_for(lambda: len(env["focuses"]) == 1)
    state_manager.emit_event(rest)
    assert wait_for(lambda: len(env["focuses"]) == 2)
    assert env["focuses"][0] == env["focuses"][1]


def test_joy_up_describes_whole_scene(env):
    state_manager.emit_event("joy_up")
    assert wait_for(lambda: env["said"] == ["A chair on the all"])
    assert env["s"].focus == "all"
    assert env["s"].last_description == "A chair on the all"
    assert state_manager.state.instruction == "A chair on the all"
    assert wait_for(lambda: env["s"].mode == Mode.IDLE)


def test_joy_left_right_set_focus(env):
    state_manager.emit_event("joy_left")
    assert wait_for(lambda: env["focuses"] == ["left"])
    assert env["s"].focus == "left"
    state_manager.emit_event("joy_right")
    assert wait_for(lambda: env["focuses"] == ["left", "right"])
    assert env["s"].focus == "right"


def test_joy_down_reads_text(env):
    state_manager.emit_event("joy_down")
    assert wait_for(lambda: env["said"] == ["Aspirin 500 mg"])
    assert env["s"].last_text_read == "Aspirin 500 mg"


def test_joy_press_repeats_last_result(env):
    state_manager.emit_event("joy_press")
    assert env["said"] == ["Nothing to repeat yet."]
    state_manager.emit_event("joy_down")
    assert wait_for(lambda: len(env["said"]) == 2)
    state_manager.emit_event("joy_press")
    assert env["said"][-1] == "Aspirin 500 mg"


def test_describer_failure_speaks_fallback(env, monkeypatch):
    def boom(_focus):
        raise RuntimeError("detector not ready")

    monkeypatch.setattr(describer, "describe", boom)
    controls.handle_action("DESCRIBE")
    assert wait_for(lambda: env["said"] == ["Description unavailable."])


def test_handle_action_rejects_non_p2_actions(env):
    for name in ("SOS", "SOS_CANCEL", "FIND_CANE", "DROP_OK", "DROP_HELP", "BOGUS"):
        assert controls.handle_action(name) is False


def test_tap_describes_when_idle(env):
    state_manager.emit_event("tap")
    assert wait_for(lambda: env["focuses"] == ["all"])


def test_tap_cancels_active_sos(env):
    env["s"].sos_active = True
    state_manager.emit_event("tap")
    assert "sos_cancel" in env["emitted"]
    assert env["focuses"] == []


def test_tap_dismisses_drop_prompt(env):
    env["s"].cane_drop_prompt = True
    state_manager.emit_event("tap")
    assert "drop_ok" in env["emitted"]
    assert env["focuses"] == []


def test_hold_countdown_completes_and_triggers_sos(env):
    state_manager.emit_event("hold_start")
    assert wait_for(lambda: "sos" in env["emitted"])
    assert env["said"] == ["SOS in 1"]
    assert env["s"].sos_countdown is None


def test_hold_release_cancels_countdown(env, monkeypatch):
    monkeypatch.setattr(controls, "SOS_COUNTDOWN_S", 3)
    state_manager.emit_event("hold_start")
    assert wait_for(lambda: env["s"].mode == Mode.SOS_COUNTDOWN)
    state_manager.emit_event("hold_release")
    assert env["said"][-1] == "SOS cancelled"
    assert env["s"].mode == Mode.IDLE
    assert env["s"].sos_countdown is None
    time.sleep(1.2)
    assert "sos" not in env["emitted"]


def test_hold_release_after_completion_does_nothing(env):
    state_manager.emit_event("hold_start")
    assert wait_for(lambda: "sos" in env["emitted"])
    state_manager.emit_event("hold_release")
    assert "SOS cancelled" not in env["said"]


def test_button_hold_triggers_sos(env):
    state_manager.emit_event("button_hold")
    assert env["emitted"].count("sos") == 1
