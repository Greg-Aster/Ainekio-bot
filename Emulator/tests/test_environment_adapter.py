from __future__ import annotations

import asyncio
import io
import json
import struct
import unittest
import wave
from datetime import datetime, timezone

from gateway.environment_adapter import (
    EnvironmentAdapter,
    EnvironmentAdapterConfig,
    translate_environment_action,
)
from gateway.environment_adapter.server import AUDIO_UTTERANCE_MAGIC
from protocol.binary_helpers import CAMERA_JPEG_FRAME_TYPE, MIC_PCM_FRAME_TYPE
import websockets
from websockets.exceptions import ConnectionClosedError


class FakeGateway:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.transcripts: list[dict[str, object]] = []
        self.event_callbacks = []
        self.frame_callbacks = []
        self.transcript_callbacks = []

    def subscribe_events(self, callback: object) -> None:
        self.event_callbacks.append(callback)

    def subscribe_frames(self, callback: object) -> None:
        self.frame_callbacks.append(callback)

    def subscribe_transcripts(self, callback: object) -> None:
        self.transcript_callbacks.append(callback)

    async def queue_intent(
        self,
        name: str,
        params: dict[str, object],
        **kwargs: object,
    ) -> int:
        self.calls.append(("intent", (name, params, kwargs)))
        return 7

    async def estop(self, **kwargs: object) -> int:
        self.calls.append(("stop", kwargs))
        return 8

    async def queue_motion_plan(
        self,
        frames: list[object],
        **kwargs: object,
    ) -> int:
        self.calls.append(("motion_plan", (frames, kwargs)))
        return 10

    async def request_snap(self, **kwargs: object) -> int:
        self.calls.append(("snap", kwargs))
        return 9

    async def wait_terminal(self, sequence: int, **kwargs: object) -> dict[str, object]:
        self.calls.append(("wait", (sequence, kwargs)))
        return {"t": "done", "seq": sequence}

    async def publish_transcript(self, transcript: dict[str, object]) -> None:
        self.transcripts.append(transcript)

    def status(self) -> dict[str, object]:
        return {
            "profile": "home",
            "robots": {
                "test-body": {
                    "connected": True,
                    "features": ["motion_plan_v1"],
                    "heartbeat_age_ms": 125,
                    "status": {"camera_ready": True},
                }
            },
        }


class SnapshotGateway(FakeGateway):
    async def request_snap(self, **kwargs: object) -> int:
        self.calls.append(("snap", kwargs))
        for callback in self.frame_callbacks:
            await callback(
                {
                    "robot_id": "test-body",
                    "epoch": 1,
                    "frame_type": CAMERA_JPEG_FRAME_TYPE,
                    "counter": 31,
                    "payload": b"\xff\xd8\xff\xd9",
                }
            )
        return 9


class BlockingMotionGateway(FakeGateway):
    def __init__(self) -> None:
        super().__init__()
        self.motion_waiting = asyncio.Event()
        self.stopped = asyncio.Event()

    async def estop(self, **kwargs: object) -> int:
        self.calls.append(("stop", kwargs))
        self.stopped.set()
        return 8

    async def wait_terminal(self, sequence: int, **kwargs: object) -> dict[str, object]:
        self.calls.append(("wait", (sequence, kwargs)))
        if sequence == 10:
            self.motion_waiting.set()
            await self.stopped.wait()
            return {"t": "cancelled", "seq": sequence, "code": "stop"}
        return {"t": "ack", "seq": sequence}


class FakeWebSocket:
    def __init__(self) -> None:
        self.closed = False
        self.sent: list[str | bytes] = []

    async def send(self, payload: str | bytes) -> None:
        self.sent.append(payload)


class EnvironmentAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_environment_websocket_requires_auth_and_returns_ready_observation(self) -> None:
        gateway = FakeGateway()
        adapter = EnvironmentAdapter(
            gateway,  # type: ignore[arg-type]
            EnvironmentAdapterConfig(token="adapter-secret"),
        )

        async with websockets.serve(
            lambda websocket, _path: adapter.handler(websocket),
            "127.0.0.1",
            0,
            ping_interval=None,
        ) as server:
            port = server.sockets[0].getsockname()[1]
            uri = f"ws://127.0.0.1:{port}/environment"
            async with websockets.connect(uri, ping_interval=None) as websocket:
                await websocket.send(
                    json.dumps(
                        {"type": "bridge.connect", "version": 1, "token": "wrong"}
                    )
                )
                with self.assertRaises(ConnectionClosedError) as closed:
                    await websocket.recv()
                self.assertEqual(closed.exception.code, 4001)

            async with websockets.connect(uri, ping_interval=None) as websocket:
                await websocket.send(
                    json.dumps(
                        {
                            "type": "bridge.connect",
                            "version": 1,
                            "token": "adapter-secret",
                        }
                    )
                )
                ready = json.loads(await websocket.recv())
                self.assertEqual(ready["type"], "bridge.ready")
                self.assertEqual(ready["observation"]["adapter"], "ainekio-gateway")
                self.assertIn(
                    "robotMotionPlan",
                    ready["observation"]["capabilities"]["actions"],
                )
                self.assertIn(
                    "captureImage",
                    ready["observation"]["capabilities"]["actions"],
                )
                self.assertTrue(
                    ready["observation"]["state"]["body"]["authenticated"]
                )

    async def test_authenticated_replacement_closes_previous_without_handler_failure(self) -> None:
        gateway = FakeGateway()
        adapter = EnvironmentAdapter(
            gateway,  # type: ignore[arg-type]
            EnvironmentAdapterConfig(token="adapter-secret"),
        )
        handler_errors: list[Exception] = []

        async def handler(websocket: object, _path: str) -> None:
            try:
                await adapter.handler(websocket)  # type: ignore[arg-type]
            except Exception as error:
                handler_errors.append(error)

        async with websockets.serve(
            handler,
            "127.0.0.1",
            0,
            ping_interval=None,
        ) as server:
            port = server.sockets[0].getsockname()[1]
            uri = f"ws://127.0.0.1:{port}/environment"
            async with websockets.connect(uri, ping_interval=None) as first:
                await first.send(
                    json.dumps(
                        {
                            "type": "bridge.connect",
                            "version": 1,
                            "token": "adapter-secret",
                        }
                    )
                )
                await first.recv()

                async with websockets.connect(uri, ping_interval=None) as second:
                    await second.send(
                        json.dumps(
                            {
                                "type": "bridge.connect",
                                "version": 1,
                                "token": "adapter-secret",
                            }
                        )
                    )
                    await second.recv()
                    with self.assertRaises(ConnectionClosedError) as closed:
                        await first.recv()
                    self.assertEqual(closed.exception.code, 4000)

        self.assertEqual(handler_errors, [])

    async def test_action_feedback_is_followed_by_one_observation(self) -> None:
        gateway = FakeGateway()
        adapter = EnvironmentAdapter(
            gateway,  # type: ignore[arg-type]
            EnvironmentAdapterConfig(
                token="adapter-secret",
                snapshot_after_action=False,
            ),
        )

        async with websockets.serve(
            lambda websocket, _path: adapter.handler(websocket),
            "127.0.0.1",
            0,
            ping_interval=None,
        ) as server:
            port = server.sockets[0].getsockname()[1]
            async with websockets.connect(
                f"ws://127.0.0.1:{port}/environment",
                ping_interval=None,
            ) as websocket:
                await websocket.send(
                    json.dumps(
                        {
                            "type": "bridge.connect",
                            "version": 1,
                            "token": "adapter-secret",
                        }
                    )
                )
                await websocket.recv()
                await websocket.send(
                    json.dumps(
                        {
                            "type": "environment.action",
                            "action": {
                                "id": "action-1",
                                "type": "move",
                                "direction": "forward",
                                "createdAt": datetime.now(timezone.utc).isoformat(),
                            },
                        }
                    )
                )

                feedback = json.loads(await websocket.recv())
                observation = json.loads(await websocket.recv())

        self.assertEqual(feedback["type"], "environment.feedback")
        self.assertEqual(feedback["feedback"]["type"], "completed")
        self.assertEqual(observation["type"], "environment.observation")

    def test_translation_emits_only_bounded_semantic_commands(self) -> None:
        snapshot = translate_environment_action({"type": "captureImage"})
        self.assertEqual(snapshot, translate_environment_action({"type": "capture_image"}))
        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        self.assertEqual((snapshot.kind, snapshot.name), ("snapshot", "captureImage"))

        move = translate_environment_action(
            {"type": "move", "direction": "backward", "units": 99}
        )
        self.assertIsNotNone(move)
        assert move is not None
        self.assertEqual((move.kind, move.name), ("intent", "walk"))
        self.assertEqual(move.params, {"dir": "back", "steps": 10})

        emote = translate_environment_action(
            {"type": "robotCommand", "command": "wave"}
        )
        self.assertIsNotNone(emote)
        assert emote is not None
        self.assertEqual((emote.name, emote.params), ("emote", {"asset": "wave"}))

        self.assertIsNone(
            translate_environment_action(
                {"type": "robotCommand", "command": "R1=180"}
            )
        )

    async def test_capture_image_returns_one_correlated_camera_observation(self) -> None:
        gateway = SnapshotGateway()
        adapter = EnvironmentAdapter(
            gateway,  # type: ignore[arg-type]
            EnvironmentAdapterConfig(token="adapter-secret"),
        )
        websocket = FakeWebSocket()
        adapter._websocket = websocket  # type: ignore[assignment]
        now = datetime.now(timezone.utc)
        robot_observer = {
            "cycleId": "cycle-1",
            "step": 1,
            "maxSteps": 3,
            "triggerSource": "autonomy",
            "graph": "environment",
            "requestedBy": "robot-observer",
        }

        await adapter._process_environment_action(
            {
                "id": "capture-1",
                "type": "captureImage",
                "createdAt": now.isoformat(),
                "correlationId": "cycle-1",
                "metadata": {"robotObserver": robot_observer},
            }
        )

        messages = [
            json.loads(message)
            for message in websocket.sent
            if isinstance(message, str)
        ]
        observations = [
            message["observation"]
            for message in messages
            if message["type"] == "environment.observation"
        ]
        feedback = [
            message["feedback"]
            for message in messages
            if message["type"] == "environment.feedback"
        ]
        self.assertEqual(len(observations), 1)
        self.assertEqual(feedback[0]["type"], "completed")
        self.assertEqual(observations[0]["metadata"]["correlationId"], "cycle-1")
        self.assertEqual(
            observations[0]["metadata"]["robotObserver"],
            robot_observer,
        )
        self.assertEqual(
            observations[0]["visual"]["metadata"]["correlationId"],
            "cycle-1",
        )
        self.assertEqual([call[0] for call in gateway.calls], ["snap", "wait"])

    async def test_post_action_snapshot_preserves_robot_observer_cycle(self) -> None:
        gateway = SnapshotGateway()
        adapter = EnvironmentAdapter(
            gateway,  # type: ignore[arg-type]
            EnvironmentAdapterConfig(
                token="adapter-secret",
                snapshot_after_action=True,
            ),
        )
        websocket = FakeWebSocket()
        adapter._websocket = websocket  # type: ignore[assignment]
        now = datetime.now(timezone.utc)
        robot_observer = {
            "cycleId": "cycle-2",
            "step": 2,
            "maxSteps": 3,
            "triggerSource": "user",
            "graph": "environment",
            "requestedBy": "robot-observer",
        }

        await adapter._process_environment_action(
            {
                "id": "move-2",
                "type": "move",
                "direction": "forward",
                "createdAt": now.isoformat(),
                "correlationId": "cycle-2",
                "metadata": {"robotObserver": robot_observer},
            }
        )

        messages = [
            json.loads(message)
            for message in websocket.sent
            if isinstance(message, str)
        ]
        observation = next(
            message["observation"]
            for message in messages
            if message["type"] == "environment.observation"
        )
        self.assertEqual(observation["metadata"]["robotObserver"], robot_observer)
        self.assertEqual(
            [call[0] for call in gateway.calls],
            ["intent", "wait", "snap", "wait"],
        )

    async def test_freestyle_action_translates_dispatches_and_advertises_only_when_enabled(self) -> None:
        gateway = FakeGateway()
        now = datetime(2026, 7, 17, tzinfo=timezone.utc)
        adapter = EnvironmentAdapter(
            gateway,  # type: ignore[arg-type]
            EnvironmentAdapterConfig(
                token="adapter-secret",
                robot_id="test-body",
                freestyle_enabled=True,
                snapshot_after_action=False,
            ),
            utcnow=lambda: now,
        )
        websocket = FakeWebSocket()
        adapter._websocket = websocket
        targets = [
            {"joint": joint, "degrees": 90.0}
            for joint in ("R1", "R2", "L1", "L2", "R4", "R3", "L3", "L4")
        ]
        result = await adapter.handle_action(
            {
                "id": "plan-1",
                "type": "robotMotionPlan",
                "createdAt": now.isoformat(),
                "frames": [{"durationMs": 300, "targets": targets}],
                "endPose": "hold",
            },
            received_at=12.5,
        )

        self.assertEqual(result["type"], "completed")
        self.assertIn("robotMotionPlan", adapter._observation()["capabilities"]["actions"])
        frames, kwargs = gateway.calls[0][1]  # type: ignore[misc]
        self.assertEqual(frames, [[300, [9000] * 8]])
        self.assertEqual(kwargs["end"], "hold")
        self.assertEqual(kwargs["received_at"], 12.5)
        telemetry = [
            json.loads(message)["telemetry"]
            for message in websocket.sent
            if isinstance(message, str)
            and json.loads(message).get("type") == "environment.telemetry"
        ]
        self.assertEqual(
            [item["status"] for item in telemetry if item["kind"] == "movement.plan"],
            ["validating", "active", "completed"],
        )
        self.assertEqual(telemetry[-1]["frameCount"], 1)
        self.assertEqual(telemetry[-1]["durationMs"], 300)
        self.assertEqual(telemetry[-1]["activeFrame"], 1)
        self.assertEqual(
            adapter._observation()["state"]["freestyleMovement"],
            {"supported": True, "enabled": True, "available": True},
        )

    async def test_stop_can_preempt_an_active_freestyle_action(self) -> None:
        gateway = BlockingMotionGateway()
        now = datetime(2026, 7, 17, tzinfo=timezone.utc)
        adapter = EnvironmentAdapter(
            gateway,  # type: ignore[arg-type]
            EnvironmentAdapterConfig(
                token="adapter-secret",
                robot_id="test-body",
                freestyle_enabled=True,
                snapshot_after_action=False,
            ),
            utcnow=lambda: now,
        )
        targets = [
            {"joint": joint, "degrees": 90}
            for joint in ("R1", "R2", "L1", "L2", "R4", "R3", "L3", "L4")
        ]
        plan_task = asyncio.create_task(adapter.handle_action({
            "id": "plan-1",
            "type": "robotMotionPlan",
            "createdAt": now.isoformat(),
            "frames": [{"durationMs": 1000, "targets": targets}],
            "endPose": "hold",
        }))
        await asyncio.wait_for(gateway.motion_waiting.wait(), timeout=0.2)

        stop_result = await adapter.handle_action({
            "id": "stop-1",
            "type": "stop",
            "createdAt": now.isoformat(),
        })
        plan_result = await asyncio.wait_for(plan_task, timeout=0.2)

        self.assertEqual(stop_result["type"], "completed")
        self.assertEqual(plan_result["type"], "cancelled")
        self.assertEqual([call[0] for call in gateway.calls], [
            "motion_plan", "wait", "stop", "wait",
        ])

    async def test_freestyle_policy_disabled_rejects_without_gateway_dispatch(self) -> None:
        gateway = FakeGateway()
        now = datetime(2026, 7, 17, tzinfo=timezone.utc)
        adapter = EnvironmentAdapter(
            gateway,  # type: ignore[arg-type]
            EnvironmentAdapterConfig(token="adapter-secret", freestyle_enabled=False),
            utcnow=lambda: now,
        )
        targets = [
            {"joint": joint, "degrees": 90}
            for joint in ("R1", "R2", "L1", "L2", "R4", "R3", "L3", "L4")
        ]
        result = await adapter.handle_action(
            {
                "id": "plan-1",
                "type": "robotMotionPlan",
                "createdAt": now.isoformat(),
                "frames": [{"durationMs": 300, "targets": targets}],
            }
        )

        self.assertEqual(result["type"], "rejected")
        self.assertIn("disabled", result["message"])
        self.assertEqual(gateway.calls, [])
        self.assertNotIn("robotMotionPlan", adapter._observation()["capabilities"]["actions"])

    async def test_adapter_rejects_stale_control_before_sequence_assignment(self) -> None:
        gateway = FakeGateway()
        adapter = EnvironmentAdapter(
            gateway,  # type: ignore[arg-type]
            EnvironmentAdapterConfig(token="adapter-secret"),
            clock=lambda: 50.0,
            utcnow=lambda: datetime(2026, 7, 14, tzinfo=timezone.utc),
        )
        result = await adapter.handle_action(
            {
                "id": "action-1",
                "type": "move",
                "direction": "forward",
                "createdAt": "2000-01-01T00:00:00Z",
            },
            received_at=41.25,
        )

        self.assertEqual(result["type"], "expired")
        self.assertEqual(gateway.calls, [])

    async def test_fresh_control_uses_local_monotonic_receipt(self) -> None:
        gateway = FakeGateway()
        now = datetime(2026, 7, 14, tzinfo=timezone.utc)
        adapter = EnvironmentAdapter(
            gateway,  # type: ignore[arg-type]
            EnvironmentAdapterConfig(token="adapter-secret"),
            clock=lambda: 50.0,
            utcnow=lambda: now,
        )
        result = await adapter.handle_action(
            {
                "id": "action-1",
                "type": "move",
                "direction": "forward",
                "createdAt": now.isoformat(),
            },
            received_at=41.25,
        )

        self.assertEqual(result["type"], "completed")
        _name, _params, kwargs = gateway.calls[0][1]  # type: ignore[misc]
        self.assertEqual(kwargs["received_at"], 41.25)

    async def test_text_is_returned_without_becoming_a_body_command(self) -> None:
        gateway = FakeGateway()
        adapter = EnvironmentAdapter(
            gateway,  # type: ignore[arg-type]
            EnvironmentAdapterConfig(token="adapter-secret"),
        )

        result = await adapter.handle_action(
            {"id": "text-1", "type": "sendText", "text": "hello"}
        )

        self.assertEqual(result["type"], "completed")
        self.assertEqual(gateway.calls, [])
        self.assertEqual(gateway.transcripts[0]["text"], "hello")

    async def test_body_action_is_rejected_before_dispatch_when_robot_is_offline(self) -> None:
        gateway = FakeGateway()
        gateway.status = lambda: {"profile": "home", "robots": {}}  # type: ignore[method-assign]
        now = datetime.now(timezone.utc)
        adapter = EnvironmentAdapter(
            gateway,  # type: ignore[arg-type]
            EnvironmentAdapterConfig(token="adapter-secret"),
            utcnow=lambda: now,
        )

        result = await adapter.handle_action(
            {
                "id": "move-offline",
                "type": "move",
                "direction": "forward",
                "createdAt": now.isoformat(),
            }
        )

        self.assertEqual(result["type"], "rejected")
        self.assertEqual(result["message"], "requested robot is not connected")
        self.assertEqual(gateway.calls, [])

    async def test_snapshot_is_rejected_when_body_camera_is_not_ready(self) -> None:
        gateway = FakeGateway()
        gateway.status = lambda: {  # type: ignore[method-assign]
            "profile": "home",
            "robots": {
                "test-body": {
                    "connected": True,
                    "features": [],
                    "heartbeat_age_ms": 10,
                    "status": {"camera_ready": False},
                }
            },
        }
        now = datetime.now(timezone.utc)
        adapter = EnvironmentAdapter(
            gateway,  # type: ignore[arg-type]
            EnvironmentAdapterConfig(token="adapter-secret"),
            utcnow=lambda: now,
        )

        result = await adapter.handle_action(
            {
                "id": "capture-unavailable",
                "type": "captureImage",
                "createdAt": now.isoformat(),
            }
        )

        self.assertEqual(result["type"], "rejected")
        self.assertEqual(result["message"], "camera is not ready")
        self.assertEqual(gateway.calls, [])

    async def test_camera_frame_becomes_bounded_multimodal_observation(self) -> None:
        gateway = FakeGateway()
        adapter = EnvironmentAdapter(
            gateway,  # type: ignore[arg-type]
            EnvironmentAdapterConfig(token="adapter-secret"),
        )
        websocket = FakeWebSocket()
        adapter._websocket = websocket  # type: ignore[assignment]

        await adapter._handle_gateway_frame(
            {
                "robot_id": "test-body",
                "frame_type": CAMERA_JPEG_FRAME_TYPE,
                "counter": 3,
                "payload": b"\xff\xd8\xff\xd9",
            }
        )

        message = json.loads(websocket.sent[0])
        self.assertEqual(message["type"], "environment.observation")
        visual = message["observation"]["visual"]
        self.assertEqual(visual["mimeType"], "image/jpeg")
        self.assertEqual(visual["dataUrl"], "data:image/jpeg;base64,/9j/2Q==")

    async def test_vad_frames_become_one_bounded_binary_wav_utterance(self) -> None:
        gateway = FakeGateway()
        now = datetime(2026, 7, 17, 12, 0, tzinfo=timezone.utc)
        adapter = EnvironmentAdapter(
            gateway,  # type: ignore[arg-type]
            EnvironmentAdapterConfig(token="adapter-secret"),
            utcnow=lambda: now,
        )
        websocket = FakeWebSocket()
        adapter._websocket = websocket  # type: ignore[assignment]
        assembler = adapter._audio_utterances.assembler

        await assembler.handle_event(
            {"t": "event", "name": "vad_open", "robot_id": "test-body", "epoch": 2}
        )
        await assembler.handle_event(
            {"t": "event", "name": "wake_word", "robot_id": "test-body", "epoch": 2}
        )
        await assembler.handle_frame(
            {
                "robot_id": "test-body",
                "epoch": 2,
                "frame_type": MIC_PCM_FRAME_TYPE,
                "counter": 7,
                "payload": bytes([1, 0]) * 320,
            }
        )
        await assembler.handle_frame(
            {
                "robot_id": "test-body",
                "epoch": 2,
                "frame_type": MIC_PCM_FRAME_TYPE,
                "counter": 9,
                "payload": bytes([2, 0]) * 320,
            }
        )
        await assembler.handle_event(
            {"t": "event", "name": "vad_close", "robot_id": "test-body", "epoch": 2}
        )

        self.assertEqual(len(websocket.sent), 1)
        encoded = websocket.sent[0]
        self.assertIsInstance(encoded, bytes)
        assert isinstance(encoded, bytes)
        self.assertEqual(encoded[:8], AUDIO_UTTERANCE_MAGIC)
        metadata_bytes = struct.unpack("<I", encoded[8:12])[0]
        metadata = json.loads(encoded[12 : 12 + metadata_bytes])
        wav_payload = encoded[12 + metadata_bytes :]
        self.assertEqual(metadata["type"], "audio.utterance")
        self.assertEqual(metadata["utteranceId"].count("-"), 4)
        self.assertEqual(metadata["robotId"], "test-body")
        self.assertEqual(metadata["firstCounter"], 7)
        self.assertEqual(metadata["lastCounter"], 9)
        self.assertEqual(metadata["frameCount"], 2)
        self.assertEqual(metadata["missingFrames"], 1)
        self.assertEqual(metadata["durationMs"], 60)
        self.assertTrue(metadata["wakeTriggered"])
        with wave.open(io.BytesIO(wav_payload), "rb") as wav:
            self.assertEqual(wav.getparams()[:4], (1, 2, 16000, 960))
            pcm = wav.readframes(960)
        self.assertEqual(pcm[640:1280], bytes(640))

    async def test_body_event_name_is_preserved_in_environment_state(self) -> None:
        gateway = FakeGateway()
        adapter = EnvironmentAdapter(
            gateway,  # type: ignore[arg-type]
            EnvironmentAdapterConfig(token="adapter-secret"),
        )
        websocket = FakeWebSocket()
        adapter._websocket = websocket  # type: ignore[assignment]

        await adapter._handle_gateway_event(
            {"t": "event", "name": "wake_word", "robot_id": "test-body", "epoch": 1}
        )

        message = json.loads(websocket.sent[0])
        self.assertEqual(message["observation"]["state"]["bodyEvent"]["name"], "wake_word")

    async def test_vad_close_clears_microphone_meter_before_body_event(self) -> None:
        gateway = FakeGateway()
        adapter = EnvironmentAdapter(
            gateway,  # type: ignore[arg-type]
            EnvironmentAdapterConfig(token="adapter-secret"),
        )
        websocket = FakeWebSocket()
        adapter._websocket = websocket  # type: ignore[assignment]

        await adapter._handle_gateway_event(
            {"t": "event", "name": "vad_close", "robot_id": "test-body", "epoch": 1}
        )

        telemetry = json.loads(websocket.sent[0])
        observation = json.loads(websocket.sent[1])
        self.assertEqual(telemetry["telemetry"]["kind"], "audio.level")
        self.assertEqual(telemetry["telemetry"]["level"], 0.0)
        self.assertEqual(
            observation["observation"]["state"]["bodyEvent"]["name"],
            "vad_close",
        )

    async def test_robot_status_uses_diagnostic_telemetry_not_an_observation(self) -> None:
        gateway = FakeGateway()
        adapter = EnvironmentAdapter(
            gateway,  # type: ignore[arg-type]
            EnvironmentAdapterConfig(token="adapter-secret"),
        )
        websocket = FakeWebSocket()
        adapter._websocket = websocket  # type: ignore[assignment]

        await adapter._handle_gateway_event(
            {
                "t": "status",
                "robot_id": "test-body",
                "epoch": 1,
                "vbat": 7.4,
                "rssi": -52,
                "state": "active",
                "uptime": 12,
                "heap": 120000,
                "sd": True,
                "camera_ready": True,
                "cam_drops": 2,
                "spk_underruns": 3,
                "mic_drops": 4,
                "wake_ready": False,
            }
        )

        message = json.loads(websocket.sent[0])
        self.assertEqual(message["type"], "environment.telemetry")
        self.assertEqual(message["telemetry"]["kind"], "robot.status")
        self.assertTrue(message["telemetry"]["camera_ready"])
        self.assertEqual(message["telemetry"]["mic_drops"], 4)
        self.assertNotIn("observation", message)

    async def test_microphone_level_telemetry_is_throttled_without_relaying_pcm(self) -> None:
        gateway = FakeGateway()
        now = 0.0
        adapter = EnvironmentAdapter(
            gateway,  # type: ignore[arg-type]
            EnvironmentAdapterConfig(token="adapter-secret"),
            clock=lambda: now,
        )
        websocket = FakeWebSocket()
        adapter._websocket = websocket  # type: ignore[assignment]
        frame = {
            "robot_id": "test-body",
            "epoch": 1,
            "frame_type": MIC_PCM_FRAME_TYPE,
            "counter": 10,
            "payload": struct.pack("<320h", *([16384] * 320)),
        }

        await adapter._handle_gateway_frame(frame)
        await adapter._handle_gateway_frame({**frame, "counter": 11})
        now = 0.11
        await adapter._handle_gateway_frame({**frame, "counter": 12})

        self.assertEqual(len(websocket.sent), 2)
        first = json.loads(websocket.sent[0])
        self.assertEqual(first["telemetry"]["kind"], "audio.level")
        self.assertEqual(first["telemetry"]["level"], 0.5)
        self.assertNotIn("payload", first["telemetry"])

    async def test_maximum_duration_emits_one_truncated_utterance_until_vad_closes(self) -> None:
        gateway = FakeGateway()
        adapter = EnvironmentAdapter(
            gateway,  # type: ignore[arg-type]
            EnvironmentAdapterConfig(
                token="adapter-secret",
                max_utterance_ms=40,
            ),
        )
        websocket = FakeWebSocket()
        adapter._websocket = websocket  # type: ignore[assignment]
        assembler = adapter._audio_utterances.assembler
        identity = {"robot_id": "test-body", "epoch": 1}

        await assembler.handle_event({"t": "event", "name": "vad_open", **identity})
        for counter in range(3):
            await assembler.handle_frame(
                {
                    **identity,
                    "frame_type": MIC_PCM_FRAME_TYPE,
                    "counter": counter,
                    "payload": bytes(640),
                }
            )
        await assembler.handle_event({"t": "event", "name": "vad_close", **identity})

        self.assertEqual(len(websocket.sent), 1)
        encoded = websocket.sent[0]
        assert isinstance(encoded, bytes)
        metadata_bytes = struct.unpack("<I", encoded[8:12])[0]
        metadata = json.loads(encoded[12 : 12 + metadata_bytes])
        self.assertEqual(metadata["durationMs"], 40)
        self.assertTrue(metadata["truncated"])

    async def test_bridge_originated_text_is_not_echoed_back_as_observation(self) -> None:
        gateway = FakeGateway()
        adapter = EnvironmentAdapter(
            gateway,  # type: ignore[arg-type]
            EnvironmentAdapterConfig(token="adapter-secret"),
        )
        websocket = FakeWebSocket()
        adapter._websocket = websocket  # type: ignore[assignment]

        await adapter._handle_gateway_transcript(
            {"source": "environment_adapter", "text": "hello"}
        )

        self.assertEqual(websocket.sent, [])

    async def test_periodic_status_does_not_queue_environment_observation(self) -> None:
        gateway = FakeGateway()
        adapter = EnvironmentAdapter(
            gateway,  # type: ignore[arg-type]
            EnvironmentAdapterConfig(token="adapter-secret"),
        )
        websocket = FakeWebSocket()
        adapter._websocket = websocket  # type: ignore[assignment]

        await adapter._handle_gateway_event({"t": "status", "battery": 80})

        self.assertEqual(len(websocket.sent), 1)
        message = json.loads(websocket.sent[0])
        self.assertEqual(message["type"], "environment.telemetry")
        self.assertNotIn("observation", message)

    def test_adapter_requires_a_bounded_secret(self) -> None:
        with self.assertRaisesRegex(ValueError, "token"):
            EnvironmentAdapterConfig(token="")


if __name__ == "__main__":
    unittest.main()
