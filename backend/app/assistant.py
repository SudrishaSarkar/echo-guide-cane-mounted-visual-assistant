"""EchoGuide voice assistant powered by the Gemini API (Person 3).

The user taps "Talk" on the /me phone page and speaks, e.g. "Take me to the
nearest pharmacy" or "How far is it now?". The phone uploads the clip (WAV) to
POST /api/assistant. Gemini listens to the audio directly (no separate
speech-to-text step), works out what the user wants, and returns structured
JSON:

    {"transcript": "...", "intent": "navigate", "destination_query": "pharmacy",
     "nearest": true, "reply": "Okay, finding the nearest pharmacy."}

Intents are then carried out locally:
    navigate         -> navigation.start(destination_query)  (Google Maps route)
    stop_navigation  -> navigation.stop()
    repeat           -> say the next direction again
    route_status     -> "You're heading to X, 200 metres to go..."
    where_am_i       -> reverse-geocoded street address
    chat / unclear   -> Gemini's short spoken reply

Gemini gets the user's care profile (demo data: name, home address, care notes)
so "take me home" or "take me to my usual park" work, plus the current
navigation status. It does NOT get raw GPS coordinates.

Typed text also works ({"text": "..."}), for the caregiver dashboard test box.
Without a Gemini key, a small keyword parser handles text so the demo still runs.

Key: GEMINI_API_KEY (or GOOGLE_API_KEY) env var, or "gemini_api_key" in
backend/settings.json. Model: "gemini_model" setting (default gemini-flash-latest).
"""
from __future__ import annotations

import base64
import binascii
import json
import logging
import os
import re
from typing import Any, Callable, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import care, hooks, maps, navigation
from .navigation import NavError, speak

log = logging.getLogger("echoguide.assistant")

DEFAULT_MODEL = "gemini-flash-latest"
MAX_AUDIO_BYTES = 2_000_000  # ~60 s of 16 kHz mono WAV
AUDIO_MIME_TYPES = {"audio/wav", "audio/x-wav", "audio/mp3", "audio/mpeg", "audio/aac",
                    "audio/ogg", "audio/flac", "audio/webm", "audio/mp4"}

INTENTS = ["navigate", "stop_navigation", "repeat", "route_status", "where_am_i", "chat", "unclear"]

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "transcript": {"type": "string", "description": "What the user said, verbatim."},
        "intent": {"type": "string", "enum": INTENTS},
        "destination_query": {
            "type": "string",
            "description": "For navigate: a Google Maps search query for the place, e.g. "
            "'pharmacy', 'Tim Hortons', or a full street address. Empty otherwise.",
        },
        "nearest": {
            "type": "boolean",
            "description": "True if the user wants the closest place of a kind (any pharmacy, "
            "a coffee shop) rather than one specific named place.",
        },
        "reply": {"type": "string", "description": "Short sentence to speak to the user."},
    },
    "required": ["transcript", "intent", "destination_query", "nearest", "reply"],
}

SYSTEM_PROMPT = """You are EchoGuide, a voice assistant built into a smart cane for a blind or \
low-vision person. Everything you say is read aloud through earbuds while they walk.

Decide what the user wants and fill the JSON fields:
- navigate: they want walking directions somewhere. Put a good Google Maps search query in \
destination_query. Resolve personal places from the profile ("home" = their home address; \
"my usual park" = from care notes). Set nearest=true for "nearest/closest/a/any <kind of place>".
- stop_navigation: stop, cancel or end directions.
- repeat: repeat the last or next direction.
- route_status: how far, how long, where am I going, am I close.
- where_am_i: what street / where am I right now.
- chat: anything else; answer helpfully in the reply.
- unclear: you couldn't understand; ask them to say it again.

Rules for reply:
- One or two short spoken sentences, under 30 words. No lists, markdown, emoji or URLs.
- For navigate, just confirm, e.g. "Okay, finding the nearest pharmacy." Never invent \
directions, distances or street names: the navigation system provides those.
- Never say a path, street or crossing is clear or safe to cross. Remind them to listen for \
traffic or use their cane when relevant.
- If they sound hurt, unwell or in danger, tell them to hold the touch sensor on the cane for \
SOS, or call emergency services.
- Address them by first name occasionally, warmly but briefly."""


