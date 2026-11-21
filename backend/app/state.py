"""Session state shared by hardware input, vision, and the frontend.

The backend owns this state so hardware events and on-screen buttons produce
identical behaviour. Field ownership is defined in docs/contracts.md —
P1 owns hazards/warning/light/connections/audio instruction; P2 and P3 add
their fields here as they implement their modules.
"""
from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass, asdict, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set


class Mode(str, Enum):
    IDLE = "IDLE"
    DESCRIBING = "DESCRIBING"
    READING = "READING"
    SOS_COUNTDOWN = "SOS_COUNTDOWN"
    SOS_ACTIVE = "SOS_ACTIVE"


@dataclass
class SessionState:
    mode: Mode = Mode.IDLE

    # P1: vision hazards + alerts
    hazards: List[dict] = field(default_factory=list)
    warning: str = ""
    warning_id: int = 0
    warning_side: Optional[str] = None
    warning_urgent: bool = False
    light: Optional[float] = None

    # P2: descriptions / OCR / focus
    last_description: str = ""
    last_text_read: str = ""
    focus: str = "all"  # "all" | "left" | "right"

    # P3: SOS / cane-drop / activity / location / events
    sos_active: bool = False
    sos_event_id: Optional[int] = None
    sos_status: str = ""
    sos_triggered_at: Optional[str] = None
    sos_countdown: Optional[int] = None
    cane_drop_prompt: bool = False
    find_cane_active: bool = False
    activity: dict = field(default_factory=dict)
    location: Optional[dict] = None
    recent_events: List[dict] = field(default_factory=list)

    # Shared: last spoken text (display only; audio comes from backend)
    instruction: str = ""
    instruction_id: int = 0

    camera_connected: bool = False
    arduino_connected: bool = False

    def to_dict(self) -> dict:
        d = asdict(self)
        d["mode"] = self.mode.value
        return d


class StateManager:
    """Holds SessionState, fans out updates to WebSocket subscribers, and
    routes named hardware events to registered handlers (P2/P3 subscribe
    via state.on_event; see docs/contracts.md section 7)."""

    def __init__(self) -> None:
        self.state = SessionState()
        self._subscribers: Set[asyncio.Queue] = set()
        self._event_handlers: Dict[str, List[Callable[..., None]]] = {}
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    # --- WebSocket pub/sub ---
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
        """Bump instruction_id only when the instruction text changes, so the
        dashboard doesn't re-display stale speech."""
        if text != self.state.instruction:
            self.state.instruction = text
            self.state.instruction_id += 1
            self._broadcast()

    def _broadcast(self) -> None:
        payload = self.state.to_dict()
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(payload)
            except Exception:
                pass

    # --- Named hardware/REST events (contract section 1 & 4) ---
    def on_event(self, name: str, handler: Callable[..., None]) -> None:
        self._event_handlers.setdefault(name, []).append(handler)

    def emit_event(self, name: str, **payload: Any) -> None:
        for handler in self._event_handlers.get(name, []):
            try:
                handler(**payload)
            except Exception as exc:
                print(f"[state] event handler for {name!r} failed: {exc}")


state_manager = StateManager()
