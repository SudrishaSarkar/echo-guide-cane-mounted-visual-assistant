"""Event history, the SOS state machine and the /api/events + /api/sos routes (Person 3).

Caregiver notifications are in-app only. An event that needs the caregiver's
attention is stored with notify_status "pending"; the caregiver dashboard
alerts (banner, sound, browser notification) and then calls
POST /api/events/{id}/seen, which marks it "delivered". So "delivered" means a
caregiver screen has actually shown it.

SOS lifecycle (sos_status in docs/contracts.md section 3):

    active ──caregiver screen shows it──> delivered ──Acknowledge──> acknowledged
      └──user cancels (from active or delivered)──> cancelled

The SOS goes out immediately. P2's 3-second hold countdown is what guards
against accidental presses. If no caregiver screen has shown it within
SOS_UNSEEN_WARN_S, the cane tells the user so they can get help another way.

Other modules call:
    trigger_sos(source)   cancel_sos(source)   acknowledge_sos(by)
    mark_seen(event_id, by)   sos_open()   record(type, payload, notify=False)
"""
from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from . import alerts, hooks
from .db import get_db

log = logging.getLogger("echoguide.events")

OPEN_STATUSES = {"active", "delivered"}

# How long an SOS may go unseen by any caregiver screen before the user is told.
SOS_UNSEEN_WARN_S = 30.0

RECENT_EVENTS_LIMIT = 20

# Returns {"lat", "lng", "accuracy", "ts"} or None. The location module sets this.
location_provider: Callable[[], Optional[dict]] = lambda: None


@dataclass
class SosState:
    event_id: int
    source: str
    triggered_at: str
    status: str = "active"
    notify_status: str = "pending"
    seen_or_closed: threading.Event = field(default_factory=threading.Event)


_lock = threading.RLock()
_sos: Optional[SosState] = None

_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="echoguide-events")
_pending: set[Future] = set()
_pending_lock = threading.Lock()


# Public API ------------------------------------------------------------------

def sos_open() -> bool:
    with _lock:
        return _sos is not None and _sos.status in OPEN_STATUSES


def sos_snapshot() -> dict:
    """The sos_* fields of SessionState."""
    with _lock:
        sos = _sos
        if sos is None:
            return {
                "sos_active": False,
                "sos_event_id": None,
                "sos_status": "idle",
                "sos_notify_status": None,
                "sos_triggered_at": None,
            }
        return {
            "sos_active": sos.status in OPEN_STATUSES,
            "sos_event_id": sos.event_id,
            "sos_status": sos.status,
            "sos_notify_status": sos.notify_status,
            "sos_triggered_at": sos.triggered_at,
        }


def publish() -> None:
    """Push the SOS fields and recent events to the dashboard."""
    hooks.update_state(**sos_snapshot(), recent_events=list_events(RECENT_EVENTS_LIMIT))


def list_events(limit: int = 100) -> list[dict]:
    """Newest first, with severity + notification attached (see alerts.py)."""
    name = _user_name()
    return [alerts.present(e, name) for e in get_db().list_events(limit)]


def record(type: str, payload: Optional[dict] = None, notify: bool = False) -> dict:
    """Store a non-SOS event. notify=True makes it a pending caregiver alert
    (in-app banner, plus a system notification if alerts.py gives it a severity)."""
    event = get_db().add_event(type, payload, "pending" if notify else "not_sent")
    publish()
    return _present(event)


def trigger_sos(source: str = "unknown") -> dict:
    """Start an SOS. While one is open, returns that SOS's event instead of a new one."""
    global _sos
    with _lock:
        if _sos is not None and _sos.status in OPEN_STATUSES:
            existing = get_db().get_event(_sos.event_id)
            sos = None
        else:
            payload: dict[str, Any] = {"source": source}
            location = _location()
            if location:
                payload["location"] = location
            event = get_db().add_event("SOS", payload, "pending")
            sos = _sos = SosState(event["id"], source, event["ts"])

    if sos is None:
        hooks.say("SOS is already active.")
        return _present(existing)

    hooks.send_cmd({"cmd": "beep", "pattern": "sos"})
    hooks.chime("sos")
    hooks.say("Sending SOS to your caregiver.")
    publish()
    _submit(_warn_if_unseen, sos)
    return _present(event)


def mark_seen(event_id: int, by: str = "caregiver") -> Optional[dict]:
    """A caregiver screen has shown this event. Returns the event, or None if unknown."""
    db = get_db()
    event = db.get_event(event_id)
    if event is None:
        return None
    if event["notify_status"] != "pending":
        return _present(event)  # already seen, or never needed an alert

    event = db.update_event(event_id, notify_status="delivered")
    confirm = False
    with _lock:
        sos = _sos
        if sos is not None and sos.event_id == event_id:
            sos.notify_status = "delivered"
            if sos.status == "active":
                sos.status = "delivered"
                sos.seen_or_closed.set()
                confirm = True
    log.info("event %s seen by %s", event_id, by)
    if confirm:
        hooks.say("Your caregiver has been alerted.")
    publish()
    return _present(event)


