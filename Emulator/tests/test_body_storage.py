"""Storage operator transport, readback and dynamic capability contract."""
from __future__ import annotations

import asyncio
import unittest

from gateway.server.service import GatewayConnection, GatewayError, GatewayService, GatewayServiceConfig
from protocol.control_v1 import ProtocolValidationError, validate_control_message
from Emulator.tests.test_p4_foundation import Socket


def storage_status(seq, mounted=True, busy=False):
    return {"t": "storage_status", "seq": seq, "available": True, "mounted": mounted, "busy": busy,
            "total_bytes": 1048576 if mounted else 0, "free_bytes": 524288 if mounted else 0,
            "dropped_records": 0, "error": "" if mounted else "No SD card"}


def body_status(caps):
    return {"t": "status", "vbat": 0, "rssi": -40, "state": "active", "uptime": 1,
            "heap": 100000, "sd": False, "cam_drops": 0, "mic_drops": 0, "spk_underruns": 0,
            "capabilities": caps}


class BodyStorageTests(unittest.IsolatedAsyncioTestCase):
    def connection(self, *, model="v2-12servo", features=("storage_control_v1", "body_capabilities_v1", "body_commands_v1")):
        service = GatewayService(GatewayServiceConfig(tokens={"p4": "test"}), clock=lambda: 1.0)
        socket = Socket()
        caps = {"motion": False, "camera": False, "speaker": True, "microphone": True,
                "storage": True, "commands": ["stop", "say"]}
        connection = GatewayConnection(service, socket, "p4", 7, features, model=model, capabilities=caps)
        service._connections["p4"] = connection
        return connection, socket

    async def test_storage_is_feature_negotiated_and_ack_is_not_result(self):
        for model, features in (("v1-8servo", ("storage_control_v1",)), ("v2-12servo", ())):
            connection, socket = self.connection(model=model, features=features)
            with self.assertRaises(GatewayError):
                await connection.send_command({"t": "storage", "op": "retry"}, received_at=1)
            self.assertEqual(socket.messages, [])
        connection, _ = self.connection()
        seq = await connection.send_command({"t": "storage", "op": "retry"}, received_at=1)
        await connection._handle_control(storage_status(seq))
        self.assertIsNone(connection.last_storage)
        await connection._handle_control({"t": "ack", "seq": seq})
        self.assertIn(seq, connection.pending)
        await connection._handle_control(storage_status(seq + 1))
        self.assertIsNone(connection.last_storage)
        await connection._handle_control(storage_status(seq))
        self.assertTrue((await connection.wait_terminal(seq, timeout=0.1))["mounted"])
        self.assertTrue(connection.service.status()["robots"]["p4"]["storage"]["mounted"])

    async def test_clear_requires_fresh_mounted_idle_snapshot(self):
        connection, socket = self.connection()
        connection.last_storage = storage_status(99)  # old mounted view is not enough
        task = asyncio.create_task(connection.service.body_storage("clear", robot_id="p4"))
        await asyncio.sleep(0); await asyncio.sleep(0)
        self.assertEqual(socket.messages[-1]["op"], "get")
        seq = socket.messages[-1]["seq"]
        await connection._handle_control({"t": "ack", "seq": seq})
        await connection._handle_control(storage_status(seq, mounted=False))
        with self.assertRaisesRegex(GatewayError, "mounted and idle"):
            await task
        self.assertEqual([m["op"] for m in socket.messages], ["get"])

    async def test_clear_completes_only_after_actual_operation_readback(self):
        connection, socket = self.connection()
        task = asyncio.create_task(connection.service.body_storage("clear", robot_id="p4"))
        await asyncio.sleep(0); await asyncio.sleep(0)
        seq = socket.messages[-1]["seq"]
        await connection._handle_control({"t": "ack", "seq": seq})
        await connection._handle_control(storage_status(seq))
        for _ in range(4):
            await asyncio.sleep(0)
        self.assertEqual(socket.messages[-1]["op"], "clear")
        seq = socket.messages[-1]["seq"]
        await connection._handle_control({"t": "ack", "seq": seq})
        self.assertFalse(task.done())
        result = storage_status(seq); result["free_bytes"] = result["total_bytes"]
        await connection._handle_control(result)
        self.assertEqual((await task)["free_bytes"], 1048576)

    async def test_dynamic_media_capabilities_enable_camera_without_reconnect(self):
        connection, socket = self.connection()
        with self.assertRaises(GatewayError):
            await connection.send_command({"t": "snap"}, received_at=1)
        updated = {**connection.capabilities, "camera": True}
        await connection._handle_control(body_status(updated))
        await connection.send_command({"t": "snap"}, received_at=1)
        self.assertTrue(connection.service.status()["robots"]["p4"]["capabilities"]["camera"])
        # SAY belongs to speaker capability, even when no body motion is enabled.
        await connection.service.queue_intent("say", {"asset": "hello"}, robot_id="p4")
        self.assertEqual(socket.messages[-1]["name"], "say")
        legacy, _ = self.connection(model="v1-8servo", features=())
        await legacy._handle_control(body_status(updated))
        self.assertFalse(legacy.capabilities["camera"])

    def test_storage_status_and_capabilities_are_bounded_and_typed(self):
        validate_control_message(storage_status(1))
        for fields in ({"free_bytes": 1048577}, {"busy": 1}, {"error": "x" * 161}, {"dropped_records": -1}):
            with self.assertRaises(ProtocolValidationError):
                validate_control_message({**storage_status(1), **fields})
        with self.assertRaises(ProtocolValidationError):
            validate_control_message({"t": "storage", "seq": 1, "op": "format"})
        connection, _ = self.connection()
        with self.assertRaises(ProtocolValidationError):
            validate_control_message(body_status({**connection.capabilities, "camera": "ready"}))
