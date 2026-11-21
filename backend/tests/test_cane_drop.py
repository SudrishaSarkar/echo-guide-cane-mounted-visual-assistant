"""Tests for the cane-drop check-in. A fake clock drives time; no hardware needed.

Vectors are accelerometer readings in g with the cane's long axis = z:
upright and still = (0, 0, 1), lying flat and still = (1, 0, 0).
"""
from __future__ import annotations

import unittest
from unittest import mock

from app import cane_drop, events, hooks
from app.cane_drop import ALERTED, IDLE, PROMPTING, WATCHING, CaneDropDetector, DropConfig
from app.db import Database, get_db, set_db

UPRIGHT = (0.0, 0.0, 1.0)
LYING = (1.0, 0.0, 0.0)
FIND = {"cmd": "beep", "pattern": "find"}
STOP = {"cmd": "buzz", "ms": 0}


class FakeClock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


class DropTestCase(unittest.TestCase):
    def setUp(self) -> None:
        set_db(Database(":memory:"))
        events.reset()
        self.patches = [
            mock.patch.object(events, "SOS_UNSEEN_WARN_S", 0.01),
            mock.patch.object(events, "location_provider", lambda: None),
            mock.patch.object(hooks, "say"),
            mock.patch.object(hooks, "chime"),
            mock.patch.object(hooks, "send_cmd"),
            mock.patch.object(hooks, "update_state"),
            mock.patch.object(hooks, "call", return_value=None),
        ]
        mocks = [p.start() for p in self.patches]
        self.say, _, self.send_cmd, self.update_state, _ = mocks[2:]
        self.clock = FakeClock()
        self.d = CaneDropDetector(DropConfig(), clock=self.clock)

    def tearDown(self) -> None:
        events.reset()
        self.assertTrue(events.drain(5))
        for p in reversed(self.patches):
            p.stop()
        set_db(None)

    # helpers

    def frame(self, vec: tuple, dt: float = 0.05) -> None:
        self.clock.t += dt
        self.d.on_frame({"ax": vec[0], "ay": vec[1], "az": vec[2]})

    def hold(self, vec: tuple, seconds: float, step: float = 0.5) -> None:
        """Feed the same reading (perfectly still) for `seconds`."""
        for _ in range(round(seconds / step)):
            self.frame(vec, step)

    def jiggle(self, base: tuple, seconds: float, step: float = 0.5) -> None:
        """Feed readings that jump around (cane moving) for `seconds`."""
        for i in range(round(seconds / step)):
            offset = 0.4 if i % 2 else -0.4
            self.frame((base[0] + offset, base[1], base[2] - offset / 2), step)

    def drop(self) -> None:
        """Impact, a moment of falling, then lying still long enough to prompt."""
        self.hold(UPRIGHT, 1)
        self.d.on_impact()
        self.jiggle((0.7, 0.0, 0.7), 1)
        self.hold(LYING, 11.5)

    def advance(self, seconds: float) -> None:
        self.clock.t += seconds
        self.d.tick()

    def spoken(self) -> list[str]:
        return [c.args[0] for c in self.say.call_args_list]

    def types(self) -> list[str]:
        return [e["type"] for e in get_db().list_events()]


