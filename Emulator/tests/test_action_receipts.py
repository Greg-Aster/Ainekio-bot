from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import monotonic

from gateway.environment_adapter.action_receipts import ActionReceipts
from gateway.environment_adapter.server import EnvironmentAdapter, EnvironmentAdapterConfig
from gateway.server.service import GatewayConnection, GatewayError, GatewayService, GatewayServiceConfig
from protocol.binary_helpers import CAMERA_JPEG_FRAME_TYPE
from Emulator.tests.test_environment_adapter import FakeGateway, FakeWebSocket, SnapshotGateway


def action(identifier: str, generation: int = 1) -> dict:
    return {"id": identifier, "type": "robotCommand", "command": "walk", "locomotionGoal": {"kind": "visual", "target": "fixture target", "completionCriteria": "fixture criterion"}, "createdAt": datetime.now(timezone.utc).isoformat(),
        "bodyLease": {"bodyId": "ainekio-01", "executionId": "execution-" + str(generation), "generation": generation}}


def accepted(identifier: str) -> dict:
    return {"id": identifier + ":accepted", "actionId": identifier, "type": "accepted", "timestamp": "fixed", "message": "accepted"}


class ActionReceiptTests(unittest.IsolatedAsyncioTestCase):
    async def test_applied_target_adjustments_remain_visible_in_terminal_feedback(self):
        from protocol.control_v1 import validate_control_message
        adapter = EnvironmentAdapter(FakeGateway(), EnvironmentAdapterConfig(token="test", receipt_path=":memory:"))
        try:
            terminal = {"t":"done", "seq":12, "position_verified":False,
                        "target_adjusted_joints":48}
            validate_control_message(terminal)
            result = adapter._terminal_feedback("wave", terminal, command="motion_plan",
                sequence=12, robot_id="test-body", epoch=2)
            self.assertFalse(result["data"]["position_verified"])
            self.assertEqual(result["data"]["target_adjusted_joints"],48)
            for mask in (-1,4096,True):
                with self.assertRaises(ValueError):
                    validate_control_message({**terminal,"target_adjusted_joints":mask})
        finally:
            adapter.receipts.close()

    async def test_status_receipt_timestamp_reaches_snapshot_and_bridge_unchanged(self) -> None:
        gateway = GatewayService(GatewayServiceConfig(tokens={"test-body": "test"}))
        connection = GatewayConnection(gateway, FakeWebSocket(), "test-body", 1)
        gateway._connections["test-body"] = connection
        adapter = EnvironmentAdapter(gateway, EnvironmentAdapterConfig(token="test", receipt_path=":memory:"))
        adapter._websocket = FakeWebSocket()
        gateway.subscribe_events(adapter._handle_gateway_event)
        packet = {"t": "status", "vbat": 0, "rssi": -40, "state": "active", "uptime": 1,
            "heap": 100000, "sd": False, "cam_drops": 0, "mic_drops": 0, "spk_underruns": 0,
            "output_ready": False, "output_armed": False, "output_fault": 1, "power_monitor_ready": False}
        try:
            for instant in (datetime(2026, 10, 14, 23, 0, tzinfo=timezone.utc),
                            datetime(2026, 10, 14, 23, 1, tzinfo=timezone.utc)):
                with patch("gateway.server.service.datetime") as clock:
                    clock.now.return_value = instant
                    await connection._handle_control(packet)
                snapshot = gateway.status()["robots"]["test-body"]["status"]
                telemetry = json.loads(adapter._websocket.sent[-1])["telemetry"]
                self.assertEqual(snapshot["status_received_at"], instant.isoformat())
                self.assertEqual(telemetry["status_received_at"], snapshot["status_received_at"])
                self.assertIs(telemetry["output_ready"], False)
                self.assertIs(telemetry["power_monitor_ready"], False)
        finally:
            adapter.receipts.close()

    async def test_terminal_rejection_preserves_detail_code_and_identity_on_replay(self) -> None:
        adapter = EnvironmentAdapter(FakeGateway(), EnvironmentAdapterConfig(token="test", receipt_path=":memory:"))
        adapter._websocket, adapter._bridge_ready = FakeWebSocket(), True
        try:
            adapter.receipts.receive(action("capture"), accepted("capture"))
            terminal = {"t": "nak", "seq": 12, "code": "busy",
                "msg": "Body is asleep; select Idle before moving"}
            feedback = adapter._terminal_feedback("capture", terminal, command="captureImage",
                sequence=12, robot_id="test-body", epoch=2)
            self.assertEqual(feedback["type"], "rejected")
            self.assertEqual(feedback["message"], terminal["msg"])
            self.assertEqual(feedback["actionId"], "capture")
            self.assertEqual(feedback["data"], {"command": "captureImage", "sequence": 12,
                "robotId": "test-body", "epoch": 2, "code": "busy"})
            await adapter._send_feedback(feedback)
            self.assertEqual(json.loads(adapter.receipts.action("capture")["result"]), feedback)
            adapter._websocket.sent.clear()
            await adapter._replay_pending_feedback(adapter._websocket)
            replayed = [json.loads(item) for item in adapter._websocket.sent]
            self.assertIn(feedback, [item.get("feedback") for item in replayed])
            for terminal, expected_type, expected_message in (
                ({"t": "nak", "seq": 12, "code": "limit"}, "rejected", "limit"),
                ({"t": "done", "seq": 12}, "completed", "done"),
                ({"t": "cancelled", "seq": 12}, "cancelled", "cancelled"),
                ({"t": "nak", "seq": 13, "code": "busy", "msg": "different command"},
                    "outcome_unknown", "different command"),
            ):
                with self.subTest(terminal=terminal):
                    result = adapter._terminal_feedback("capture", terminal, command="captureImage",
                        sequence=12, robot_id="test-body", epoch=2)
                    self.assertEqual(result["type"], expected_type)
                    self.assertEqual(result["message"], expected_message)
                    self.assertEqual(result["data"].get("code"), terminal.get("code"))
        finally:
            adapter.receipts.close()

    async def test_new_feedback_does_not_replay_the_delivery_backlog(self) -> None:
        adapter = EnvironmentAdapter(FakeGateway(), EnvironmentAdapterConfig(token="test", receipt_path=":memory:"))
        adapter._websocket, adapter._bridge_ready = FakeWebSocket(), True
        try:
            adapter.receipts.queue("older", None, {"type": "environment.observation", "observation": {"id": "older"}})
            feedback = adapter._feedback("new", "completed", "done")
            await adapter._send_feedback(feedback)
            self.assertEqual([json.loads(item)["feedback"] for item in adapter._websocket.sent], [feedback])
            self.assertEqual(len(adapter.receipts.pending()), 2)
        finally:
            adapter.receipts.close()

    async def test_replay_is_bound_to_its_connection_and_keeps_unacknowledged_receipts(self) -> None:
        adapter = EnvironmentAdapter(FakeGateway(), EnvironmentAdapterConfig(token="test", receipt_path=":memory:"))
        old, replacement = FakeWebSocket(), FakeWebSocket()
        adapter._websocket, adapter._bridge_ready = old, True
        first = {"type": "environment.observation", "observation": {"id": "first"}}
        second = {"type": "environment.observation", "observation": {"id": "second"}}
        adapter.receipts.queue("first", None, first)
        adapter.receipts.queue("second", None, second)
        send = old.send

        async def replace_after_send(payload):
            await send(payload)
            adapter.receipts.acknowledge("first")
            adapter._websocket = replacement

        old.send = replace_after_send
        try:
            await adapter._replay_pending_feedback(old)
            self.assertEqual([json.loads(item) for item in old.sent], [first])
            self.assertEqual(replacement.sent, [], "Old replay must not migrate to the replacement socket")
            self.assertEqual(adapter.receipts.pending(), [second])
            await adapter._replay_pending_feedback(replacement)
            self.assertEqual([json.loads(item) for item in replacement.sent], [second])
            self.assertEqual(adapter.receipts.pending(), [second], "Sending alone is not acknowledgement")
        finally:
            adapter.receipts.close()

    async def test_historical_unknown_recovery_preserves_evidence_without_producing_it_again(self) -> None:
        adapter = EnvironmentAdapter(FakeGateway(), EnvironmentAdapterConfig(token="test", receipt_path=":memory:"))
        adapter._websocket, adapter._bridge_ready = FakeWebSocket(), True
        try:
            adapter.receipts.receive(action("old"), accepted("old"))
            adapter.receipts.begin("old", {"gatewayInstance": "previous-gateway", "sequence": 1})
            original = adapter._feedback("old", "outcome_unknown", "reconnect")
            await adapter._send_feedback(original)
            await adapter._recover_action_receipts()
            pending = adapter.receipts.pending()
            self.assertEqual(len(pending), 2, "A missing observation is produced once")
            for _ in range(3):
                await adapter._recover_action_receipts()
                self.assertEqual(adapter.receipts.pending(), pending)
            for envelope in pending:
                adapter.receipts.acknowledge((envelope.get("feedback") or envelope["observation"])["id"])
            adapter._websocket.sent.clear()
            await adapter._recover_action_receipts()
            self.assertEqual(adapter.receipts.pending(), [])
            self.assertEqual(adapter._websocket.sent, [])
            self.assertEqual(json.loads(adapter.receipts.action("old")["result"]), original)
            self.assertEqual(adapter.receipts.action("old")["state"], "outcome_unknown")
            self.assertEqual(adapter.gateway.calls, [])
        finally:
            adapter.receipts.close()

    async def test_same_session_recovery_publishes_only_a_new_correlated_result(self) -> None:
        class Gateway(FakeGateway):
            terminal = None

            async def wait_terminal(self, sequence, **kwargs):
                if self.terminal is None:
                    raise GatewayError("reconnect")
                return self.terminal

        gateway = Gateway()
        adapter = EnvironmentAdapter(gateway, EnvironmentAdapterConfig(token="test", receipt_path=":memory:"))
        adapter._websocket, adapter._bridge_ready = FakeWebSocket(), True
        try:
            adapter.receipts.receive(action("same"), accepted("same"))
            adapter.receipts.begin("same", {"gatewayInstance": gateway.instance_id, "robotId": "test-body", "epoch": 1, "sequence": 1})
            for _ in range(3):
                await adapter._recover_action_receipts()
                await asyncio.gather(*tuple(adapter._action_tasks))
                self.assertEqual(len(adapter.receipts.pending()), 2)
            original = json.loads(adapter.receipts.action("same")["result"])
            gateway.terminal = {"t": "done", "seq": 1}
            await adapter._recover_action_receipts()
            await asyncio.gather(*tuple(adapter._action_tasks))
            self.assertEqual(adapter.receipts.action("same")["state"], "terminal")
            observations = [item["observation"] for item in adapter.receipts.pending() if item["type"] == "environment.observation"]
            self.assertEqual(len(observations), 2)
            self.assertEqual(observations[0]["feedback"], [original])
            self.assertEqual(observations[1]["feedback"][0]["type"], "completed")
            self.assertEqual(gateway.calls, [], "Recovery never dispatches the action again")
        finally:
            adapter.receipts.close()

    async def test_new_result_recovers_its_own_observation_after_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = EnvironmentAdapterConfig(token="test", receipt_path=str(Path(directory) / "receipts.sqlite"))
            adapter = EnvironmentAdapter(FakeGateway(), config)
            adapter.receipts.receive(action("changed"), accepted("changed"))
            unknown = adapter._feedback("changed", "outcome_unknown", "unknown")
            await adapter._send_feedback(unknown)
            await adapter._send_observation(feedback=[unknown])
            completed = adapter._feedback("changed", "completed", "done")
            await adapter._send_feedback(completed)
            self.assertEqual(adapter.receipts.action("changed")["observation_recorded"], 0)
            adapter.receipts.close()
            resumed = EnvironmentAdapter(FakeGateway(), config)
            try:
                await resumed._recover_action_receipts()
                observations = [item["observation"] for item in resumed.receipts.pending() if item["type"] == "environment.observation"]
                self.assertEqual([item["feedback"] for item in observations], [[unknown], [completed]])
                self.assertEqual(resumed.receipts.action("changed")["observation_recorded"], 1)
                await resumed._recover_action_receipts()
                self.assertEqual(len(resumed.receipts.pending()), 4)
            finally:
                resumed.receipts.close()

    async def test_action_result_has_no_fixed_duration_cutoff(self) -> None:
        class CompletionGateway(FakeGateway):
            async def wait_terminal(self, sequence: int, **kwargs: object) -> dict[str, object]:
                if kwargs.get("timeout") is not None:
                    raise TimeoutError("fixture: motion outlasted the fixed result deadline")
                return {"t": "done", "seq": sequence}

        gateway = CompletionGateway()
        adapter = EnvironmentAdapter(gateway, EnvironmentAdapterConfig(token="test", receipt_path=":memory:"))
        try:
            result = await adapter.handle_action(action("long-motion"))
            self.assertEqual(result["type"], "completed")
            self.assertEqual(len([call for call in gateway.calls if call[0] == "intent"]), 1)
        finally:
            adapter.receipts.close()

    async def test_recovery_resolves_saved_command_without_resending_it(self) -> None:
        for terminal_type in ("done", "cancelled"):
            with self.subTest(terminal_type=terminal_type):
                gateway = GatewayService(GatewayServiceConfig(tokens={"test-body": "test"}))
                wire_socket = FakeWebSocket()
                connection = GatewayConnection(gateway, wire_socket, "test-body", 7)
                gateway._connections["test-body"] = connection
                adapter = EnvironmentAdapter(gateway, EnvironmentAdapterConfig(
                    token="test", robot_id="test-body", receipt_path=":memory:"))
                adapter._websocket, adapter._bridge_ready = FakeWebSocket(), True
                original = action("recover")
                adapter.receipts.receive(original, accepted("recover"))
                sequence = await connection.send_command({"t": "intent", "name": "stand"},
                    received_at=monotonic(), on_sequence=lambda seq: adapter.receipts.dispatch("recover",
                        {"robotId": "test-body", "epoch": 7, "sequence": seq, "kind": "intent",
                            "gatewayInstance": gateway.instance_id}))
                unknown = {"id": "recover:unknown", "actionId": "recover", "timestamp": "fixed",
                    "type": "outcome_unknown", "message": "result wait expired"}
                await adapter._send_feedback(unknown)
                try:
                    await adapter._recover_action_receipts()
                    # Recovery restores the same camera/result path before
                    # the body produces the action's correlated still.
                    await asyncio.sleep(0)
                    await adapter._handle_gateway_event({"robot_id": "test-body", "epoch": 7,
                        "t": "cam_meta", "fps": 0, "counter_base": 42, "origin": "action", "origin_id": sequence})
                    await adapter._handle_gateway_frame({"robot_id": "test-body", "epoch": 7,
                        "frame_type": CAMERA_JPEG_FRAME_TYPE, "counter": 42, "payload": b"\xff\xd8\xff\xd9"})
                    await connection._handle_control({"t": "ack", "seq": sequence})
                    await connection._handle_control({"t": terminal_type, "seq": sequence})
                    await asyncio.wait_for(asyncio.gather(*tuple(adapter._action_tasks)), 2)
                    receipt = adapter.receipts.action("recover")
                    self.assertEqual(receipt["state"], "terminal")
                    result = json.loads(receipt["result"])
                    self.assertEqual(result["type"], "completed" if terminal_type == "done" else "cancelled")
                    self.assertEqual(result["data"]["sequence"], sequence)
                    self.assertEqual(result["data"]["epoch"], 7)
                    self.assertEqual(len(wire_socket.sent), 1, "Recovery must not send the motion again")
                    if terminal_type == "done":
                        observations = [json.loads(value)["observation"] for value in adapter._websocket.sent
                            if json.loads(value).get("type") == "environment.observation"]
                        self.assertEqual(len(observations), 1)
                        self.assertEqual(observations[0]["visual"]["metadata"]["actionId"], "recover")
                    await adapter._recover_action_receipts()
                    self.assertEqual(json.loads(adapter.receipts.action("recover")["result"]), result)
                finally:
                    for task in tuple(adapter._action_tasks):
                        task.cancel()
                    await asyncio.gather(*adapter._action_tasks, return_exceptions=True)
                    adapter.receipts.close()

    async def test_recovery_after_gateway_restart_ends_only_the_old_control_session(self) -> None:
        for legacy in (False, True):
            with self.subTest(legacy=legacy), tempfile.TemporaryDirectory() as directory:
                receipt_path = str(Path(directory) / "receipts.sqlite")
                original = action("restart")
                original["createdAt"] = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
                receipts = ActionReceipts(receipt_path)
                receipts.receive(original, accepted("restart"))
                receipts.begin("restart", {"robotId": "test-body", "epoch": 1, "sequence": 1, "kind": "intent",
                    **({} if legacy else {"gatewayInstance": "previous-gateway"})})
                receipts.close()
                gateway = GatewayService(GatewayServiceConfig(tokens={"test-body": "test"}))
                adapter = EnvironmentAdapter(gateway, EnvironmentAdapterConfig(
                    token="test", robot_id="test-body", receipt_path=receipt_path))
                adapter._websocket, adapter._bridge_ready = FakeWebSocket(), True
                try:
                    await adapter._recover_action_receipts()
                    await asyncio.wait_for(asyncio.gather(*tuple(adapter._action_tasks)), 2)
                    self.assertEqual(adapter.receipts.action("restart")["state"], "outcome_unknown",
                        "An offline body is not evidence of a new authenticated session")
                    socket = FakeWebSocket()
                    connection = GatewayConnection(gateway, socket, "test-body", 1)
                    gateway._connections["test-body"] = connection
                    connection.completed[1] = {"t": "done", "seq": 1}
                    await adapter._handle_gateway_event({"t": "connection", "status": "connected",
                        "robot_id": "test-body", "epoch": 1})
                    await asyncio.wait_for(asyncio.gather(*tuple(adapter._action_tasks)), 2)
                    feedback = json.loads(adapter.receipts.action("restart")["result"])
                    self.assertEqual(feedback["type"], "outcome_unknown", "A new session's reused seq is not the old result")
                    self.assertIs(feedback["data"].get("executionEnded"), True)
                    self.assertEqual(adapter.receipts.action("restart")["state"], "terminal")
                    self.assertEqual(feedback["data"]["sessionReplacement"]["current"],
                        {"gatewayInstance": gateway.instance_id, "robotId": "test-body", "epoch": 1})
                    self.assertEqual(feedback["data"]["priorOutcome"]["type"], "outcome_unknown")
                    pending = adapter.receipts.pending()
                    await adapter._recover_action_receipts()
                    self.assertEqual(adapter.receipts.pending(), pending, "Settled recovery produces no new work")
                    self.assertEqual(socket.sent, [], "Recovery must not force a stop or repeat an action")
                    adapter.receipts.close()
                    adapter = EnvironmentAdapter(gateway, EnvironmentAdapterConfig(
                        token="test", robot_id="test-body", receipt_path=receipt_path))
                    await adapter._recover_action_receipts()
                    self.assertEqual(adapter.receipts.recoverable(), [])
                    self.assertEqual(json.loads(adapter.receipts.action("restart")["result"]), feedback)
                    self.assertEqual(adapter.receipts.pending(), pending, "Restart retains identical delivery receipts")
                finally:
                    for task in tuple(adapter._action_tasks):
                        task.cancel()
                    await asyncio.gather(*adapter._action_tasks, return_exceptions=True)
                    adapter.receipts.close()

    async def test_same_gateway_reconnect_settles_movement_and_speech_but_preserves_late_correlated_result(self) -> None:
        for kind in ("intent", "speech"):
            with self.subTest(kind=kind):
                gateway = GatewayService(GatewayServiceConfig(tokens={"test-body": "test"}))
                socket = FakeWebSocket()
                gateway._connections["test-body"] = GatewayConnection(gateway, socket, "test-body", 2)
                adapter = EnvironmentAdapter(gateway, EnvironmentAdapterConfig(token="test", receipt_path=":memory:"))
                try:
                    adapter.receipts.receive(action(kind), accepted(kind))
                    adapter.receipts.begin(kind, {"gatewayInstance": gateway.instance_id, "robotId": "test-body",
                        "epoch": 1, "sequence": 1, "kind": kind})
                    original = adapter._feedback(kind, "outcome_unknown", "disconnect")
                    await adapter._send_feedback(original)
                    await adapter._recover_action_receipts()
                    await asyncio.gather(*tuple(adapter._action_tasks))
                    ended = json.loads(adapter.receipts.action(kind)["result"])
                    self.assertIs(ended["data"]["executionEnded"], True)
                    self.assertEqual(ended["data"]["priorOutcome"], original)
                    self.assertEqual(adapter.receipts.action(kind)["state"], "terminal")
                    await adapter._cancel_action({"actionId": kind, "cancellationId": "late-cancel",
                        "bodyLease": action(kind)["bodyLease"]})
                    self.assertEqual(json.loads(adapter.receipts.action(kind)["result"]), ended)
                    actual = adapter._terminal_feedback(kind, {"t": "cancelled", "seq": 1},
                        command=kind, robot_id="test-body", epoch=1, sequence=1)
                    await adapter._send_feedback(actual)
                    self.assertEqual(json.loads(adapter.receipts.action(kind)["result"])["type"], "cancelled")
                    self.assertEqual(socket.sent, [])
                finally:
                    adapter.receipts.close()

    async def test_computer_playback_recovery_ends_only_a_replaced_gateway_process(self) -> None:
        gateway = FakeGateway()
        adapter = EnvironmentAdapter(gateway, EnvironmentAdapterConfig(token="test", receipt_path=":memory:"))
        try:
            for name, instance in (("old", "old-process"), ("current", gateway.instance_id)):
                adapter.receipts.receive(action(name), accepted(name))
                adapter.receipts.begin(name, {"gatewayInstance": instance, "kind": "computer-speech"})
            await adapter._recover_action_receipts()
            await asyncio.gather(*tuple(adapter._action_tasks))
            self.assertEqual(adapter.receipts.action("old")["state"], "terminal")
            self.assertEqual(adapter.receipts.action("current")["state"], "outcome_unknown")
            self.assertEqual(gateway.calls, [])
        finally:
            adapter.receipts.close()

    async def test_gateway_wait_matches_the_original_robot_epoch(self) -> None:
        gateway = GatewayService(GatewayServiceConfig(tokens={"test-body": "test"}))
        connection = GatewayConnection(gateway, FakeWebSocket(), "test-body", 2)
        gateway._connections["test-body"] = connection
        connection.completed[1] = {"t": "done", "seq": 1}
        with self.assertRaisesRegex(GatewayError, "ended robot session"):
            await gateway.wait_terminal(1, robot_id="test-body", epoch=1, timeout=None)
        gateway.terminals.append({"robot_id": "test-body", "epoch": 1, "seq": 1,
            "result": {"t": "cancelled", "seq": 1, "code": "disconnect"}})
        result = await gateway.wait_terminal(1, robot_id="test-body", epoch=1, timeout=None)
        self.assertEqual(result["t"], "cancelled")

    async def test_capture_cancellation_requires_its_receipt_before_releasing_capture_wait(self) -> None:
        gateway = GatewayService(GatewayServiceConfig(tokens={"test-body": "test"}))
        dispatched = asyncio.Queue()

        class Wire(FakeWebSocket):
            async def send(self, value):
                await super().send(value)
                message = json.loads(value)
                await connection._handle_control({"t": "ack", "seq": message["seq"]})
                await dispatched.put(message)

        wire = Wire()
        connection = GatewayConnection(gateway, wire, "test-body", 1)
        connection.last_status = {"camera_ready": True}
        gateway._connections["test-body"] = connection
        adapter = EnvironmentAdapter(gateway, EnvironmentAdapterConfig(token="test", robot_id="test-body", receipt_path=":memory:"))
        adapter._websocket, adapter._bridge_ready = FakeWebSocket(), True
        original = {**action("capture"), "type": "captureImage"}
        try:
            adapter.receipts.receive(original, accepted("capture"))
            await adapter._acknowledge_feedback("capture:accepted", admitted=True)
            self.assertEqual((await asyncio.wait_for(dispatched.get(), 2))["t"], "snap")
            self.assertTrue(adapter._snapshot_lock.locked())
            with patch("gateway.environment_adapter.server.CANCELLATION_TIMEOUT_SECONDS", 0.01):
                await adapter._cancel_action({"actionId": "capture", "cancellationId": "owner-cancel",
                    "bodyLease": original["bodyLease"]})
            self.assertEqual(json.loads(adapter.receipts.action("capture")["result"])["type"], "outcome_unknown")
            self.assertTrue(adapter._snapshot_lock.locked())
            await connection._handle_control({"t": "cancelled", "seq": 1, "code": "stop"})
            await asyncio.wait_for(asyncio.gather(*tuple(adapter._action_tasks)), 2)
            self.assertFalse(adapter._snapshot_lock.locked())
            self.assertEqual(connection.pending, {})
            self.assertEqual(json.loads(adapter.receipts.action("capture")["result"])["type"], "cancelled")
            following = {**action("next", 2), "type": "captureImage"}
            adapter.receipts.receive(following, accepted("next"))
            await adapter._acknowledge_feedback("next:accepted", admitted=True)
            sent = await asyncio.wait_for(dispatched.get(), 2)
            self.assertEqual(sent, {"t": "snap", "seq": 2})
            await connection._handle_control({"t": "done", "seq": 2})
            await asyncio.wait_for(asyncio.gather(*tuple(adapter._action_tasks)), 2)
        finally:
            for task in tuple(adapter._action_tasks):
                task.cancel()
            await asyncio.gather(*adapter._action_tasks, return_exceptions=True)
            adapter.receipts.close()

    async def test_delayed_approval_executes_movement_and_capture_once_across_replay(self) -> None:
        for kind in ("robotCommand", "captureImage"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                receipt_path = str(Path(directory) / "receipts.sqlite")
                gateway = SnapshotGateway()
                clock = [100.0]
                config = EnvironmentAdapterConfig(token="fixture", robot_id="test-body", receipt_path=receipt_path)
                adapter = EnvironmentAdapter(gateway, config, clock=lambda: clock[0])
                adapter._websocket, adapter._bridge_ready = FakeWebSocket(), True
                original = {**action("delayed"), "type": kind, "createdAt": "2000-01-01T00:00:00Z"}
                adapter.receipts.receive(original, accepted("delayed"))
                self.assertEqual(gateway.calls, [], "Admission must precede the physical send")
                clock[0] += 10.0
                await adapter._acknowledge_feedback("delayed:accepted", admitted=True)
                await asyncio.gather(*adapter._action_tasks)
                result = json.loads(adapter.receipts.action("delayed")["result"])
                self.assertEqual(result["type"], "completed")
                self.assertEqual([call[0] for call in gateway.calls], ["intent" if kind == "robotCommand" else "snap", "wait"])
                if kind == "robotCommand":
                    self.assertEqual(gateway.calls[0][1][2]["received_at"], 110.0)
                adapter.receipts.close()
                resumed = EnvironmentAdapter(gateway, config)
                self.assertEqual(resumed.receipts.receive(original, accepted("delayed")), result)
                await resumed._acknowledge_feedback("delayed:accepted", admitted=True)
                self.assertEqual(len(gateway.calls), 2, "Restart and duplicate approval cannot resend the action")
                resumed.receipts.close()

    async def test_shared_fence_is_checked_after_an_old_owner_wakes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "receipts.sqlite")
            old, new = ActionReceipts(path), ActionReceipts(path)
            old.receive(action("old"), accepted("old"))
            new.receive(action("new", 2), accepted("new"))
            with self.assertRaisesRegex(GatewayError, "ownership"):
                old.begin("old", {"sequence": 1})
            self.assertEqual(new.db.execute("SELECT generation FROM body_owner").fetchone()[0], 2)
            new.begin("new", {"sequence": 2})
            with self.assertRaisesRegex(GatewayError, "already"):
                old.begin("new", {"sequence": 2})
            old.close()
            new.close()

    async def test_result_and_delivery_commit_together_and_replay_is_identical(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "receipts.sqlite")
            receipts = ActionReceipts(path)
            original = action("action")
            receipts.receive(original, accepted("action"))
            receipts.begin("action", {"sequence": 1})
            result = {"id": "result", "actionId": "action", "type": "completed", "message": "done", "timestamp": "fixed"}
            message = {"type": "environment.feedback", "feedback": result}
            receipts.db.execute("CREATE TRIGGER fail_delivery BEFORE INSERT ON delivery BEGIN SELECT RAISE(ABORT, 'disk failure'); END")
            with self.assertRaisesRegex(Exception, "disk failure"):
                receipts.queue_feedback(message)
            self.assertEqual(receipts.action("action")["state"], "started")
            receipts.db.execute("DROP TRIGGER fail_delivery")
            receipts.queue_feedback(message)
            receipts.close()
            resumed = ActionReceipts(path)
            self.assertEqual(resumed.pending(), [message])
            self.assertEqual(resumed.receive(original, accepted("action")), result)
            with self.assertRaisesRegex(GatewayError, "different content"):
                resumed.receive({**original, "command": "dance"}, accepted("action"))
            resumed.prune(float("inf"))
            self.assertIsNotNone(resumed.action("action"))
            resumed.acknowledge("result")
            resumed.queue("frame", "action", {"type": "environment.observation", "observation": {"id": "frame"}})
            resumed.acknowledge("frame")
            resumed.prune(float("inf"))
            self.assertIsNone(resumed.action("action"))
            self.assertEqual(resumed.db.execute("SELECT generation FROM body_owner").fetchone()[0], 1)
            resumed.close()

    async def test_cancellation_and_restart_never_resend_a_started_action(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "receipts.sqlite")
            gateway = FakeGateway()
            adapter = EnvironmentAdapter(gateway, EnvironmentAdapterConfig(token="test", receipt_path=path))
            socket = FakeWebSocket()
            adapter._websocket, adapter._bridge_ready = socket, True
            adapter.receipts.receive(action("cancel"), accepted("cancel"))
            await adapter._acknowledge_feedback("cancel:accepted", admitted=False)
            await asyncio.sleep(0)
            self.assertEqual(gateway.calls, [])
            self.assertEqual(adapter.receipts.action("cancel")["state"], "terminal")
            messages = [json.loads(value) for value in socket.sent]
            self.assertTrue(any(value.get("feedback", {}).get("type") == "cancelled" for value in messages))
            self.assertTrue(any(value.get("type") == "environment.observation" for value in messages))
            adapter.receipts.receive(action("started", 2), accepted("started"))
            adapter.receipts.begin("started", {"sequence": 9})
            adapter.receipts.close()
            resumed = EnvironmentAdapter(gateway, EnvironmentAdapterConfig(token="test", receipt_path=path))
            await resumed._recover_action_receipts()
            await resumed._acknowledge_feedback("started:accepted", admitted=True)
            await asyncio.sleep(0)
            self.assertEqual(gateway.calls, [])
            self.assertEqual(resumed.receipts.action("started")["state"], "outcome_unknown")
            self.assertTrue(any(item.get("feedback", {}).get("type") == "outcome_unknown" for item in resumed.receipts.pending()))
            resumed.receipts.close()

    async def test_current_fence_covers_wire_send_and_releases_under_pool_pressure(self) -> None:
        asyncio.get_running_loop().set_default_executor(ThreadPoolExecutor(max_workers=32))
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "receipts.sqlite")
            old, new = ActionReceipts(path), ActionReceipts(path)
            old.receive(action("old"), accepted("old"))
            effects = []

            class Wire(FakeWebSocket):
                def __init__(self, owner, blocked=False):
                    super().__init__()
                    self.owner, self.entered, self.release = owner, asyncio.Event(), asyncio.Event()
                    if not blocked:
                        self.release.set()

                async def send(self, value):
                    self.entered.set()
                    await self.release.wait()
                    effects.append((self.owner, json.loads(value)))

            service = GatewayService(GatewayServiceConfig(tokens={"fixture": "fixture"}, max_action_age_ms=60000))
            first, second = Wire("old", True), Wire("new")
            old_connection = GatewayConnection(service, first, "body", 1)
            new_connection = GatewayConnection(service, second, "body", 1)
            sent = asyncio.create_task(old_connection.send_command(
                {"t": "intent", "name": "walk", "dir": "fwd", "steps": 1}, received_at=monotonic(),
                on_sequence=lambda sequence: old.dispatch("old", {"sequence": sequence, "kind": "intent"})))
            await asyncio.wait_for(first.entered.wait(), 2)
            admission = asyncio.create_task(asyncio.to_thread(new.receive,
                {**action("new", 2), "type": "stop"}, accepted("new")))
            readers = [asyncio.create_task(asyncio.to_thread(old.action, "old")) for _ in range(31)]
            await asyncio.sleep(.05)
            self.assertFalse(admission.done(), "New ownership cannot overtake an in-flight accepted send")
            first.release.set()
            released = True
            try:
                await asyncio.wait_for(asyncio.shield(sent), 1)
            except TimeoutError:
                released = False
                # Release only this fixture's leaked guard so a failing old
                # implementation cannot hang the entire test process.
                old._release_dispatch()
            results = await asyncio.gather(sent, admission, *readers, return_exceptions=True)
            self.assertTrue(released, "Releasing the fence cannot depend on a pool worker waiting for it")
            self.assertFalse(any(isinstance(value, BaseException) for value in results))
            self.assertTrue(all(value["id"] == "old" for value in results[2:]))
            await new_connection.send_command({"t": "stop"}, received_at=monotonic(),
                on_sequence=lambda sequence: new.dispatch("new", {"sequence": sequence, "kind": "stop"}))
            self.assertEqual([owner for owner, _ in effects], ["old", "new"])
            self.assertEqual(new.db.execute("SELECT generation FROM body_owner").fetchone()[0], 2)
            old.close()
            new.close()

    async def test_repeated_cancellation_cannot_orphan_an_acquired_guard(self) -> None:
        receipts = ActionReceipts(":memory:")
        receipts.receive(action("cancel-wait"), accepted("cancel-wait"))
        receipts.begin("cancel-wait", {"sequence": 1})
        loop = asyncio.get_running_loop()
        entered, acquired, released = asyncio.Event(), asyncio.Event(), asyncio.Event()
        acquire = receipts._acquire_dispatch
        release = receipts._release_dispatch

        def observed_acquisition(*args):
            loop.call_soon_threadsafe(entered.set)
            acquire(*args)
            loop.call_soon_threadsafe(acquired.set)

        def observed_release():
            release()
            released.set()

        receipts._acquire_dispatch = observed_acquisition
        receipts._release_dispatch = observed_release
        receipts._lock.acquire()
        guard = receipts._wire_guard("cancel-wait", "started")
        pending = asyncio.create_task(guard.__aenter__())
        await entered.wait()
        pending.cancel()
        await asyncio.sleep(0)
        pending.cancel()
        receipts._lock.release()
        await asyncio.gather(pending, return_exceptions=True)
        await asyncio.wait_for(acquired.wait(), 1)
        try:
            await asyncio.wait_for(released.wait(), 1)
        except TimeoutError:
            pass  # Assert the captured leak after releasing this test fixture.
        leaked = receipts._lock.locked() or receipts.db.in_transaction
        if leaked:
            receipts._release_dispatch()
        receipts.close()
        self.assertFalse(leaked, "Cancelled acquisition must release the transaction even after repeated cancellation")

    async def test_wire_failure_and_legacy_missing_identity_preserve_uncertainty(self) -> None:
        for fail in (True, False):
            with self.subTest(wire_failure=fail):
                service = GatewayService(GatewayServiceConfig(tokens={"fixture": "fixture"}))

                wire_attempts = []

                class Wire(FakeWebSocket):
                    async def send(self, value):
                        wire_attempts.append(value)
                        if fail:
                            raise OSError("controlled wire disconnect")
                        await super().send(value)
                        await connection._handle_control({"t": "ack", "seq": json.loads(value)["seq"]})

                connection = GatewayConnection(service, Wire(), "body", 1)
                service._connections["body"] = connection
                adapter = EnvironmentAdapter(service, EnvironmentAdapterConfig(token="fixture", robot_id="body", receipt_path=":memory:"))
                socket = FakeWebSocket()
                adapter._websocket, adapter._bridge_ready = socket, True
                # Stand now belongs to Freestyle. Use the direct Stop wire path
                # for transport failure, retaining Stand for the legacy receipt.
                original = {**action("transport"), "command": "stop" if fail else "stand"}
                adapter.receipts.receive(original, accepted("transport"))
                if fail:
                    await adapter._process_environment_action(original)
                    self.assertEqual(len(wire_attempts), 1, "The failure must occur after dispatch reaches the wire")
                    self.assertEqual(json.loads(wire_attempts[0])["t"], "stop")
                    expected = "outcome_unknown"
                else:
                    adapter.receipts.begin("transport", {"robotId": "body", "sequence": 9, "kind": "intent"})
                    await adapter._cancel_action({"cancellationId": "transport:cancel", "actionId": "transport",
                        "bodyLease": original["bodyLease"]})
                    expected = "outcome_unknown"
                row = adapter.receipts.action("transport")
                self.assertEqual(json.loads(row["result"])["type"], expected)
                messages = [json.loads(value) for value in socket.sent]
                self.assertTrue(any(value.get("feedback", {}).get("type") == expected for value in messages))
                self.assertTrue(any(value.get("type") == "environment.observation" for value in messages))
                adapter.receipts.close()

    async def test_cancellation_overtaking_delivery_cannot_execute_the_late_original(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "receipts.sqlite")
            gateway = FakeGateway()
            adapter = EnvironmentAdapter(gateway, EnvironmentAdapterConfig(token="fixture", receipt_path=path))
            original = action("late")
            await adapter._cancel_action({"cancellationId": "late:cancel", "actionId": "late", "bodyLease": original["bodyLease"]})
            result = json.loads(adapter.receipts.action("late")["result"])
            self.assertEqual(result["type"], "cancelled")
            adapter.receipts.close()
            resumed = ActionReceipts(path)
            self.assertEqual(resumed.receive(original, accepted("late")), result)
            with self.assertRaisesRegex(GatewayError, "already"):
                resumed.begin("late", {"sequence": 1})
            self.assertEqual(gateway.calls, [])
            resumed.close()

    async def test_terminal_race_publishes_one_committed_result_in_feedback_and_observation(self) -> None:
        class Gateway(FakeGateway):
            def status(self):
                result = super().status()
                result["robots"]["test-body"]["body_command_sequence"] = 1
                return result

            async def wait_terminal(self, sequence, **kwargs):
                return {"t": "cancelled", "seq": sequence, "code": "stop"}

            async def estop(self, **kwargs):
                async with kwargs["on_sequence"](8):
                    self.calls.append(("stop", 8))
                return 8

        adapter = EnvironmentAdapter(Gateway(), EnvironmentAdapterConfig(token="fixture", receipt_path=":memory:"))
        socket = FakeWebSocket()
        adapter._websocket, adapter._bridge_ready = socket, True
        original = action("race")
        adapter.receipts.receive(original, accepted("race"))
        adapter.receipts.begin("race", {"robotId": "test-body", "epoch": 1, "gatewayInstance": adapter.gateway.instance_id, "sequence": 1, "kind": "intent"})
        ready, release = asyncio.Event(), asyncio.Event()
        send = adapter._send_feedback

        async def delayed_cancel(feedback):
            if feedback["type"] == "cancelled":
                ready.set()
                await release.wait()
            return await send(feedback)

        adapter._send_feedback = delayed_cancel
        cancel = asyncio.create_task(adapter._cancel_action({"cancellationId": "race:cancel", "actionId": "race",
            "bodyLease": original["bodyLease"]}))
        await asyncio.wait_for(ready.wait(), 2)
        completed = await send(adapter._feedback("race", "completed", "Natural completion"))
        release.set()
        await cancel
        self.assertEqual(json.loads(adapter.receipts.action("race")["result"]), completed)
        for message in (json.loads(value) for value in socket.sent):
            if message["type"] == "environment.feedback":
                self.assertEqual(message["feedback"], completed)
            elif message["type"] == "environment.observation":
                self.assertEqual(message["observation"]["feedback"], [completed])
        adapter.receipts.close()

    async def test_later_stop_ack_does_not_reconcile_earlier_command_uncertainty(self) -> None:
        receipts = ActionReceipts(":memory:")
        original = action("uncertain")
        receipts.receive(original, accepted("uncertain"))
        receipts.begin("uncertain", {"sequence": 1, "kind": "intent"})
        unknown = {"id": "unknown", "actionId": "uncertain", "timestamp": "fixed", "type": "outcome_unknown", "message": "Acknowledgement lost"}
        receipts.queue_feedback({"type": "environment.feedback", "feedback": unknown})
        retry = receipts.queue_feedback({"type": "environment.feedback", "feedback": {**unknown, "timestamp": "later", "message": "Another delivery attempt"}})
        self.assertEqual(retry["feedback"], unknown)
        other = {**action("other-body"), "bodyLease": {**original["bodyLease"], "bodyId": "other"}}
        receipts.receive(other, accepted("other-body"))
        stop = {**action("stop", 2), "command": "stop"}
        receipts.receive(stop, accepted("stop"))
        receipts.begin("stop", {"sequence": 2, "kind": "stop"})
        self.assertEqual(receipts.action("uncertain")["state"], "outcome_unknown")
        receipts.queue_feedback({"type": "environment.feedback", "feedback": {
            "id": "stop-done", "actionId": "stop", "timestamp": "later", "type": "completed", "message": "Stop acknowledged"}})
        cancelled = json.loads(receipts.action("uncertain")["result"])
        self.assertEqual(cancelled, unknown)
        self.assertEqual(receipts.action("uncertain")["state"], "outcome_unknown")
        self.assertEqual(receipts.action("other-body")["state"], "received")
        self.assertTrue(any(value.get("feedback") == cancelled for value in receipts.pending()))
        receipts.close()


if __name__ == "__main__":
    unittest.main()
