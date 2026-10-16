import math
import unittest
from gateway.body_events import BodyEvents, DEFAULTS, validate_settings
from gateway.environment_adapter import EnvironmentAdapter, EnvironmentAdapterConfig
from protocol.control_v1 import validate_control_message
from Emulator.tests.test_environment_adapter import FakeGateway


def sample(at, tilt=0, acceleration=9.80665, rate=0):
    radians = math.radians(tilt)/2
    return {"boot_id": 7, "timestamp_us": at, "age_us": 1000, "available": True,
        "fresh": True, "startup": False, "calibration_applied": True,
        "orientation_wxyz": [math.cos(radians), math.sin(radians), 0, 0],
        "acceleration_m_s2": [0, 0, acceleration], "angular_rate_rad_s": [rate, 0, 0]}


class BodyEventTests(unittest.TestCase):
    def test_tilt_requires_duration_and_rearms_only_after_clearing(self):
        body = BodyEvents()
        self.assertEqual(body.observe("p4", 1, sample(1000, 70)), [])
        self.assertEqual(body.observe("p4", 1, sample(300999, 70)), [])
        events = body.observe("p4", 1, sample(301000, 70))
        self.assertEqual(events[0]["data"]["kind"], "tipped")
        self.assertEqual(events[0]["data"]["imu"]["timestamp_us"], 301000)
        self.assertEqual(body.observe("p4", 1, sample(900000, 70)), [])
        body.observe("p4", 1, sample(1000000, 30))
        body.observe("p4", 1, sample(1100000, 70))
        self.assertEqual(len(body.observe("p4", 1, sample(1400000, 70))), 1)

    def test_rapid_event_does_not_repeat_until_measurements_clear(self):
        body = BodyEvents()
        body.configure("p4", {**DEFAULTS, "rapid_cooldown_s": 0})
        self.assertEqual(body.observe("p4", 1, sample(1)), [])
        event = body.observe("p4", 1, sample(2, rate=4))[0]
        self.assertEqual(event["data"]["kind"], "rapid_movement")
        self.assertEqual(body.observe("p4", 1, sample(3, rate=4)), [])
        body.observe("p4", 1, sample(4))
        self.assertEqual(len(body.observe("p4", 1, sample(5, acceleration=20))), 1)

    def test_rapid_cooldown_drops_crossings_without_extending_or_delaying_them(self):
        now = [0.0]
        body = BodyEvents(clock=lambda: now[0])
        self.assertEqual(len(body.observe("p4", 1, sample(1, rate=4))), 1)
        body.observe("p4", 1, sample(2))
        now[0] = 9.9
        self.assertEqual(body.observe("p4", 1, sample(3, rate=4)), [])
        now[0] = 10.0
        self.assertEqual(body.observe("p4", 1, sample(4, rate=4)), [], "No delayed event on expiry")
        body.observe("p4", 1, sample(5))
        self.assertEqual(len(body.observe("p4", 1, sample(6, rate=4))), 1)
        self.assertEqual(len(body.recent), 2)

    def test_cooldown_is_per_robot_and_survives_settings_and_connection_changes(self):
        now = [100.0]
        body = BodyEvents(clock=lambda: now[0])
        self.assertEqual(len(body.observe("p4", 1, sample(1, rate=4))), 1)
        self.assertEqual(len(body.observe("other", 1, sample(1, rate=4))), 1)
        body.configure("p4", {**DEFAULTS, "rapid_cooldown_s": 2.5})
        now[0] = 102.4
        self.assertEqual(body.observe("p4", 2, sample(1, rate=4)), [])
        body.observe("p4", 2, sample(2))
        now[0] = 102.5
        self.assertEqual(len(body.observe("p4", 2, sample(3, rate=4))), 1)
        body.configure("p4", {**DEFAULTS, "rapid_cooldown_s": 0})
        self.assertEqual(len(body.observe("p4", 2, sample(4, rate=4))), 1)

    def test_cooldown_does_not_delay_tip_or_wake(self):
        body = BodyEvents(clock=lambda: 1.0)
        body.observe("p4", 1, sample(1, rate=4))
        body.observe("p4", 1, sample(1000, 70))
        events = body.observe("p4", 1, sample(301000, 70))
        self.assertEqual([e["data"]["kind"] for e in events], ["tipped"])
        self.assertEqual(body.wake("p4", 1, "boot")["data"]["kind"], "wake")

    def test_legacy_settings_gain_default_cooldown_and_invalid_values_are_rejected(self):
        legacy = {key: value for key, value in DEFAULTS.items() if key != "rapid_cooldown_s"}
        legacy["tip_degrees"] = 70
        self.assertEqual(validate_settings(legacy), {**legacy, "rapid_cooldown_s": 10.0})
        self.assertNotIn("rapid_cooldown_s", legacy)
        for invalid in [-1, float("nan"), float("inf"), True, "10"]:
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                validate_settings({**DEFAULTS, "rapid_cooldown_s": invalid})

    def test_settings_and_robot_identity_are_independent(self):
        body = BodyEvents()
        body.configure("one", {**DEFAULTS, "rapid_enabled": False, "wake_enabled": False})
        self.assertEqual(body.observe("one", 1, sample(1, rate=4)), [])
        self.assertEqual(len(body.observe("two", 1, sample(1, rate=4))), 1)
        self.assertIsNone(body.wake("one", 1, "boot"))
        self.assertEqual(body.wake("two", 1, "boot")["data"]["reason"], "boot")
        with self.assertRaises(ValueError):
            validate_settings({**DEFAULTS, "tip_clear_degrees": 65})
        with self.assertRaises(ValueError):
            validate_settings({**DEFAULTS, "rapid_accel_g": float("nan")})

    def test_stale_or_repeated_samples_do_not_create_events(self):
        body = BodyEvents()
        self.assertEqual(body.observe("p4", 1, {**sample(1, rate=4), "fresh": False}), [])
        body.observe("p4", 1, sample(2))
        self.assertEqual(body.observe("p4", 1, sample(1, rate=4)), [])
        validate_control_message({"t": "event", "name": "imu", "data": sample(1)})

    def test_adapter_preserves_event_measurements(self):
        adapter = EnvironmentAdapter(FakeGateway(), EnvironmentAdapterConfig(token="test", receipt_path=":memory:"))
        event = BodyEvents().observe("p4", 1, sample(1, rate=4))[0]
        observation = adapter._observation(body_event=event)
        self.assertEqual(observation["state"]["bodyEvent"]["data"], event["data"])
        self.assertEqual(observation["state"]["bodyEvent"]["event_id"], event["event_id"])
