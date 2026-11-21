"""Cane activity summary and the no-movement check (Person 3).

- A frame counts as motion when its reading differs from the previous one by
  more than MOTION_DELTA_G (the ±1.5 g MMA7660 resolves about 0.047 g per step).
- A minute counts as "moving" when it has >= MOTION_FRAMES_PER_MINUTE motion frames.
- NO_MOVEMENT (WARNING popup) fires once per still spell, after
  `no_movement_after_s` without motion, during `active_hours` (local time),
  and only while frames are still arriving: an unplugged Arduino is
  "unknown", not "not moving".

Published as SessionState.activity and served at GET /api/activity:
    {"moving_minutes_last_hour": 12, "last_motion_ts": iso | null,
     "still_for_s": 40, "hourly": [{"hour_start": iso, "moving_minutes": 7}, ...]}

Settings: no_movement_after_s (default 10800 = 3 h; use ~120 for the demo),
active_hours ([8, 22]).
Wiring: activity.register() subscribes to frames and starts a 1 s ticker.
"""
from __future__ import annotations

import logging
import math
import threading
import time
from datetime import datetime, timezone
from typing import Callable, Optional

from fastapi import APIRouter

from . import events, hooks
from .cane_drop import Vector, read_vector

log = logging.getLogger("echoguide.activity")

MOTION_DELTA_G = 0.08
MOTION_FRAMES_PER_MINUTE = 5
FRAMES_STALE_S = 30.0  # no frames for this long = sensor offline
OFFLINE_BELOW_G = 0.3  # |a| this small can't be a resting sensor (gravity is 1 g)
HOURS_SHOWN = 12
KEEP_MINUTES = 24 * 60


def iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def human_duration(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 120:
        return f"{seconds} seconds"
    if seconds < 2 * 3600:
        minutes = seconds // 60
        return "1 hour" if minutes == 60 else f"{minutes} minutes"
    hours = seconds // 3600
    return f"{hours} hours"


class ActivityTracker:
    def __init__(
        self,
        no_movement_after_s: float = 3 * 3600,
        active_hours: tuple[int, int] = (8, 22),
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.no_movement_after_s = no_movement_after_s
        self.active_hours = active_hours
        self._clock = clock
        self._lock = threading.Lock()
        self._minutes: dict[int, int] = {}  # epoch minute -> motion frames
        self._prev: Optional[Vector] = None
        self._last_motion: Optional[float] = None
        self._first_frame: Optional[float] = None
        self._last_frame: Optional[float] = None
        self._alerted = False
        self._published: Optional[tuple] = None

    @classmethod
    def from_settings(cls) -> "ActivityTracker":
        hours = hooks.setting("active_hours", [8, 22])
        try:
            start, end = int(hours[0]), int(hours[1])
        except (TypeError, ValueError, IndexError):
            start, end = 8, 22
        return cls(float(hooks.setting("no_movement_after_s", 3 * 3600)), (start, end))

    def on_frame(self, frame: dict) -> None:
        vec = read_vector(frame)
        if vec is None or math.sqrt(sum(c * c for c in vec)) < OFFLINE_BELOW_G:
            return  # the firmware sends 0 g when the accelerometer isn't answering
        now = self._clock()
        with self._lock:
            if self._first_frame is None:
                self._first_frame = now
            if self._prev is not None and math.dist(vec, self._prev) > MOTION_DELTA_G:
                minute = int(now // 60)
                self._minutes[minute] = self._minutes.get(minute, 0) + 1
                self._last_motion = now
                self._alerted = False  # a new still spell can alert again later
            self._prev = vec
            self._last_frame = now

    def snapshot(self) -> dict:
        with self._lock:
            return self._snapshot_locked(self._clock())

    def _snapshot_locked(self, now: float) -> dict:
        this_minute = int(now // 60)
        moving = {m for m, n in self._minutes.items() if n >= MOTION_FRAMES_PER_MINUTE}
        last_hour = sum(1 for m in moving if this_minute - 59 <= m <= this_minute)

        local_now = datetime.fromtimestamp(now).astimezone()
        hour_start = local_now.replace(minute=0, second=0, microsecond=0).timestamp()
        hourly = []
        for back in range(HOURS_SHOWN - 1, -1, -1):
            start = hour_start - back * 3600
            first, last = int(start // 60), int((start + 3600) // 60)
            hourly.append({
                "hour_start": iso(start),
                "moving_minutes": sum(1 for m in moving if first <= m < last),
            })

        since = self._still_since()
        return {
            "moving_minutes_last_hour": last_hour,
            "last_motion_ts": iso(self._last_motion) if self._last_motion else None,
            "still_for_s": int(now - since) if since is not None else None,
            "hourly": hourly,
        }

    def _still_since(self) -> Optional[float]:
        return self._last_motion if self._last_motion is not None else self._first_frame

    def tick(self) -> None:
        now = self._clock()
        alert_payload = None
        with self._lock:
            for minute in [m for m in self._minutes if m < int(now // 60) - KEEP_MINUTES]:
                del self._minutes[minute]

            since = self._still_since()
            online = self._last_frame is not None and now - self._last_frame <= FRAMES_STALE_S
            start, end = self.active_hours
            daytime = start <= datetime.fromtimestamp(now).hour < end
            if (
                online
                and daytime
                and not self._alerted
                and since is not None
                and now - since >= self.no_movement_after_s
            ):
                self._alerted = True
                alert_payload = {"duration": human_duration(now - since), "still_since": iso(since)}

            snap = self._snapshot_locked(now)
            key = (snap["moving_minutes_last_hour"], snap["last_motion_ts"], str(snap["hourly"]))
            changed = key != self._published
            self._published = key

        if alert_payload is not None:
            log.info("no cane movement for %s", alert_payload["duration"])
            events.record("NO_MOVEMENT", alert_payload, notify=True)
        if changed:
            hooks.update_state(activity=snap)


_tracker: Optional[ActivityTracker] = None
_tracker_lock = threading.Lock()
_ticker_stop = threading.Event()


def get_tracker() -> ActivityTracker:
    global _tracker
    with _tracker_lock:
        if _tracker is None:
            _tracker = ActivityTracker.from_settings()
        return _tracker


def set_tracker(tracker: Optional[ActivityTracker]) -> None:
    global _tracker
    with _tracker_lock:
        _tracker = tracker


def on_frame(frame: dict) -> None:
    get_tracker().on_frame(frame)


def register(tick_interval_s: float = 1.0) -> None:
    hooks.call("state", "on_frame", on_frame)
    _ticker_stop.clear()

    def loop() -> None:
        while not _ticker_stop.wait(tick_interval_s):
            try:
                get_tracker().tick()
            except Exception:
                log.exception("activity tick failed")

    threading.Thread(target=loop, name="echoguide-activity", daemon=True).start()


def stop() -> None:
    _ticker_stop.set()


router = APIRouter()


@router.get("/api/activity")
def api_activity() -> dict:
    return get_tracker().snapshot()
