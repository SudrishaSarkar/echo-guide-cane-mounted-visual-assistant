"""Severity and system-notification text for caregiver events (Person 3).

Every event the dashboard receives carries:
    "severity":     "alert" | "warning" | "update" | "info"
    "notification": {"title", "body", "tag", "require_interaction"} or None

For a `pending` event with a notification, the caregiver dashboard shows an
operating-system notification via the browser Notification API, as well as
the in-app banner. Titles are prefixed with the severity tag ("ALERT: ...").
`tag` lets a later notification replace an earlier one: an SOS_CANCELLED
reuses its SOS's tag, so the false alarm replaces the SOS on screen.
`require_interaction` keeps ALERTs on screen until the caregiver clicks them.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

SEVERITY: dict[str, str] = {
    "SOS": "alert",
    "DROP_HELP": "alert",
    "CANE_DROP": "alert",
    "NO_MOVEMENT": "warning",
    "SOS_CANCELLED": "update",
    "DROP_OK": "update",  # only pops up when it's an all-clear after a CANE_DROP alert
}

TAG_TEXT = {"alert": "ALERT", "warning": "WARNING", "update": "UPDATE"}

# type -> (title, body). Placeholders: {name} {time} {duration}
TEMPLATES: dict[str, tuple[str, str]] = {
    "SOS": ("SOS from {name}", "{name} asked for help at {time}."),
    "DROP_HELP": (
        "{name} needs help after a cane drop",
        "{name} asked for help after their cane was dropped ({time}).",
    ),
    "CANE_DROP": (
        "{name} may have fallen",
        "At {time} the cane hit the ground hard (possible fall). "
        "An SOS has been sent.",
    ),
    "NO_MOVEMENT": (
        "No cane movement for {duration}",
        "{name}'s cane hasn't moved for {duration} (as of {time}).",
    ),
    "SOS_CANCELLED": (
        "{name} cancelled the SOS",
        "False alarm: {name} cancelled the SOS at {time}.",
    ),
    "DROP_OK": (
        "Cane drop resolved",
        "{name} answered that they're OK ({time}).",
    ),
}

# DROP_OK body when nobody answered but the cane started moving again.
PICKED_UP_BODY = "The cane was picked up and is moving again ({time})."


def severity_for(event_type: str) -> str:
    return SEVERITY.get(event_type, "info")


def local_time(ts: str) -> str:
    """'2026-11-21T19:02:00Z' -> '2:02 PM' in the server's local timezone."""
    try:
        moment = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone()
    except ValueError:
        return ts
    return moment.strftime("%I:%M %p").lstrip("0")


def notification_for(event: dict, user_name: str) -> Optional[dict]:
    severity = severity_for(event["type"])
    if severity == "info":
        return None
    payload = event.get("payload") or {}
    title, body = TEMPLATES[event["type"]]
    if event["type"] == "DROP_OK" and payload.get("source") == "picked_up":
        body = PICKED_UP_BODY
    values = {
        "name": user_name,
        "time": local_time(event["ts"]),
        "duration": payload.get("duration", "a while"),
    }
    body = body.format(**values)
    if payload.get("location"):
        body += " Last known location is on the map."
    return {
        "title": f"{TAG_TEXT[severity]}: {title.format(**values)}",
        "body": body,
        "tag": _tag(event, payload),
        "require_interaction": severity == "alert",
    }


def _tag(event: dict, payload: dict) -> str:
    """Follow-ups share their incident's tag so they replace it on screen."""
    kind = event["type"]
    if kind == "SOS":
        return f"echoguide-sos-{event['id']}"
    if kind == "SOS_CANCELLED" and payload.get("sos_id"):
        return f"echoguide-sos-{payload['sos_id']}"
    if kind == "CANE_DROP":
        return f"echoguide-drop-{event['id']}"
    if kind == "DROP_OK" and payload.get("drop_id"):
        return f"echoguide-drop-{payload['drop_id']}"
    return f"echoguide-{event['id']}"


def present(event: dict, user_name: str) -> dict:
    """The event as sent to the dashboard: adds severity and notification."""
    return {
        **event,
        "severity": severity_for(event["type"]),
        "notification": notification_for(event, user_name),
    }
