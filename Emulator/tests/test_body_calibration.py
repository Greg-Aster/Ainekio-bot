"""Operator calibration transport tests; hardware persistence is verified on-device."""
from __future__ import annotations

import asyncio
import copy
import unittest

from gateway.server.service import GatewayConnection, GatewayError, GatewayService, GatewayServiceConfig
from protocol.control_v1 import ProtocolValidationError, validate_control_message
from Emulator.tests.test_p4_foundation import Socket


def calibration_status(sequence: int, *, dirty: bool = False, saved: bool = True) -> dict[str, object]:
    return {"t": "calibration_status", "seq": sequence, "dirty": dirty, "saved": saved,
            "ready": True, "joints": [{"id": index, "channel": index,
                "home_us": 1500, "invert": False, "pulse_us": 1500}
                for index in range(12)]}


class BodyCalibrationTests(unittest.IsolatedAsyncioTestCase):
    def connection(self, *, model: str = "v2-12servo", feature: bool = True):
        gateway = GatewayService(GatewayServiceConfig(tokens={"p4": "test"}), clock=lambda: 1.0)
        socket = Socket()
        connection = GatewayConnection(gateway, socket, "p4", 7,
            ("body_calibration_v2",) if feature else (), model=model,
            capabilities={"motion": False, "camera": False, "speaker": True,
                          "microphone": True, "profile": True, "power": True,
                          "reasons": {"camera": "OV5647 is not connected"}})
        gateway._connections["p4"] = connection
        return connection, socket

    async def test_model_feature_and_payload_validation_precede_sequence_assignment(self):
        for model, feature in (("v1-8servo", True), ("v2-12servo", False), ("unknown", True)):
            connection, socket = self.connection(model=model, feature=feature)
            with self.assertRaises(GatewayError):
                await connection.send_command({"t": "calibration", "op": "get"}, received_at=1)
            self.assertEqual(connection.next_sequence, 1)
            self.assertEqual(socket.messages, [])
        connection, _ = self.connection()
        for fields in ({"id": 12, "pulse_us": 1500}, {"id": 11, "pulse_us": True},
                       {"id": 11, "pulse_us": 0}, {"id": 11, "pulse_us": 65536}):
            with self.assertRaises(ProtocolValidationError):
                await connection.send_command({"t": "calibration", "op": "move", **fields}, received_at=1)
        self.assertEqual(connection.next_sequence, 1)

    async def test_removed_calibration_contract_is_not_accepted(self):
        connection, socket = self.connection()
        connection.features = ("body_calibration_v1",)
        with self.assertRaises(GatewayError):
            await connection.send_command({"t": "calibration", "op": "get"}, received_at=1)
        self.assertEqual(connection.next_sequence, 1)
        self.assertEqual(socket.messages, [])

        connection, socket = self.connection()
        fields = {"id": 7, "channel": 7, "home_us": 1590, "invert": False}
        for field in ("min_us", "max_us"):
            with self.subTest(field=field), self.assertRaisesRegex(GatewayError, "unknown calibration fields"):
                await connection.service.body_calibration("set", {**fields, field: 1500}, robot_id="p4")
        self.assertEqual(connection.next_sequence, 1)
        self.assertEqual(socket.messages, [])

    async def test_ack_is_not_readback_and_unrelated_responses_cannot_complete_it(self):
        connection, socket = self.connection()
        seq = await connection.send_command({"t": "calibration", "op": "move", "id": 11, "pulse_us": 1505}, received_at=1)
        await connection._handle_control(calibration_status(seq))  # out of order
        self.assertIsNone(connection.last_calibration)
        await connection._handle_control({"t": "ack", "seq": seq})
        self.assertIn(seq, connection.pending)
        await connection._handle_control(calibration_status(seq + 1))
        self.assertIn(seq, connection.pending)
        status = calibration_status(seq)
        status["joints"][11]["pulse_us"] = 1505
        await connection._handle_control(status)
        self.assertEqual((await connection.wait_terminal(seq, timeout=0.1))["joints"][11]["pulse_us"], 1505)
        self.assertEqual(connection.service.status()["robots"]["p4"]["calibration"], status)
        self.assertEqual(socket.messages[0]["id"], 11)

    async def test_manual_pulses_round_trip_without_changing_home(self):
        connection, socket = self.connection()
        for pulse in (499, 2501, 3000):
            seq = await connection.send_command({"t": "calibration", "op": "move", "id": 11,
                                                 "pulse_us": pulse}, received_at=1)
            self.assertEqual(socket.messages[-1]["pulse_us"], pulse)
            await connection._handle_control({"t": "ack", "seq": seq})
            status = calibration_status(seq)
            status.update(pulse_min_us=3, pulse_max_us=19986)
            status["joints"][11]["pulse_us"] = pulse
            await connection._handle_control(status)
            actual = await connection.wait_terminal(seq, timeout=0.1)
            self.assertEqual(actual["joints"][11]["pulse_us"], pulse)
            self.assertEqual(actual["joints"][11]["home_us"], 1500)

    async def test_save_reports_only_confirmed_readback_and_nak_preserves_previous_record(self):
        connection, _ = self.connection()
        previous = calibration_status(1, dirty=True, saved=False)
        connection.last_calibration = previous
        task = asyncio.create_task(connection.service.body_calibration("save", robot_id="p4"))
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        sequence = next(iter(connection.pending))
        await connection._handle_control({"t": "nak", "seq": sequence, "code": "unsafe", "msg": "NVS save failed"})
        with self.assertRaisesRegex(GatewayError, "NVS save failed"):
            await task
        self.assertEqual(connection.last_calibration, previous)
        task = asyncio.create_task(connection.service.body_calibration("save", robot_id="p4"))
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        sequence = next(iter(connection.pending))
        await connection._handle_control({"t": "ack", "seq": sequence})
        self.assertFalse(task.done())
        await connection._handle_control(calibration_status(sequence))
        self.assertTrue((await task)["saved"])
        replacement, _ = self.connection()
        self.assertIsNone(replacement.last_calibration)  # reconnect must read the device afresh

    async def test_angle_mapping_is_forwarded_and_returns_device_readback(self):
        connection, socket = self.connection()
        fields = {"id": 7, "channel": 7, "home_us": 1505,
                  "invert": True, "home_cd": -1245, "us_per_degree": 11.111111}
        task = asyncio.create_task(connection.service.body_calibration("set", fields, robot_id="p4"))
        await asyncio.sleep(0)
        self.assertFalse(task.done())
        sequence = socket.messages[-1]["seq"]
        self.assertEqual(socket.messages[-1], {"t": "calibration", "seq": sequence, "op": "set", **fields})
        await connection._handle_control({"t": "ack", "seq": sequence})
        self.assertFalse(task.done())
        status = calibration_status(sequence, dirty=True, saved=False)
        status["joints"][7].update(fields)
        await connection._handle_control(status)
        self.assertEqual((await task)["joints"][7]["home_cd"], -1245)
        self.assertEqual(connection.last_calibration["joints"][7]["us_per_degree"], 11.111111)

    async def test_stop_cancels_pending_readback_and_stale_response_cannot_restore_it(self):
        connection, _ = self.connection()
        seq = await connection.send_command({"t": "calibration", "op": "home"}, received_at=1)
        await connection._handle_control({"t": "ack", "seq": seq})
        stop = await connection.send_command({"t": "stop", "detach": True}, received_at=1)
        await connection._handle_control({"t": "ack", "seq": stop})
        self.assertEqual((await connection.wait_terminal(seq, timeout=0.1))["t"], "cancelled")
        await connection._handle_control(calibration_status(seq))
        self.assertIsNone(connection.last_calibration)

    async def test_capabilities_gate_new_hardware_but_leave_legacy_controls_compatible(self):
        connection, socket = self.connection()
        with self.assertRaisesRegex(GatewayError, "OV5647 is not connected"):
            await connection.send_command({"t": "snap"}, received_at=1)
        with self.assertRaises(GatewayError):
            await connection.send_command({"t": "intent", "name": "face", "expr": "default"}, received_at=1)
        await connection.send_command({"t": "profile", "name": "tether"}, received_at=1)
        self.assertEqual(len(socket.messages), 1)
        legacy, socket = self.connection(model="v1-8servo", feature=False)
        await legacy.send_command({"t": "servo", "id": 7, "deg": 90, "ms": 400}, received_at=1)
        self.assertEqual(socket.messages[0], {"t": "servo", "seq": 1, "id": 7, "deg": 90, "ms": 400})

    def test_status_rejects_bad_joint_arrays_home_channels_and_false_saved_state(self):
        good = calibration_status(1)
        validate_control_message(good)
        mutations = []
        short = copy.deepcopy(good); short["joints"].pop(); mutations.append(short)
        duplicate_id = copy.deepcopy(good); duplicate_id["joints"][11]["id"] = 10; mutations.append(duplicate_id)
        duplicate_channel = copy.deepcopy(good); duplicate_channel["joints"][11]["channel"] = 10; mutations.append(duplicate_channel)
        invalid_home = copy.deepcopy(good); invalid_home["joints"][8]["home_us"] = 0; mutations.append(invalid_home)
        false_saved = copy.deepcopy(good); false_saved["dirty"] = True; mutations.append(false_saved)
        bad_pulse = copy.deepcopy(good); bad_pulse["joints"][6]["pulse_us"] = 65536; mutations.append(bad_pulse)
        for message in mutations:
            with self.subTest(message=message), self.assertRaises(ProtocolValidationError):
                validate_control_message(message)
        good["joints"][8]["channel"] = -1
        good["joints"][11]["channel"] = -1
        good["joints"][11]["pulse_us"] = 0
        validate_control_message(good)

    def test_calibration_wire_bounds_do_not_impose_servo_travel(self):
        request = {"t": "calibration", "seq": 1, "op": "set", "id": 11, "channel": 11,
                   "home_us": 3000, "invert": True}
        validate_control_message(request)
        for pulse in (1, 499, 2501, 3000, 65535):
            validate_control_message({"t": "calibration", "seq": 1, "op": "move", "id": 11, "pulse_us": pulse})
            validate_control_message({**request, "home_us": pulse})
        for field, value in (("home_us", 65536), ("home_us", 0),
                             ("channel", 12), ("invert", 1)):
            with self.subTest(field=field), self.assertRaises(ProtocolValidationError):
                validate_control_message({**request, field: value})
        without_home = {key: value for key, value in request.items() if key != "home_us"}
        with self.assertRaises(ProtocolValidationError):
            validate_control_message(without_home)
        for pulse in (0, 1, 499, 2501, 3000, 65535):
            status = calibration_status(1)
            status["joints"][11]["pulse_us"] = pulse
            validate_control_message(status)

    def test_reported_pwm_bounds_are_optional_paired_and_ordered(self):
        status = calibration_status(1)
        validate_control_message(status)
        for fields in ({"pulse_min_us": 3, "pulse_max_us": 19986},
                       {"pulse_min_us": 1, "pulse_max_us": 65535},
                       {"pulse_min_us": 3, "pulse_max_us": 3}):
            validate_control_message({**status, **fields})
        for fields in ({"pulse_min_us": 3}, {"pulse_max_us": 19986},
                       {"pulse_min_us": 0, "pulse_max_us": 19986},
                       {"pulse_min_us": 3, "pulse_max_us": 65536},
                       {"pulse_min_us": 3000, "pulse_max_us": 2500},
                       {"pulse_min_us": True, "pulse_max_us": 19986},
                       {"pulse_min_us": 3, "pulse_max_us": 19986.5}):
            with self.subTest(fields=fields), self.assertRaises(ProtocolValidationError):
                validate_control_message({**status, **fields})

    async def test_mapping_survives_command_and_device_readback(self):
        connection, socket = self.connection()
        request = {"t": "calibration", "op": "set", "id": 11, "channel": 11,
                   "home_us": 1495, "invert": True,
                   "home_cd": -8352, "us_per_degree": 11.111111}
        sequence = await connection.send_command(request, received_at=1)
        self.assertEqual(socket.messages[0]["home_cd"], -8352)
        self.assertEqual(socket.messages[0]["us_per_degree"], 11.111111)
        await connection._handle_control({"t": "ack", "seq": sequence})
        status = calibration_status(sequence, dirty=True, saved=False)
        for joint in status["joints"]:
            joint.update(home_cd=0, us_per_degree=10.0)
        status["joints"][11].update({k: v for k, v in request.items() if k not in {"t", "op"}})
        await connection._handle_control(status)
        readback = await connection.wait_terminal(sequence, timeout=0.1)
        self.assertEqual(readback["joints"][11]["home_cd"], -8352)
        self.assertTrue(readback["dirty"])

    def test_mapping_pair_is_optional_but_cannot_be_partial_or_nonfinite(self):
        unmapped = {"t": "calibration", "seq": 1, "op": "set", "id": 11, "channel": 11,
                    "home_us": 1500, "invert": False}
        validate_control_message(unmapped)
        mapped = {**unmapped, "home_cd": -36000, "us_per_degree": 100}
        validate_control_message(mapped)
        invalid = [{**unmapped, "home_cd": 0}, {**unmapped, "us_per_degree": 10}]
        for value in (0, -1, 100.01, float("nan"), float("inf"), True):
            invalid.append({**mapped, "us_per_degree": value})
        for value in (-36001, 36001, 0.5, True):
            invalid.append({**mapped, "home_cd": value})
        for message in invalid:
            with self.subTest(message=message), self.assertRaises(ProtocolValidationError):
                validate_control_message(message)
        status = calibration_status(1)
        status["joints"][8]["home_cd"] = 0
        with self.assertRaises(ProtocolValidationError):
            validate_control_message(status)

class ServoProfileReadbackTests(unittest.TestCase):
    def test_recommended_reference_is_separate_from_saved_mapping(self):
        status = calibration_status(1)
        status.update(profile_confirmed=False, servo_profile_id="v2-24-38-servo-centers-20260923",
                      recommended_reference_us=1600,
                      provisional_us_per_degree=2600 / 234, shaft_travel_measured=False)
        for joint in status["joints"]:
            joint["recommended_home_cd"] = (0, 5350, 4300)[joint["id"] % 3]
        validate_control_message(status)
        self.assertEqual(status["joints"][1]["home_us"], 1500)
        self.assertEqual(status["joints"][1]["recommended_home_cd"], 5350)
        for key, value in (("profile_confirmed", "yes"), ("provisional_us_per_degree", 0),
                           ("recommended_reference_us", 65536)):
            invalid = copy.deepcopy(status)
            invalid[key] = value
            with self.assertRaises(ProtocolValidationError):
                validate_control_message(invalid)
