"""Tests for geo, maps, navigation and the Gemini assistant (no network)."""
from __future__ import annotations

import base64
import json
import unittest
from unittest import mock

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import assistant, care, geo, hooks, maps, navigation
from app.db import Database, set_db

START = (43.0096, -81.2737)


class FakeClock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


class GeoTests(unittest.TestCase):
    def test_decode_polyline(self) -> None:
        pts = geo.decode_polyline("_p~iF~ps|U_ulLnnqC_mqNvxq`@")
        self.assertEqual(pts, [(38.5, -120.2), (40.7, -120.95), (43.252, -126.453)])

    def test_distance_and_bearing(self) -> None:
        north = geo.offset(START, 100, 0)
        self.assertAlmostEqual(geo.haversine_m(START, north), 100, delta=0.5)
        self.assertAlmostEqual(geo.bearing_deg(START, north), 0, delta=0.5)
        east = geo.offset(START, 0, 100)
        self.assertAlmostEqual(geo.bearing_deg(START, east), 90, delta=0.5)

    def test_distance_to_path(self) -> None:
        a, b = START, geo.offset(START, 100, 0)
        p = geo.offset(START, 50, 20)
        self.assertAlmostEqual(geo.distance_to_path_m(p, [a, b]), 20, delta=0.5)

    def test_clock_direction(self) -> None:
        self.assertEqual(geo.clock_direction(0, 0), "12 o'clock")
        self.assertEqual(geo.clock_direction(0, 90), "3 o'clock")
        self.assertEqual(geo.clock_direction(90, 0), "9 o'clock")
        self.assertIsNone(geo.clock_direction(None, 45))

    def test_spoken_distance(self) -> None:
        self.assertEqual(geo.spoken_distance(4), "a few metres")
        self.assertEqual(geo.spoken_distance(43), "45 metres")
        self.assertEqual(geo.spoken_distance(456), "460 metres")
        self.assertEqual(geo.spoken_distance(1000), "1 kilometre")
        self.assertEqual(geo.spoken_distance(2340), "2.3 kilometres")


class GoogleMapsTests(unittest.TestCase):
    def test_find_place_and_route(self) -> None:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            if "places" in str(request.url):
                return httpx.Response(200, json={"places": [{
                    "displayName": {"text": "Demo Pharmacy"},
                    "formattedAddress": "1 King St",
                    "location": {"latitude": 43.01, "longitude": -81.27},
                }]})
            return httpx.Response(200, json={"routes": [{
                "distanceMeters": 250, "duration": "200s",
                "polyline": {"encodedPolyline": "_p~iF~ps|U_ulLnnqC"},
                "legs": [{"steps": [{
                    "distanceMeters": 250,
                    "startLocation": {"latLng": {"latitude": 43.0, "longitude": -81.2}},
                    "endLocation": {"latLng": {"latitude": 43.01, "longitude": -81.27}},
                    "navigationInstruction": {"maneuver": "DEPART", "instructions": "Head north\non King St"},
                }]}],
            }]})

        gm = maps.GoogleMaps("k", httpx.Client(transport=httpx.MockTransport(handler)))
        place = gm.find_place("pharmacy", START, nearest=True)
        self.assertEqual(place.name, "Demo Pharmacy")
        body = json.loads(seen[0].content)
        self.assertEqual(body["rankPreference"], "DISTANCE")
        self.assertEqual(seen[0].headers["X-Goog-Api-Key"], "k")
        route = gm.walking_route(START, place)
        self.assertEqual(json.loads(seen[1].content)["travelMode"], "WALK")
        self.assertEqual(route.duration_s, 200)
        self.assertEqual(route.steps[0].instruction, "Head north. on King St")
        self.assertEqual(len(route.steps[0].path), 2)

    def test_errors_are_speakable(self) -> None:
        gm = maps.GoogleMaps("k", httpx.Client(transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json={}))))
        with self.assertRaises(maps.MapsError):
            gm.find_place("nowhere", START)
        gm = maps.GoogleMaps("k", httpx.Client(transport=httpx.MockTransport(
            lambda r: httpx.Response(403, json={"error": "denied"}))))
        with self.assertRaisesRegex(maps.MapsError, "error"):
            gm.find_place("x", START)


class NavigatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = FakeClock()
        self.said: list[str] = []
        self.snaps: list[dict] = []
        self.fix: dict | None = {"lat": START[0], "lng": START[1], "accuracy": 5, "heading": None}
        self.fake = maps.FakeMaps()
        self.nav = navigation.Navigator(
            provider=lambda: self.fake,
            clock=self.clock,
            say=self.said.append,
            publish=self.snaps.append,
            run_async=lambda fn: fn(),
            location=lambda: self.fix,
        )

    def walk(self, d_m: float, heading: float | None = None, jitter_east: float = 0.0) -> None:
        assert self.nav.route is not None
        p = geo.point_along(self.nav.route.path, d_m)
        p = geo.offset(p, 0, jitter_east)
        self.clock.t += 1
        self.nav.on_location({"lat": p[0], "lng": p[1], "accuracy": 5, "heading": heading})

    def test_needs_location(self) -> None:
        self.fix = None
        with self.assertRaisesRegex(navigation.NavError, "press Start"):
            self.nav.start("pharmacy")

    def test_full_walk_gives_turns_and_arrives(self) -> None:
        text = self.nav.start("pharmacy")
        self.assertIn("Starting directions to Pharmacy", text)
        self.assertIn("Head north on Demo Street", text)
        total = geo.path_length_m(self.nav.route.path)
        d = 0.0
        while self.nav.status == "navigating" and d < total + 20:
            d += 2
            self.walk(d)
        self.assertEqual(self.nav.status, "arrived")
        joined = " | ".join(self.said)
        self.assertIn("In 40 metres, turn right onto Example Avenue", joined)
        self.assertIn("Now, turn right onto Example Avenue", joined)
        self.assertIn("Now, turn left onto Sample Lane", joined)
        self.assertIn("You have arrived near Pharmacy", self.said[-1])
        self.assertEqual(sum("Now, turn right" in s for s in self.said), 1)

    def test_initial_clock_direction_when_facing_wrong_way(self) -> None:
        self.fix = {**self.fix, "heading": 180.0}  # facing south, route goes north
        text = self.nav.start("pharmacy")
        self.assertIn("Turn to face your 6 o'clock", text)

    def test_off_route_reroutes(self) -> None:
        self.nav.start("pharmacy")
        self.walk(20)
        self.walk(20, jitter_east=80)
        self.assertFalse(any("off the route" in s for s in self.said))
        self.walk(20, jitter_east=85)
        self.assertTrue(any("off the route" in s for s in self.said))
        self.assertTrue(self.said[-1].startswith("New route ready"))
        self.assertEqual(self.nav.status, "navigating")

    def test_reassurance_when_quiet(self) -> None:
        self.nav.start("pharmacy")
        n = len(self.said)
        self.clock.t += navigation.REASSURE_S
        self.walk(5)
        self.assertEqual(len(self.said), n + 1)
        self.assertTrue(self.said[-1].startswith("Continue. Turn right onto Example Avenue in"))

    def test_lost_location_warning(self) -> None:
        self.nav.start("pharmacy")
        self.clock.t += navigation.LOST_FIX_S + 1
        self.nav.tick()
        self.nav.tick()
        self.assertEqual(sum("lost your location" in s for s in self.said), 1)

    def test_stop_and_snapshot(self) -> None:
        self.nav.start("pharmacy")
        snap = self.nav.snapshot()
        self.assertEqual(snap["status"], "navigating")
        self.assertEqual(snap["destination"]["name"], "Pharmacy")
        self.assertTrue(snap["path"])
        self.assertGreater(snap["remaining_m"], 200)
        self.nav.stop()
        self.assertEqual(self.said[-1], "Navigation stopped.")
        self.assertEqual(self.nav.snapshot()["status"], "idle")

    def test_too_far(self) -> None:
        class Far(maps.FakeMaps):
            def walking_route(self, origin, place):  # type: ignore[override]
                r = super().walking_route(origin, place)
                r.distance_m = navigation.MAX_ROUTE_M + 1
                return r

        self.fake = Far()
        with self.assertRaisesRegex(navigation.NavError, "too far"):
            self.nav.start("Toronto")
        self.assertEqual(self.nav.status, "error")


class FakeGemini:
    def __init__(self, result: dict) -> None:
        self.result = result
        self.calls: list[tuple] = []

    def understand(self, context, text, audio, mime):  # noqa: ANN001
        self.calls.append((context, text, audio, mime))
        return self.result


