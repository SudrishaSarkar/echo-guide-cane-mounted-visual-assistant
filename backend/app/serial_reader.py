"""Reads Arduino JSON lines over USB serial and turns them into actions.

Expected line format, ~20 Hz:
    {"type":"input","seq":42,"joy_x":512,"joy_y":508,"touch":0}

Calibrates the joystick centre from the first readings, applies a dead zone,
requires the joystick to return to centre between deflections (one action per
deflection), and debounces the touch signal into short-touch / long-touch
events. Close the Arduino Serial Monitor before running this — only one
program can own the COM port at a time.
"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional

import serial

from .config import settings


class Action(str, Enum):
    PREV_OBJECT = "PREV_OBJECT"
    NEXT_OBJECT = "NEXT_OBJECT"
    START = "START"
    REPEAT = "REPEAT"
    TOUCH_SHORT = "TOUCH_SHORT"
    TOUCH_LONG = "TOUCH_LONG"


@dataclass
class _AxisLatch:
    """Fires once per deflection past the dead zone; must return to centre to re-arm."""

    center: int
    deadzone: int
    armed: bool = True

    def read(self, value: int) -> Optional[str]:
        delta = value - self.center
        if abs(delta) <= self.deadzone:
            self.armed = True
            return None
        if not self.armed:
            return None
        self.armed = False
        return "positive" if delta > 0 else "negative"


class SerialReader:
    def __init__(self, on_action: Callable[[Action], None], on_connection_change: Callable[[bool], None]):
        self.on_action = on_action
        self.on_connection_change = on_connection_change
        self._ser: Optional[serial.Serial] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._x_latch: Optional[_AxisLatch] = None
        self._y_latch: Optional[_AxisLatch] = None
        self._touch_down_at: Optional[float] = None
        self._touch_was_long = False
        self._calibration_samples: list[tuple[int, int]] = []
        self._connected = False

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._ser is not None:
            self._ser.close()

    def _set_connected(self, connected: bool) -> None:
        if connected != self._connected:
            self._connected = connected
            self.on_connection_change(connected)

    def _run(self) -> None:
        while self._running:
            try:
                self._ser = serial.Serial(settings.serial_port, settings.baud_rate, timeout=1)
                # Opening the port only proves *some* device answered (e.g. an unrelated
                # Bluetooth COM port) - "connected" means valid EchoGuide JSON is flowing.
                self._read_loop()
            except serial.SerialException:
                self._set_connected(False)
                time.sleep(1.0)

    def _read_loop(self) -> None:
        assert self._ser is not None
        consecutive_empty_reads = 0
        while self._running:
            line = self._ser.readline()
            if not line:
                consecutive_empty_reads += 1
                if consecutive_empty_reads >= 3:  # ~3s of silence at timeout=1
                    self._set_connected(False)
                continue
            try:
                payload = json.loads(line.decode("utf-8", errors="ignore").strip())
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            if payload.get("type") != "input":
                continue
            consecutive_empty_reads = 0
            self._set_connected(True)
            self._handle_payload(payload)

    def _handle_payload(self, payload: dict) -> None:
        joy_x, joy_y, touch = payload["joy_x"], payload["joy_y"], payload["touch"]

        if len(self._calibration_samples) < 10:
            self._calibration_samples.append((joy_x, joy_y))
            if len(self._calibration_samples) == 10:
                cx = sum(s[0] for s in self._calibration_samples) // 10
                cy = sum(s[1] for s in self._calibration_samples) // 10
                self._x_latch = _AxisLatch(center=cx, deadzone=settings.joystick_deadzone)
                self._y_latch = _AxisLatch(center=cy, deadzone=settings.joystick_deadzone)
            return

        assert self._x_latch is not None and self._y_latch is not None
        x_dir = self._x_latch.read(joy_x)
        y_dir = self._y_latch.read(joy_y)
        if x_dir == "negative":
            self.on_action(Action.PREV_OBJECT)
        elif x_dir == "positive":
            self.on_action(Action.NEXT_OBJECT)
        if y_dir == "negative":
            self.on_action(Action.START)
        elif y_dir == "positive":
            self.on_action(Action.REPEAT)

        self._handle_touch(bool(touch))

    def _handle_touch(self, pressed: bool) -> None:
        now = time.monotonic()
        if pressed and self._touch_down_at is None:
            self._touch_down_at = now
            self._touch_was_long = False
        elif pressed and self._touch_down_at is not None:
            held_ms = (now - self._touch_down_at) * 1000
            if held_ms >= settings.touch_long_press_ms and not self._touch_was_long:
                self._touch_was_long = True
                self.on_action(Action.TOUCH_LONG)
        elif not pressed and self._touch_down_at is not None:
            if not self._touch_was_long:
                self.on_action(Action.TOUCH_SHORT)
            self._touch_down_at = None
            self._touch_was_long = False


if __name__ == "__main__":
    reader = SerialReader(
        on_action=lambda action: print(f"action: {action.value}"),
        on_connection_change=lambda connected: print(f"arduino connected: {connected}"),
    )
    reader.start()
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        reader.stop()
