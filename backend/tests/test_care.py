"""Tests for find_cane, activity and care (profile/location)."""
from __future__ import annotations

import time
import unittest
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import activity, care, cane_drop, events, find_cane, hooks
from app.db import Database, get_db, set_db


class BaseCase(unittest.TestCase):
    def setUp(self) -> None:
        set_db(Database(":memory:"))
        events.reset()
        care.clear_location()
        self.patches = [
            mock.patch.object(events, "SOS_UNSEEN_WARN_S", 0.01),
            mock.patch.object(hooks, "say"),
            mock.patch.object(hooks, "chime"),
            mock.patch.object(hooks, "send_cmd"),
            mock.patch.object(hooks, "update_state"),
            mock.patch.object(hooks, "call", return_value=None),
        ]
        mocks = [p.start() for p in self.patches]
        self.say, _, self.send_cmd, self.update_state, self.hook_call = mocks[1:]

    def tearDown(self) -> None:
        events.reset()
        self.assertTrue(events.drain(5))
        for p in reversed(self.patches):
            p.stop()
        set_db(None)

    def types(self) -> list[str]:
        return [e["type"] for e in get_db().list_events()]


class FakeClock:
    def __init__(self, t: float) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


# find_cane ---------------------------------------------------------------------

class FindCaneTests(BaseCase):
    def setUp(self) -> None:
        super().setUp()
        self.clock = FakeClock(100.0)
        self.finder = find_cane.FindCane(clock=self.clock)
        self.addCleanup(self.finder.stop)

    def test_clap_buzzes_then_stops(self) -> None:
        with mock.patch.object(find_cane, "FIND_DURATION_S", 0.05):
            self.finder.find("clap")
            self.send_cmd.assert_called_with({"cmd": "beep", "pattern": "find"})
            self.update_state.assert_any_call(find_cane_active=True)
            self.assertTrue(self.finder.active)
            time.sleep(0.3)
        self.assertFalse(self.finder.active)
        self.send_cmd.assert_called_with({"cmd": "buzz", "ms": 0})
        self.update_state.assert_any_call(find_cane_active=False)
        event = get_db().list_events()[0]
        self.assertEqual((event["type"], event["payload"]), ("FIND_CANE", {"source": "clap"}))

    def test_repeated_requests_record_once(self) -> None:
        self.finder.find("clap")
        self.clock.t += 3
        self.finder.find("app")
        self.assertEqual(self.types(), ["FIND_CANE"])
        self.clock.t += 11
        self.finder.find("app")
        self.assertEqual(self.types(), ["FIND_CANE", "FIND_CANE"])

    def test_does_not_silence_cane_drop_beeps(self) -> None:
        self.finder.find("clap")
        self.send_cmd.reset_mock()
        with mock.patch.object(cane_drop, "prompt_active", return_value=True):
            self.finder.stop()
        self.send_cmd.assert_not_called()

    def test_loud_noise_rate_limited(self) -> None:
        self.finder.on_loud()
        self.clock.t += 30
        self.finder.on_loud()
        self.assertEqual(self.types(), ["LOUD_NOISE"])
        self.clock.t += 31
        self.finder.on_loud()
        self.assertEqual(self.types(), ["LOUD_NOISE", "LOUD_NOISE"])
        self.assertEqual(get_db().list_events()[0]["notify_status"], "not_sent")

    def test_action_and_register(self) -> None:
        find_cane.set_finder(self.finder)
        self.addCleanup(find_cane.set_finder, find_cane.FindCane())
        find_cane.ACTIONS["FIND_CANE"]()
        self.assertEqual(get_db().list_events()[0]["payload"], {"source": "app"})
        find_cane.register()
        self.hook_call.assert_any_call("state", "on_event", "clap", find_cane.on_clap)
        self.hook_call.assert_any_call("state", "on_event", "loud", find_cane.on_loud)


# activity ------------------------------------------------------------------------

NOON = time.mktime((2026, 11, 21, 12, 0, 0, 0, 0, -1))  # local noon
STILL = {"ax": 0.0, "ay": 0.0, "az": 1.0}


