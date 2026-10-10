from __future__ import annotations

import json
import unittest
from pathlib import Path

from gateway.body_capabilities import expression_library
from gateway.environment_adapter import EnvironmentAdapter, EnvironmentAdapterConfig, translate_environment_action
from gateway.environment_adapter.action_receipts import ActionReceipts
from test_environment_adapter import FakeGateway
from protocol.control_v1 import validate_control_message, ProtocolValidationError
from gateway.server.service import GatewayConnection, GatewayService, GatewayServiceConfig, GatewayError


class ExpressionBridgeTests(unittest.IsolatedAsyncioTestCase):
    async def test_timed_display_requires_advertised_firmware_without_sending_motion(self):
        class Socket:
            closed = False
            def __init__(self):
                self.sent = []
            async def send(self, raw):
                self.sent.append(json.loads(raw))
        socket = Socket()
        service = GatewayService(GatewayServiceConfig(tokens={"robot": "fixture"}))
        connection = GatewayConnection(service, socket, "robot", 1, model="v2-12servo", capabilities={"display": True})
        service._connections["robot"] = connection
        with self.assertRaisesRegex(GatewayError, "face_feedback_v1"):
            await service.queue_intent("face", {"expr": "thinking", "token": "turn", "timeout_ms": 5000}, robot_id="robot")
        self.assertEqual(socket.sent, [])
        self.assertEqual(connection.next_sequence, 1)
        connection.features = ("face_feedback_v1",)
        sequence = await service.queue_intent("face", {"expr": "thinking", "token": "turn", "timeout_ms": 5000}, robot_id="robot")
        self.assertEqual(socket.sent, [{"t": "intent", "seq": sequence, "name": "face", "expr": "thinking", "token": "turn", "timeout_ms": 5000}])

    async def test_library_expression_dispatches_only_face_intent(self):
        gateway = FakeGateway()
        adapter = EnvironmentAdapter(gateway, EnvironmentAdapterConfig(token="fixture", receipt_path=":memory:"))
        result = await adapter.handle_action({"id": "face-1", "type": "faceExpression", "expression": "bow"})
        self.assertEqual(result["type"], "completed")
        self.assertEqual(gateway.calls[0][0:1], ("intent",))
        self.assertEqual(gateway.calls[0][1][0:2], ("face", {"expr": "bow"}))
        self.assertEqual([call[0] for call in gateway.calls], ["intent", "wait"])

    def test_catalog_is_the_body_control_catalog_and_not_the_motion_catalog(self):
        robot = {"model": "v2-12servo", "capabilities": {"display": True}}
        catalog = expression_library(robot)
        source = Path(__file__).resolve().parents[2] / "Master/gateway/dashboard/static/faces/catalog.json"
        self.assertEqual([entry["name"] for entry in catalog], [entry["name"] for entry in json.loads(source.read_text())])
        self.assertIn("thinking", [entry["name"] for entry in catalog])
        self.assertEqual(expression_library({"model": "v1-8servo", "capabilities": {"display": True}}), [])
        self.assertEqual(expression_library({"model": "v2-12servo", "capabilities": {"display": False}}), [])

    def test_display_receipt_does_not_replace_movement_ownership(self):
        receipts = ActionReceipts(":memory:")
        motion = {"id": "motion", "type": "robotCommand", "command": "walk",
                  "bodyLease": {"bodyId": "body", "executionId": "motion", "generation": 9}}
        face = {"id": "face", "type": "faceExpression", "expression": "thinking",
                "bodyLease": {"bodyId": "body", "executionId": "face", "generation": 1, "channel": "display"}}
        receipts.receive(motion, {"type": "accepted"})
        receipts.receive(face, {"type": "accepted"})
        receipts.begin(motion["id"], {"sequence": 1})
        receipts.begin(face["id"], {"sequence": 2})
        receipts.db.close()

    def test_translation_uses_the_requested_library_name(self):
        for name in ("thinking", "bow", "happy", "talk_confused"):
            action = translate_environment_action({"type": "faceExpression", "expression": name})
            self.assertEqual((action.kind, action.name, action.params), ("intent", "face", {"expr": name}))

    def test_timed_and_conditional_replacement_protocol(self):
        action = translate_environment_action({"type": "faceExpression", "expression": "thinking",
            "displayToken": "turn1", "displayTimeoutMs": 15000, "displayBackground": True})
        self.assertEqual(action.params, {"expr": "thinking", "token": "turn1", "timeout_ms": 15000, "background": True})
        validate_control_message({"t": "intent", "name": "face", "seq": 1, **action.params})
        off = translate_environment_action({"type": "faceExpression", "displayRelease": True, "displayToken": "turn1"})
        self.assertEqual(off.params, {"release": True, "token": "turn1"})
        validate_control_message({"t": "intent", "name": "face", "seq": 2, **off.params})
        for params in ({"release": True}, {"expr": "thinking", "timeout_ms": -1},
                       {"expr": "thinking", "timeout_ms": True}, {"expr": "thinking", "token": "../file"}):
            with self.assertRaises(ProtocolValidationError):
                validate_control_message({"t": "intent", "name": "face", "seq": 3, **params})


if __name__ == "__main__":
    unittest.main()
