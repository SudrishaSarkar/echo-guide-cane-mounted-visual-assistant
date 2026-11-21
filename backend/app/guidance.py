"""Turns target/hand positions into stable spoken instructions.

Image coordinates are unmirrored throughout: top of frame = far edge of
table, bottom = near the user (set during overhead-camera calibration).
Camera-space overlap is treated only as a guidance cue, never as proof of
physical contact — the user must confirm the find explicitly.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

from .config import settings

NEUTRAL_ZONE = 0.06  # fraction of frame; prevents left/right oscillation near center


@dataclass
class Position:
    x: float
    y: float


class GuidanceEngine:
    def __init__(self) -> None:
        self._pending_instruction: Optional[str] = None
        self._pending_since: Optional[float] = None
        self._last_spoken: Optional[str] = None
        self._last_spoken_at: float = 0.0

    def reset(self) -> None:
        self._pending_instruction = None
        self._pending_since = None
        self._last_spoken = None
        self._last_spoken_at = 0.0

    def step(
        self, target: Optional[Position], hand: Optional[Position]
    ) -> tuple[str, bool]:
        """Returns (instruction_text, near_target)."""
        if hand is None:
            return self._stabilize("Place your hand in view")
        if target is None:
            return self._stabilize("Target lost. Pause while I look again")

        dx = target.x - hand.x
        dy = target.y - hand.y
        distance = (dx**2 + dy**2) ** 0.5

        if distance <= settings.near_target_radius:
            return self._stabilize("Your hand is near the object", near_target=True)

        if abs(dx) >= abs(dy):
            instruction = "Move left" if dx < -NEUTRAL_ZONE else "Move right" if dx > NEUTRAL_ZONE else None
        else:
            instruction = (
                "Move away from you" if dy < -NEUTRAL_ZONE else "Move toward you" if dy > NEUTRAL_ZONE else None
            )

        if instruction is None:
            return self._stabilize("Your hand is near the object", near_target=True)
        return self._stabilize(instruction)

    def _stabilize(self, instruction: str, near_target: bool = False) -> tuple[str, bool]:
        now = time.monotonic()

        if instruction != self._pending_instruction:
            self._pending_instruction = instruction
            self._pending_since = now

        held_frames_ok = (now - (self._pending_since or now)) >= 0.0
        # Caller feeds this once per processed frame, so persistence is time-based
        # using instruction_persist_frames as an approximate frame budget.
        min_hold_s = settings.instruction_persist_frames / 15.0
        if (now - (self._pending_since or now)) < min_hold_s:
            if self._last_spoken is not None:
                return self._last_spoken, near_target
            return "", near_target

        if instruction == self._last_spoken:
            if (now - self._last_spoken_at) < settings.instruction_repeat_delay_s:
                return self._last_spoken, near_target

        self._last_spoken = instruction
        self._last_spoken_at = now
        return instruction, near_target
