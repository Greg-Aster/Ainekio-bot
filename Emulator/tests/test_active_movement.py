from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import websockets

from gateway.environment_adapter.server import EnvironmentAdapter, EnvironmentAdapterConfig
from gateway.environment_adapter.action_receipts import ActionConflictError, ActionReceipts
from gateway.server.service import GatewayConnection, GatewayService, GatewayServiceConfig
from protocol.control_v1 import BODY_CAPABILITIES_FEATURE, BODY_COMMANDS_FEATURE, COMMAND_DEADLINE_FEATURE, LOCOMOTION_FEATURE, RUN_GAIT_FEATURE
from test_action_receipts import accepted, action
from test_environment_adapter import FakeWebSocket


class ActiveMovementTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.now = 100.0
        self.gateway = GatewayService(GatewayServiceConfig(tokens={"robot": "test-token"}), clock=lambda: self.now)
        self.body = FakeWebSocket()
        self.connection = GatewayConnection(self.gateway, self.body, "robot", 7,
            (BODY_CAPABILITIES_FEATURE, BODY_COMMANDS_FEATURE, COMMAND_DEADLINE_FEATURE, LOCOMOTION_FEATURE, RUN_GAIT_FEATURE), model="v2-12servo",
            capabilities={"motion": True, "camera": False, "commands": ["walk", "left", "run", "stop"]})
        self.connection.observe_body_clock({"clock_ms": 20000})
        self.gateway._connections["robot"] = self.connection
        self.adapter = EnvironmentAdapter(self.gateway, EnvironmentAdapterConfig(
            token="bridge-secret", receipt_path=":memory:", robot_id="robot"), clock=lambda: self.now)
        self.bridge = FakeWebSocket()
        self.adapter._websocket = self.bridge
        self.tasks: list[asyncio.Task] = []
        self.original = {**action("walk-task"), "continuous": True, "speed": 50}

    async def asyncTearDown(self) -> None:
        tasks = set(self.tasks) | self.adapter._action_tasks
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.connection.cancel_pending()
        self.adapter.receipts.close()

    async def sent(self, count: int) -> dict:
        async def wait():
            while len(self.body.sent) < count:
                await asyncio.sleep(0.001)
        await asyncio.wait_for(wait(), 1)
        return json.loads(self.body.sent[count - 1])

    async def start(self, **fields) -> None:
        self.original.update(fields)
        self.adapter.receipts.receive(self.original, accepted(self.original["id"]))
        task = asyncio.create_task(self.adapter._process_environment_action(self.original))
        self.tasks.append(task)
        first = await self.sent(1)
        await self.connection._handle_control({"t": "ack", "seq": first["seq"]})

    def request(self, revision: int = 1, **fields) -> dict:
        return {"type": "environment.action.update", "version": 1, "sessionId": self.adapter.config.session_id,
            "gatewayInstance": self.gateway.instance_id, "robotId": "robot", "epoch": 7,
            "actionId": self.original["id"], "bodyLease": self.original["bodyLease"], "revision": revision,
            "validForMs": 1000, "controls": {"speed": 70}, **fields}

    async def update(self, request: dict) -> asyncio.Task:
        await self.adapter._schedule_walk_update(request, self.bridge)
        return self.adapter._walk_update_task

    def result(self) -> dict:
        return next(json.loads(value) for value in reversed(self.bridge.sent)
                    if json.loads(value).get("type") == "environment.action.update.result")

    async def acknowledge_update(self, count: int = 2) -> None:
        command = await self.sent(count)
        await self.connection._handle_control({"t": "ack", "seq": command["seq"]})
        await asyncio.wait_for(self.adapter._walk_update_task, 1)

    async def test_steering_updates_keep_original_action_and_sequence(self) -> None:
        await self.start(forward=70, turn=20)
        self.assertEqual(json.loads(self.body.sent[0])["forward"], 70)
        await self.update(self.request(controls={"speed": 50, "forward": 70, "turn": -30}))
        await self.acknowledge_update()
        command = json.loads(self.body.sent[-1])
        self.assertEqual(command["update"], json.loads(self.body.sent[0])["seq"])
        self.assertEqual((command["forward"], command["turn"]), (70, -30))
        self.assertEqual(self.adapter.receipts.action(self.original["id"])["state"], "started")
        self.assertEqual(self.result()["actionId"], self.original["id"])

    async def test_updates_keep_parent_active_until_original_walk_completes(self) -> None:
        await self.start()
        await self.update(self.request())
        await self.acknowledge_update()
        update = json.loads(self.body.sent[-1])
        self.assertEqual({key: update[key] for key in ("name", "dir", "steps", "speed", "update")},
                         {"name": "walk", "dir": "fwd", "steps": 0, "speed": 70, "update": 1})
        self.assertEqual(self.result()["status"], "acknowledged")
        row = self.adapter.receipts.action(self.original["id"])
        self.assertEqual(row["state"], "started")
        self.assertIsNone(row["result"])
        self.assertEqual(json.loads(row["wire"])["sequence"], 1)
        self.assertFalse(self.tasks[0].done())
        await self.update(self.request(2, controls={"stride": 60, "rate": 0.8}))
        await self.acknowledge_update(3)
        self.assertFalse(self.tasks[0].done())
        await self.connection._handle_control({"t": "done", "seq": 1})
        await asyncio.wait_for(self.tasks[0], 1)
        self.assertEqual(json.loads(self.adapter.receipts.action(self.original["id"])["result"])["type"], "completed")

    async def test_direction_and_actual_run_wire_are_inherited(self) -> None:
        await self.start(command="run")
        self.assertEqual(json.loads(self.body.sent[0])["name"], "walk")
        await self.update(self.request())
        await self.acknowledge_update()
        self.assertEqual(json.loads(self.body.sent[1])["gait"], "walk")
        self.assertEqual(json.loads(self.body.sent[1])["dir"], "fwd")

    async def test_turning_walk_retains_its_original_direction(self) -> None:
        await self.start(command="left")
        await self.update(self.request())
        await self.acknowledge_update()
        self.assertEqual(json.loads(self.body.sent[1])["dir"], "turn_l")

    async def test_replayed_or_old_revision_never_sends_again(self) -> None:
        await self.start()
        await self.update(self.request(3))
        await self.acknowledge_update()
        for revision in (3, 2, 1):
            await (await self.update(self.request(revision)))
            self.assertEqual(self.result()["status"], "rejected")
        self.assertEqual(len(self.body.sent), 2)

    async def test_wrong_owner_session_and_raw_controls_are_rejected(self) -> None:
        await self.start()
        for fields in (
            {"bodyLease": {**self.original["bodyLease"], "generation": 2}}, {"epoch": 8},
            {"gatewayInstance": "previous-gateway"}, {"sessionId": "other-session"},
            {"controls": {"speed": 70, "dir": "turn_r"}}, {"controls": {"servo": [0, 180]}},
            {"controls": {"rate": 1}}, {"controls": {"speed": float("nan")}},
            {"validForMs": 0}, {"revision": True},
        ):
            await (await self.update(self.request(**fields)))
            self.assertEqual(self.result()["status"], "rejected", fields)
        self.assertEqual(len(self.body.sent), 1)

    async def test_finite_motion_cannot_be_converted_into_ongoing_walk(self) -> None:
        await self.start(continuous=False, units=3)
        await (await self.update(self.request()))
        self.assertEqual(self.result()["status"], "rejected")
        self.assertEqual(len(self.body.sent), 1)

    async def test_update_expiring_behind_send_lock_does_not_reach_body(self) -> None:
        await self.start()
        async with self.connection._send_lock:
            task = await self.update(self.request(validForMs=10))
            await asyncio.sleep(0)
            self.now += 0.05
        await task
        self.assertEqual(self.result()["status"], "rejected")
        self.assertEqual(len(self.body.sent), 1)
        await self.update(self.request(2))
        await self.acknowledge_update()

    async def test_short_validity_reaches_body_without_resetting_on_dispatch(self) -> None:
        await self.start()
        async with self.connection._send_lock:
            await self.update(self.request(validForMs=500))
            self.now += 0.125
        await self.acknowledge_update()
        command = json.loads(self.body.sent[-1])
        self.assertEqual(command["epoch"], 7)
        self.assertEqual(command["deadline_ms"], 20370)

    async def test_update_cannot_extend_gateway_validity_limit(self) -> None:
        await self.start()
        self.gateway.config = replace(self.gateway.config, max_action_age_ms=100)
        await self.update(self.request(validForMs=1000))
        await self.acknowledge_update()
        self.assertEqual(json.loads(self.body.sent[-1])["deadline_ms"], 20095)

    async def test_missing_body_deadlines_disable_updates(self) -> None:
        await self.start()
        self.connection.features = tuple(feature for feature in self.connection.features
                                         if feature != COMMAND_DEADLINE_FEATURE)
        self.assertFalse(self.adapter._observation()["state"]["activeMovementUpdates"]["available"])
        await (await self.update(self.request()))
        self.assertEqual(self.result()["status"], "rejected")
        self.assertEqual(len(self.body.sent), 1)

    async def test_new_gateway_identity_cannot_claim_old_action(self) -> None:
        await self.start()
        self.gateway.instance_id = "new-instance"
        await (await self.update(self.request()))
        self.assertEqual(self.result()["status"], "rejected")
        self.assertEqual(len(self.body.sent), 1)

    async def test_cancellation_and_new_owner_fence_queued_update(self) -> None:
        await self.start()
        async with self.connection._send_lock:
            task = await self.update(self.request())
            await asyncio.sleep(0)
            self.adapter.receipts.request_cancel(self.original["id"], self.original["bodyLease"],
                self.adapter._feedback(self.original["id"], "cancelled", "test cancellation"))
        await task
        self.assertEqual(self.result()["status"], "rejected")
        self.assertEqual(len(self.body.sent), 1)

    async def test_changed_body_owner_blocks_old_task_without_restarting_walk(self) -> None:
        await self.start()
        async with self.connection._send_lock:
            task = await self.update(self.request())
            await asyncio.sleep(0)
            self.adapter.receipts.receive(action("new-owner", 2), accepted("new-owner"))
        await task
        self.assertEqual(self.result()["status"], "rejected")
        self.assertEqual(len(self.body.sent), 1)

    async def test_completion_or_bridge_replacement_blocks_delayed_update(self) -> None:
        await self.start()
        async with self.connection._send_lock:
            task = await self.update(self.request())
            await asyncio.sleep(0)
            await self.connection._handle_control({"t": "done", "seq": 1})
        await task
        self.assertEqual(self.result()["status"], "rejected")
        self.assertEqual(len(self.body.sent), 1)

    async def test_bridge_replacement_does_not_dispatch_old_bridge_update(self) -> None:
        await self.start()
        async with self.connection._send_lock:
            task = await self.update(self.request())
            await asyncio.sleep(0)
            self.adapter._websocket = FakeWebSocket()
        await task
        self.assertEqual(len(self.body.sent), 1)
        self.assertFalse(any(json.loads(value).get("type") == "environment.action.update.result"
                             for value in self.adapter._websocket.sent))

    async def test_unacknowledged_update_blocks_further_updates_until_receipt_arrives(self) -> None:
        await self.start()
        with patch("gateway.environment_adapter.server.WALK_UPDATE_ACK_TIMEOUT_SECONDS", 0.01):
            await (await self.update(self.request()))
        self.assertEqual(self.result()["status"], "outcome_unknown")
        self.assertEqual(self.adapter.receipts.action(self.original["id"])["state"], "started")
        await (await self.update(self.request(2)))
        self.assertEqual(self.result()["status"], "rejected")
        self.assertEqual(len(self.body.sent), 2)
        await self.connection._handle_control({"t": "ack", "seq": 2})
        await self.update(self.request(3))
        await self.acknowledge_update(3)
        self.assertEqual(self.result()["status"], "acknowledged")

    async def test_one_in_flight_update_enforces_backpressure(self) -> None:
        await self.start()
        first = await self.update(self.request())
        await self.sent(2)
        await self.adapter._schedule_walk_update(self.request(2), self.bridge)
        self.assertIs(self.adapter._walk_update_task, first)
        self.assertEqual(self.result()["status"], "rejected")
        self.assertEqual(len(self.body.sent), 2)
        await self.acknowledge_update()

    async def test_cancellation_can_stop_body_while_update_ack_is_missing(self) -> None:
        await self.start()
        update = await self.update(self.request())
        await self.sent(2)
        cancel = asyncio.create_task(self.adapter._cancel_action({"actionId": self.original["id"],
            "cancellationId": "cancel-update", "bodyLease": self.original["bodyLease"]}))
        self.tasks.append(cancel)
        stop = await self.sent(3)
        self.assertEqual(stop["t"], "stop")
        self.assertFalse(update.done(), "stop must be sent without waiting for the update receipt")
        await self.connection._handle_control({"t": "ack", "seq": stop["seq"]})
        await asyncio.wait_for(cancel, 1)
        self.assertEqual(json.loads(self.adapter.receipts.action(self.original["id"])["result"])["type"], "cancelled")
        await self.connection._handle_control({"t": "nak", "seq": 2, "code": "busy"})
        await asyncio.wait_for(update, 1)
        self.assertEqual(self.result()["status"], "rejected")

    async def test_authenticated_bridge_updates_and_cancels_same_parent_action(self) -> None:
        self.adapter._websocket = None
        async with websockets.serve(self.adapter.handler, "127.0.0.1", 0, ping_interval=None) as server:
            port = server.sockets[0].getsockname()[1]
            async with websockets.connect(f"ws://127.0.0.1:{port}", ping_interval=None) as bridge:
                await bridge.send(json.dumps({"type": "bridge.connect", "version": 1, "token": "bridge-secret"}))
                ready = json.loads(await bridge.recv())
                self.assertTrue(ready["observation"]["state"]["activeMovementUpdates"]["available"])
                await bridge.send(json.dumps({"type": "environment.action", "action": self.original}))
                accepted_result = json.loads(await bridge.recv())["feedback"]
                await bridge.send(json.dumps({"type": "environment.feedback.ack",
                    "feedbackId": accepted_result["id"], "admitted": True}))
                await self.sent(1)
                await self.connection._handle_control({"t": "ack", "seq": 1})
                await bridge.send(json.dumps(self.request()))
                await self.sent(2)
                await self.connection._handle_control({"t": "ack", "seq": 2})
                result = json.loads(await asyncio.wait_for(bridge.recv(), 1))
                self.assertEqual((result["type"], result["status"]), ("environment.action.update.result", "acknowledged"))
                self.assertEqual(self.adapter.receipts.action(self.original["id"])["state"], "started")
                await bridge.send(json.dumps({"type": "environment.cancel", "actionId": self.original["id"],
                    "cancellationId": "cancel-1", "bodyLease": self.original["bodyLease"]}))
                stop = await self.sent(3)
                self.assertEqual(stop["t"], "stop")
                await self.connection._handle_control({"t": "cancelled", "seq": 1})
                await self.connection._handle_control({"t": "ack", "seq": stop["seq"]})
                async def cancelled():
                    while True:
                        message = json.loads(await bridge.recv())
                        if message.get("type") == "environment.feedback" and message["feedback"]["type"] == "cancelled":
                            return message
                await asyncio.wait_for(cancelled(), 1)
                await bridge.send(json.dumps(self.request(2)))
                async def rejected():
                    while True:
                        message = json.loads(await bridge.recv())
                        if message.get("type") == "environment.action.update.result":
                            return message
                self.assertEqual((await asyncio.wait_for(rejected(), 1))["status"], "rejected")
                self.assertEqual(len(self.body.sent), 3)


