"""Session state machine shared by hardware input, vision, and the frontend.

The backend owns this state so joystick/touch input and on-screen buttons
produce identical behaviour (see the integration contract in docs/demo.md
and the project build guide).
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, asdict
from enum import Enum
from typing import Optional, Set


class Mode(str, Enum):
    IDLE = "IDLE"
    DESCRIBING = "DESCRIBING"
    SEARCHING = "SEARCHING"
    GUIDING = "GUIDING"
    NEAR_TARGET = "NEAR_TARGET"
    PAUSED = "PAUSED"
    CONFIRMED = "CONFIRMED"


@dataclass
class SessionState:
    mode: Mode = Mode.IDLE
    selected_object: Optional[str] = None
    target_visible: bool = False
    hand_visible: bool = False
    instruction: str = ""
    instruction_id: int = 0
    camera_connected: bool = False
    arduino_connected: bool = False

    def to_dict(self) -> dict:
        d = asdict(self)
        d["mode"] = self.mode.value
        return d


class StateManager:
    """Holds the current SessionState and fans out updates to WebSocket subscribers."""

    def __init__(self) -> None:
        self.state = SessionState()
        self._subscribers: Set[asyncio.Queue] = set()

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers.add(queue)
        queue.put_nowait(self.state.to_dict())
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subscribers.discard(queue)

    def update(self, **changes) -> None:
        for key, value in changes.items():
            setattr(self.state, key, value)
        self._broadcast()

    def set_instruction(self, text: str) -> None:
        """Bump instruction_id only when the instruction text actually changes.

        The frontend speaks only when instruction_id changes, so re-sending the
        same instruction must not retrigger speech.
        """
        if text != self.state.instruction:
            self.state.instruction = text
            self.state.instruction_id += 1
            self._broadcast()

    def _broadcast(self) -> None:
        payload = self.state.to_dict()
        for queue in self._subscribers:
            queue.put_nowait(payload)


state_manager = StateManager()
