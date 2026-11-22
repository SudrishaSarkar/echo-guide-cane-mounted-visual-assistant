"""P2: joystick/touch events and dashboard buttons -> describe / read text / focus / repeat,
plus the touch-hold SOS countdown. See docs/contracts.md sections 1, 3 and 4.

Hardware events (serial_reader) and POST /action (main.py) both arrive through
state_manager.emit_event(); this module subscribes to both sets of names on import,
so a joystick flick and the matching dashboard button run the same handler.
SOS, SOS cancel and drop-prompt replies are handed to P3 as the same events
main.py emits for /action ("sos", "sos_cancel", "drop_ok").
"""
from __future__ import annotations

import logging
import threading
from typing import Callable

from . import describer, reader
from .audio import audio
from .state import Mode, state_manager

log = logging.getLogger(__name__)

SOS_COUNTDOWN_S = 3

P2_ACTIONS = ("DESCRIBE", "READ_TEXT", "FOCUS_LEFT", "FOCUS_RIGHT", "REPEAT")

# Hardware event names (contract section 1) and main.py's /action event names.
EVENT_ACTIONS = {
    "joy_up": "DESCRIBE",
    "joy_down": "READ_TEXT",
    "joy_left": "FOCUS_LEFT",
    "joy_right": "FOCUS_RIGHT",
    "joy_press": "REPEAT",
    "describe": "DESCRIBE",
    "read_text": "READ_TEXT",
    "focus_left": "FOCUS_LEFT",
    "focus_right": "FOCUS_RIGHT",
    "repeat": "REPEAT",
}

_lock = threading.Lock()
_last_spoken = ""
_request_id = 0
_countdown_cancel: threading.Event | None = None
_registered = False


def register() -> None:
    global _registered
    if _registered:
        return
    _registered = True
    for name, action in EVENT_ACTIONS.items():
        state_manager.on_event(name, _action_handler(action))
    state_manager.on_event("tap", lambda **_: on_tap())
    state_manager.on_event("hold_start", lambda **_: on_hold_start())
    state_manager.on_event("hold_release", lambda **_: on_hold_release())
    state_manager.on_event("button_hold", lambda **_: on_button_hold())


def handle_action(name: str) -> bool:
    """Runs a P2 action. Returns False for actions owned by another module."""
    if name == "DESCRIBE":
        _start_describe("all")
    elif name == "FOCUS_LEFT":
        _start_describe("left")
    elif name == "FOCUS_RIGHT":
        _start_describe("right")
    elif name == "READ_TEXT":
        _start_read()
    elif name == "REPEAT":
        _say(_last_spoken or "Nothing to repeat yet.")
    else:
        return False
    return True


def on_tap() -> None:
    s = state_manager.state
    if s.sos_active:
        state_manager.emit_event("sos_cancel")
        if s.cane_drop_prompt:  # SOS came from a fall: one tap answers both
            state_manager.emit_event("drop_ok")
    elif s.cane_drop_prompt:
        state_manager.emit_event("drop_ok")
    else:
        handle_action("DESCRIBE")


def on_hold_start() -> None:
    global _countdown_cancel
    if state_manager.state.sos_active:
        return
    if state_manager.state.cane_drop_prompt:
        state_manager.emit_event("drop_help")  # straight to SOS, no countdown
        return
    with _lock:
        if _countdown_cancel is not None:
            return
        cancel = threading.Event()
        _countdown_cancel = cancel
    threading.Thread(target=_run_countdown, args=(cancel,), daemon=True).start()


def on_hold_release() -> None:
    global _countdown_cancel
    with _lock:
        cancel, _countdown_cancel = _countdown_cancel, None
    if cancel is None:
        return
    cancel.set()
    state_manager.update(mode=Mode.IDLE, sos_countdown=None)
    _say("SOS cancelled")


def on_button_hold() -> None:
    if not state_manager.state.sos_active:
        state_manager.emit_event("sos")


def _action_handler(action: str) -> Callable[..., None]:
    return lambda **_: handle_action(action)


def _run_countdown(cancel: threading.Event) -> None:
    global _countdown_cancel
    state_manager.update(mode=Mode.SOS_COUNTDOWN, sos_countdown=SOS_COUNTDOWN_S)
    for remaining in range(SOS_COUNTDOWN_S, 0, -1):
        if cancel.is_set():
            return
        state_manager.update(sos_countdown=remaining)
        _say(f"SOS in {remaining}" if remaining == SOS_COUNTDOWN_S else str(remaining))
        if cancel.wait(1.0):
            return
    with _lock:
        if cancel.is_set() or _countdown_cancel is not cancel:
            return
        _countdown_cancel = None
    state_manager.update(sos_countdown=None)
    state_manager.emit_event("sos")


def _start_describe(focus: str) -> None:
    state_manager.update(focus=focus)
    _run_latest(Mode.DESCRIBING, lambda: describer.describe(focus), "last_description",
                "Description unavailable.")


def _start_read() -> None:
    _run_latest(Mode.READING, reader.read_text, "last_text_read", "Text reading unavailable.")


def _run_latest(mode: Mode, work: Callable[[], str], field: str, fallback: str) -> None:
    """Runs work off the serial thread; only the newest request is spoken."""
    global _request_id
    with _lock:
        _request_id += 1
        my_id = _request_id
    if _countdown_cancel is None and not state_manager.state.sos_active:
        state_manager.update(mode=mode)

    def task() -> None:
        global _last_spoken
        try:
            text = work()
        except Exception:
            log.exception("%s failed", mode.value)
            text = fallback
        with _lock:
            if my_id != _request_id:
                return
        _last_spoken = text
        state_manager.update(**{field: text})
        _say(text)
        if (_countdown_cancel is None and not state_manager.state.sos_active
                and state_manager.state.mode == mode):
            state_manager.update(mode=Mode.IDLE)

    threading.Thread(target=task, daemon=True).start()


def _say(text: str) -> None:
    audio.say(text)
    state_manager.set_instruction(text)


register()
