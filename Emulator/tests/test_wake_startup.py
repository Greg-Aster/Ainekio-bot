"""Body-owned startup through the existing bridge and camera paths; no hardware."""
import asyncio
import json
import unittest
from unittest.mock import AsyncMock

from gateway.environment_adapter import EnvironmentAdapter, EnvironmentAdapterConfig
from gateway.server.service import GatewayError
from Emulator.tests.test_environment_adapter import SnapshotGateway, FakeWebSocket


class WakeStartupTests(unittest.IsolatedAsyncioTestCase):
    async def test_freestyle_wake_submits_stretch_without_waiting_for_generation(self):
        gateway, adapter = self.adapter()
        from gateway.server.service import GatewayService
        from types import SimpleNamespace
        gateway._connection = lambda robot: SimpleNamespace(robot_id="test-body")
        gateway.motion_systems = {"test-body": "freestyle"}
        gateway.freestyle_motion = AsyncMock(return_value={"job_id": "stretch-job"})
        gateway.request_motion = GatewayService.request_motion.__get__(gateway)
        await adapter._handle_gateway_event(self.event())
        observations = await self.finish(adapter)
        gateway.freestyle_motion.assert_awaited_once_with("test-body", "stretch", execute=True)
        self.assertEqual([call[0] for call in gateway.calls], ["snap", "wait"])
        stretch = observations[0]["state"]["bodyEvent"]["data"]["startup"]["stretch"]
        self.assertEqual((stretch["system"], stretch["jobId"], stretch["state"]),
                         ("freestyle", "stretch-job", "submitted"))
        self.assertNotIn("sequence", stretch)
        self.assertIsNotNone(observations[0].get("visual"))

    async def test_unavailable_selected_freestyle_does_not_dispatch_library(self):
        gateway, adapter = self.adapter()
        from gateway.server.service import GatewayService
        from types import SimpleNamespace
        gateway._connection = lambda robot: SimpleNamespace(robot_id="test-body")
        gateway.motion_systems = {"test-body": "freestyle"}
        gateway.freestyle_motion = None
        gateway.request_motion = GatewayService.request_motion.__get__(gateway)
        await adapter._handle_gateway_event(self.event())
        observations = await self.finish(adapter)
        stretch = observations[0]["state"]["bodyEvent"]["data"]["startup"]["stretch"]
        self.assertEqual(stretch["state"], "dispatch_failed")
        self.assertIn("not loaded", stretch["error"])
        self.assertEqual([call[0] for call in gateway.calls], ["snap", "wait"])

    def adapter(self):
        gateway = SnapshotGateway()
        adapter = EnvironmentAdapter(gateway, EnvironmentAdapterConfig(token="fixture", receipt_path=":memory:"))
        self.addCleanup(adapter.receipts.close)
        adapter._websocket = FakeWebSocket()
        return gateway, adapter

    def event(self, reason="boot"):
        return {"t": "event", "name": "body_event", "robot_id": "test-body", "epoch": 1,
                "event_id": "startup-1", "data": {"kind": "wake", "reason": reason, "clock_us": 123456}}

    async def finish(self, adapter):
        await asyncio.gather(*adapter._action_tasks)
        return [json.loads(item)["observation"] for item in adapter._websocket.sent
                if json.loads(item)["type"] == "environment.observation"]

    async def test_fresh_image_and_wake_are_one_input_while_stretch_is_unfinished(self):
        for reason in ["boot", "wake_from_sleep", "explicit_good_morning_request"]:
            with self.subTest(reason=reason):
                gateway, adapter = self.adapter()
                await adapter._handle_gateway_event(self.event(reason))
                observations = await self.finish(adapter)
                self.assertEqual(len(observations), 1)
                event = observations[0]["state"]["bodyEvent"]
                self.assertEqual(event["data"]["reason"], reason)
                self.assertEqual(event["data"]["clock_us"], 123456)
                self.assertEqual(event["data"]["startup"]["stretch"]["state"], "dispatched")
                self.assertEqual(observations[0]["visual"]["metadata"]["bodyEventId"], "startup-1")
                self.assertTrue(observations[0]["visual"]["timestamp"])
                self.assertEqual(observations[0]["state"]["gateway"]["robots"]["test-body"]["status"]["camera_ready"], True)
                self.assertEqual([call[0] for call in gateway.calls], ["snap", "wait", "intent"])
                self.assertEqual(gateway.calls[-1][1][:2], ("emote", {"asset": "stretch"}))
                self.assertEqual([call[1][0] for call in gateway.calls if call[0] == "wait"], [9],
                                 "Only capture completion is consumed; stretch never blocks greeting")
                self.assertEqual(adapter._pending_action_visuals, {})
                self.assertEqual(adapter._robot_action_contexts, {})
                self.assertEqual(len(adapter.receipts.pending()), 1)

    async def test_slow_capture_does_not_block_incoming_body_events(self):
        gateway, adapter = self.adapter()
        started, release = asyncio.Event(), asyncio.Event()
        snap = gateway.request_snap
        async def delayed(**kwargs):
            started.set()
            await release.wait()
            return await snap(**kwargs)
        gateway.request_snap = delayed
        await adapter._handle_gateway_event(self.event())
        await started.wait()
        await adapter._handle_gateway_event({**self.event(), "event_id": "tip-1", "data": {"kind": "tipped"}})
        self.assertEqual(json.loads(adapter._websocket.sent[0])["observation"]["state"]["bodyEvent"]["event_id"], "tip-1")
        release.set()
        observations = await self.finish(adapter)
        self.assertEqual(len(observations), 2)

    async def test_camera_failure_remains_explicit_and_does_not_invent_an_image(self):
        gateway, adapter = self.adapter()
        gateway.request_snap = AsyncMock(side_effect=GatewayError("camera unavailable"))
        await adapter._handle_gateway_event(self.event())
        observations = await self.finish(adapter)
        self.assertEqual(len(observations), 1)
        self.assertIsNone(observations[0].get("visual"))
        startup = observations[0]["state"]["bodyEvent"]["data"]["startup"]
        self.assertFalse(startup["imageAvailable"])
        self.assertEqual(startup["capture"]["type"], "rejected")
        self.assertEqual(startup["stretch"]["state"], "dispatched")

    async def test_stretch_dispatch_failure_is_reported_without_losing_photo(self):
        gateway, adapter = self.adapter()
        gateway.queue_intent = AsyncMock(side_effect=GatewayError("motion unavailable"))
        await adapter._handle_gateway_event(self.event())
        observations = await self.finish(adapter)
        self.assertIsNotNone(observations[0].get("visual"))
        self.assertEqual(observations[0]["state"]["bodyEvent"]["data"]["startup"]["stretch"],
                         {"state": "dispatch_failed", "error": "motion unavailable"})

    async def test_reconnect_and_other_robots_do_not_start_a_wake_procedure(self):
        gateway, adapter = self.adapter()
        await adapter._handle_gateway_event({"t": "connection", "status": "connected", "robot_id": "test-body", "epoch": 1})
        await adapter._handle_gateway_event({**self.event(), "robot_id": "unselected"})
        await self.finish(adapter)
        self.assertEqual(gateway.calls, [])

    async def test_a_new_bridge_connection_does_not_receive_unadmitted_old_wake(self):
        gateway, adapter = self.adapter()
        old = adapter._websocket
        snap = gateway.request_snap
        async def reconnect(**kwargs):
            result = await snap(**kwargs)
            old.closed = True
            adapter._websocket = FakeWebSocket()
            return result
        gateway.request_snap = reconnect
        await adapter._handle_gateway_event(self.event())
        self.assertEqual(await self.finish(adapter), [])
        self.assertEqual(adapter.receipts.pending(), [])
        self.assertEqual([call[0] for call in gateway.calls], ["snap", "wait", "intent"])

    async def test_real_gateway_receives_boot_and_camera_while_stretch_stays_pending(self):
        from gateway.server.service import GatewayService, GatewayServiceConfig, GatewayConnection
        from protocol.binary_helpers import CAMERA_JPEG_FRAME_TYPE, encode_binary_frame
        commands = asyncio.Queue()
        class Socket:
            closed = False
            async def send(self, raw):
                await commands.put(json.loads(raw))
        gateway = GatewayService(GatewayServiceConfig(tokens={"test-body": "fixture"}))
        connection = GatewayConnection(gateway, Socket(), "test-body", 1, model="v2-12servo", features=("body_commands_v1",),
            capabilities={"camera": True, "motion": True, "commands": ["stretch"]})
        connection.last_status = {"camera_ready": True, "status_received_at": "2026-10-23T12:00:00Z"}
        gateway._connections["test-body"] = connection
        adapter = EnvironmentAdapter(gateway, EnvironmentAdapterConfig(token="fixture", receipt_path=":memory:"))
        self.addCleanup(adapter.receipts.close)
        self.addCleanup(connection.cancel_pending)
        adapter._websocket = FakeWebSocket()
        await connection._handle_control({"t": "event", "name": "boot", "reason": "boot", "event_id": "boot-wire", "clock_us": 123})
        async with asyncio.timeout(3):
            snap = await commands.get()
            self.assertEqual(snap["t"], "snap")
            await connection._handle_control({"t": "ack", "seq": snap["seq"]})
            await connection._handle_control({"t": "cam_meta", "fps": 0, "res": "XGA",
                "counter_base": 17, "origin": "request", "origin_id": snap["seq"]})
            await connection._handle_binary(encode_binary_frame(CAMERA_JPEG_FRAME_TYPE, 17, b"\xff\xd8jpeg\xff\xd9"))
            await connection._handle_control({"t": "done", "seq": snap["seq"]})
            stretch = await commands.get()
            self.assertEqual((stretch["t"], stretch["name"], stretch["asset"]), ("intent", "emote", "stretch"))
            observations = await self.finish(adapter)
        self.assertEqual(len(observations), 1)
        self.assertEqual(observations[0]["state"]["bodyEvent"]["event_id"], "boot-wire")
        self.assertEqual(observations[0]["visual"]["metadata"]["counter"], 17)
        self.assertFalse(connection.pending[stretch["seq"]].future.done())
        self.assertEqual(observations[0]["state"]["gateway"]["robots"]["test-body"]["body_command"]["asset"], "stretch")

    async def test_recipient_belongs_to_event_admission_not_later_task_start(self):
        gateway, adapter = self.adapter()
        adapter._websocket = None
        await adapter._handle_gateway_event(self.event())
        adapter._websocket = FakeWebSocket()
        self.assertEqual(await self.finish(adapter), [])
        self.assertEqual(adapter.receipts.pending(), [])
        self.assertEqual([call[0] for call in gateway.calls], ["snap", "wait", "intent"])

    async def test_capture_does_not_depend_on_bridge_camera_delivery_worker(self):
        gateway, adapter = self.adapter()
        adapter._camera_delivery_queue = asyncio.Queue(maxsize=1)
        await adapter._handle_gateway_event(self.event())
        async with asyncio.timeout(1):
            observations = await self.finish(adapter)
        self.assertEqual(len(observations), 1)
        self.assertIsNotNone(observations[0].get("visual"))
        self.assertTrue(adapter._camera_delivery_queue.empty())
