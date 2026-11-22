"""Cane-drop check-in (Person 3).

The Grove accelerometer is ±1.5 g (MMA7660FC), and a white cane bumps the
ground all the time, so an `impact` event alone never means "dropped". After an impact the
cane must also end up lying down and stay still:

    IDLE ──impact──> WATCHING ──lying + still for 10 s──> PROMPTING ──no answer 30 s──> ALERTED
                       │                                    │  tap / DROP_OK ──> IDLE
                       │ upright again after 3 s, or        │  hold / DROP_HELP ──> SOS
                       │ never settles within 30 s ──> IDLE  │  picked up ──> IDLE
                                                           ALERTED: picked up / OK ──> IDLE,
                                                                    plus an all-clear to the caregiver

While prompting or alerted, the buzzer plays the `find` pattern so the cane can
be found on the floor (it stops after BEEP_MAX_S, or when resolved).

"Lying down" uses gravity: when the cane is still, the accelerometer reads
about 1 g pointing down. Upright, that's along the cane's long axis; lying on
the floor, it's across it. Which board axis runs along the cane depends on
how the clamp holds it, so set "cane_axis" ("x", "y" or "z") in
settings.json after mounting. The default is "z".

Wiring (main.py / P1):
    state.on_event("impact", cane_drop.on_impact)
    state.on_frame(cane_drop.on_frame)        # every input frame
    cane_drop.register() does both and starts the timeout ticker.
P2's controls: while cane_drop.prompt_active(), tap -> respond_ok("touch"),
hold_start -> respond_help("touch").
"""
from __future__ import annotations

import logging
import math
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

from . import events, hooks
from .db import utc_now_iso

log = logging.getLogger("echoguide.cane_drop")

IDLE, WATCHING, PROMPTING, ALERTED = "idle", "watching", "prompting", "alerted"

PROMPT = "The cane may have been dropped. Tap if you're OK, or hold for help."
ALERT_SENT = "No response. Sending SOS to your caregiver."
FALL_SPOKEN = "Fall detected. SOS sent to your caregiver. Tap if you're OK."
ALARM_MS = 30000  # loud continuous buzzer when nobody answers (fall + unresponsive)
OK_REPLY = "OK, glad you're all right."
OK_AFTER_ALERT = "OK. I've told your caregiver you're all right."

Vector = tuple[float, float, float]
Action = Callable[[], Any]


@dataclass
class DropConfig:
    enabled: bool = True
    cane_axis: str = "z"
    lying_angle_deg: float = 60.0    # tilt from upright that counts as lying down
    upright_angle_deg: float = 45.0  # tilt at or below this counts as picked up
    still_delta_g: float = 0.12      # max change between frames that still counts as still
    rest_min_g: float = 0.75         # |a| must be near 1 g to count as resting
    rest_max_g: float = 1.25
    settle_s: float = 3.0            # after an impact, time allowed to end up lying down
    still_required_s: float = 10.0   # lying + still this long -> prompt
    watch_timeout_s: float = 30.0    # give up if it never settles
    response_timeout_s: float = 30.0 # no answer -> caregiver alert
    reprompt_s: float = 15.0         # repeat the question once
    beep_max_s: float = 120.0        # stop the find beeps after this long
    # True: the impact itself raises the alarm, logs the fall and sends the
    # SOS in the same instant (no still/no-answer wait). One tap cancels.
    instant_sos: bool = False

    @classmethod
    def from_settings(cls) -> "DropConfig":
        axis = str(hooks.setting("cane_axis", "z")).strip().lstrip("+-").lower()
        if axis not in ("x", "y", "z"):
            log.warning("cane_axis %r is not x/y/z; using z", axis)
            axis = "z"
        response = float(hooks.setting("cane_drop_response_s", 20.0))
        return cls(
            enabled=bool(hooks.setting("cane_drop_enabled", True)),
            cane_axis=axis,
            still_required_s=float(hooks.setting("cane_drop_inactivity_s", 10.0)),
            instant_sos=bool(hooks.setting("fall_instant_sos", True)),
            response_timeout_s=response,
            reprompt_s=response / 2,
        )


def read_vector(frame: dict) -> Optional[Vector]:
    try:
        return float(frame["ax"]), float(frame["ay"]), float(frame["az"])
    except (KeyError, TypeError, ValueError):
        return None


def tilt_deg(vec: Vector, axis: str) -> Optional[float]:
    """Angle between the cane's long axis and gravity: 0 = upright, 90 = flat."""
    magnitude = math.sqrt(sum(c * c for c in vec))
    if magnitude < 0.3:  # falling or garbage: no usable gravity direction
        return None
    along = abs(vec["xyz".index(axis)]) / magnitude
    return math.degrees(math.acos(min(1.0, along)))