class ActiveMovementReceiptTests(unittest.IsolatedAsyncioTestCase):
    async def test_consumed_revision_survives_receipt_store_reopen(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "receipts.sqlite")
            original = action("persistent-walk")
            wire = {"gatewayInstance": "instance", "robotId": "robot", "epoch": 7,
                    "sequence": 1, "kind": "intent"}
            receipts = ActionReceipts(path)
            receipts.receive(original, accepted(original["id"]))
            receipts.begin(original["id"], wire)
            async with receipts.walk_update_dispatch(original["id"], original["bodyLease"], wire, 3, 2, lambda: None):
                pass
            receipts.close()
            reopened = ActionReceipts(path)
            try:
                with self.assertRaises(ActionConflictError):
                    async with reopened.walk_update_dispatch(original["id"], original["bodyLease"], wire, 3, 3, lambda: None):
                        self.fail("replayed revision must never reach the physical send")
                row = reopened.action(original["id"])
                self.assertEqual(row["state"], "started")
                self.assertIsNone(row["result"])
                self.assertEqual(json.loads(row["wire"])["sequence"], 1)
                self.assertEqual(json.loads(row["wire"])["walkUpdate"],
                                 {"revision": 3, "sequence": 2, "dispatched": True})
            finally:
                reopened.close()
