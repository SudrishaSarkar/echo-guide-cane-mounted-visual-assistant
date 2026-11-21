"""Tests for Person 3's SOS/events/db modules.

Run from backend/:
    ..\\.venv\\Scripts\\python -m unittest discover -s tests -t . -v
No hardware, P1 modules or network needed: speech, buzzer and state are faked.
"""
from __future__ import annotations

import unittest
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import events, hooks
from app.db import Database, get_db, set_db

UNSEEN_WARNING = (
    "Your alert hasn't reached a caregiver screen yet. If you can, call for help another way."
)


class EventsTestCase(unittest.TestCase):
    def setUp(self) -> None:
        set_db(Database(":memory:"))
        events.reset()
        self.patches = [
            # Short by default so background work finishes fast; tests that need
            # the warning *not* to fire override it.
            mock.patch.object(events, "SOS_UNSEEN_WARN_S", 0.01),
            mock.patch.object(events, "location_provider", lambda: None),
            mock.patch.object(hooks, "say"),
            mock.patch.object(hooks, "chime"),
            mock.patch.object(hooks, "send_cmd"),
            mock.patch.object(hooks, "update_state"),
            mock.patch.object(hooks, "call", return_value=None),
        ]
        mocks = [p.start() for p in self.patches]
        self.say, self.chime, self.send_cmd, self.update_state, self.hook_call = mocks[2:]

    def tearDown(self) -> None:
        events.reset()
        self.assertTrue(events.drain(5), "background work did not finish")
        for p in reversed(self.patches):
            p.stop()
        set_db(None)

    def spoken(self) -> list[str]:
        return [c.args[0] for c in self.say.call_args_list]

    def finish(self) -> None:
        self.assertTrue(events.drain(5))

    def status(self) -> tuple:
        snap = events.sos_snapshot()
        return snap["sos_active"], snap["sos_status"], snap["sos_notify_status"]


class SosFlowTests(EventsTestCase):
    def test_trigger_is_immediate_and_pending(self) -> None:
        event = events.trigger_sos("touch")

        self.assertEqual(event["type"], "SOS")
        self.assertEqual(event["payload"], {"source": "touch"})
        self.assertEqual(event["notify_status"], "pending")
        self.send_cmd.assert_any_call({"cmd": "beep", "pattern": "sos"})
        self.chime.assert_any_call("sos")
        self.assertEqual(self.spoken()[0], "Sending SOS to your caregiver.")
        self.assertNotIn("Your caregiver has been alerted.", self.spoken())
        self.assertEqual(self.status(), (True, "active", "pending"))
        self.update_state.assert_called()

    def test_caregiver_screen_marks_delivered(self) -> None:
        with mock.patch.object(events, "SOS_UNSEEN_WARN_S", 5):
            sos = events.trigger_sos("touch")
            seen = events.mark_seen(sos["id"], "caregiver")
            self.finish()  # watcher exits as soon as it's seen
        self.assertEqual(seen["notify_status"], "delivered")
        self.assertEqual(get_db().get_event(sos["id"])["notify_status"], "delivered")
        self.assertEqual(self.status(), (True, "delivered", "delivered"))
        self.assertEqual(
            self.spoken(), ["Sending SOS to your caregiver.", "Your caregiver has been alerted."]
        )

    def test_mark_seen_is_idempotent(self) -> None:
        sos = events.trigger_sos("touch")
        events.mark_seen(sos["id"])
        events.mark_seen(sos["id"])
        self.assertEqual(self.spoken().count("Your caregiver has been alerted."), 1)

    def test_warns_when_no_caregiver_screen_sees_it(self) -> None:
        events.trigger_sos("touch")
        self.finish()
        self.assertIn(UNSEEN_WARNING, self.spoken())
        self.assertEqual(self.status(), (True, "active", "pending"))

    def test_no_warning_once_seen(self) -> None:
        with mock.patch.object(events, "SOS_UNSEEN_WARN_S", 0.3):
            sos = events.trigger_sos("touch")
            events.mark_seen(sos["id"])
            self.finish()
        self.assertNotIn(UNSEEN_WARNING, self.spoken())

    def test_second_trigger_while_open_is_ignored(self) -> None:
        first = events.trigger_sos("touch")
        second = events.trigger_sos("me")
        self.assertEqual(first["id"], second["id"])
        self.assertEqual([e["type"] for e in get_db().list_events()], ["SOS"])
        self.assertIn("SOS is already active.", self.spoken())

    def test_location_is_attached(self) -> None:
        loc = {"lat": 43.0096, "lng": -81.2737, "accuracy": 12, "ts": "2026-11-21T10:00:00Z"}
        with mock.patch.object(events, "location_provider", lambda: loc):
            event = events.trigger_sos("me")
        self.assertEqual(event["payload"]["location"], loc)

    def test_broken_location_provider_does_not_block_sos(self) -> None:
        def broken() -> dict:
            raise RuntimeError("gps exploded")

        with mock.patch.object(events, "location_provider", broken), \
                self.assertLogs("echoguide.events", "ERROR"):
            event = events.trigger_sos("me")
        self.assertNotIn("location", event["payload"])
        self.assertEqual(self.status()[1], "active")


