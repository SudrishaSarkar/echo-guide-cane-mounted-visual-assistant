"""Care profile and the user's phone location (Person 3).

Routes:
    GET  /api/profile         -> {"data": Profile, "updated_at": iso}  (seeded with demo data)
    PUT  /api/profile         <- Profile
    GET  /api/location        -> {lat, lng, accuracy, ts} | null
    POST /api/location        <- {lat, lng, accuracy}  (from the /me phone page)

The location is kept in memory only (latest fix), pushed to the dashboard as
SessionState.location, and attached to SOS and cane-drop alerts through
events.location_provider. The profile is DEMO DATA: never enter a real
person's medical details.
"""
from __future__ import annotations

import threading
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from . import events, hooks
from .db import get_db, utc_now_iso


class Contact(BaseModel):
    name: str = Field("", max_length=100)
    relation: str = Field("", max_length=60)
    phone: str = Field("", max_length=40)


class Medication(BaseModel):
    name: str = Field("", max_length=100)
    dose: str = Field("", max_length=100)


class Profile(BaseModel):
    name: str = Field("", max_length=100)
    age: Optional[int] = Field(None, ge=0, le=130)
    address: str = Field("", max_length=300)
    contacts: list[Contact] = Field(default_factory=list, max_length=20)
    medical_history: str = Field("", max_length=5000)
    medications: list[Medication] = Field(default_factory=list, max_length=50)
    allergies: list[str] = Field(default_factory=list, max_length=50)
    care_notes: str = Field("", max_length=5000)


# Clearly fictional: 555-01xx numbers are reserved for fiction.
DEMO_PROFILE = Profile(
    name="Alex Rivera",
    age=72,
    address="123 Demo Street, London, ON (demo)",
    contacts=[
        Contact(name="Sam Rivera", relation="Daughter (primary caregiver)", phone="555-0101"),
        Contact(name="Jordan Lee", relation="Neighbour", phone="555-0102"),
    ],
    medical_history="Glaucoma (low vision since 2015). Type 2 diabetes. Demo data.",
    medications=[
        Medication(name="Latanoprost eye drops", dose="1 drop each eye, evenings"),
        Medication(name="Metformin", dose="500 mg twice daily"),
    ],
    allergies=["Penicillin"],
    care_notes="Prefers spoken updates. Walks to the park most mornings around 9 AM. Demo data.",
)


class LocationIn(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lng: float = Field(..., ge=-180, le=180)
    accuracy: Optional[float] = Field(None, ge=0)


_location: Optional[dict] = None
_location_lock = threading.Lock()


def latest_location() -> Optional[dict]:
    with _location_lock:
        return dict(_location) if _location else None


def set_location(lat: float, lng: float, accuracy: Optional[float] = None) -> dict:
    global _location
    fix = {"lat": lat, "lng": lng, "accuracy": accuracy, "ts": utc_now_iso()}
    with _location_lock:
        _location = fix
    hooks.update_state(location=fix)
    return dict(fix)


def clear_location() -> None:
    global _location
    with _location_lock:
        _location = None


def get_profile() -> dict:
    stored = get_db().get_profile()
    if stored is None:
        updated_at = get_db().set_profile(DEMO_PROFILE.model_dump())
        stored = {"data": DEMO_PROFILE.model_dump(), "updated_at": updated_at}
    return stored


def save_profile(profile: Profile) -> dict:
    updated_at = get_db().set_profile(profile.model_dump())
    hooks.update_state(profile_updated_at=updated_at)
    return {"data": profile.model_dump(), "updated_at": updated_at}


def register() -> None:
    """Attach the phone location to SOS and cane-drop alerts."""
    events.location_provider = latest_location
    get_profile()  # seed demo data on first run


router = APIRouter()


@router.get("/api/profile")
def api_get_profile() -> dict:
    return get_profile()


@router.put("/api/profile")
def api_put_profile(profile: Profile) -> dict:
    return save_profile(profile)


@router.get("/api/location")
def api_get_location() -> Optional[dict]:
    return latest_location()


@router.post("/api/location")
def api_post_location(body: LocationIn) -> dict:
    return set_location(body.lat, body.lng, body.accuracy)