def cancel_sos(source: str = "unknown") -> Optional[dict]:
    """Cancel the open SOS. Returns the SOS_CANCELLED event, or None if nothing was open."""
    db = get_db()
    with _lock:
        sos = _sos
        if sos is None or sos.status not in OPEN_STATUSES:
            return None
        seen = sos.notify_status == "delivered"
        sos.status = "cancelled"
        sos.seen_or_closed.set()
        if not seen:
            # No caregiver saw it, so there's nothing to alert them about any more.
            sos.notify_status = "not_sent"
            db.update_event(sos.event_id, notify_status="not_sent")
        # If they did see it, they need to see the false alarm too.
        event = db.add_event(
            "SOS_CANCELLED",
            {"source": source, "sos_id": sos.event_id},
            "pending" if seen else "not_sent",
        )

    hooks.send_cmd({"cmd": "buzz", "ms": 0})
    hooks.chime("ok")
    if seen:
        hooks.say("SOS cancelled. Your caregiver will see it was a false alarm.")
    else:
        hooks.say("SOS cancelled.")
    publish()
    return _present(event)


def acknowledge_sos(by: str = "caregiver") -> Optional[dict]:
    """Caregiver pressed Acknowledge. Returns the SOS_ACKNOWLEDGED event, or None if nothing was open."""
    db = get_db()
    with _lock:
        sos = _sos
        if sos is None or sos.status not in OPEN_STATUSES:
            return None
        sos.status = "acknowledged"
        sos.seen_or_closed.set()
        if sos.notify_status == "pending":  # acknowledging implies they've seen it
            sos.notify_status = "delivered"
            db.update_event(sos.event_id, notify_status="delivered")
        event = db.add_event("SOS_ACKNOWLEDGED", {"by": by, "sos_id": sos.event_id})

    hooks.send_cmd({"cmd": "buzz", "ms": 0})
    hooks.chime("ok")
    hooks.say("Your caregiver has seen your alert.")
    publish()
    return _present(event)


def drain(timeout: float = 10.0) -> bool:
    """Wait for background work (unseen-SOS warnings). True if all finished."""
    deadline = time.monotonic() + timeout
    while True:
        with _pending_lock:
            pending = set(_pending)
        if not pending:
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        wait(pending, timeout=remaining)


def shutdown() -> None:
    with _lock:
        if _sos is not None:
            _sos.seen_or_closed.set()
    _executor.shutdown(wait=False, cancel_futures=True)


def reset() -> None:
    """Forget the current SOS (for tests)."""
    global _sos
    with _lock:
        if _sos is not None:
            _sos.seen_or_closed.set()
        _sos = None


# Background work -------------------------------------------------------------

def _submit(fn: Callable[..., Any], *args: Any) -> None:
    future = _executor.submit(_run_logged, fn, *args)
    with _pending_lock:
        _pending.add(future)
    future.add_done_callback(_forget)


def _forget(future: Future) -> None:
    with _pending_lock:
        _pending.discard(future)


def _run_logged(fn: Callable[..., Any], *args: Any) -> None:
    try:
        fn(*args)
    except Exception:
        log.exception("background task %s failed", getattr(fn, "__name__", fn))


def _warn_if_unseen(sos: SosState) -> None:
    if sos.seen_or_closed.wait(SOS_UNSEEN_WARN_S):
        return
    with _lock:
        still_unseen = sos.status == "active"
    if still_unseen:
        hooks.say(
            "Your alert hasn't reached a caregiver screen yet. "
            "If you can, call for help another way."
        )


def _user_name() -> str:
    profile = get_db().get_profile()
    name = (profile or {}).get("data", {}).get("name")
    return name or hooks.setting("user_display_name", "EchoGuide user")


def _present(event: dict) -> dict:
    return alerts.present(event, _user_name())


def current_location() -> Optional[dict]:
    """Latest phone location, or None. Safe to call from any module."""
    return _location()


def _location() -> Optional[dict]:
    try:
        location = location_provider()
    except Exception:
        log.exception("location_provider failed")
        return None
    return location if isinstance(location, dict) else None


# HTTP routes (main.py includes this router) ----------------------------------

router = APIRouter()


class SourceBody(BaseModel):
    source: str = "dashboard"


class ByBody(BaseModel):
    by: str = "caregiver"


@router.get("/api/events")
def api_events(limit: int = Query(100, ge=1, le=1000)) -> list[dict]:
    return list_events(limit)


@router.post("/api/events/{event_id}/seen")
def api_event_seen(event_id: int, body: Optional[ByBody] = None) -> dict:
    event = mark_seen(event_id, (body or ByBody()).by)
    if event is None:
        raise HTTPException(status_code=404, detail="No such event")
    return event


@router.get("/api/sos")
def api_sos_status() -> dict:
    return sos_snapshot()


@router.post("/api/sos")
def api_sos(body: Optional[SourceBody] = None) -> dict:
    event = trigger_sos((body or SourceBody()).source)
    return {"event": event, **sos_snapshot()}


@router.post("/api/sos/cancel")
def api_sos_cancel(body: Optional[SourceBody] = None) -> dict:
    event = cancel_sos((body or SourceBody()).source)
    if event is None:
        raise HTTPException(status_code=409, detail="No open SOS to cancel")
    return {"event": event, **sos_snapshot()}


@router.post("/api/sos/ack")
def api_sos_ack(body: Optional[ByBody] = None) -> dict:
    event = acknowledge_sos((body or ByBody()).by)
    if event is None:
        raise HTTPException(status_code=409, detail="No open SOS to acknowledge")
    return {"event": event, **sos_snapshot()}


# For main.py's POST /action dispatcher (docs/contracts.md section 4).
ACTIONS: dict[str, Callable[[], Any]] = {
    "SOS": lambda: trigger_sos("dashboard"),
    "SOS_CANCEL": lambda: cancel_sos("dashboard"),
    "SOS_ACK": lambda: acknowledge_sos("caregiver"),
}