class AssistantTests(unittest.TestCase):
    def setUp(self) -> None:
        set_db(Database(":memory:"))
        care.clear_location()
        self.said: list[str] = []
        self.patches = [
            mock.patch.object(hooks, "say", side_effect=self.said.append),
            mock.patch.object(hooks, "update_state"),
            mock.patch.object(hooks, "call", return_value=None),
        ]
        for p in self.patches:
            p.start()
        maps.set_provider(maps.FakeMaps())
        navigation.set_navigator(navigation.Navigator(run_async=lambda fn: fn()))
        assistant.set_client(None)
        app = FastAPI()
        app.include_router(assistant.router)
        app.include_router(navigation.router)
        app.include_router(care.router)
        self.client = TestClient(app)

    def tearDown(self) -> None:
        for p in reversed(self.patches):
            p.stop()
        navigation.set_navigator(None)
        maps.set_provider(None)
        assistant.set_client(None)
        set_db(None)

    def test_fallback_parse(self) -> None:
        r = assistant.fallback_parse("Take me to the nearest pharmacy")
        self.assertEqual((r["intent"], r["destination_query"], r["nearest"]), ("navigate", "pharmacy", True))
        self.assertEqual(assistant.fallback_parse("stop navigation")["intent"], "stop_navigation")
        self.assertEqual(assistant.fallback_parse("Where am I?")["intent"], "where_am_i")
        self.assertEqual(assistant.fallback_parse("how far is it")["intent"], "route_status")
        home = assistant.fallback_parse("take me home")
        self.assertIn("Demo Street", home["destination_query"])

    def test_navigate_by_text_without_gemini(self) -> None:
        self.client.post("/api/location", json={"lat": START[0], "lng": START[1], "accuracy": 5})
        r = self.client.post("/api/assistant", json={"text": "take me to the library"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()["ok"])
        self.assertEqual(r.json()["nav"]["status"], "navigating")
        self.assertIn("Starting directions to Library", self.said[-1])
        # Location updates now drive the navigator through care.location_listeners.
        navigation.register()
        nav = navigation.get_navigator()
        p = geo.point_along(nav.route.path, 10)
        self.client.post("/api/location", json={"lat": p[0], "lng": p[1], "accuracy": 5})
        self.assertLess(nav.snapshot()["remaining_m"], nav.route.distance_m)
        r = self.client.post("/api/assistant", json={"text": "stop navigation"})
        self.assertEqual(self.said[-1], "Navigation stopped.")
        care.location_listeners.clear()

    def test_navigate_without_location_explains(self) -> None:
        r = self.client.post("/api/assistant", json={"text": "take me to the library"})
        self.assertFalse(r.json()["ok"])
        self.assertIn("press Start", self.said[-1])

    def test_audio_goes_to_gemini(self) -> None:
        fake = FakeGemini({"transcript": "how are you", "intent": "chat", "destination_query": "",
                           "nearest": False, "reply": "I'm well, Alex. Where shall we go?"})
        assistant.set_client(fake)
        audio = b"RIFF....WAVEfmt "
        r = self.client.post("/api/assistant", json={
            "audio_b64": base64.b64encode(audio).decode(), "mime_type": "audio/wav"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(fake.calls[0][2], audio)
        self.assertIn("Alex Rivera", fake.calls[0][0])
        self.assertEqual(self.said[-1], "I'm well, Alex. Where shall we go?")

    def test_audio_without_gemini_key(self) -> None:
        r = self.client.post("/api/assistant", json={"audio_b64": base64.b64encode(b"x").decode()})
        self.assertFalse(r.json()["ok"])
        self.assertIn("Gemini API key", self.said[-1])

    def test_bad_requests(self) -> None:
        self.assertEqual(self.client.post("/api/assistant", json={}).status_code, 400)
        self.assertEqual(self.client.post("/api/assistant", json={
            "audio_b64": "!!!", "mime_type": "audio/wav"}).status_code, 400)
        self.assertEqual(self.client.post("/api/assistant", json={
            "audio_b64": "AAAA", "mime_type": "video/mp4"}).status_code, 400)

    def test_gemini_failure_falls_back_for_text(self) -> None:
        class Broken:
            def understand(self, *a):  # noqa: ANN002
                raise RuntimeError("quota")

        assistant.set_client(Broken())
        r = self.client.post("/api/assistant", json={"text": "where am i"})
        self.assertEqual(r.json()["intent"], "where_am_i")


if __name__ == "__main__":
    unittest.main()
