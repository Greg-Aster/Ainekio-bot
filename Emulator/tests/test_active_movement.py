from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import websockets

from gateway.dashboard.server import DashboardHandler
from gateway.environment_adapter.server import EnvironmentAdapter, EnvironmentAdapterConfig
from gateway.environment_adapter.action_receipts import ActionConflictError, ActionReceipts
from gateway.server.service import GatewayConnection, GatewayError, GatewayService, GatewayServiceConfig
from protocol.control_v1 import BODY_CAPABILITIES_FEATURE, BODY_COMMANDS_FEATURE, COMMAND_DEADLINE_FEATURE, LOCOMOTION_FEATURE, RUN_GAIT_FEATURE, WALK_STEERING_FEATURE, ProtocolValidationError
from Emulator.tests.test_action_receipts import accepted, action
from Emulator.tests.test_environment_adapter import FakeWebSocket


class ActiveMovementTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.now = 100.0
        self.gateway = GatewayService(GatewayServiceConfig(tokens={"robot": "test-token"}), clock=lambda: self.now)
        self.body = FakeWebSocket()
        self.connection = GatewayConnection(self.gateway, self.body, "robot", 7,
            (BODY_CAPABILITIES_FEATURE, BODY_COMMANDS_FEATURE, COMMAND_DEADLINE_FEATURE, LOCOMOTION_FEATURE, RUN_GAIT_FEATURE, WALK_STEERING_FEATURE), model="v2-12servo",
            capabilities={"motion": True, "camera": False, "commands": ["walk", "left", "run", "stop", "wave"]})
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

    def interpretation_body(self, sequence=None) -> list:
        return [self.adapter.config.session_id, self.gateway.instance_id, "robot", 7, sequence]

    async def complete_interpreted(self, identifier: str, command: str, fence: list) -> dict:
        payload = {**action(identifier), "sessionId": self.adapter.config.session_id,
            "command": command, "metadata": {"interpretationBody": fence}}
        if command == "stop":
            payload["type"] = "stop"
        self.adapter.receipts.receive(payload, accepted(identifier))
        count = len(self.body.sent) + 1
        task = asyncio.create_task(self.adapter._process_environment_action(payload))
        self.tasks.append(task)
        wire = await self.sent(count)
        await self.connection._handle_control({"t": "ack", "seq": wire["seq"]})
        if command != "stop":
            await self.connection._handle_control({"t": "done", "seq": wire["seq"]})
        await asyncio.wait_for(task, 10)
        return json.loads(self.adapter.receipts.action(identifier)["result"])

    async def manual_walk(self) -> int:
        # Exercise the actual dashboard route and service send, without opening
        # a listening port or assigning the ownership marker in the fixture.
        loop = asyncio.get_running_loop()
        handler = DashboardHandler.__new__(DashboardHandler)
        handler.server = SimpleNamespace(gateway=self.gateway, stop_latched=False,
            audit_log=SimpleNamespace(record=lambda *args, **kwargs: None),
            call_gateway=lambda operation: asyncio.run_coroutine_threadsafe(operation, loop).result(1))
        result = await asyncio.to_thread(handler._dispatch_api, "/api/intent", {
            "robot_id": "robot", "name": "walk", "params": {"dir": "fwd", "steps": 0, "speed": 40}})
        await self.connection._handle_control({"t": "ack", "seq": result["seq"]})
        return result["seq"]

    async def test_program_wave_then_manual_takeover_rejects_old_stop_and_walk(self) -> None:
        wave = await self.complete_interpreted("program-wave", "wave", self.interpretation_body())
        self.assertEqual(wave["type"], "completed")
        fence = wave["data"].get("interpretationBody")
        self.assertEqual(fence, self.interpretation_body(1), "Correlated completion advances program ownership")
        manual = await self.manual_walk()
        for command in ("stop", "walk"):
            payload = {**action("old-" + command), "command": command,
                "sessionId": self.adapter.config.session_id, "metadata": {"interpretationBody": fence}}
            if command == "stop":
                payload["type"] = "stop"
            self.adapter.receipts.receive(payload, accepted(payload["id"]))
            await self.adapter._process_environment_action(payload)
            result = json.loads(self.adapter.receipts.action(payload["id"])["result"])
            self.assertNotEqual(result["type"], "completed")
            self.assertIn("ended body owner or session", result["message"])
            self.assertNotIn("interpretationBody", result.get("data", {}), "Rejected admission cannot claim ownership")
        self.assertEqual(len(self.body.sent), 2, "No old Stop or movement may reach the simulated body")
        self.assertEqual(self.connection.body_command_sequence, manual)

    async def test_late_program_receipt_does_not_adopt_manual_dispatch_owner(self) -> None:
        await self.start(sessionId=self.adapter.config.session_id,
            metadata={"interpretationBody": self.interpretation_body()})
        await self.manual_walk()
        await self.connection._handle_control({"t": "cancelled", "seq": 1, "code": "replaced"})
        await self.tasks[0]
        result = json.loads(self.adapter.receipts.action(self.original["id"])["result"])
        self.assertEqual(result["data"]["interpretationBody"], self.interpretation_body(1))
        self.assertEqual(self.connection.body_command_sequence, 2)

    async def test_program_ordinary_multistep_advances_correlated_dispatch_owner(self) -> None:
        fence = self.interpretation_body()
        for index, command in enumerate(("wave", "walk", "stop"), 1):
            result = await self.complete_interpreted("program-" + str(index), command, fence)
            self.assertEqual(result["type"], "completed")
            fence = result["data"].get("interpretationBody")
            self.assertEqual(fence, self.interpretation_body(index))
        self.assertEqual(len(self.body.sent), 3)

    async def test_program_receipt_recovery_keeps_owned_fence_after_manual_takeover_and_reconnect(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.adapter.receipts.close()
            receipt_path = str(Path(directory) / "receipts.sqlite")
            self.adapter.receipts = ActionReceipts(receipt_path)
            wave = await self.complete_interpreted("program-wave", "wave", self.interpretation_body())
            fence = wave["data"].get("interpretationBody")
            self.assertEqual(fence, self.interpretation_body(1))
            await self.manual_walk()
            self.adapter.receipts.close()
            self.adapter.receipts = ActionReceipts(receipt_path)
            # Adapter receipt recovery / bridge reconnect must replay its own
            # recorded dispatch, never adopt the current manual body's sequence.
            await self.adapter._recover_action_receipts()
            saved = json.loads(self.adapter.receipts.action("program-wave")["result"])
            self.assertEqual(saved["data"]["interpretationBody"], fence)
            for epoch in (7, 8):
                self.connection.epoch = epoch
                payload = {**action("old-after-recovery-" + str(epoch)), "type": "stop",
                    "sessionId": self.adapter.config.session_id, "metadata": {"interpretationBody": fence}}
                self.adapter.receipts.receive(payload, accepted(payload["id"]))
                await self.adapter._process_environment_action(payload)
                self.assertEqual(len(self.body.sent), 2)

    async def test_interpreted_command_preserves_current_dispatch_owner(self) -> None:
        fence = [self.adapter.config.session_id, self.gateway.instance_id, "robot", 7, None]
        await self.start(metadata={"interpretationBody": fence})
        self.assertEqual(len(self.body.sent), 1)
        self.assertEqual(self.connection.body_command_sequence, 1)

    async def test_manual_takeover_while_interpreted_command_waits_for_send_lock(self) -> None:
        self.original["metadata"] = {"interpretationBody": [
            self.adapter.config.session_id, self.gateway.instance_id, "robot", 7, None]}
        self.adapter.receipts.receive(self.original, accepted(self.original["id"]))
        async with self.connection._send_lock:
            task = asyncio.create_task(self.adapter._process_environment_action(self.original))
            self.tasks.append(task)
            await asyncio.sleep(0.02)
            self.connection.body_command_sequence = 999  # Manual wire command won the lock.
        await asyncio.wait_for(task, 1)
        self.assertEqual(self.body.sent, [])
        result = json.loads(self.adapter.receipts.action(self.original["id"])["result"])
        self.assertIn("ended body owner or session", result["message"])
        self.assertNotEqual(result["type"], "completed")

    async def test_late_interpreted_stop_is_fenced_but_emergency_stop_remains_available(self) -> None:
        self.connection.body_command_sequence = 999
        stop = {**self.original, "type": "stop", "metadata": {"interpretationBody": [
            self.adapter.config.session_id, self.gateway.instance_id, "robot", 7, None]}}
        self.adapter.receipts.receive(stop, accepted(stop["id"]))
        await self.adapter._process_environment_action(stop)
        self.assertEqual(self.body.sent, [], "An obsolete LLM Stop cannot interrupt manual control")
        await self.gateway.estop(robot_id="robot", received_at=self.now)
        self.assertEqual(json.loads(self.body.sent[0])["t"], "stop", "Emergency Stop does not depend on inference")

    async def test_reconnected_body_rejects_interpreted_command_from_old_epoch(self) -> None:
        self.original["metadata"] = {"interpretationBody": [
            self.adapter.config.session_id, self.gateway.instance_id, "robot", 6, None]}
        self.adapter.receipts.receive(self.original, accepted(self.original["id"]))
        await self.adapter._process_environment_action(self.original)
        self.assertEqual(self.body.sent, [])
        self.assertNotEqual(json.loads(self.adapter.receipts.action(self.original["id"])["result"])["type"], "completed")

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

    async def test_legacy_firmware_never_receives_substitute_motion_for_steering(self) -> None:
        self.connection.features = tuple(feature for feature in self.connection.features
                                         if feature != WALK_STEERING_FEATURE)
        for controls in ({"forward": 80, "turn": 25}, {"forward": 0, "turn": 0},
                         {"forward": 50}, {"turn": -25}):
            with self.subTest(controls=controls), self.assertRaisesRegex(GatewayError, "steering"):
                await self.connection.send_command({"t": "intent", "name": "walk", "dir": "fwd",
                    "steps": 0, "speed": 50, **controls}, received_at=self.now)
        self.assertEqual(self.body.sent, [])
        self.assertEqual(self.connection.next_sequence, 1)
        self.assertEqual(self.connection.pending, {})

    async def test_finish_preserves_concurrent_speech_and_requires_original_done(self) -> None:
        await self.start()
        self.connection.capabilities["speaker"] = True
        speech = await self.connection.send_command({"t": "tts", "op": "start"}, received_at=self.now)
        await self.connection._handle_control({"t": "ack", "seq": speech})
        update = await self.update(self.request(controls={"speed": 0}))
        finish = await self.sent(3)
        self.assertEqual(finish["update"], 1)
        self.assertEqual(finish["speed"], 0)
        await self.connection._handle_control({"t": "ack", "seq": finish["seq"]})
        await update
        self.assertEqual(self.result()["status"], "acknowledged")
        self.assertIn(1, self.connection.pending)
        self.assertIn(speech, self.connection.pending)
        self.assertEqual(self.adapter.receipts.action(self.original["id"])["state"], "started")
        await self.connection._handle_control({"t": "done", "seq": 1})
        await self.tasks[0]
        self.assertIn(speech, self.connection.pending, "Normal Finish must leave speech running")
        self.assertEqual(json.loads(self.adapter.receipts.action(self.original["id"])["result"])["type"], "completed")
        stop = await self.gateway.estop(robot_id="robot", received_at=self.now)
        self.assertEqual((await self.sent(4))["t"], "stop", "Emergency Stop remains available")
        await self.connection._handle_control({"t": "ack", "seq": stop})
        await self.connection._handle_control({"t": "cancelled", "seq": speech, "code": "stop"})
        self.assertEqual(self.connection.completed[speech]["t"], "cancelled")

    async def test_stop_ack_without_original_terminal_is_bounded_unknown_then_late_receipt_reconciles(self) -> None:
        await self.start(sessionId=self.adapter.config.session_id)
        with patch("gateway.environment_adapter.server.CANCELLATION_TIMEOUT_SECONDS", 0.03):
            cancel = asyncio.create_task(self.adapter._cancel_action({"actionId": self.original["id"],
                "cancellationId": "missing-terminal", "bodyLease": self.original["bodyLease"]}))
            self.tasks.append(cancel)
            stop = await self.sent(2)
            await self.connection._handle_control({"t": "ack", "seq": stop["seq"]})
            await asyncio.wait_for(cancel, 1)
        unknown = json.loads(self.adapter.receipts.action(self.original["id"])["result"])
        self.assertEqual(unknown["type"], "outcome_unknown")
        self.assertEqual(unknown["data"]["cancellationBody"], [self.original["sessionId"],
            self.gateway.instance_id, "robot", 7, stop["seq"]])
        self.assertEqual(unknown["data"]["interpretationBody"], unknown["data"]["cancellationBody"])
        self.assertFalse(self.tasks[0].done())
        await self.connection._handle_control({"t": "cancelled", "seq": 1, "code": "stop"})
        await self.tasks[0]
        self.assertEqual(json.loads(self.adapter.receipts.action(self.original["id"])["result"])["type"], "cancelled")

    async def test_manual_takeover_blocks_old_cleanup_and_late_updates_even_before_old_receipt(self) -> None:
        await self.start()
        manual = await self.connection.send_command({"t": "intent", "name": "walk", "dir": "fwd",
            "steps": 0, "speed": 40, "update": 1}, received_at=self.now)
        await self.adapter._cancel_action({"actionId": self.original["id"], "cancellationId": "late-cleanup",
            "bodyLease": self.original["bodyLease"]})
        self.assertEqual(len(self.body.sent), 2, "Old cleanup must not send Stop after manual update")
        self.assertEqual(json.loads(self.adapter.receipts.action(self.original["id"])["result"])["type"], "outcome_unknown")
        await (await self.update(self.request()))
        self.assertEqual(self.result()["status"], "rejected")
        await self.connection._handle_control({"t": "cancelled", "seq": 1, "code": "stop"})
        await self.tasks[0]
        self.assertIn(manual, self.connection.pending)
        self.assertEqual(len(self.body.sent), 2)

    async def test_reconnect_blocks_old_cleanup_and_does_not_replay_motion(self) -> None:
        await self.start()
        self.connection.cancel_pending()
        self.connection.epoch = 8
        await self.tasks[0]
        await self.adapter._cancel_action({"actionId": self.original["id"], "cancellationId": "old-epoch",
            "bodyLease": self.original["bodyLease"]})
        self.assertEqual(len(self.body.sent), 1)
        self.assertEqual(json.loads(self.adapter.receipts.action(self.original["id"])["result"])["type"], "outcome_unknown")

    async def test_old_gateway_cancellation_cannot_claim_a_reused_sequence_terminal(self) -> None:
        self.adapter.receipts.receive(self.original, accepted(self.original["id"]))
        self.adapter.receipts.begin(self.original["id"], {"gatewayInstance": "previous-process",
            "robotId": "robot", "epoch": 7, "sequence": 1, "kind": "intent"})
        self.connection.completed[1] = {"t": "done", "seq": 1}
        await self.adapter._cancel_action({"actionId": self.original["id"], "cancellationId": "previous-process",
            "bodyLease": self.original["bodyLease"]})
        self.assertEqual(self.body.sent, [])
        self.assertEqual(json.loads(self.adapter.receipts.action(self.original["id"])["result"])["type"], "outcome_unknown")

    async def test_new_owner_fences_cancellation_after_waiting_for_send_lock(self) -> None:
        await self.start()
        async with self.connection._send_lock:
            cancel = asyncio.create_task(self.adapter._cancel_action({"actionId": self.original["id"],
                "cancellationId": "old-owner", "bodyLease": self.original["bodyLease"]}))
            self.tasks.append(cancel)
            for _ in range(100):
                if self.adapter.receipts.action(self.original["id"])["state"] == "cancelling":
                    break
                await asyncio.sleep(0.001)
            self.adapter.receipts.receive(action("replacement", 2), accepted("replacement"))
        await asyncio.wait_for(cancel, 1)
        self.assertEqual(len(self.body.sent), 1)
        self.assertEqual(json.loads(self.adapter.receipts.action(self.original["id"])["result"])["type"], "outcome_unknown")

    async def test_legacy_steering_rejection_preserves_emergency_stop(self) -> None:
        self.connection.features = tuple(feature for feature in self.connection.features
                                         if feature != WALK_STEERING_FEATURE)
        original = await self.connection.send_command(
            {"t": "intent", "name": "walk", "dir": "fwd", "steps": 0, "speed": 50},
            received_at=self.now)
        await self.connection._handle_control({"t": "ack", "seq": original})
        with self.assertRaisesRegex(GatewayError, "steering"):
            await self.connection.send_command(
                {"t": "intent", "name": "walk", "dir": "fwd", "steps": 0,
                 "speed": 50, "forward": 80, "turn": 25, "update": original}, received_at=self.now)
        self.assertEqual(len(self.body.sent), 1)
        # Forward-compatible extra fields must not turn STOP into a steering request.
        sequence = await self.connection.send_command(
            {"t": "stop", "detach": True, "forward": 80, "turn": 25}, received_at=self.now)
        stop = await self.sent(2)
        self.assertEqual(stop["t"], "stop")
        self.assertTrue(stop["detach"])
        self.assertNotIn("deadline_ms", stop)
        await self.connection._handle_control({"t": "ack", "seq": sequence})
        self.assertIn(original, self.connection.pending, "Stop ACK cannot synthesize original termination")
        await self.connection._handle_control({"t": "cancelled", "seq": original, "code": "stop"})
        self.assertEqual(self.connection.completed[original]["t"], "cancelled")

    async def test_run_alias_never_discards_steering_but_legacy_run_remains_supported(self) -> None:
        self.connection.features = tuple(feature for feature in self.connection.features
                                         if feature != WALK_STEERING_FEATURE)
        command = {"t": "intent", "name": "emote", "asset": "run"}
        with self.assertRaisesRegex(GatewayError, "steering requires a walk"):
            await self.connection.send_command({**command, "forward": 80, "turn": 25},
                                               received_at=self.now)
        self.assertEqual(self.body.sent, [])
        self.assertEqual(self.connection.next_sequence, 1)
        self.assertEqual(self.connection.pending, {})
        sequence = await self.connection.send_command(command, received_at=self.now)
        sent = await self.sent(1)
        self.assertEqual((sent["name"], sent["speed"], sent["seq"]), ("walk", 150, sequence))
        self.assertNotIn("forward", sent)

    async def test_legacy_speed_updates_remain_available_without_advertising_steering(self) -> None:
        self.connection.features = tuple(feature for feature in self.connection.features
                                         if feature != WALK_STEERING_FEATURE)
        capability = self.adapter._observation()["state"]["activeMovementUpdates"]
        self.assertTrue(capability["available"])
        self.assertEqual(capability["controls"], ["speed", "stride", "rate"])
        await self.start()
        await (await self.update(self.request(controls={"speed": 50, "forward": 80, "turn": 25})))
        self.assertEqual(self.result()["status"], "rejected")
        self.assertIn("steering", self.result()["message"])
        self.assertEqual(len(self.body.sent), 1)
        await self.update(self.request(2))
        await self.acknowledge_update()
        self.assertNotIn("forward", json.loads(self.body.sent[-1]))
        self.assertEqual(self.adapter.receipts.action(self.original["id"])["state"], "started")

    async def test_supported_steering_requires_paired_finite_bounded_controls(self) -> None:
        for controls in ({"forward": 80}, {"turn": -25}, {"forward": True, "turn": 0},
                         {"forward": float("nan"), "turn": 0}, {"forward": 101, "turn": 0},
                         {"forward": 0, "turn": -101}):
            with self.subTest(controls=controls), self.assertRaises(ProtocolValidationError):
                await self.connection.send_command({"t": "intent", "name": "walk", "dir": "fwd",
                    "steps": 0, "speed": 50, **controls}, received_at=self.now)
        self.assertEqual(self.body.sent, [])
        self.assertEqual(self.connection.next_sequence, 1)

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
        self.assertEqual(command["deadline_ms"], 20495)

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
        await self.connection._handle_control({"t": "cancelled", "seq": 1, "code": "stop"})
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