class DetectionTests(DropTestCase):
    def test_cane_tapping_while_walking_is_ignored(self) -> None:
        for _ in range(10):
            self.d.on_impact()
            self.jiggle(UPRIGHT, 1)
        self.hold(UPRIGHT, 15)
        self.assertEqual(self.d.state, IDLE)
        self.assertEqual(self.spoken(), [])

    def test_drop_prompts_user_and_beeps(self) -> None:
        self.drop()
        self.assertEqual(self.d.state, PROMPTING)
        self.assertEqual(self.spoken(), [cane_drop.PROMPT])
        self.send_cmd.assert_any_call(FIND)
        self.update_state.assert_any_call(cane_drop_prompt=True)
        self.assertEqual(self.types(), [])  # nothing for the caregiver yet

    def test_needs_full_ten_seconds_still(self) -> None:
        self.hold(UPRIGHT, 1)
        self.d.on_impact()
        self.hold(LYING, 9)
        self.assertEqual(self.d.state, WATCHING)
        self.hold(LYING, 2)
        self.assertEqual(self.d.state, PROMPTING)

    def test_movement_restarts_the_still_timer(self) -> None:
        self.d.on_impact()
        self.hold(LYING, 8)
        self.jiggle(LYING, 1)  # being dragged or rolling
        self.hold(LYING, 8)
        self.assertEqual(self.d.state, WATCHING)
        self.hold(LYING, 3)
        self.assertEqual(self.d.state, PROMPTING)

    def test_laying_cane_down_gently_does_not_prompt(self) -> None:
        self.hold(UPRIGHT, 1)
        self.hold(LYING, 30)  # no impact first
        self.assertEqual(self.d.state, IDLE)

    def test_upright_and_still_after_impact_does_not_prompt(self) -> None:
        self.d.on_impact()
        self.hold(UPRIGHT, 15)  # e.g. leaning against a wall
        self.assertEqual(self.d.state, IDLE)

    def test_gives_up_if_it_never_settles(self) -> None:
        self.d.on_impact()
        self.jiggle(LYING, 31)
        self.assertEqual(self.d.state, IDLE)

    def test_cane_axis_setting(self) -> None:
        self.d = CaneDropDetector(DropConfig(cane_axis="x"), clock=self.clock)
        self.d.on_impact()
        self.hold((1.0, 0.0, 0.0), 12)  # along x = upright for this mounting
        self.assertEqual(self.d.state, IDLE)
        self.d.on_impact()
        self.hold((0.0, 0.0, 1.0), 12)  # across x = lying
        self.assertEqual(self.d.state, PROMPTING)

    def test_bad_frames_are_ignored(self) -> None:
        self.d.on_impact()
        for bad in ({}, {"ax": "x", "ay": 0, "az": 1}, {"ax": None, "ay": 0, "az": 1}):
            self.d.on_frame(bad)
        self.assertEqual(self.d.state, WATCHING)

    def test_disabled(self) -> None:
        self.d = CaneDropDetector(DropConfig(enabled=False), clock=self.clock)
        self.d.on_impact()
        self.hold(LYING, 12)
        self.assertEqual(self.d.state, IDLE)

    def test_tilt(self) -> None:
        self.assertAlmostEqual(cane_drop.tilt_deg(UPRIGHT, "z"), 0.0)
        self.assertAlmostEqual(cane_drop.tilt_deg(LYING, "z"), 90.0)
        self.assertAlmostEqual(cane_drop.tilt_deg((0.0, 0.0, -1.0), "z"), 0.0)  # mounted upside down
        self.assertIsNone(cane_drop.tilt_deg((0.0, 0.1, 0.0), "z"))  # free fall


class ResponseTests(DropTestCase):
    def test_tap_ok(self) -> None:
        self.drop()
        self.assertTrue(self.d.respond_ok("touch"))
        self.assertEqual(self.d.state, IDLE)
        self.send_cmd.assert_any_call(STOP)
        self.update_state.assert_any_call(cane_drop_prompt=False)
        self.assertEqual(self.spoken()[-1], cane_drop.OK_REPLY)
        ok = get_db().list_events()[0]
        self.assertEqual((ok["type"], ok["notify_status"]), ("DROP_OK", "not_sent"))

    def test_hold_for_help_triggers_sos(self) -> None:
        self.drop()
        self.assertTrue(self.d.respond_help("touch"))
        self.assertEqual(self.d.state, IDLE)
        self.assertEqual(self.types(), ["SOS", "DROP_HELP"])
        sos = get_db().list_events()[0]
        self.assertEqual(sos["payload"]["source"], "cane_drop")
        self.assertEqual(sos["notify_status"], "pending")
        self.assertEqual(get_db().list_events()[1]["notify_status"], "not_sent")  # no double ALERT

    def test_picking_cane_up_dismisses_prompt(self) -> None:
        self.drop()
        self.hold(UPRIGHT, 1)
        self.assertEqual(self.d.state, IDLE)
        self.assertEqual(self.types(), ["DROP_OK"])
        self.assertEqual(get_db().list_events()[0]["payload"], {"source": "picked_up"})
        self.assertNotIn(cane_drop.OK_REPLY, self.spoken())

    def test_respond_when_nothing_to_answer(self) -> None:
        self.assertFalse(self.d.respond_ok("touch"))
        self.assertFalse(self.d.respond_help("touch"))
        self.assertEqual(self.types(), [])


