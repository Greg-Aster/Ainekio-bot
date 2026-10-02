from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from gateway.dashboard.auth import AuditLog
from gateway.server.__main__ import _audit_fields
from gateway.environment_adapter import EnvironmentAdapter, EnvironmentAdapterConfig
from gateway.server.service import ActionExpiredError, GatewayConnection, GatewayError, GatewayService, GatewayServiceConfig
from protocol.control_v1 import ProtocolValidationError, validate_control_message
from Emulator.tests.test_environment_adapter import FakeGateway


class Socket:
    closed = False

    def __init__(self) -> None:
        self.messages: list[dict[str, object]] = []

    async def send(self, raw: str) -> None:
        self.messages.append(json.loads(raw))


class P4FoundationTests(unittest.IsolatedAsyncioTestCase):
    def connection(self, *, features: tuple[str, ...] = ()) -> tuple[GatewayConnection, Socket, list[float]]:
        clock = [100.0]
        service = GatewayService(GatewayServiceConfig(tokens={"p4": "test"}, max_action_age_ms=500), clock=lambda: clock[0])
        socket = Socket()
        return GatewayConnection(service, socket, "p4", 7, features), socket, clock

    async def test_legacy_wire_remains_unchanged(self) -> None:
        connection, socket, _ = self.connection()
        await connection.send_command({"t": "mode", "name": "calibrate"}, received_at=100.0)
        self.assertEqual(socket.messages, [{"t": "mode", "name": "calibrate", "seq": 1}])

    async def test_deadline_keeps_upstream_expiry_and_consumes_no_sequence_on_missing_clock(self) -> None:
        connection, socket, clock = self.connection(features=("command_deadline_v1",))
        with self.assertRaises(ActionExpiredError):
            await connection.send_command({"t": "mode", "name": "calibrate"}, received_at=100.0)
        self.assertEqual(connection.next_sequence, 1)
        connection.observe_body_clock({"clock_ms": 20000})
        clock[0] += 0.25
        sequence = await connection.send_command({"t": "mode", "name": "calibrate"}, received_at=100.0)
        self.assertEqual(sequence, 1)
        self.assertEqual(socket.messages[0]["epoch"], 7)
        self.assertEqual(socket.messages[0]["deadline_ms"], 20495)
        # Old samples are not silently extended by moving the host's clock.
        clock[0] += 1
        with self.assertRaises(ActionExpiredError):
            await connection.send_command({"t": "mode", "name": "normal"}, received_at=clock[0])
        self.assertEqual(connection.next_sequence, 2)
        await connection.send_command({"t": "stop", "detach": True}, received_at=clock[0])
        self.assertNotIn("deadline_ms", socket.messages[-1])
        self.assertEqual(socket.messages[-1]["epoch"], 7)

    async def test_cached_body_clock_does_not_expire_a_fresh_command(self) -> None:
        connection, socket, clock = self.connection(features=("command_deadline_v1",))
        connection.observe_body_clock({"clock_ms": 20000})
        clock[0] += 0.75
        await connection.send_command({"t": "mode", "name": "calibrate"}, received_at=clock[0])
        body_now_ms = 20750  # Both monotonic clocks advance; transport latency is zero.
        deadline_ms = socket.messages[0]["deadline_ms"]
        self.assertGreater(deadline_ms, body_now_ms)
        self.assertLessEqual(deadline_ms, body_now_ms + 500 - 5)

    async def test_delayed_clock_sample_does_not_extend_upstream_validity(self) -> None:
        connection, socket, clock = self.connection(features=("command_deadline_v1",))
        connection.observe_body_clock({"clock_ms": 20000})
        # The observed timestamp took 100 ms to reach the gateway. The gateway
        # cannot know that delay and must not invent compensation for it.
        clock[0] += 0.25
        await connection.send_command({"t": "mode", "name": "calibrate"}, received_at=100.0)
        body_now_ms = 20350
        upstream_expiry_ms = 20600
        deadline_ms = socket.messages[0]["deadline_ms"]
        self.assertGreater(deadline_ms, body_now_ms)
        self.assertLessEqual(deadline_ms, upstream_expiry_ms - 5)

    async def test_clock_gap_dispatch_failure_and_robot_rejection_are_saved(self) -> None:
        connection, socket, clock = self.connection(features=("command_deadline_v1",))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "operations.jsonl"
            audit = AuditLog(path)
            connection.service.subscribe_diagnostics(
                lambda row: audit.record(str(row["event"]), **_audit_fields(row)))
            connection.observe_body_clock({"clock_ms": 20000})
            clock[0] += 1.25
            with self.assertRaisesRegex(ActionExpiredError, "fresh body clock"):
                await connection.send_command({"t": "mode", "name": "calibrate"}, received_at=clock[0])
            self.assertEqual(socket.messages, [])
            self.assertEqual(connection.next_sequence, 1)
            connection.observe_body_clock({"clock_ms": 21250})
            sequence = await connection.send_command({"t": "mode", "name": "calibrate"}, received_at=clock[0])
            await connection._handle_control({"t": "nak", "seq": sequence, "code": "busy",
                "msg": "Servo controller I2C transfer missed its deadline",
                "output_timing": {"last_io_us": 6000, "max_io_us": 6000, "transfers": 2, "failures": 0}})
            rows = [json.loads(line) for line in path.read_text().splitlines()]
            self.assertEqual([row["event"] for row in rows],
                             ["dispatch_rejected", "body_clock_gap", "command_result"])
            self.assertEqual(rows[0]["clock_age_ms"], 1250)
            self.assertEqual(rows[1]["clock_gap_ms"], 1250)
            self.assertEqual(rows[1]["clock_advance_ms"], 1250)
            self.assertEqual(rows[2]["epoch"], 7)
            self.assertEqual(rows[2]["seq"], sequence)
            self.assertEqual(rows[2]["t"], "nak")
            self.assertEqual(rows[2]["output_timing"]["last_io_us"], 6000)
            self.assertEqual(rows[2]["msg"], "Servo controller I2C transfer missed its deadline")

    def test_diagnostic_audit_keeps_motion_context_without_pairing_credentials(self) -> None:
        fields = _audit_fields({"robot_token": "robot-secret", "wifi_password": "wifi-secret",
            "setup_password": "setup-secret", "auth": "hello-secret", "t": "nak", "msg": "deadline",
            "speed": 150, "gait": "walk", "output_timing": {"max_io_us": 6000}})
        self.assertEqual(fields, {"t": "nak", "msg": "deadline", "speed": 150,
                                 "gait": "walk", "output_timing": {"max_io_us": 6000}})

    def test_bringup_body_does_not_advertise_motion_or_speech(self) -> None:
        class P4Gateway(FakeGateway):
            def status(self) -> dict[str, object]:
                result = super().status()
                robot = result["robots"]["test-body"]
                robot["features"] = ["body_capabilities_v1"]
                robot["capabilities"] = dict.fromkeys(("motion", "camera", "microphone", "speaker"), False)
                robot["status"] = None
                return result

        adapter = EnvironmentAdapter(P4Gateway(), EnvironmentAdapterConfig(receipt_path=":memory:", token="test"))
        observation = adapter._observation()
        self.assertFalse(observation["capabilities"]["movement"])
        self.assertEqual(observation["capabilities"]["robotCommands"], [])
        self.assertFalse(observation["state"]["body"]["speakerReady"])
        self.assertNotIn("robotMotionPlan", observation["capabilities"]["actions"])

    def test_handshake_validation(self) -> None:
        hello = {"t": "hello", "ver": 1, "fw": "test", "id": "p4", "auth": "test", "features": ["command_deadline_v1"]}
        with self.assertRaises(ProtocolValidationError):
            validate_control_message(hello)
        hello["clock_ms"] = 0
        validate_control_message(hello)
        hello["features"].append("body_capabilities_v1")
        with self.assertRaises(ProtocolValidationError):
            validate_control_message(hello)