class ActivityTests(BaseCase):
    def setUp(self) -> None:
        super().setUp()
        self.clock = FakeClock(NOON)
        self.t = activity.ActivityTracker(no_movement_after_s=120, clock=self.clock)

    def walk(self, seconds: int) -> None:
        for i in range(seconds * 4):
            self.clock.t += 0.25
            self.t.on_frame({"ax": 0.3 if i % 2 else -0.3, "ay": 0.0, "az": 1.0})

    def sit(self, seconds: int, step: float = 1.0) -> None:
        for _ in range(int(seconds / step)):
            self.clock.t += step
            self.t.on_frame(STILL)
            self.t.tick()

    def test_counts_moving_minutes(self) -> None:
        self.walk(150)  # 2.5 minutes of walking
        snap = self.t.snapshot()
        self.assertIn(snap["moving_minutes_last_hour"], (2, 3))
        self.assertEqual(snap["hourly"][-1]["moving_minutes"], snap["moving_minutes_last_hour"])
        self.assertEqual(len(snap["hourly"]), activity.HOURS_SHOWN)
        self.assertIsNotNone(snap["last_motion_ts"])

    def test_sensor_noise_is_not_motion(self) -> None:
        for i in range(400):
            self.clock.t += 0.25
            self.t.on_frame({"ax": 0.047 if i % 2 else 0.0, "ay": 0.0, "az": 1.0})  # sensor jitter
        self.assertEqual(self.t.snapshot()["moving_minutes_last_hour"], 0)

    def test_no_movement_warning_once(self) -> None:
        self.walk(10)
        self.sit(119)
        self.assertEqual(self.types(), [])
        self.sit(5)
        self.assertEqual(self.types(), ["NO_MOVEMENT"])
        shown = events.list_events(1)[0]
        self.assertEqual(shown["notify_status"], "pending")
        self.assertEqual(shown["severity"], "warning")
        self.assertEqual(shown["payload"]["duration"], "2 minutes")
        self.sit(300)
        self.assertEqual(self.types(), ["NO_MOVEMENT"])  # once per still spell

    def test_can_warn_again_after_moving(self) -> None:
        self.sit(130)
        self.walk(5)
        self.sit(130)
        self.assertEqual(self.types(), ["NO_MOVEMENT", "NO_MOVEMENT"])

    def test_unplugged_sensor_does_not_warn(self) -> None:
        self.walk(5)
        self.clock.t += 600  # no frames at all
        self.t.tick()
        self.assertEqual(self.types(), [])

    def test_dead_accelerometer_does_not_warn(self) -> None:
        self.walk(5)
        for _ in range(300):
            self.clock.t += 1
            self.t.on_frame({"ax": 0.0, "ay": 0.0, "az": 0.0})  # firmware: sensor not answering
            self.t.tick()
        self.assertEqual(self.types(), [])

    def test_night_time_does_not_warn(self) -> None:
        self.clock.t = NOON + 11 * 3600  # 11 PM
        self.sit(200)
        self.assertEqual(self.types(), [])

    def test_publishes_activity_state(self) -> None:
        self.walk(5)
        self.t.tick()
        snap = self.update_state.call_args.kwargs["activity"]
        self.assertIn("moving_minutes_last_hour", snap)

    def test_human_duration(self) -> None:
        self.assertEqual(activity.human_duration(45), "45 seconds")
        self.assertEqual(activity.human_duration(125), "2 minutes")
        self.assertEqual(activity.human_duration(3600), "1 hour")
        self.assertEqual(activity.human_duration(3 * 3600 + 50), "3 hours")

    def test_route(self) -> None:
        activity.set_tracker(self.t)
        self.addCleanup(activity.set_tracker, None)
        app = FastAPI()
        app.include_router(activity.router)
        body = TestClient(app).get("/api/activity").json()
        self.assertIn("hourly", body)


# care: profile + location -------------------------------------------------------

class CareTests(BaseCase):
    def setUp(self) -> None:
        super().setUp()
        app = FastAPI()
        app.include_router(care.router)
        app.include_router(events.router)
        self.client = TestClient(app)
        self.addCleanup(setattr, events, "location_provider", events.location_provider)

    def test_profile_seeded_with_demo_data(self) -> None:
        body = self.client.get("/api/profile").json()
        self.assertEqual(body["data"]["name"], "Alex Rivera")
        self.assertTrue(body["updated_at"])
        self.assertEqual(body["data"]["allergies"], ["Penicillin"])

    def test_profile_update(self) -> None:
        profile = self.client.get("/api/profile").json()["data"]
        profile["care_notes"] = "Changed"
        profile["contacts"].append({"name": "Pat", "relation": "Friend", "phone": "555-0199"})
        r = self.client.put("/api/profile", json=profile)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.client.get("/api/profile").json()["data"]["care_notes"], "Changed")
        self.update_state.assert_any_call(profile_updated_at=r.json()["updated_at"])

    def test_profile_validation(self) -> None:
        self.assertEqual(self.client.put("/api/profile", json={"age": 500}).status_code, 422)

    def test_profile_name_used_in_alerts(self) -> None:
        profile = self.client.get("/api/profile").json()["data"]
        profile["name"] = "Robin"
        self.client.put("/api/profile", json=profile)
        sos = events.trigger_sos("me")
        self.assertEqual(sos["notification"]["title"], "ALERT: SOS from Robin")

    def test_location(self) -> None:
        self.assertIsNone(self.client.get("/api/location").json())
        r = self.client.post("/api/location", json={"lat": 43.0096, "lng": -81.2737, "accuracy": 14})
        self.assertEqual(r.status_code, 200)
        fix = self.client.get("/api/location").json()
        self.assertEqual((fix["lat"], fix["lng"], fix["accuracy"]), (43.0096, -81.2737, 14))
        self.assertTrue(fix["ts"].endswith("Z"))
        self.update_state.assert_any_call(location=fix)

    def test_location_validation(self) -> None:
        self.assertEqual(self.client.post("/api/location", json={"lat": 91, "lng": 0}).status_code, 422)

    def test_sos_carries_phone_location(self) -> None:
        care.register()
        care.set_location(43.0, -81.2, 10)
        sos = events.trigger_sos("me")
        self.assertEqual(sos["payload"]["location"]["lat"], 43.0)



if __name__ == "__main__":
    unittest.main()