# Gemini ------------------------------------------------------------------------

def gemini_key() -> str:
    return (
        os.environ.get("GEMINI_API_KEY")
        or os.environ.get("GOOGLE_API_KEY")
        or hooks.setting("gemini_api_key", "")
        or ""
    )


class GeminiClient:
    """Thin wrapper so tests can swap in a fake: understand(context, text, audio, mime) -> dict."""

    def __init__(self, key: str, model: Optional[str] = None) -> None:
        from google import genai  # imported lazily: optional dependency

        self._client = genai.Client(api_key=key)
        self.model = model or hooks.setting("gemini_model", DEFAULT_MODEL) or DEFAULT_MODEL

    def understand(
        self, context: str, text: Optional[str], audio: Optional[bytes], mime: str
    ) -> dict:
        from google.genai import types

        parts: list[Any] = [types.Part.from_text(text=f"Current situation:\n{context}")]
        if audio is not None:
            parts.append(types.Part.from_text(text="The user's spoken request:"))
            parts.append(types.Part.from_bytes(data=audio, mime_type=mime))
        else:
            parts.append(types.Part.from_text(text=f"The user's request: {text}"))
        resp = self._client.models.generate_content(
            model=self.model,
            contents=[types.Content(role="user", parts=parts)],
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                response_mime_type="application/json",
                response_json_schema=RESPONSE_SCHEMA,
                temperature=0.3,
            ),
        )
        return json.loads(resp.text or "{}")


_client: Optional[Any] = None
_client_checked = False


def get_client() -> Optional[Any]:
    global _client, _client_checked
    if not _client_checked:
        _client_checked = True
        key = gemini_key()
        if key:
            try:
                _client = GeminiClient(key)
            except Exception:
                log.exception("couldn't start the Gemini client")
        else:
            log.warning("no Gemini key: the assistant uses the offline keyword parser")
    return _client


def set_client(client: Optional[Any]) -> None:
    global _client, _client_checked
    _client, _client_checked = client, True


# Offline fallback --------------------------------------------------------------

_NAV_RE = re.compile(
    r"\b(?:take me|navigate|guide me|directions|walk me|bring me|go|head|get me)\b"
    r"(?:\s+(?:to|towards|toward))?\s+(?:the\s+)?(?P<place>.+)",
    re.I,
)


def fallback_parse(text: str) -> dict:
    t = text.strip().rstrip(".?!")
    low = t.lower()
    result = {"transcript": text, "intent": "chat", "destination_query": "", "nearest": False,
              "reply": "Sorry, I can only help with directions right now."}
    if re.search(r"\b(stop|cancel|end)\b.*\b(navigation|directions|route|guiding)\b|^stop$", low):
        result.update(intent="stop_navigation", reply="Okay.")
    elif re.search(r"\b(repeat|say that again|again|next direction)\b", low):
        result.update(intent="repeat", reply="")
    elif re.search(r"\bwhere am i\b|\bwhat street\b", low):
        result.update(intent="where_am_i", reply="")
    elif re.search(r"\bhow far\b|\bhow long\b|\bam i close\b|\bwhere am i going\b", low):
        result.update(intent="route_status", reply="")
    elif m := _NAV_RE.search(t):
        place = m.group("place").strip()
        nearest = bool(re.match(r"(?:nearest|closest|a|an|any)\b", place, re.I))
        place = re.sub(r"^(?:nearest|closest|a|an|any)\s+", "", place, flags=re.I)
        if place.lower() in ("home", "my home", "my house"):
            place = care.get_profile()["data"].get("address") or place
        result.update(intent="navigate", destination_query=place, nearest=nearest,
                      reply=f"Okay, finding {'the nearest ' if nearest else ''}{place}.")
    return result


# Orchestration -----------------------------------------------------------------