class CaneDropDetector:
    def __init__(
        self, config: Optional[DropConfig] = None, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.config = config or DropConfig()
        self._clock = clock
        self._lock = threading.Lock()
        self._state = IDLE
        self._prev: Optional[Vector] = None
        self._impact_at = 0.0
        self._impact_ts = ""
        self._still_since: Optional[float] = None
        self._tilt: Optional[float] = None
        self._prompt_at = 0.0
        self._alert_at = 0.0
        self._reprompted = False
        self._beeping = False
        self._drop_event_id: Optional[int] = None
        self._payload: dict = {}
        self._instant = False

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    def prompt_active(self) -> bool:
        with self._lock:
            return self._state in (PROMPTING, ALERTED)

    # Inputs ---------------------------------------------------------------

    def on_impact(self, *_: Any) -> None:
        if not self.config.enabled:
            return
        if self.config.instant_sos:
            self._instant_fall()
            return
        with self._lock:
            if self._state not in (IDLE, WATCHING):
                return
            self._state = WATCHING
            self._impact_at = self._clock()
            self._impact_ts = utc_now_iso()
            self._still_since = None
        log.info("impact: watching for a dropped cane")

    def _instant_fall(self) -> None:
        """Impact -> alarm + logged fall + SOS, all at once."""
        now = self._clock()
        with self._lock:
            if self._state in (PROMPTING, ALERTED):
                return  # already raised; don't stack SOSes
            ts = utc_now_iso()
            self._state = ALERTED
            self._instant = True
            self._impact_at = self._alert_at = now
            self._impact_ts = ts
            self._beeping = True
            self._drop_event_id = None
            tilt = tilt_deg(self._prev, self.config.cane_axis) if self._prev else None
            payload = {"impact_ts": ts, "alert_ts": ts, "trigger": "impact"}
            if tilt is not None:
                payload["tilt_deg"] = round(tilt)
        log.warning("impact: fall alarm + SOS sent immediately")
        _run([
            lambda: hooks.update_state(cane_drop_prompt=True),
            lambda: self._send_drop_alert(payload),          # SOS + incident log
            lambda: hooks.send_cmd({"cmd": "buzz", "ms": ALARM_MS}),  # after the SOS's own beeps
            lambda: hooks.say(FALL_SPOKEN),
        ])

    def on_frame(self, frame: dict) -> None:
        vec = read_vector(frame)
        if vec is None:
            return
        cfg = self.config
        now = self._clock()
        actions: list[Action] = []
        with self._lock:
            magnitude = math.sqrt(sum(c * c for c in vec))
            jolted = self._prev is not None and math.dist(vec, self._prev) > cfg.still_delta_g
            resting = not jolted and cfg.rest_min_g <= magnitude <= cfg.rest_max_g
            self._prev = vec
            tilt = tilt_deg(vec, cfg.cane_axis)

            if self._state == WATCHING:
                lying = tilt is not None and tilt >= cfg.lying_angle_deg
                if lying and resting:
                    if self._still_since is None:
                        self._still_since = now
                    self._tilt = tilt
                else:
                    self._still_since = None
                if not lying and now - self._impact_at >= cfg.settle_s:
                    log.info("impact was just a bump: cane is upright")
                    self._to_idle()
                elif self._still_since is not None and now - self._still_since >= cfg.still_required_s:
                    actions += self._start_prompt(now)
            elif self._state in (PROMPTING, ALERTED) and not self._instant:
                # (After an instant fall alert, someone picking the cane up
                # doesn't mean the person is OK: only a tap clears it.)
                if tilt is not None and tilt <= cfg.upright_angle_deg:
                    actions += self._resolve_ok("picked_up")

            actions += self._tick_locked(now)
        _run(actions)

    def tick(self) -> None:
        """Advance timeouts. Called by the ticker so they fire even without frames."""
        with self._lock:
            actions = self._tick_locked(self._clock())
        _run(actions)

    def respond_ok(self, source: str = "unknown") -> bool:
        with self._lock:
            if self._state not in (PROMPTING, ALERTED):
                return False
            actions = self._resolve_ok(source)
        _run(actions)
        return True

    def respond_help(self, source: str = "unknown") -> bool:
        with self._lock:
            if self._state not in (PROMPTING, ALERTED):
                return False
            drop_id = self._drop_event_id
            self._to_idle()
        payload = {"source": source}
        if drop_id is not None:
            payload["drop_id"] = drop_id
        _run([
            lambda: hooks.send_cmd({"cmd": "buzz", "ms": 0}),
            lambda: hooks.update_state(cane_drop_prompt=False),
            lambda: events.record("DROP_HELP", payload),
            lambda: events.trigger_sos("cane_drop"),  # SOS is the alert; DROP_HELP is context
        ])
        return True

    # Transitions (call with the lock held; return side effects to run after) --

    def _start_prompt(self, now: float) -> list[Action]:
        still_s = now - (self._still_since or now)
        self._state = PROMPTING
        self._prompt_at = now
        self._reprompted = False
        self._beeping = True
        self._drop_event_id = None
        self._payload = {
            "impact_ts": self._impact_ts,
            "still_s": round(still_s, 1),
            "tilt_deg": round(self._tilt or 0.0),
        }
        log.info("cane looks dropped: prompting the user")
        return [
            lambda: hooks.send_cmd({"cmd": "beep", "pattern": "find"}),
            lambda: hooks.update_state(cane_drop_prompt=True),
            lambda: hooks.say(PROMPT),
        ]

    def _tick_locked(self, now: float) -> list[Action]:
        cfg = self.config
        if self._state == WATCHING and now - self._impact_at >= cfg.watch_timeout_s:
            log.info("cane never settled after the impact; ignoring it")
            self._to_idle()
        elif self._state == PROMPTING:
            if now - self._prompt_at >= cfg.response_timeout_s:
                self._state = ALERTED
                self._alert_at = now
                payload = dict(self._payload)
                payload["alert_ts"] = utc_now_iso()
                payload["no_answer_s"] = round(now - self._prompt_at, 1)
                # Fall + no answer: loud alarm for bystanders, an SOS to the
                # caregiver, and a logged fall incident linked to that SOS.
                return [
                    lambda: self._send_drop_alert(payload),
                    lambda: hooks.send_cmd({"cmd": "buzz", "ms": ALARM_MS}),
                    lambda: hooks.chime("sos"),
                    lambda: hooks.say(ALERT_SENT),
                ]
            if not self._reprompted and now - self._prompt_at >= cfg.reprompt_s:
                self._reprompted = True
                return [lambda: hooks.say(PROMPT)]
        elif self._state == ALERTED and self._beeping and now - self._alert_at >= cfg.beep_max_s:
            self._beeping = False
            return [lambda: hooks.send_cmd({"cmd": "buzz", "ms": 0})]
        return []

    def _resolve_ok(self, source: str) -> list[Action]:
        was = self._state
        drop_id = self._drop_event_id
        self._to_idle()
        actions: list[Action] = [
            lambda: hooks.send_cmd({"cmd": "buzz", "ms": 0}),
            lambda: hooks.update_state(cane_drop_prompt=False),
        ]
        if was == ALERTED:
            # The caregiver already got an ALERT, so send them the all-clear.
            payload = {"source": source}
            if drop_id is not None:
                payload["drop_id"] = drop_id
            actions.append(lambda: events.record("DROP_OK", payload, notify=True))
            if source != "picked_up":
                actions.append(lambda: hooks.say(OK_AFTER_ALERT))
        else:
            actions.append(lambda: events.record("DROP_OK", {"source": source}))
            if source != "picked_up":
                actions.append(lambda: hooks.say(OK_REPLY))
        log.info("cane drop resolved (%s)", source)
        return actions

    def _to_idle(self) -> None:
        self._state = IDLE
        self._instant = False
        self._still_since = None
        self._beeping = False
        self._drop_event_id = None

    def _send_drop_alert(self, payload: dict) -> None:
        location = events.current_location()
        if location:
            payload["location"] = location
        payload["kind"] = "fall"
        try:
            sos = events.trigger_sos("fall")
            if sos and sos.get("id") is not None:
                payload["sos_event_id"] = sos["id"]
        except Exception:
            log.exception("SOS after fall failed")
        event = events.record("CANE_DROP", payload, notify=True)
        with self._lock:
            if self._state == ALERTED:
                self._drop_event_id = event["id"]


def _run(actions: list[Action]) -> None:
    for action in actions:
        try:
            action()
        except Exception:
            log.exception("cane_drop action failed")


# Module-level detector and wiring --------------------------------------------

_detector: Optional[CaneDropDetector] = None
_detector_lock = threading.Lock()
_ticker_stop = threading.Event()


def get_detector() -> CaneDropDetector:
    global _detector
    with _detector_lock:
        if _detector is None:
            _detector = CaneDropDetector(DropConfig.from_settings())
        return _detector


def set_detector(detector: Optional[CaneDropDetector]) -> None:
    """Swap the shared detector (tests)."""
    global _detector
    with _detector_lock:
        _detector = detector


def on_impact(*args: Any) -> None:
    get_detector().on_impact(*args)


def on_frame(frame: dict) -> None:
    get_detector().on_frame(frame)


def prompt_active() -> bool:
    return get_detector().prompt_active()


def respond_ok(source: str = "unknown") -> bool:
    return get_detector().respond_ok(source)


def respond_help(source: str = "unknown") -> bool:
    return get_detector().respond_help(source)


def register(tick_interval_s: float = 0.5) -> None:
    """Subscribe to P1's state hooks and start the timeout ticker."""
    hooks.call("state", "on_event", "impact", on_impact)
    hooks.call("state", "on_frame", on_frame)
    _ticker_stop.clear()

    def loop() -> None:
        while not _ticker_stop.wait(tick_interval_s):
            get_detector().tick()

    threading.Thread(target=loop, name="echoguide-cane-drop", daemon=True).start()


def stop() -> None:
    _ticker_stop.set()


# For main.py's POST /action dispatcher (docs/contracts.md section 4).
ACTIONS: dict[str, Callable[[], Any]] = {
    "DROP_OK": lambda: respond_ok("dashboard"),
    "DROP_HELP": lambda: respond_help("dashboard"),
}
