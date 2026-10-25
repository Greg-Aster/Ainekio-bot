import math
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock
from gateway.body_events import BodyEvents, DEFAULTS, validate_settings
from gateway.server.service import GatewayConnection
from gateway.environment_adapter import EnvironmentAdapter, EnvironmentAdapterConfig
from protocol.control_v1 import validate_control_message
from Emulator.tests.test_environment_adapter import FakeGateway


def sample(at, tilt=0, acceleration=9.80665, rate=0, motion=None):
    radians = math.radians(tilt)/2
    result = {"boot_id": 7, "timestamp_us": at, "age_us": 1000, "available": True,
        "fresh": True, "startup": False, "calibration_applied": True,
        "orientation_wxyz": [math.cos(radians), math.sin(radians), 0, 0],
        "acceleration_m_s2": [0, 0, acceleration], "angular_rate_rad_s": [rate, 0, 0]}
    if motion is not None:
        result["motion"] = motion
    return result


def executing(command="walk", activity="locomotion", phase="motion", tilt=0, started=0):
    angle = math.radians(tilt)
    return {"command": command, "activity": activity, "phase": phase, "sequence": 42,
            "started_us": started, "sampled_us": started,
            "expected_up": [0, math.sin(angle), math.cos(angle)]}


class BodyEventTests(unittest.TestCase):
    def test_event_face_suppresses_shake_and_tip_without_delayed_notifications(self):
        body = BodyEvents()
        body.configure("p4", {**DEFAULTS, "motion_cooldown_s": 0})
        self.assertEqual(len(body.observe("p4", 1, sample(1, rate=4))), 1)
        for at in [2, 400002, 800002]:
            body.observe("p4", 1, {**sample(at), "face_token": "be_reaction"})
            self.assertEqual(body.observe("p4", 1,
                {**sample(at+1, 90, rate=4), "face_token": "be_reaction"}), [])
            self.assertEqual(body.observe("p4", 1,
                {**sample(at+300001, 90, rate=4), "face_token": "be_reaction"}), [])
        # The final shake/tip was already classified while the face was active.
        self.assertEqual(body.observe("p4", 1, {**sample(1200000, 90, rate=4), "face_token": ""}), [])
        body.observe("p4", 1, sample(1200001))
        self.assertEqual(body.observe("p4", 1, sample(1200002, rate=4))[0]["data"]["kind"], "rapid_movement")
        body.observe("p4", 1, sample(1200003, 90))
        self.assertEqual(body.observe("p4", 1, sample(1500003, 90))[0]["data"]["kind"], "tipped")

    def test_unrelated_face_or_replacement_does_not_suppress_events(self):
        for token in ["", "ordinary_face", "thinking", "a"*32]:
            body = BodyEvents()
            body.observe("p4", 1, {**sample(1), "face_token": "be_reaction"})
            self.assertEqual(len(body.observe("p4", 1, {**sample(2, rate=4), "face_token": token})), 1)

    def test_reaction_face_survives_gateway_reconnect_without_a_host_timer(self):
        for epoch in [1, 2]:
            body = BodyEvents()
            self.assertEqual(body.observe("p4", epoch,
                {**sample(1, rate=4), "face_token": "be_reaction"}), [])
            self.assertNotIn("p4", body.last_motion_report)
            body.observe("p4", epoch, {**sample(2), "face_token": ""})
            self.assertEqual(len(body.observe("p4", epoch, sample(3, rate=4))), 1)

    def test_commanded_locomotion_does_not_generate_rapid_reactions(self):
        for command in ["walk", "run", "crawl", "crab"]:
            with self.subTest(command=command):
                body = BodyEvents()
                motion = executing(command)
                self.assertEqual(body.observe("p4", 1, sample(1, rate=4, motion=motion)), [])
                self.assertEqual(body.observe("p4", 1, sample(2, acceleration=20, motion=motion)), [])
                self.assertNotIn("p4", body.last_motion_report)

    def test_walking_still_reports_an_unexpected_fall(self):
        body = BodyEvents()
        motion = executing()
        body.observe("p4", 1, sample(1, 90, rate=4, motion=motion))
        events = body.observe("p4", 1, sample(300001, 90, rate=4, motion=motion))
        self.assertEqual([e["data"]["kind"] for e in events], ["tipped"])
        self.assertEqual(events[0]["data"]["motion"]["sequence"], 42)

    def test_commanded_poses_clips_and_freestyle_do_not_generate_rapid_reactions(self):
        for command, activity in [("stand", "pose"), ("neutral", "pose"),
                                  ("wave", "clip"), ("motion_plan", "freestyle"),
                                  ("manual", "manual")]:
            for phase in ("entry", "motion", "replanning"):
                with self.subTest(command=command, phase=phase):
                    body = BodyEvents()
                    motion = executing(command, activity, phase)
                    self.assertEqual(body.observe("p4", 1, sample(1, rate=4, motion=motion)), [])
                    body.observe("p4", 1, sample(2, motion=motion))
                    self.assertEqual(body.observe("p4", 1, sample(3, acceleration=20, motion=motion)), [])
                    self.assertNotIn("p4", body.last_motion_report)
                    body.observe("p4", 1, sample(4, 90, motion=motion))
                    events = body.observe("p4", 1, sample(300004, 90, motion=motion))
                    self.assertEqual([e["data"]["kind"] for e in events], ["tipped"])

    def test_recorded_stand_entry_does_not_trigger_recovery(self):
        body = BodyEvents()
        # 2026-10-23 Stand sequence 12: normal entry was falsely reported at
        # 0.793 g acceleration change with only 5.14 degrees of unexpected tilt.
        motion = executing("stand", "pose", "entry", started=1558520678)
        motion.update(sequence=12, sampled_us=1558562982)
        imu = sample(1558571303, 5.141701611995355, motion=motion)
        imu.update(acceleration_m_s2=[0.0478564538, -1.33998072, 1.52662086],
                   angular_rate_rad_s=[0.117057055, 0.0125752315, -0.247724935])
        self.assertEqual(body.observe("p4", 2, imu), [])
        # Do not defer that crossing until completion. A later distinct
        # disturbance while holding still must continue to be reported.
        motion = {**motion, "phase":"hold"}
        self.assertEqual(body.observe("p4", 2, {**imu, "timestamp_us":1558571304, "motion":motion}), [])
        body.observe("p4", 2, sample(1558571305, motion=motion))
        events = body.observe("p4", 2, sample(1558571306, rate=4, motion=motion))
        self.assertEqual([e["data"]["kind"] for e in events], ["rapid_movement"])

    def test_intentional_tilt_and_held_posture_use_the_authored_reference(self):
        body = BodyEvents()
        for at, phase in [(1, "motion"), (400001, "motion"), (500001, "hold"), (900001, "hold")]:
            self.assertEqual(body.observe("p4", 1, sample(at, 70,
                motion=executing("upright", "clip", phase, tilt=70))), [])
        held = executing("upright", "clip", "hold", tilt=70)
        body.observe("p4", 1, sample(1000001, -70, motion=held))
        event = body.observe("p4", 1, sample(1300001, -70, motion=held))[0]
        self.assertAlmostEqual(event["data"]["tilt_degrees"], 70)
        self.assertAlmostEqual(event["data"]["unexpected_tilt_degrees"], 140)
        self.assertEqual(event["data"]["motion"], held)

    def test_commanded_crossing_is_not_delayed_until_walk_finishes(self):
        body = BodyEvents()
        self.assertEqual(body.observe("p4", 1, sample(1, rate=4, motion=executing())), [])
        hold = executing("stand", "pose", "hold")
        self.assertEqual(body.observe("p4", 1, sample(2, rate=4, motion=hold)), [])
        body.observe("p4", 1, sample(3, motion=hold))
        self.assertEqual(body.observe("p4", 1, sample(4, rate=4, motion=hold))[0]["data"]["kind"], "rapid_movement")

    def test_future_command_cannot_explain_an_older_measurement(self):
        body = BodyEvents()
        event = body.observe("p4", 1, sample(1, rate=4, motion=executing(started=10)))[0]
        self.assertIsNone(event["data"]["motion"])
        body = BodyEvents()
        body.observe("p4", 1, sample(1, motion=executing()))
        future = executing("stand", "pose", "hold", started=10)
        self.assertEqual(body.observe("p4", 1, sample(2, rate=4, motion=future)), [])
        # A new boot must not reuse the previous boot's motion context.
        event = body.observe("p4", 2, sample(2, rate=4, motion=future))[0]
        self.assertIsNone(event["data"]["motion"])

    def test_manual_or_freestyle_without_body_orientation_retains_tip_detection(self):
        body = BodyEvents()
        motion = {**executing("motion_plan", "freestyle"), "expected_up": None}
        body.observe("p4", 1, sample(1, 90, motion=motion))
        self.assertEqual(body.observe("p4", 1, sample(300001, 90, motion=motion))[0]["data"]["kind"], "tipped")

    def test_unverified_sensor_axes_do_not_masquerade_as_a_matching_body_pose(self):
        body = BodyEvents()
        for at in [1, 300001]:
            events = body.observe("p4", 1, {**sample(at, 70,
                motion=executing("upright", "clip", "hold", tilt=70)), "calibration_applied": False})
        self.assertEqual(events[0]["data"]["kind"], "tipped")

    def test_tilt_requires_duration_and_rearms_only_after_clearing(self):
        body = BodyEvents()
        body.configure("p4", {**DEFAULTS, "motion_cooldown_s": 0})
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
        body.configure("p4", {**DEFAULTS, "motion_cooldown_s": 0})
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
        body.configure("p4", {**DEFAULTS, "motion_cooldown_s": 2.5})
        now[0] = 102.4
        self.assertEqual(body.observe("p4", 2, sample(1, rate=4)), [])
        body.observe("p4", 2, sample(2))
        now[0] = 102.5
        self.assertEqual(len(body.observe("p4", 2, sample(3, rate=4))), 1)
        body.configure("p4", {**DEFAULTS, "motion_cooldown_s": 0})
        self.assertEqual(len(body.observe("p4", 2, sample(4, rate=4))), 1)

    def test_shake_and_tip_share_cooldown_without_delaying_notifications(self):
        now = [0.0]
        body = BodyEvents(clock=lambda: now[0])
        body.observe("p4", 1, sample(1, rate=4))
        body.observe("p4", 1, sample(1000, 70))
        now[0] = 0.5
        events = body.observe("p4", 1, sample(301000, 70))
        self.assertEqual(events, [])
        self.assertEqual(body.wake("p4", 1, "boot")["data"]["kind"], "wake")
        now[0] = 10.0
        self.assertEqual(body.observe("p4", 1, sample(10000000, 70)), [])
        body.observe("p4", 1, sample(10000001))
        body.observe("p4", 1, sample(10000002, 70))
        self.assertEqual(body.observe("p4", 1, sample(10300002, 70))[0]["data"]["kind"], "tipped")
        # The tip now owns the same interval, suppressing another shake.
        now[0] = 19.99
        self.assertEqual(body.observe("p4", 1, sample(10300003, rate=4)), [])
        body.observe("p4", 1, sample(10300004))
        now[0] = 20.0
        self.assertEqual(body.observe("p4", 1, sample(10300005, rate=4))[0]["data"]["kind"], "rapid_movement")
        self.assertEqual([e["data"]["kind"] for e in body.recent],
                         ["rapid_movement", "wake", "tipped", "rapid_movement"])

    def test_simultaneous_crossings_emit_one_notification_with_shared_cooldown(self):
        for interval, expected in [(10, ["tipped"]), (0, ["tipped", "rapid_movement"])]:
            body = BodyEvents(clock=lambda: 0.0)
            body.configure("p4", {**DEFAULTS, "motion_cooldown_s": interval})
            body.observe("p4", 1, sample(1, 70))
            events = body.observe("p4", 1, sample(300001, 70, rate=4))
            self.assertEqual([e["data"]["kind"] for e in events], expected)
            self.assertEqual(list(body.recent), events)

    def test_repeated_tip_crossings_also_obey_cooldown(self):
        now = [0.0]
        body = BodyEvents(clock=lambda: now[0])
        body.observe("p4", 1, sample(1, 70))
        self.assertEqual(len(body.observe("p4", 1, sample(300001, 70))), 1)
        body.observe("p4", 1, sample(300002))
        body.observe("p4", 1, sample(300003, 70))
        now[0] = 9.9
        self.assertEqual(body.observe("p4", 1, sample(600003, 70)), [])
        body.observe("p4", 1, sample(600004))
        body.observe("p4", 1, sample(600005, 70))
        now[0] = 10.0
        self.assertEqual(len(body.observe("p4", 1, sample(900005, 70))), 1)

    def test_legacy_settings_gain_default_cooldown_and_invalid_values_are_rejected(self):
        legacy = {key: value for key, value in DEFAULTS.items() if key != "motion_cooldown_s"}
        legacy["tip_degrees"] = 70
        self.assertEqual(validate_settings(legacy), {**legacy, "motion_cooldown_s": 10.0})
        self.assertNotIn("motion_cooldown_s", legacy)
        rapid_only = {**legacy, "rapid_cooldown_s": 2.5}
        self.assertEqual(validate_settings(rapid_only), {**legacy, "motion_cooldown_s": 2.5})
        self.assertEqual(rapid_only["rapid_cooldown_s"], 2.5)
        for invalid in [-1, float("nan"), float("inf"), True, "10"]:
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                validate_settings({**DEFAULTS, "motion_cooldown_s": invalid})

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


class MotionEventRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_feedback_fault_uses_existing_bridge_without_stopping_motion(self):
        now = [0.0]
        body = BodyEvents(clock=lambda: now[0])
        connection = object.__new__(GatewayConnection)
        connection.robot_id, connection.epoch, connection.last_status = "p4", 17, None
        connection.service = SimpleNamespace(body_events=body, _publish_event=AsyncMock())
        health = {"enabled": True, "usable": False, "scan": 1, "clock_us": 1000,
                  "calibrated_mask": 4095, "unavailable_mask": 0, "clipped_mask": 0,
                  "below_calibration_mask": 4095, "above_calibration_mask": 0,
                  "adc_error": "ESP_OK", "supply_voltage_available": False,
                  "signal_millivolts": [120]*12}
        message = {"t": "event", "name": "servo_feedback", "data": health}
        validate_control_message(message)
        await connection._handle_control(message)
        event = connection.service._publish_event.call_args.args[0]
        self.assertEqual(event["data"]["kind"], "servo_feedback_fault")
        self.assertEqual(len(event["data"]["joints"]), 12)
        self.assertEqual(event["data"]["joints"][0]["signal_millivolts"], 120)
        self.assertFalse(event["data"]["outputs_released"])
        self.assertEqual(event["data"]["motion_policy"], "continue_authored_motion")
        self.assertEqual(connection.last_status["servo_feedback"], health)
        self.assertEqual(body.observe_feedback("p4", 17, {**health, "scan": 2}), [])
        clear = {**health, "scan": 3, "usable": True, "below_calibration_mask": 0}
        restored = body.observe_feedback("p4", 17, clear)
        self.assertEqual(restored[0]["data"]["kind"], "servo_feedback_restored")
        self.assertEqual(body.observe_feedback("p4", 17, {**health, "scan": 4}), [])
        now[0] = DEFAULTS["motion_cooldown_s"]
        self.assertEqual(body.observe_feedback("p4", 17, {**health, "scan": 5}, "be_reaction"), [])
        self.assertEqual(len(body.observe_feedback("p4", 17, {**health, "scan": 6})), 1)
        # A stopped reader can change health without completing another scan.
        body.observe_feedback("p4", 17, {**clear, "scan": 6})
        now[0] += DEFAULTS["motion_cooldown_s"]
        unavailable = {**clear, "scan": 6, "usable": False,
                       "unavailable_mask": 4095, "signal_millivolts": [None]*12}
        self.assertEqual(len(body.observe_feedback("p4", 17, unavailable)), 1)
        self.assertEqual(body.observe_feedback("p4", 17, unavailable), [])
        adapter = EnvironmentAdapter(FakeGateway(), EnvironmentAdapterConfig(token="test", receipt_path=":memory:"))
        adapter._selected_robot = lambda: ("p4", 17)
        adapter._send_observation = AsyncMock()
        await adapter._handle_gateway_event(event)
        self.assertEqual(adapter._send_observation.call_args.kwargs,
            {"body_event": event, "metadata": {"perceptionEvent": "body_event"}})
        validate_control_message({"t": "done", "seq": 7, "position_verified": False})
        receipt = adapter._terminal_feedback("stand", {"t": "done", "seq": 7,
            "position_verified": False}, command="stand", sequence=7, robot_id="p4", epoch=17)
        self.assertEqual(receipt["type"], "completed")
        self.assertFalse(receipt["data"]["position_verified"])

    async def test_stall_uses_the_existing_body_event_bridge_with_joint_identity(self):
        for sequence,released in ((0,True),(941,True),(0,False),(941,False)):
            connection = object.__new__(GatewayConnection)
            connection.robot_id, connection.epoch = "p4", 17
            connection.service = SimpleNamespace(body_events=BodyEvents(), _publish_event=AsyncMock())
            message = {"t": "event", "name": "servo_stall", "event_id": "7:1200000",
                       "clock_us": 1200000, "seq": sequence, "joint_mask": 48, "outputs_released": released}
            validate_control_message(message)
            await connection._handle_control(message)
            event = connection.service._publish_event.call_args.args[0]
            self.assertEqual(event["name"], "body_event")
            self.assertEqual(event["data"]["kind"], "servo_stall")
            self.assertEqual(event["event_id"], "7:1200000")
            self.assertEqual(event["data"]["joints"], [
                {"id": 4, "name": "rear_right_carrier"}, {"id": 5, "name": "rear_right_crank"}])
            self.assertEqual(event["data"]["outputs_released"],released)
            self.assertEqual(event["data"]["command_sequence"], sequence)
            adapter = EnvironmentAdapter(FakeGateway(), EnvironmentAdapterConfig(token="test", receipt_path=":memory:"))
            adapter._selected_robot = lambda: ("p4", 17)
            adapter._send_observation = AsyncMock()
            await adapter._handle_gateway_event(event)
            self.assertEqual(adapter._send_observation.call_args.kwargs,
                {"body_event": event, "metadata": {"perceptionEvent": "body_event"}})

    async def test_reaction_face_does_not_hide_imu_or_generate_more_bridge_events(self):
        connection = object.__new__(GatewayConnection)
        connection.robot_id, connection.epoch, connection.last_status = "p4", 17, None
        connection.service = SimpleNamespace(body_events=BodyEvents(), _publish_event=AsyncMock())
        for at, tilt, rate, token in [(1, 90, 4, "be_reaction"),
                                      (300001, 90, 4, "be_reaction"),
                                      (300002, 0, 0, ""), (300003, 0, 4, "")]:
            message = {"t": "event", "name": "imu", "data": {**sample(at, tilt, rate=rate), "face_token": token}}
            validate_control_message(message)
            await connection._handle_control(message)
        published = [call.args[0] for call in connection.service._publish_event.call_args_list]
        self.assertEqual(sum(e["t"] == "imu" for e in published), 4)
        events = [e for e in published if e.get("name") == "body_event"]
        self.assertEqual([e["data"]["kind"] for e in events], ["rapid_movement"])

    async def test_only_unexpected_events_reach_the_existing_adapter_reaction_path(self):
        connection = object.__new__(GatewayConnection)
        connection.robot_id, connection.epoch, connection.last_status = "p4", 17, None
        connection.service = SimpleNamespace(body_events=BodyEvents(), _publish_event=AsyncMock())
        movement = executing()
        await connection._handle_control({"t": "event", "name": "imu",
                                          "data": sample(1, rate=4, motion=movement)})
        calls = connection.service._publish_event.call_args_list
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].args[0]["t"], "imu")
        await connection._handle_control({"t": "event", "name": "imu",
                                          "data": sample(1000, 90, rate=4, motion=movement)})
        await connection._handle_control({"t": "event", "name": "imu",
                                          "data": sample(301000, 90, rate=4, motion=movement)})
        event = connection.service._publish_event.call_args_list[-1].args[0]
        self.assertEqual(event["data"]["kind"], "tipped")
        adapter = EnvironmentAdapter(FakeGateway(), EnvironmentAdapterConfig(token="test", receipt_path=":memory:"))
        observation = adapter._observation(body_event=event)
        self.assertEqual(observation["state"]["bodyEvent"]["data"]["motion"], movement)