def _context() -> str:
    profile = care.get_profile()["data"]
    nav = navigation.get_navigator()
    lines = [
        f"User's name: {profile.get('name') or 'unknown'}",
        f"Home address: {profile.get('address') or 'unknown'}",
        f"Care notes: {profile.get('care_notes') or 'none'}",
        f"Location known: {'yes' if care.latest_location() else 'no (phone not sharing)'}",
        f"Navigation: {nav.status_sentence()}",
    ]
    return "\n".join(lines)


def _where_am_i() -> str:
    fix = care.latest_location()
    if not fix:
        return "I don't know where you are. On your phone, press Start to share your location."
    address = maps.get_provider().reverse_geocode((fix["lat"], fix["lng"]))
    acc = fix.get("accuracy")
    approx = f", give or take {round(acc)} metres" if acc else ""
    if address:
        return f"You're near {address.split(',')[0]}{approx}."
    return f"I can't look up the street name right now, but your caregiver can see you on the map{approx}."


def handle(text: Optional[str] = None, audio: Optional[bytes] = None,
           mime: str = "audio/wav",
           client_factory: Optional[Callable[[], Optional[Any]]] = None) -> dict:
    """Understand one request and act on it. Returns {transcript, intent, reply, ...}."""
    client = (client_factory or get_client)()
    if client is not None:
        try:
            parsed = client.understand(_context(), text, audio, mime)
        except Exception:
            log.exception("Gemini request failed")
            if text is None:
                return _respond({"intent": "error", "transcript": "",
                                 "reply": "Sorry, I couldn't reach the assistant. Please try again."})
            parsed = fallback_parse(text)
    elif text is not None:
        parsed = fallback_parse(text)
    else:
        return _respond({"intent": "error", "transcript": "",
                         "reply": "Voice questions need a Gemini API key. Ask your caregiver to set one up."})

    intent = parsed.get("intent", "unclear")
    reply = (parsed.get("reply") or "").strip()
    nav = navigation.get_navigator()

    if intent == "navigate":
        query = (parsed.get("destination_query") or "").strip()
        if not query:
            return _respond({**parsed, "intent": "unclear", "reply": "Where would you like to go?"})
        if reply and care.latest_location():
            speak(reply)
        try:
            spoken = nav.start(query, bool(parsed.get("nearest")))
        except NavError as exc:
            speak(str(exc))
            return {**parsed, "reply": str(exc), "ok": False, "nav": nav.snapshot()}
        return {**parsed, "reply": spoken, "ok": True, "nav": nav.snapshot()}
    if intent == "stop_navigation":
        if nav.active:
            nav.stop()  # says "Navigation stopped."
            return {**parsed, "reply": "Navigation stopped.", "ok": True}
        return _respond({**parsed, "reply": "You're not navigating anywhere right now."})
    if intent == "repeat":
        return {**parsed, "reply": nav.repeat(), "ok": True}
    if intent == "route_status":
        return _respond({**parsed, "reply": nav.status_sentence()})
    if intent == "where_am_i":
        return _respond({**parsed, "reply": _where_am_i()})
    if not reply:
        reply = "Sorry, I didn't catch that. Please say it again."
    return _respond({**parsed, "reply": reply})


def _respond(result: dict) -> dict:
    speak(result["reply"])
    return {"ok": result.get("intent") not in ("error", "unclear"), **result}


# Route -------------------------------------------------------------------------

class AssistantBody(BaseModel):
    text: Optional[str] = Field(None, max_length=500)
    audio_b64: Optional[str] = Field(None, max_length=MAX_AUDIO_BYTES * 4 // 3 + 16)
    mime_type: str = "audio/wav"


router = APIRouter()


@router.post("/api/assistant")
def api_assistant(body: AssistantBody) -> dict:
    if not body.text and not body.audio_b64:
        raise HTTPException(status_code=400, detail="Send text or audio_b64")
    audio = None
    if body.audio_b64:
        mime = body.mime_type.split(";")[0].strip().lower()
        if mime not in AUDIO_MIME_TYPES:
            raise HTTPException(status_code=400, detail=f"Unsupported audio type {mime}")
        try:
            audio = base64.b64decode(body.audio_b64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise HTTPException(status_code=400, detail="audio_b64 isn't valid base64") from exc
        return handle(audio=audio, mime=mime)
    return handle(text=body.text)