class AlertTests(DropTestCase):
    def test_reprompts_then_alerts_caregiver(self) -> None:
        self.drop()
        self.advance(15)
        self.assertEqual(self.spoken(), [cane_drop.PROMPT, cane_drop.PROMPT])
        self.advance(15)
        self.assertEqual(self.d.state, ALERTED)
        self.assertEqual(self.spoken()[-1], cane_drop.ALERT_SENT)

        alert = get_db().list_events()[0]
        self.assertEqual((alert["type"], alert["notify_status"]), ("CANE_DROP", "pending"))
        self.assertEqual(alert["payload"]["tilt_deg"], 90)
        self.assertGreaterEqual(alert["payload"]["still_s"], 10)
        shown = events.list_events(1)[0]
        self.assertEqual(shown["severity"], "alert")
        self.assertEqual(shown["notification"]["tag"], f"echoguide-drop-{alert['id']}")

    def test_alert_includes_location(self) -> None:
        loc = {"lat": 43.0, "lng": -81.2, "accuracy": 9, "ts": "t"}
        with mock.patch.object(events, "location_provider", lambda: loc):
            self.drop()
            self.advance(31)
        self.assertEqual(get_db().list_events()[0]["payload"]["location"], loc)

    def test_pickup_after_alert_sends_all_clear(self) -> None:
        self.drop()
        self.advance(31)
        drop_id = get_db().list_events()[0]["id"]
        self.hold(UPRIGHT, 1)

        self.assertEqual(self.d.state, IDLE)
        clear = events.list_events(1)[0]
        self.assertEqual(clear["type"], "DROP_OK")
        self.assertEqual(clear["notify_status"], "pending")  # caregiver gets an UPDATE
        self.assertEqual(clear["payload"], {"source": "picked_up", "drop_id": drop_id})
        n = clear["notification"]
        self.assertEqual(n["title"], "UPDATE: Cane drop resolved")
        self.assertTrue(n["body"].startswith("The cane was picked up"))
        self.assertEqual(n["tag"], f"echoguide-drop-{drop_id}")  # replaces the ALERT

    def test_ok_after_alert(self) -> None:
        self.drop()
        self.advance(31)
        self.assertTrue(self.d.respond_ok("touch"))
        self.assertEqual(self.spoken()[-1], cane_drop.OK_AFTER_ALERT)
        clear = events.list_events(1)[0]
        self.assertEqual((clear["type"], clear["notify_status"]), ("DROP_OK", "pending"))
        self.assertIn("answered that they're OK", clear["notification"]["body"])

    def test_help_after_alert(self) -> None:
        self.drop()
        self.advance(31)
        drop_id = get_db().list_events()[0]["id"]
        self.assertTrue(self.d.respond_help("me"))
        help_event = get_db().list_events()[1]
        self.assertEqual(help_event["payload"], {"source": "me", "drop_id": drop_id})
        self.assertTrue(events.sos_open())

    def test_beeping_stops_eventually(self) -> None:
        self.drop()
        self.advance(31)
        self.send_cmd.reset_mock()
        self.advance(119)
        self.send_cmd.assert_not_called()
        self.advance(2)
        self.send_cmd.assert_called_once_with(STOP)
        self.assertEqual(self.d.state, ALERTED)  # still waiting for pickup/answer

    def test_timeouts_fire_without_frames(self) -> None:
        self.drop()
        self.advance(31)  # tick() only, no frames: e.g. Arduino unplugged
        self.assertEqual(self.d.state, ALERTED)


class ModuleWiringTests(DropTestCase):
    def test_module_functions_and_actions(self) -> None:
        cane_drop.set_detector(self.d)
        self.addCleanup(cane_drop.set_detector, None)
        self.drop()
        self.assertTrue(cane_drop.prompt_active())
        cane_drop.ACTIONS["DROP_OK"]()
        self.assertFalse(cane_drop.prompt_active())

    def test_config_from_settings(self) -> None:
        values = {"cane_axis": "-Y", "cane_drop_inactivity_s": 4, "cane_drop_enabled": True}
        with mock.patch.object(hooks, "setting", side_effect=lambda k, d=None: values.get(k, d)):
            cfg = DropConfig.from_settings()
        self.assertEqual((cfg.cane_axis, cfg.still_required_s, cfg.enabled), ("y", 4.0, True))

    def test_register_subscribes(self) -> None:
        with mock.patch.object(hooks, "call") as call:
            cane_drop.register(tick_interval_s=60)
        self.addCleanup(cane_drop.stop)
        call.assert_any_call("state", "on_event", "impact", cane_drop.on_impact)
        call.assert_any_call("state", "on_frame", cane_drop.on_frame)


if __name__ == "__main__":
    unittest.main()