class CancelAndAckTests(EventsTestCase):
    def test_cancel_before_seen_withdraws_alert(self) -> None:
        sos = events.trigger_sos("touch")
        cancel = events.cancel_sos("touch")

        self.assertEqual(cancel["payload"], {"source": "touch", "sos_id": sos["id"]})
        self.assertEqual(cancel["notify_status"], "not_sent")
        self.assertEqual(get_db().get_event(sos["id"])["notify_status"], "not_sent")
        self.send_cmd.assert_any_call({"cmd": "buzz", "ms": 0})
        self.assertEqual(self.spoken()[-1], "SOS cancelled.")
        self.assertEqual(self.status(), (False, "cancelled", "not_sent"))

    def test_cancel_after_seen_alerts_false_alarm(self) -> None:
        sos = events.trigger_sos("touch")
        events.mark_seen(sos["id"])
        cancel = events.cancel_sos("touch")

        self.assertEqual(cancel["notify_status"], "pending")  # caregiver must see this too
        self.assertEqual(get_db().get_event(sos["id"])["notify_status"], "delivered")
        self.assertEqual(
            self.spoken()[-1], "SOS cancelled. Your caregiver will see it was a false alarm."
        )
        self.assertEqual(events.mark_seen(cancel["id"])["notify_status"], "delivered")
        self.assertFalse(events.sos_open())

    def test_cancel_stops_unseen_warning(self) -> None:
        with mock.patch.object(events, "SOS_UNSEEN_WARN_S", 0.3):
            events.trigger_sos("touch")
            events.cancel_sos("touch")
            self.finish()
        self.assertNotIn(UNSEEN_WARNING, self.spoken())

    def test_acknowledge(self) -> None:
        sos = events.trigger_sos("touch")
        events.mark_seen(sos["id"])
        ack = events.acknowledge_sos("caregiver")

        self.assertEqual(ack["type"], "SOS_ACKNOWLEDGED")
        self.assertEqual(ack["payload"], {"by": "caregiver", "sos_id": sos["id"]})
        self.assertEqual(ack["notify_status"], "not_sent")
        self.assertEqual(self.spoken()[-1], "Your caregiver has seen your alert.")
        self.assertEqual(self.status(), (False, "acknowledged", "delivered"))
        self.assertIsNone(events.cancel_sos("touch"))  # nothing open any more

    def test_acknowledge_before_seen_counts_as_seen(self) -> None:
        sos = events.trigger_sos("touch")
        events.acknowledge_sos("caregiver")
        self.assertEqual(get_db().get_event(sos["id"])["notify_status"], "delivered")
        self.assertEqual(self.status(), (False, "acknowledged", "delivered"))

    def test_nothing_open(self) -> None:
        self.assertIsNone(events.cancel_sos("touch"))
        self.assertIsNone(events.acknowledge_sos("caregiver"))
        self.assertFalse(events.sos_open())

    def test_new_sos_after_cancel(self) -> None:
        first = events.trigger_sos("touch")
        events.cancel_sos("touch")
        second = events.trigger_sos("touch")
        self.assertNotEqual(first["id"], second["id"])
        self.assertTrue(events.sos_open())


class RecordAndChainTests(EventsTestCase):
    def test_record_with_alert(self) -> None:
        event = events.record("CANE_DROP", {"still_s": 10}, notify=True)
        self.assertEqual(event["notify_status"], "pending")
        seen = events.mark_seen(event["id"])
        self.assertEqual(seen["notify_status"], "delivered")
        self.assertEqual(self.spoken(), [])  # only the SOS gets a spoken confirmation

    def test_record_without_alert(self) -> None:
        event = events.record("FIND_CANE", {"source": "clap"})
        self.assertEqual(event["notify_status"], "not_sent")
        self.assertEqual(events.mark_seen(event["id"])["notify_status"], "not_sent")

    def test_mark_seen_unknown_event(self) -> None:
        self.assertIsNone(events.mark_seen(999))



