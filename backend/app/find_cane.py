"""Find-my-cane (double clap or app button -> buzzer) and loud-noise logging (Person 3).

The Arduino sends `clap` only for a double clap (two sharp spikes within
~0.6 s), so voices and doors don't set it off. The buzzer plays the repeating
`find` pattern for FIND_DURATION_S, then stops. If the cane-drop check-in is
beeping at that moment, its beeps are left running.

`loud` (sustained loud sound) is logged as a LOUD_NOISE event for the
caregiver's history, at most once per LOUD_COOLDOWN_S. It's info only, with no
popup.

Wiring: find_cane.register() subscribes to the `clap` and `loud` events.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, Optional

from . import cane_drop, events, hooks

log = logging.getLogger("echoguide.find_cane")

FIND_DURATION_S = 5.0
RECORD_COOLDOWN_S = 10.0  # one FIND_CANE history entry per burst of requests
LOUD_COOLDOWN_S = 60.0


class FindCane:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._timer: Optional[threading.Timer] = None
        self._active = False
        self._last_record = -1e9
        self._last_loud = -1e9

    @property
    def active(self) -> bool:
        with self._lock:
            return self._active

    def find(self, source: str = "unknown") -> None:
        now = self._clock()
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()  # a new request restarts the 5 s
            self._timer = threading.Timer(FIND_DURATION_S, self.stop)
            self._timer.daemon = True
            self._timer.start()
            self._active = True
            should_record = now - self._last_record >= RECORD_COOLDOWN_S
            if should_record:
                self._last_record = now
        hooks.send_cmd({"cmd": "beep", "pattern": "find"})
        hooks.update_state(find_cane_active=True)
        if should_record:
            events.record("FIND_CANE", {"source": source})
        log.info("find cane (%s)", source)

    def stop(self) -> None:
        with self._lock:
            if not self._active:
                return
            self._active = False
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
        if not cane_drop.prompt_active():  # don't silence the drop check-in's beeps
            hooks.send_cmd({"cmd": "buzz", "ms": 0})
        hooks.update_state(find_cane_active=False)

    def on_loud(self, *_: Any) -> None:
        now = self._clock()
        with self._lock:
            if now - self._last_loud < LOUD_COOLDOWN_S:
                return
            self._last_loud = now
        events.record("LOUD_NOISE", {})


_finder = FindCane()


def get_finder() -> FindCane:
    return _finder


def set_finder(finder: FindCane) -> None:
    global _finder
    _finder = finder


def on_clap(*_: Any) -> None:
    _finder.find("clap")


def on_loud(*args: Any) -> None:
    _finder.on_loud(*args)


def register() -> None:
    hooks.call("state", "on_event", "clap", on_clap)
    hooks.call("state", "on_event", "loud", on_loud)


# For main.py's POST /action dispatcher. The /me page and dashboard use this.
ACTIONS: dict[str, Callable[[], Any]] = {
    "FIND_CANE": lambda: _finder.find("app"),
}
