from __future__ import annotations

import json
import unittest

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
        self.assertEqual(socket.messages[0]["deadline_ms"], 20245)
        # Old samples are not silently extended by moving the host's clock.
        clock[0] += 1
        with self.assertRaises(ActionExpiredError):
            await connection.send_command({"t": "mode", "name": "normal"}, received_at=clock[0])
        self.assertEqual(connection.next_sequence, 2)
        await connection.send_command({"t": "stop", "detach": True}, received_at=clock[0])
        self.assertNotIn("deadline_ms", socket.messages[-1])
        self.assertEqual(socket.messages[-1]["epoch"], 7)

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