class SystemNotificationTests(EventsTestCase):
    def setUp(self) -> None:
        super().setUp()
        get_db().set_profile({"name": "Alex"})

    def test_sos_is_an_alert(self) -> None:
        event = events.trigger_sos("touch")
        self.assertEqual(event["severity"], "alert")
        n = event["notification"]
        self.assertEqual(n["title"], "ALERT: SOS from Alex")
        self.assertTrue(n["body"].startswith("Alex asked for help at "))
        self.assertEqual(n["tag"], f"echoguide-sos-{event['id']}")
        self.assertTrue(n["require_interaction"])

    def test_location_mentioned(self) -> None:
        loc = {"lat": 43.0, "lng": -81.2, "accuracy": 5, "ts": "t"}
        with mock.patch.object(events, "location_provider", lambda: loc):
            event = events.trigger_sos("me")
        self.assertTrue(event["notification"]["body"].endswith("Last known location is on the map."))

    def test_cancel_replaces_sos_notification(self) -> None:
        sos = events.trigger_sos("touch")
        events.mark_seen(sos["id"])
        cancel = events.cancel_sos("touch")
        self.assertEqual(cancel["severity"], "update")
        self.assertEqual(cancel["notification"]["title"], "UPDATE: Alex cancelled the SOS")
        self.assertEqual(cancel["notification"]["tag"], sos["notification"]["tag"])
        self.assertFalse(cancel["notification"]["require_interaction"])

    def test_cane_drop_and_no_movement(self) -> None:
        drop = events.record("CANE_DROP", {}, notify=True)
        self.assertEqual(drop["notification"]["title"], "ALERT: Alex's cane may have been dropped")
        still = events.record("NO_MOVEMENT", {"duration": "3 hours"}, notify=True)
        self.assertEqual(still["severity"], "warning")
        self.assertEqual(still["notification"]["title"], "WARNING: No cane movement for 3 hours")

    def test_info_events_have_no_system_notification(self) -> None:
        for kind in ("FIND_CANE", "LOUD_NOISE"):
            event = events.record(kind, {})
            self.assertEqual(event["severity"], "info")
            self.assertIsNone(event["notification"])

    def test_dashboard_state_carries_notifications(self) -> None:
        events.trigger_sos("touch")
        pushed = self.update_state.call_args.kwargs["recent_events"]
        self.assertEqual(pushed[0]["notification"]["title"], "ALERT: SOS from Alex")

    def test_default_name(self) -> None:
        get_db().set_profile({})
        with mock.patch.object(hooks, "setting", return_value="EchoGuide user"):
            event = events.trigger_sos("touch")
        self.assertEqual(event["notification"]["title"], "ALERT: SOS from EchoGuide user")

    def test_local_time_format(self) -> None:
        from app import alerts

        self.assertRegex(alerts.local_time("2026-11-21T19:02:00Z"), r"^\d{1,2}:\d{2} (AM|PM)$")
        self.assertEqual(alerts.local_time("garbage"), "garbage")


class RouteTests(EventsTestCase):
    def setUp(self) -> None:
        super().setUp()
        app = FastAPI()
        app.include_router(events.router)
        self.client = TestClient(app)

    def test_sos_routes(self) -> None:
        self.assertEqual(self.client.get("/api/sos").json()["sos_status"], "idle")
        self.assertEqual(self.client.post("/api/sos/cancel").status_code, 409)

        r = self.client.post("/api/sos", json={"source": "me"})
        self.assertEqual(r.status_code, 200)
        sos_id = r.json()["event"]["id"]
        self.assertEqual(r.json()["event"]["payload"]["source"], "me")
        self.assertTrue(r.json()["sos_active"])
        self.assertEqual(self.client.post("/api/sos").status_code, 200)  # body optional

        r = self.client.post(f"/api/events/{sos_id}/seen", json={"by": "caregiver"})
        self.assertEqual(r.json()["notify_status"], "delivered")
        self.assertEqual(self.client.get("/api/sos").json()["sos_status"], "delivered")
        self.assertEqual(self.client.post("/api/events/999/seen").status_code, 404)

        r = self.client.post("/api/sos/ack", json={"by": "caregiver"})
        self.assertEqual(r.json()["sos_status"], "acknowledged")
        self.assertEqual(self.client.post("/api/sos/ack").status_code, 409)

        types = [e["type"] for e in self.client.get("/api/events").json()]
        self.assertEqual(types, ["SOS_ACKNOWLEDGED", "SOS"])
        self.assertEqual(len(self.client.get("/api/events?limit=1").json()), 1)

    def test_actions_table(self) -> None:
        events.ACTIONS["SOS"]()
        self.assertEqual(events.sos_snapshot()["sos_status"], "active")
        events.ACTIONS["SOS_CANCEL"]()
        self.assertEqual(events.sos_snapshot()["sos_status"], "cancelled")
        events.ACTIONS["SOS"]()
        events.ACTIONS["SOS_ACK"]()
        self.assertEqual(events.sos_snapshot()["sos_status"], "acknowledged")


class DatabaseTests(unittest.TestCase):
    def test_round_trip(self) -> None:
        db = Database(":memory:")
        e = db.add_event("SOS", {"source": "touch"}, "pending")
        self.assertEqual(db.get_event(e["id"]), e)
        db.update_event(e["id"], notify_status="delivered")
        self.assertEqual(db.get_event(e["id"])["notify_status"], "delivered")
        db.add_event("FIND_CANE")
        self.assertEqual([x["type"] for x in db.list_events()], ["FIND_CANE", "SOS"])
        with self.assertRaises(ValueError):
            db.add_event("SOS", notify_status="failed")

    def test_profile(self) -> None:
        db = Database(":memory:")
        self.assertIsNone(db.get_profile())
        db.set_profile({"name": "A"})
        db.set_profile({"name": "B"})
        self.assertEqual(db.get_profile()["data"], {"name": "B"})


if __name__ == "__main__":
    unittest.main()
