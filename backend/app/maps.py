"""Google Maps Platform calls for walking navigation (Person 3).

    find_place(query, near, nearest)  -> Place   (Places API (New): Text Search)
    walking_route(origin, place)      -> Route   (Routes API: computeRoutes, WALK)
    reverse_geocode(point)            -> str     (Geocoding API)

The key comes from the GOOGLE_MAPS_API_KEY environment variable or
"google_maps_api_key" in backend/settings.json. Enable "Places API (New)",
"Routes API" and "Geocoding API" for that key in Google Cloud.

Without a key, FakeMaps is used: it invents a short grid route from the
current location, so the whole navigation flow can be demoed and tested
offline. `provider` is the active backend; tests may replace it.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Optional, Protocol

import httpx

from . import geo, hooks
from .geo import Point

log = logging.getLogger("echoguide.maps")

PLACES_URL = "https://places.googleapis.com/v1/places:searchText"
ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
TIMEOUT_S = 10.0
SEARCH_RADIUS_M = 3000.0


class MapsError(Exception):
    """A user-presentable failure (the message is safe to speak)."""


@dataclass
class Place:
    name: str
    address: str
    location: Point


@dataclass
class Step:
    instruction: str
    maneuver: str
    start: Point
    end: Point
    distance_m: float
    path: list[Point] = field(default_factory=list)


@dataclass
class Route:
    destination: Place
    steps: list[Step]
    distance_m: float
    duration_s: float
    path: list[Point]


class MapsProvider(Protocol):
    def find_place(self, query: str, near: Optional[Point], nearest: bool = False) -> Place: ...
    def walking_route(self, origin: Point, place: Place) -> Route: ...
    def reverse_geocode(self, point: Point) -> Optional[str]: ...


def api_key() -> str:
    return os.environ.get("GOOGLE_MAPS_API_KEY") or hooks.setting("google_maps_api_key", "") or ""


# Google ----------------------------------------------------------------------

class GoogleMaps:
    def __init__(self, key: str, client: Optional[httpx.Client] = None) -> None:
        self.key = key
        self.client = client or httpx.Client(timeout=TIMEOUT_S)

    def _post(self, url: str, body: dict, field_mask: str) -> dict:
        try:
            resp = self.client.post(
                url,
                json=body,
                headers={"X-Goog-Api-Key": self.key, "X-Goog-FieldMask": field_mask},
            )
        except httpx.HTTPError as exc:
            log.warning("maps request failed: %s", exc)
            raise MapsError("I can't reach the maps service right now.") from exc
        if resp.status_code != 200:
            log.warning("maps %s -> %s %s", url, resp.status_code, resp.text[:300])
            raise MapsError("The maps service returned an error.")
        return resp.json()

    def find_place(self, query: str, near: Optional[Point], nearest: bool = False) -> Place:
        body: dict = {"textQuery": query, "languageCode": "en"}
        if near is not None:
            body["locationBias"] = {
                "circle": {
                    "center": {"latitude": near[0], "longitude": near[1]},
                    "radius": SEARCH_RADIUS_M,
                }
            }
            if nearest:
                body["rankPreference"] = "DISTANCE"
        data = self._post(
            PLACES_URL, body, "places.displayName,places.formattedAddress,places.location"
        )
        places = data.get("places") or []
        if not places:
            raise MapsError(f"I couldn't find {query} nearby.")
        p = places[0]
        loc = p.get("location") or {}
        return Place(
            name=(p.get("displayName") or {}).get("text") or query,
            address=p.get("formattedAddress", ""),
            location=(float(loc["latitude"]), float(loc["longitude"])),
        )

    def walking_route(self, origin: Point, place: Place) -> Route:
        def waypoint(p: Point) -> dict:
            return {"location": {"latLng": {"latitude": p[0], "longitude": p[1]}}}

        body = {
            "origin": waypoint(origin),
            "destination": waypoint(place.location),
            "travelMode": "WALK",
            "languageCode": "en",
            "units": "METRIC",
        }
        mask = ",".join(
            [
                "routes.distanceMeters",
                "routes.duration",
                "routes.polyline.encodedPolyline",
                "routes.legs.steps.distanceMeters",
                "routes.legs.steps.startLocation",
                "routes.legs.steps.endLocation",
                "routes.legs.steps.navigationInstruction",
                "routes.legs.steps.polyline.encodedPolyline",
            ]
        )
        data = self._post(ROUTES_URL, body, mask)
        routes = data.get("routes") or []
        if not routes:
            raise MapsError(f"I couldn't find a walking route to {place.name}.")
        return parse_route(routes[0], place)

    def reverse_geocode(self, point: Point) -> Optional[str]:
        try:
            resp = self.client.get(
                GEOCODE_URL, params={"latlng": f"{point[0]},{point[1]}", "key": self.key}
            )
            results = resp.json().get("results") or []
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("reverse geocode failed: %s", exc)
            return None
        return results[0].get("formatted_address") if results else None


def _latlng(loc: dict) -> Point:
    ll = loc.get("latLng") or {}
    return (float(ll.get("latitude", 0.0)), float(ll.get("longitude", 0.0)))


def parse_route(route: dict, place: Place) -> Route:
    steps: list[Step] = []
    for leg in route.get("legs") or []:
        for s in leg.get("steps") or []:
            nav = s.get("navigationInstruction") or {}
            start, end = _latlng(s.get("startLocation") or {}), _latlng(s.get("endLocation") or {})
            encoded = (s.get("polyline") or {}).get("encodedPolyline")
            path = geo.decode_polyline(encoded) if encoded else [start, end]
            steps.append(
                Step(
                    instruction=(nav.get("instructions") or "Continue").replace("\n", ". "),
                    maneuver=nav.get("maneuver", ""),
                    start=start,
                    end=end,
                    distance_m=float(s.get("distanceMeters", 0)),
                    path=path,
                )
            )
    if not steps:
        raise MapsError(f"I couldn't find a walking route to {place.name}.")
    encoded = (route.get("polyline") or {}).get("encodedPolyline")
    path = geo.decode_polyline(encoded) if encoded else [p for s in steps for p in s.path]
    duration = str(route.get("duration", "0s")).rstrip("s") or "0"
    return Route(
        destination=place,
        steps=steps,
        distance_m=float(route.get("distanceMeters", sum(s.distance_m for s in steps))),
        duration_s=float(duration),
        path=path,
    )


# Offline stand-in ------------------------------------------------------------

class FakeMaps:
    """Invents a destination ~300 m away with two turns. For demos without a key."""

    def find_place(self, query: str, near: Optional[Point], nearest: bool = False) -> Place:
        if near is None:
            raise MapsError("I don't know where you are yet.")
        return Place(
            name=query.strip().title() or "Destination",
            address="Demo destination (no Google Maps key set)",
            location=geo.offset(near, 160, 120),
        )

    def walking_route(self, origin: Point, place: Place) -> Route:
        north = geo.haversine_m(origin, (place.location[0], origin[1]))
        corner1 = geo.offset(origin, north * 0.6, 0)
        corner2 = (corner1[0], place.location[1])
        legs = [
            ("Head north on Demo Street", "DEPART", origin, corner1),
            ("Turn right onto Example Avenue", "TURN_RIGHT", corner1, corner2),
            ("Turn left onto Sample Lane. Destination will be on the right", "TURN_LEFT", corner2, place.location),
        ]
        steps = [
            Step(text, man, a, b, geo.haversine_m(a, b), [a, b]) for text, man, a, b in legs
        ]
        path = [origin, corner1, corner2, place.location]
        dist = geo.path_length_m(path)
        return Route(place, steps, dist, dist / 1.3, path)

    def reverse_geocode(self, point: Point) -> Optional[str]:
        return None


def _default_provider() -> MapsProvider:
    key = api_key()
    if key:
        return GoogleMaps(key)
    log.warning("no Google Maps key: using FakeMaps demo routes")
    return FakeMaps()


_provider: Optional[MapsProvider] = None


def get_provider() -> MapsProvider:
    global _provider
    if _provider is None:
        _provider = _default_provider()
    return _provider


def set_provider(provider: Optional[MapsProvider]) -> None:
    global _provider
    _provider = provider


def using_fake() -> bool:
    return isinstance(get_provider(), FakeMaps)
