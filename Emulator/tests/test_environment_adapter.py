from __future__ import annotations

import asyncio
import io
import json
import struct
import unittest
import wave
from datetime import datetime, timedelta, timezone

from gateway.environment_adapter import (
    EnvironmentAdapter,
    EnvironmentAdapterConfig,
    translate_environment_action,
)
from gateway.environment_adapter.server import AUDIO_UTTERANCE_MAGIC
from gateway.server.service import CONTROL_STALE_SECONDS, GatewayError
from protocol.binary_helpers import CAMERA_JPEG_FRAME_TYPE, MIC_PCM_FRAME_TYPE
import websockets
from websockets.legacy.server import serve
from websockets.legacy.client import connect
from websockets.exceptions import ConnectionClosedError


class FakeGateway:
    def __init__(self) -> None:
        self.instance_id = "fixture-gateway"
        self.calls: list[tuple[str, object]] = []
        self.transcripts: list[dict[str, object]] = []
        self.event_callbacks = []
        self.frame_callbacks = []
        self.transcript_callbacks = []

    def subscribe_events(self, callback: object) -> None:
        self.event_callbacks.append(callback)

    def subscribe_external_speech(self, callback):
        pass

    def subscribe_frames(self, callback: object) -> None:
        self.frame_callbacks.append(callback)

    def subscribe_transcripts(self, callback: object) -> None:
        self.transcript_callbacks.append(callback)

    async def request_motion(self, name, *, robot_id=None, job_id=None, **kwargs):
        self.calls.append(("request_motion", (name, robot_id)))
        self.motion_robot_id=robot_id
        return {"system": "freestyle", "jobId": job_id or "fixture-motion"}

    async def freestyle_result(self, job_id):
        self.calls.append(("freestyle_result", (job_id, self.motion_robot_id)))
        return {"id":job_id,"state":"completed","robot_id":self.motion_robot_id,"epoch":1,"receipts":[]}

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

    async def cancel_speech(self, **kwargs: object) -> int:
        self.calls.append(("cancel_speech", kwargs))
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
                    "epoch": 1,
                    "features": ["motion_plan_v1"],
                    "heartbeat_age_ms": 125,
                    "status": {"camera_ready": True},
                }
            },
        }


class SnapshotGateway(FakeGateway):
    def __init__(self) -> None:
        super().__init__()
        self.camera_counter = 31

    async def _emit_snapshot(self, origin: str, origin_id: int) -> None:
        counter = self.camera_counter
        self.camera_counter += 1
        for callback in self.event_callbacks:
            await callback(
                {
                    "robot_id": "test-body",
                    "epoch": 1,
                    "t": "cam_meta",
                    "res": "XGA",
                    "fps": 0,
                    "counter_base": counter,
                    "origin": origin,
                    "origin_id": origin_id,
                }
            )
        for callback in self.frame_callbacks:
            await callback(
                {
                    "robot_id": "test-body",
                    "epoch": 1,
                    "frame_type": CAMERA_JPEG_FRAME_TYPE,
                    "counter": counter,
                    "payload": b"\xff\xd8\xff\xd9",
                }
            )

    async def request_snap(self, **kwargs: object) -> int:
        self.calls.append(("snap", kwargs))
        await self._emit_snapshot("request", 9)
        return 9

    async def wait_terminal(self, sequence: int, **kwargs: object) -> dict[str, object]:
        self.calls.append(("wait", (sequence, kwargs)))
        if sequence != 9:
            await self._emit_snapshot("action", sequence)
        return {"t": "done", "seq": sequence}


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


class BlockingWebSocket(FakeWebSocket):
    def __init__(self) -> None:
        super().__init__()
        self.send_started = asyncio.Event()
        self.release_send = asyncio.Event()

    async def send(self, payload: str | bytes) -> None:
        self.send_started.set()
        await self.release_send.wait()
        await super().send(payload)


class EnvironmentAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_wake_delivers_its_photo_and_recognition_together_without_holding_robot_receive(self):
        from gateway.plugins import CameraFramePlugin
        from gateway.perception import RecognitionResult, RecognizedObject
        class Gateway(SnapshotGateway):
            def clock(self):
                return asyncio.get_running_loop().time()
            def unsubscribe_frames(self, callback):
                self.frame_callbacks.remove(callback)
            async def _publish_event(self, event):
                for callback in self.event_callbacks:
                    await callback(event)
            def status(self):
                state = super().status()
                state["robots"]["test-body"]["connection_state"] = "online"
                return state
        for failed in (False, True):
            gateway = Gateway()
            adapter = EnvironmentAdapter(gateway, EnvironmentAdapterConfig(token="test", receipt_path=":memory:"))
            socket = FakeWebSocket()
            adapter._websocket, adapter._bridge_ready = socket, True
            started, release = asyncio.Event(), asyncio.Event()
            calls = []
            async def recognize(jpeg):
                calls.append(jpeg)
                started.set()
                await release.wait()
                if failed:
                    raise ValueError("fixture recognition failure")
                return RecognitionResult("fixture", "person-identity", "one face match", (
                    RecognizedObject("person", .9, (.1, .1, .5, .8),
                        {"state": "face_match", "trackId": "t", "personId": "p", "name": "Fixture Person", "faceAgeMs": 0, "similarity": .7}),), ())
            camera = CameraFramePlugin(gateway, recognize)
            adapter.camera_capture, adapter.camera_analysis = camera.capture, camera.latest_analysis
            event = {"t": "event", "name": "body_event", "robot_id": "test-body", "epoch": 1,
                "event_id": "fixture-boot", "data": {"kind": "wake", "reason": "boot"}}
            wake = asyncio.create_task(adapter._process_wake(event, socket))
            try:
                await asyncio.wait_for(started.wait(), 1)
                await adapter._handle_gateway_transcript({"text": "an independent request"})
                self.assertTrue(any("an independent request" in item for item in socket.sent))
                self.assertFalse(any(json.loads(item).get("observation", {}).get("visual") for item in socket.sent))
                release.set()
                await asyncio.wait_for(wake, 1)
                observation = next(json.loads(item)["observation"] for item in socket.sent if json.loads(item).get("observation", {}).get("visual"))
                visual = observation["visual"]
                self.assertEqual(visual["metadata"]["counter"], 31)
                self.assertEqual(visual["metadata"]["bodyEventId"], "fixture-boot")
                self.assertEqual(visual["dataUrl"], "data:image/jpeg;base64,/9j/2Q==")
                self.assertNotIn("_recognition_result", visual)
                if failed:
                    self.assertIn("fixture recognition failure", visual["metadata"]["recognitionFailure"]["reason"])
                    self.assertNotIn("recognition", visual["metadata"])
                else:
                    recognition = visual["metadata"]["recognition"]
                    self.assertEqual(recognition["frameCounter"], visual["metadata"]["counter"])
                    self.assertEqual(recognition["observedAt"], visual["timestamp"])
                    self.assertEqual(recognition["objects"][0]["identity"]["name"], "Fixture Person")
                self.assertEqual(calls, [b"\xff\xd8\xff\xd9"])
                self.assertEqual(camera._inflight, {})
                self.assertEqual(adapter._pending_action_visuals, {})
                self.assertEqual([call[0] for call in gateway.calls], ["request_motion", "snap", "wait"])
            finally:
                release.set()
                wake.cancel()
                await asyncio.gather(wake, return_exceptions=True)
                await camera.aclose()
                adapter.receipts.close()

    async def test_large_observation_replay_preserves_content_and_drains_on_ack(self) -> None:
        from websockets.legacy.server import serve
        from websockets.legacy.client import connect

        adapter = EnvironmentAdapter(FakeGateway(), EnvironmentAdapterConfig(token="test", receipt_path=":memory:"))
        observation = {"id": "large-frame", "timestamp": "2026-10-20T20:18:17Z",
                       "visual": {"dataUrl": "data:image/jpeg;base64," + "a" * 600_000},
                       "state": {"locomotionMeasurement": {"position": {
                           "depthPreview": "data:image/png;base64," + "b" * 114_000}}}}
        envelope = {"type": "environment.observation", "version": 1, "observation": observation}
        adapter.receipts.queue(observation["id"], None, envelope)
        try:
            async with serve(lambda ws, _: adapter.handler(ws), "127.0.0.1", 0, max_size=None) as server:
                url = f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}"
                # An unacknowledged disconnect must preserve the original message.
                for acknowledge in (False, True):
                    async with connect(url, max_size=None) as ws:
                        await ws.send(json.dumps({"type": "bridge.connect", "version": 1, "token": "test"}))
                        self.assertEqual(json.loads(await ws.recv())["type"], "bridge.ready")
                        self.assertEqual(json.loads(await asyncio.wait_for(ws.recv(), 3)), envelope)
                        if acknowledge:
                            await ws.send(json.dumps({"type": "environment.observation.ack",
                                                     "observationId": observation["id"], "admitted": True}))
                            async with asyncio.timeout(3):
                                while adapter.receipts.pending():
                                    await asyncio.sleep(0.001)
                        else:
                            self.assertEqual(adapter.receipts.pending(), [envelope])
                self.assertEqual(adapter.receipts.pending(), [])
                self.assertEqual(adapter.gateway.calls, [])
            self.assertEqual(adapter._decode_message(json.dumps(envelope)), envelope)
            with self.assertRaises(ValueError):
                adapter._decode_message("[]")
        finally:
            adapter.receipts.close()

    async def test_new_offline_input_is_not_queued_but_existing_input_resumes(self) -> None:
        adapter = EnvironmentAdapter(SnapshotGateway(), EnvironmentAdapterConfig(token="test", receipt_path=":memory:"))
        event = {"t": "event", "name": "body_event", "robot_id": "test-body", "epoch": 1,
                 "event_id": "boot-event", "data": {"kind": "wake", "reason": "boot"}}
        visual = {"dataUrl": "data:image/jpeg;base64," + "a" * 600_000, "timestamp": "2026-10-20T20:18:17Z"}

        async def publish():
            await adapter._handle_gateway_event(event)
            await asyncio.gather(*adapter._action_tasks)
            await adapter._handle_gateway_transcript({"text": "fixture transcript"})
            await adapter._send_observation(visual=visual, metadata={"perceptionEvent": "audio_utterance"})

        try:
            await publish()
            self.assertEqual(adapter.receipts.pending(), [], "Offline input must not be saved for later reactions")
            connected = FakeWebSocket()
            adapter._websocket, adapter._bridge_ready = connected, True
            await adapter._replay_pending_feedback(connected)
            self.assertEqual(connected.sent, [])
            await publish()
            observations = [json.loads(message)["observation"] for message in connected.sent]
            self.assertEqual(len(observations), 3)
            self.assertEqual(observations[0]["state"]["bodyEvent"]["event_id"], "boot-event")
            self.assertEqual(observations[1]["text"][0]["text"], "fixture transcript")
            self.assertEqual(observations[2]["visual"], visual)
            saved = adapter.receipts.pending()
            self.assertEqual([item["observation"] for item in saved], observations)
            connected.closed = True
            await publish()
            replacement = FakeWebSocket()
            adapter._websocket = replacement
            await adapter._replay_pending_feedback(replacement)
            self.assertEqual([json.loads(item) for item in replacement.sent], saved,
                             "Previously admitted input resumes; new offline input is absent")
            for item in saved:
                adapter.receipts.acknowledge(item["observation"]["id"])
            self.assertEqual(adapter.receipts.pending(), [])
            self.assertEqual([call[0] for call in adapter.gateway.calls], ["request_motion", "snap", "wait"] * 3)
            self.assertEqual(adapter.gateway.calls[0][1][0], "Stand up, stretch, and finish standing.")
        finally:
            adapter.receipts.close()

    async def test_disconnect_after_admission_preserves_input_for_reconnect(self) -> None:
        adapter = EnvironmentAdapter(FakeGateway(), EnvironmentAdapterConfig(token="test", receipt_path=":memory:"))

        class DisconnectedSocket(FakeWebSocket):
            async def send(self, payload):
                self.closed = True
                raise OSError("fixture connection lost")

            async def close(self, **kwargs):
                self.closed = True

        adapter._websocket, adapter._bridge_ready = DisconnectedSocket(), True
        try:
            await adapter._send_observation(text=[{"id": "live-text", "source": "environment", "text": "fixture"}])
            saved = adapter.receipts.pending()
            self.assertEqual(len(saved), 1)
            replacement = FakeWebSocket()
            adapter._websocket = replacement
            await adapter._replay_pending_feedback(replacement)
            self.assertEqual([json.loads(item) for item in replacement.sent], saved)
        finally:
            adapter.receipts.close()

    async def test_reconnect_replay_reads_acknowledgements_and_drains_without_regeneration(self) -> None:
        adapter = EnvironmentAdapter(FakeGateway(), EnvironmentAdapterConfig(token="test", receipt_path=":memory:"))
        for index in range(256):
            observation = {"id": f"replay-{index}"}
            adapter.receipts.queue(observation["id"], None, {"type": "environment.observation", "observation": observation})
        acknowledged = asyncio.Event()
        loop = asyncio.get_running_loop()
        acknowledge = adapter.receipts.acknowledge
        send = adapter._send

        def record_ack(identifier):
            acknowledge(identifier)
            if identifier == "replay-0":
                loop.call_soon_threadsafe(acknowledged.set)

        async def replay_send(message, **kwargs):
            if message.get("observation", {}).get("id") == "replay-1":
                await asyncio.wait_for(acknowledged.wait(), 2)
            return await send(message, **kwargs)

        adapter.receipts.acknowledge = record_ack
        adapter._send = replay_send
        try:
            async with serve(lambda ws, _: adapter.handler(ws), "127.0.0.1", 0) as server:
                url = f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}"
                async with connect(url) as ws:
                    await ws.send(json.dumps({"type": "bridge.connect", "version": 1, "token": "test"}))
                    self.assertEqual(json.loads(await ws.recv())["type"], "bridge.ready")
                    for index in range(256):
                        message = json.loads(await asyncio.wait_for(ws.recv(), 3))
                        self.assertEqual(message["observation"]["id"], f"replay-{index}")
                        await ws.send(json.dumps({"type": "environment.observation.ack", "observationId": f"replay-{index}", "admitted": True}))
                    async with asyncio.timeout(3):
                        while adapter.receipts.pending():
                            await asyncio.sleep(0.001)
                async with connect(url) as ws:
                    await ws.send(json.dumps({"type": "bridge.connect", "version": 1, "token": "test"}))
                    self.assertEqual(json.loads(await ws.recv())["type"], "bridge.ready")
                    self.assertEqual(adapter.receipts.pending(), [])
                    self.assertEqual(adapter.gateway.calls, [])
        finally:
            adapter.receipts.close()

    async def test_behavior_settings_roundtrip_errors_and_disconnect(self) -> None:
        adapter = EnvironmentAdapter(FakeGateway(), EnvironmentAdapterConfig(
            receipt_path=":memory:", token="adapter-secret"))
        with self.assertRaisesRegex(GatewayError, "MetaHuman Environment Bridge is disconnected"):
            await adapter.behavior_settings()
        async with serve(lambda ws, _: adapter.handler(ws), "127.0.0.1", 0) as server:
            async with connect(f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}") as ws:
                await ws.send(json.dumps({"type": "bridge.connect", "version": 1, "token": "adapter-secret"}))
                self.assertEqual(json.loads(await ws.recv())["type"], "bridge.ready")
                for enabled in (None, False, True):
                    request = asyncio.create_task(adapter.behavior_settings(enabled))
                    message = json.loads(await ws.recv())
                    self.assertEqual(message["type"], "behavior.settings")
                    self.assertEqual(message.get("enabled"), enabled)
                    await ws.send(json.dumps({"type": "behavior.settings.result", "requestId": "unrelated", "enabled": True}))
                    self.assertFalse(request.done())
                    await ws.send(json.dumps({"type": "behavior.settings.result", "requestId": message["requestId"],
                        "enabled": enabled or False, "unresolvedActions": [{"id": "waiting-for-terminal"}]}))
                    result = await request
                    self.assertEqual(result["enabled"], enabled or False)
                    self.assertEqual(result["unresolvedActions"], [{"id": "waiting-for-terminal"}])
                request = asyncio.create_task(adapter.behavior_settings(True))
                message = json.loads(await ws.recv())
                await ws.send(json.dumps({"type": "behavior.settings.result", "requestId": message["requestId"], "error": "Sign in first"}))
                with self.assertRaisesRegex(GatewayError, "Sign in first"):
                    await request
                request = asyncio.create_task(adapter.behavior_settings())
                await ws.recv()
                await ws.close()
                with self.assertRaisesRegex(GatewayError, "disconnected"):
                    await request
        self.assertFalse(adapter._settings_requests)

    async def test_cancel_after_switch_stays_addressed_to_original_robot(self) -> None:
        class PendingSpeechGateway(FakeGateway):
            async def wait_terminal(self, sequence, **kwargs):
                if kwargs.get("timeout") == 0:
                    raise TimeoutError
                return await super().wait_terminal(sequence, **kwargs)

        gateway = PendingSpeechGateway()
        adapter = EnvironmentAdapter(gateway, EnvironmentAdapterConfig(
            receipt_path=":memory:", token="adapter-secret"))
        adapter._websocket = FakeWebSocket()
        adapter.receipts.receive({"id": "old-speech", "type": "speechAudio"},
                                 adapter._feedback("old-speech", "accepted", "accepted"))
        adapter.receipts.begin("old-speech", {"robotId": "previous-body", "epoch": 1,
            "sequence": 4, "gatewayInstance": gateway.instance_id})
        await adapter._cancel_action({"actionId": "old-speech", "cancellationId": "cancel-old"})
        self.assertEqual(gateway.calls[0][0], "cancel_speech")
        self.assertEqual(gateway.calls[0][1]["robot_id"], "previous-body")
        self.assertEqual(gateway.calls[1][1][1]["robot_id"], "previous-body")

    async def test_automatic_selection_switches_v1_v2_v1_with_audio_and_commands(self) -> None:
        gateway = FakeGateway()
        robots = {
            "v1": {"connected": False, "model": "v1-8servo", "epoch": 1,
                   "features": [], "status": {"camera_ready": True}},
            "v2": {"connected": False, "model": "v2-12servo", "epoch": 2,
                   "features": ["body_commands_v1"], "status": {"camera_ready": True},
                   "capabilities": {"commands": ["stand", "walk", "run", "stop", "say", "face"],
                                    "motion": True, "speaker": True, "microphone": True}},
        }
        gateway.status = lambda: {"robots": robots}
        adapter = EnvironmentAdapter(gateway, EnvironmentAdapterConfig(
            receipt_path=":memory:", token="adapter-secret"))
        websocket = FakeWebSocket()
        adapter._websocket = websocket
        assembler = adapter._audio_utterances.assembler
        for index, robot_id in enumerate(("v1", "v2", "v1")):
            for name, robot in robots.items():
                robot["connected"] = name == robot_id
            observation = adapter._observation()
            self.assertEqual(observation["state"]["body"]["robotId"], robot_id)
            self.assertTrue(observation["state"]["body"]["authenticated"])
            self.assertTrue(observation["state"]["body"]["speakerReady"])
            self.assertTrue(observation["capabilities"]["movement"])
            identity = {"robot_id": robot_id, "epoch": robots[robot_id]["epoch"]}
            await assembler.handle_event({**identity, "t": "event", "name": "vad_open"})
            await assembler.handle_event({**identity, "t": "event", "name": "wake_word"})
            await assembler.handle_frame({**identity, "frame_type": MIC_PCM_FRAME_TYPE,
                                          "counter": index, "payload": bytes([index, 0]) * 320})
            await assembler.handle_event({**identity, "t": "event", "name": "vad_close"})
            encoded = websocket.sent[-1]
            size = struct.unpack("<I", encoded[8:12])[0]
            metadata = json.loads(encoded[12:12 + size])
            self.assertEqual(metadata["robotId"], robot_id)
            self.assertTrue(metadata["wakeTriggered"])
            self.assertEqual(metadata["frameCount"], 1)
            result = await adapter.handle_action({"id": f"stand-{index}", "type": "robotCommand",
                                                  "command": "stand"})
            self.assertEqual(result["type"], "completed")
            self.assertEqual(gateway.calls[-2], ("request_motion", ("stand", robot_id)))
            self.assertEqual(gateway.calls[-1][1][1], robot_id)
        robots["v2"]["connected"] = True
        self.assertEqual(adapter._selected_robot(), (None, None))
        for robot in robots.values():
            robot["connected"] = False
        self.assertEqual(adapter._selected_robot(), (None, None))

    async def test_environment_websocket_requires_auth_and_returns_ready_observation(self) -> None:
        gateway = FakeGateway()
        adapter = EnvironmentAdapter(
            gateway,  # type: ignore[arg-type]
            EnvironmentAdapterConfig(receipt_path=":memory:", token="adapter-secret"),
        )

        async with serve(
            lambda websocket, _path: adapter.handler(websocket),
            "127.0.0.1",
            0,
            ping_interval=None,
        ) as server:
            port = server.sockets[0].getsockname()[1]
            uri = f"ws://127.0.0.1:{port}/environment"
            async with connect(uri, ping_interval=None) as websocket:
                await websocket.send(
                    json.dumps(
                        {"type": "bridge.connect", "version": 1, "token": "wrong"}
                    )
                )
                with self.assertRaises(ConnectionClosedError) as closed:
                    await websocket.recv()
                self.assertEqual(closed.exception.code, 4001)

            async with connect(uri, ping_interval=None) as websocket:
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
                self.assertNotIn(
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
            EnvironmentAdapterConfig(receipt_path=":memory:", token="adapter-secret"),
        )
        handler_errors: list[Exception] = []

        async def handler(websocket: object, _path: str) -> None:
            try:
                await adapter.handler(websocket)  # type: ignore[arg-type]
            except Exception as error:
                handler_errors.append(error)

        async with serve(
            handler,
            "127.0.0.1",
            0,
            ping_interval=None,
        ) as server:
            port = server.sockets[0].getsockname()[1]
            uri = f"ws://127.0.0.1:{port}/environment"
            async with connect(uri, ping_interval=None) as first:
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

                async with connect(uri, ping_interval=None) as second:
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
            EnvironmentAdapterConfig(receipt_path=":memory:", token="adapter-secret"),
        )

        async with serve(
            lambda websocket, _path: adapter.handler(websocket),
            "127.0.0.1",
            0,
            ping_interval=None,
        ) as server:
            port = server.sockets[0].getsockname()[1]
            async with connect(
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
                                "bodyLease": {"bodyId": "ainekio-01", "executionId": "test-execution", "generation": 1},
                                "type": "move", "locomotionGoal": {"kind": "visual", "target": "fixture", "completionCriteria": "fixture"},
                                "direction": "forward",
                                "createdAt": datetime.now(timezone.utc).isoformat(),
                            },
                        }
                    )
                )

                accepted = json.loads(await websocket.recv())
                self.assertEqual(gateway.calls, [])
                await websocket.send(json.dumps({
                    "type": "environment.feedback.ack",
                    "feedbackId": accepted["feedback"]["id"],
                    "admitted": True,
                }))
                feedback = json.loads(await websocket.recv())
                await websocket.send(json.dumps({
                    "type": "environment.feedback.ack",
                    "feedbackId": feedback["feedback"]["id"],
                    "admitted": True,
                }))
                observation = json.loads(await websocket.recv())
                await asyncio.sleep(0)

        self.assertEqual(accepted["type"], "environment.feedback")
        self.assertEqual(accepted["feedback"]["type"], "accepted")
        self.assertEqual(feedback["type"], "environment.feedback")
        self.assertEqual(feedback["feedback"]["type"], "completed")
        self.assertNotEqual(accepted["feedback"]["id"], feedback["feedback"]["id"])
        self.assertEqual(observation["type"], "environment.observation")
        self.assertFalse(any(item["type"] == "environment.feedback" for item in adapter.receipts.pending()))

    def test_translation_emits_only_bounded_semantic_commands(self) -> None:
        snapshot = translate_environment_action({"type": "captureImage"})
        self.assertEqual(snapshot, translate_environment_action({"type": "capture_image"}))
        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        self.assertEqual((snapshot.kind, snapshot.name), ("snapshot", "captureImage"))

        move = translate_environment_action(
            {"type": "move", "locomotionGoal": {"kind": "visual", "target": "fixture", "completionCriteria": "fixture"}, "direction": "backward", "units": 99}
        )
        self.assertIsNotNone(move)
        assert move is not None
        self.assertEqual((move.kind, move.name), ("intent", "walk"))
        self.assertEqual(move.params, {"dir": "back", "steps": 10})

        for action, asset in (
            ({"type": "move", "locomotionGoal": {"kind": "visual", "target": "fixture", "completionCriteria": "fixture"}, "direction": "left"}, "turn_left_45"),
            ({"type": "robotCommand", "command": "turn right"}, "turn_right_45"),
            ({"type": "robotCommand", "command": "turn left quarter turn"}, "turn_left_45"),
            ({"type": "robotCommand", "command": "turn right half turn"}, "turn_right_90"),
            ({"type": "robotCommand", "command": "turn around"}, "turn_right_180"),
            ({"type": "robotCommand", "command": "look around"}, "curious"),
            ({"type": "robotCommand", "command": "#1"}, "number_one"),
            ({"type": "robotCommand", "command": "#2"}, "number_two"),
        ):
            with self.subTest(action=action):
                turn = translate_environment_action(action)
                self.assertIsNotNone(turn)
                assert turn is not None
                self.assertEqual(
                    (turn.kind, turn.name, turn.params),
                    ("intent", "emote", {"asset": asset}),
                )

        emote = translate_environment_action(
            {"type": "robotCommand", "command": "wave"}
        )
        self.assertIsNotNone(emote)
        assert emote is not None
        self.assertEqual((emote.name, emote.params), ("emote", {"asset": "wave"}))

        for command in ("sit", "sit down", "take a seat", "have a seat"):
            with self.subTest(command=command):
                sit = translate_environment_action(
                    {"type": "robotCommand", "command": command}
                )
                self.assertEqual((sit.kind, sit.name, sit.params), ("intent", "sit", {}))

        for command in (
            "nod", "celebrate", "stretch", "macarena", "salsa", "surprised",
            "sad", "curious", "turn_left_45", "turn_right_45",
            "turn_left_90", "turn_right_90", "turn_left_180", "turn_right_180",
            "walk_slow", "run", "number_one", "number_two",
        ):
            with self.subTest(command=command):
                translated = translate_environment_action(
                    {"type": "robotCommand", "command": command}
                )
                self.assertIsNotNone(translated)
                assert translated is not None
                self.assertEqual(
                    (translated.name, translated.params),
                    ("emote", {"asset": command}),
                )

        self.assertIsNone(
            translate_environment_action(
                {"type": "robotCommand", "command": "R1=180"}
            )
        )

    async def test_capture_image_returns_one_correlated_camera_observation(self) -> None:
        gateway = SnapshotGateway()
        adapter = EnvironmentAdapter(
            gateway,  # type: ignore[arg-type]
            EnvironmentAdapterConfig(receipt_path=":memory:", token="adapter-secret"),
        )
        websocket = FakeWebSocket()
        adapter._websocket = websocket  # type: ignore[assignment]
        adapter._bridge_ready = True
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
        self.assertEqual(len(observations[0]["feedback"]), 1)
        self.assertEqual(observations[0]["feedback"][0]["id"], feedback[0]["id"])
        self.assertEqual(observations[0]["metadata"]["correlationId"], "cycle-1")
        self.assertEqual(observations[0]["metadata"]["actionId"], "capture-1")
        self.assertEqual(
            observations[0]["metadata"]["robotObserver"],
            robot_observer,
        )
        self.assertEqual(
            observations[0]["visual"]["metadata"]["correlationId"],
            "cycle-1",
        )
        self.assertEqual(
            observations[0]["visual"]["metadata"]["actionId"],
            "capture-1",
        )
        self.assertEqual([call[0] for call in gateway.calls], ["snap", "wait"])

    async def test_post_action_snapshot_preserves_robot_observer_cycle(self) -> None:
        gateway = SnapshotGateway()
        adapter = EnvironmentAdapter(
            gateway,  # type: ignore[arg-type]
            EnvironmentAdapterConfig(receipt_path=":memory:",
                token="adapter-secret",
            ),
        )
        websocket = FakeWebSocket()
        adapter._websocket = websocket  # type: ignore[assignment]
        adapter._bridge_ready = True
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
                "type": "move", "locomotionGoal": {"kind": "visual", "target": "fixture", "completionCriteria": "fixture"},
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
        self.assertEqual(observation["metadata"]["actionId"], "move-2")
        self.assertEqual(len(observation["feedback"]), 1)
        self.assertEqual(
            [call[0] for call in gateway.calls],
            ["intent", "wait"],
        )

    async def test_explicit_trajectory_dispatch_remains_usable_without_advertising_the_retired_generator(self) -> None:
        gateway = FakeGateway()
        now = datetime(2026, 7, 17, tzinfo=timezone.utc)
        adapter = EnvironmentAdapter(
            gateway,  # type: ignore[arg-type]
            EnvironmentAdapterConfig(receipt_path=":memory:",
                token="adapter-secret",
                robot_id="test-body",
                freestyle_enabled=True,
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
        self.assertNotIn("robotMotionPlan", adapter._observation()["capabilities"]["actions"])
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

    async def test_p4_freestyle_uses_twelve_named_signed_joints(self):
        from protocol.joints_v2 import JOINT_LABELS
        class P4Gateway(FakeGateway):
            def status(self):
                status=super().status()
                status["robots"]["test-body"].update(model="v2-12servo",features=["motion_targets_v1"])
                return status
        gateway=P4Gateway()
        adapter=EnvironmentAdapter(gateway,EnvironmentAdapterConfig(
            receipt_path=":memory:",token="test",robot_id="test-body"))
        self.addCleanup(adapter.receipts.close)
        action={"id":"p4-plan","type":"robotMotionPlan","endPose":"hold",
            "frames":[{"speedDegS":120,"targets":[{"joint":j,"degrees":-117.68}
                for j in reversed(JOINT_LABELS)]}]}
        result=await adapter.handle_action(action)
        self.assertEqual(result["type"],"completed")
        self.assertEqual(gateway.calls[0][1][0],[[12000,[-11768]*12]])
        self.assertEqual(gateway.calls[0][1][1]["control"], "targets")
        for rate in (0, -1, float('inf'), .001):
            invalid = {**action, 'frames': [{**action['frames'][0], 'speedDegS': rate}]}
            self.assertIsNone(translate_environment_action(invalid, model='v2-12servo'))
        timed = {**action, 'frames': [{'durationMs': 120, 'targets': action['frames'][0]['targets']}]}
        self.assertIsNone(translate_environment_action(timed, model='v2-12servo'))
        state=adapter._observation()["state"]["freestyleMovement"]
        self.assertTrue(state["available"])
        self.assertEqual(state["jointMap"]["version"],2)
        self.assertEqual(len(state["jointMap"]["joints"]),12)
        self.assertIsNone(translate_environment_action({**action,"frames":[{
            "durationMs":100,"targets":[{"joint":j,"degrees":90} for j in ("R1","R2","L1","L2","R4","R3","L3","L4")]}]},model="v2-12servo"))

    async def test_stop_can_preempt_an_active_freestyle_action(self) -> None:
        gateway = BlockingMotionGateway()
        now = datetime(2026, 7, 17, tzinfo=timezone.utc)
        adapter = EnvironmentAdapter(
            gateway,  # type: ignore[arg-type]
            EnvironmentAdapterConfig(receipt_path=":memory:",
                token="adapter-secret",
                robot_id="test-body",
                freestyle_enabled=True,
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
            EnvironmentAdapterConfig(receipt_path=":memory:", token="adapter-secret", freestyle_enabled=False),
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

    async def test_coordinator_admitted_control_uses_local_dispatch_time_not_creation_age(self) -> None:
        gateway = FakeGateway()
        adapter = EnvironmentAdapter(
            gateway,  # type: ignore[arg-type]
            EnvironmentAdapterConfig(receipt_path=":memory:", token="adapter-secret"),
            clock=lambda: 50.0,
            utcnow=lambda: datetime(2026, 7, 14, tzinfo=timezone.utc),
        )
        result = await adapter.handle_action(
            {
                "id": "action-1",
                                "bodyLease": {"bodyId": "ainekio-01", "executionId": "test-execution", "generation": 1},
                "type": "move", "locomotionGoal": {"kind": "visual", "target": "fixture", "completionCriteria": "fixture"},
                "direction": "forward",
                "createdAt": "2000-01-01T00:00:00Z",
            },
        )

        self.assertEqual(result["type"], "completed")
        self.assertEqual([call[0] for call in gateway.calls], ["intent", "wait"])
        self.assertEqual(gateway.calls[0][1][2]["received_at"], 50.0)

    async def test_fresh_control_uses_local_monotonic_receipt(self) -> None:
        gateway = FakeGateway()
        now = datetime(2026, 7, 14, tzinfo=timezone.utc)
        adapter = EnvironmentAdapter(
            gateway,  # type: ignore[arg-type]
            EnvironmentAdapterConfig(receipt_path=":memory:", token="adapter-secret"),
            clock=lambda: 50.0,
            utcnow=lambda: now,
        )
        result = await adapter.handle_action(
            {
                "id": "action-1",
                                "bodyLease": {"bodyId": "ainekio-01", "executionId": "test-execution", "generation": 1},
                "type": "move", "locomotionGoal": {"kind": "visual", "target": "fixture", "completionCriteria": "fixture"},
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
            EnvironmentAdapterConfig(receipt_path=":memory:", token="adapter-secret"),
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
            EnvironmentAdapterConfig(receipt_path=":memory:", token="adapter-secret"),
            utcnow=lambda: now,
        )

        result = await adapter.handle_action(
            {
                "id": "move-offline",
                "type": "move", "locomotionGoal": {"kind": "visual", "target": "fixture", "completionCriteria": "fixture"},
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
            EnvironmentAdapterConfig(receipt_path=":memory:", token="adapter-secret"),
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
            EnvironmentAdapterConfig(receipt_path=":memory:", token="adapter-secret"),
        )
        websocket = FakeWebSocket()
        adapter._websocket = websocket  # type: ignore[assignment]
        adapter._snapshot_in_flight = True
        adapter._pending_snapshot_context = {"correlationId": "test-snapshot"}
        await adapter._handle_gateway_event(
            {"t": "cam_meta", "res": "QVGA", "fps": 0, "counter_base": 3}
        )

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

    async def test_camera_identity_survives_counter_restart_and_robot_selection(self) -> None:
        gateway = FakeGateway()
        adapter = EnvironmentAdapter(gateway, EnvironmentAdapterConfig(receipt_path=":memory:", token="fixture"))
        websocket = FakeWebSocket()
        adapter._websocket = websocket
        for instance, robot, epoch in [
            ("first", "test-body", 1), ("first", "test-body", 2),
            ("second", "test-body", 1), ("second", "other-body", 1),
        ]:
            gateway.instance_id = instance
            await adapter._deliver_camera_frame({"robot_id": robot, "epoch": epoch,
                "counter": 4, "payload": b"\xff\xd8\xff\xd9"}, {})
        frames = [json.loads(message)["observation"]["visual"] for message in websocket.sent]
        self.assertEqual(len({frame["id"] for frame in frames}), 4)
        self.assertNotIn("ainekio-camera-4", {frame["id"] for frame in frames})
        self.assertEqual(frames[1]["metadata"]["epoch"], 2)
        self.assertEqual(frames[2]["metadata"]["gatewayInstance"], "second")
        self.assertEqual(gateway.calls, [])

    async def test_continuous_camera_frame_stays_out_of_llm_observations(self) -> None:
        gateway = FakeGateway()
        adapter = EnvironmentAdapter(
            gateway,  # type: ignore[arg-type]
            EnvironmentAdapterConfig(receipt_path=":memory:", token="adapter-secret"),
        )
        websocket = FakeWebSocket()
        adapter._websocket = websocket  # type: ignore[assignment]

        await adapter._handle_gateway_frame(
            {
                "robot_id": "test-body",
                "frame_type": CAMERA_JPEG_FRAME_TYPE,
                "counter": 4,
                "payload": b"\xff\xd8\xff\xd9",
            }
        )

        self.assertEqual(websocket.sent, [])

    async def test_selected_camera_read_returns_latest_stream_without_capture_or_observation(self) -> None:
        gateway = FakeGateway()
        gateway.clock = lambda: 100.0
        now = datetime(2026, 10, 11, tzinfo=timezone.utc)
        adapter = EnvironmentAdapter(gateway, EnvironmentAdapterConfig(receipt_path=":memory:", token="fixture"),
                                     utcnow=lambda: now)
        websocket = FakeWebSocket()
        adapter._websocket = websocket
        for counter in (4, 5):
            await adapter._handle_gateway_frame({"robot_id": "test-body", "epoch": 1,
                "frame_type": CAMERA_JPEG_FRAME_TYPE, "counter": counter,
                "received_at": 98.0, "payload": b"\xff\xd8\xff\xd9"})
        self.assertEqual(websocket.sent, [])
        for request_id in ("read-one", "read-two"):
            await adapter._read_camera_visual({"type": "environment.visual.read", "version": 1,
                "requestId": request_id, "sessionId": adapter.config.session_id})
            result = json.loads(websocket.sent[-1])
            self.assertEqual(result["type"], "environment.visual.result")
            self.assertEqual(result["requestId"], request_id)
            self.assertEqual(result["visual"]["metadata"]["counter"], 5)
            self.assertEqual(result["visual"]["timestamp"], "2026-10-10T23:59:58+00:00")
        self.assertEqual(gateway.calls, [])
        self.assertEqual(adapter._camera_observation_count, 0)

    async def test_camera_read_carries_recognition_with_its_own_jpeg(self):
        import base64
        from gateway.plugins import CameraAnalysis
        from gateway.perception import RecognitionResult, RecognizedObject
        gateway = FakeGateway()
        gateway.clock = lambda: 100.0
        adapter = EnvironmentAdapter(gateway, EnvironmentAdapterConfig(receipt_path=":memory:", token="fixture"),
            utcnow=lambda: datetime(2026, 10, 11, tzinfo=timezone.utc))
        socket = FakeWebSocket()
        adapter._websocket = socket
        old_jpeg = b"\xff\xd8recognized\xff\xd9"
        new_jpeg = b"\xff\xd8unprocessed\xff\xd9"
        identity = {"state": "face_match", "personId": "greg", "name": "Greg",
                    "trackId": "person-1", "faceAgeMs": 0, "similarity": 0.82}
        result = RecognitionResult("ultralytics+sface", "fixture", "1 face match",
            (RecognizedObject("person", 0.9, (0.1, 0.2, 0.3, 0.4), identity),), ())
        analysis = CameraAnalysis("test-body", 1, 43, 98.0, 99.0, result, jpeg=old_jpeg)
        adapter.camera_analysis = lambda robot_id: analysis
        frame = {"robot_id": "test-body", "epoch": 1, "counter": 44,
            "received_at": 99.0, "frame_type": CAMERA_JPEG_FRAME_TYPE, "payload": new_jpeg}
        await adapter._handle_gateway_frame(frame)
        self.assertNotIn("recognition", adapter._camera_visual(frame, {})["metadata"])
        for request_id in ("first", "repeat"):
            await adapter._read_camera_visual({"type": "environment.visual.read", "version": 1,
                "requestId": request_id, "sessionId": adapter.config.session_id})
            visual = json.loads(socket.sent[-1])["visual"]
            self.assertEqual(base64.b64decode(visual["dataUrl"].split(",")[1]), old_jpeg)
            self.assertEqual(visual["metadata"]["counter"], 43)
            recognition = visual["metadata"]["recognition"]
            self.assertEqual(recognition["frameCounter"], 43)
            self.assertEqual(recognition["observedAt"], visual["timestamp"])
            self.assertEqual(recognition["objects"][0]["identity"], identity)
        adapter.camera_analysis = lambda robot_id: None
        await adapter._read_camera_visual({"version": 1, "requestId": "unrecognized",
            "sessionId": adapter.config.session_id})
        visual = json.loads(socket.sent[-1])["visual"]
        self.assertEqual(visual["metadata"]["counter"], 44)
        self.assertNotIn("recognition", visual["metadata"])
        self.assertEqual(gateway.calls, [])

    async def test_camera_read_preserves_missing_frame_and_selected_epoch(self) -> None:
        gateway = FakeGateway()
        adapter = EnvironmentAdapter(gateway, EnvironmentAdapterConfig(receipt_path=":memory:", token="fixture"))
        websocket = FakeWebSocket()
        adapter._websocket = websocket
        request = {"type": "environment.visual.read", "version": 1,
                   "requestId": "read", "sessionId": adapter.config.session_id}
        await adapter._read_camera_visual(request)
        self.assertIsNone(json.loads(websocket.sent[-1])["visual"])
        await adapter._handle_gateway_frame({"robot_id": "test-body", "epoch": 1,
            "frame_type": CAMERA_JPEG_FRAME_TYPE, "counter": 4, "payload": b"\xff\xd8\xff\xd9"})
        status = gateway.status()
        status["robots"]["test-body"]["epoch"] = 2
        gateway.status = lambda: status
        await adapter._read_camera_visual(request)
        self.assertIsNone(json.loads(websocket.sent[-1])["visual"])
        await adapter._read_camera_visual({**request, "sessionId": "other-body"})
        self.assertIn("error", json.loads(websocket.sent[-1]))
        self.assertEqual(gateway.calls, [])

    async def test_vision_configuration_uses_existing_request_result_without_body_commands(self):
        gateway = FakeGateway()
        adapter = EnvironmentAdapter(gateway, EnvironmentAdapterConfig(receipt_path=":memory:", token="fixture"))
        websocket = FakeWebSocket()
        adapter._websocket = websocket
        requests = []
        async def configure(request):
            requests.append(request)
            return {"operation": request["operation"], "queryId": request["requestId"]}
        adapter.vision_operation = configure
        request = {"type": "environment.visual.read", "version": 1,
            "sessionId": adapter.config.session_id, "requestId": "search-keys", "operation": "search", "labels": ["keys"]}
        await adapter._read_camera_visual(request)
        self.assertEqual(requests, [request])
        reply = json.loads(websocket.sent[-1])
        self.assertEqual(reply["type"], "environment.visual.result")
        self.assertEqual(reply["vision"]["queryId"], "search-keys")
        self.assertEqual(reply["requestId"], "search-keys")
        self.assertNotIn("visual", reply)
        self.assertEqual(gateway.calls, [])
        async def disconnected(request):
            adapter._websocket = FakeWebSocket()
            return {"queryId": "search-keys"}
        adapter.vision_operation = disconnected
        await adapter._read_camera_visual(request)
        self.assertEqual(adapter._websocket.sent, [], "a completed old request cannot write to a replacement bridge")

    async def test_camera_delivery_is_queued_outside_robot_receive_callback(self) -> None:
        gateway = FakeGateway()
        adapter = EnvironmentAdapter(
            gateway,  # type: ignore[arg-type]
            EnvironmentAdapterConfig(receipt_path=":memory:", token="adapter-secret"),
        )
        websocket = FakeWebSocket()
        adapter._websocket = websocket  # type: ignore[assignment]
        adapter._camera_delivery_queue = asyncio.Queue(maxsize=1)
        adapter._robot_snapshot_contexts[("test-body", 1, 4)] = {
            "correlationId": "first",
        }
        adapter._robot_snapshot_contexts[("test-body", 1, 5)] = {
            "correlationId": "second",
        }

        await adapter._handle_gateway_frame(
            {
                "robot_id": "test-body",
                "epoch": 1,
                "frame_type": CAMERA_JPEG_FRAME_TYPE,
                "counter": 4,
                "payload": b"\xff\xd8\xff\xd9",
            }
        )
        await adapter._handle_gateway_frame(
            {
                "robot_id": "test-body",
                "epoch": 1,
                "frame_type": CAMERA_JPEG_FRAME_TYPE,
                "counter": 5,
                "payload": b"\xff\xd8\xff\xd9",
            }
        )

        self.assertEqual(adapter._camera_delivery_queue.qsize(), 1)
        queued_frame, queued_context = adapter._camera_delivery_queue.get_nowait()
        self.assertEqual(queued_frame["counter"], 5)
        self.assertEqual(queued_context["correlationId"], "second")
        self.assertEqual(websocket.sent, [])

    async def test_snapshot_correlation_is_cleared_across_robot_epochs(self) -> None:
        gateway = FakeGateway()
        adapter = EnvironmentAdapter(
            gateway,  # type: ignore[arg-type]
            EnvironmentAdapterConfig(receipt_path=":memory:", token="adapter-secret"),
        )
        adapter._robot_action_contexts[("test-body", 1, 7)] = {
            "actionId": "old-action",
        }
        await adapter._handle_gateway_event(
            {
                "t": "cam_meta",
                "robot_id": "test-body",
                "epoch": 1,
                "res": "XGA",
                "fps": 0,
                "counter_base": 0,
                "origin": "action",
                "origin_id": 7,
            }
        )
        self.assertIn(
            ("test-body", 1, 0),
            adapter._robot_snapshot_contexts,
        )

        await adapter._handle_gateway_event(
            {
                "t": "connection",
                "status": "connected",
                "robot_id": "test-body",
                "epoch": 2,
            }
        )

        self.assertEqual(adapter._robot_action_contexts, {})
        self.assertEqual(adapter._robot_snapshot_contexts, {})
        websocket = FakeWebSocket()
        adapter._websocket = websocket  # type: ignore[assignment]
        await adapter._handle_gateway_frame(
            {
                "robot_id": "test-body",
                "epoch": 2,
                "frame_type": CAMERA_JPEG_FRAME_TYPE,
                "counter": 0,
                "payload": b"\xff\xd8\xff\xd9",
            }
        )
        self.assertEqual(websocket.sent, [])

    async def test_pending_action_visuals_are_bounded_and_late_images_drop(self) -> None:
        gateway = FakeGateway()
        adapter = EnvironmentAdapter(
            gateway,  # type: ignore[arg-type]
            EnvironmentAdapterConfig(receipt_path=":memory:", token="adapter-secret"),
        )
        loop = asyncio.get_running_loop()
        for index in range(40):
            adapter._remember_action_visual(
                f"action-{index}",
                loop.create_future(),
            )
        self.assertEqual(len(adapter._pending_action_visuals), 32)
        self.assertNotIn("action-0", adapter._pending_action_visuals)

        websocket = FakeWebSocket()
        adapter._websocket = websocket  # type: ignore[assignment]
        adapter._robot_snapshot_contexts[("test-body", 1, 41)] = {
            "actionId": "expired-action",
        }
        await adapter._handle_gateway_frame(
            {
                "robot_id": "test-body",
                "epoch": 1,
                "frame_type": CAMERA_JPEG_FRAME_TYPE,
                "counter": 41,
                "payload": b"\xff\xd8\xff\xd9",
            },
        )
        self.assertEqual(websocket.sent, [])
        for future in adapter._pending_action_visuals.values():
            future.cancel()

    async def test_vad_frames_become_one_bounded_binary_wav_utterance(self) -> None:
        gateway = FakeGateway()
        now = datetime(2026, 7, 17, 12, 0, tzinfo=timezone.utc)
        adapter = EnvironmentAdapter(
            gateway,  # type: ignore[arg-type]
            EnvironmentAdapterConfig(receipt_path=":memory:", token="adapter-secret"),
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

    async def test_wake_utterance_receives_one_firmware_correlated_snapshot(self) -> None:
        gateway = FakeGateway()
        adapter = EnvironmentAdapter(
            gateway,  # type: ignore[arg-type]
            EnvironmentAdapterConfig(receipt_path=":memory:", token="adapter-secret"),
        )
        websocket = FakeWebSocket()
        adapter._websocket = websocket  # type: ignore[assignment]
        assembler = adapter._audio_utterances.assembler
        identity = {"robot_id": "test-body", "epoch": 2}

        await assembler.handle_event(
            {"t": "event", "name": "vad_open", "origin_id": 7, **identity}
        )
        await assembler.handle_event(
            {"t": "event", "name": "wake_word", "origin_id": 7, **identity}
        )
        await assembler.handle_frame(
            {
                **identity,
                "frame_type": MIC_PCM_FRAME_TYPE,
                "counter": 7,
                "payload": bytes([1, 0]) * 320,
            }
        )
        await assembler.handle_event(
            {"t": "event", "name": "vad_close", "origin_id": 7, **identity}
        )

        encoded = next(message for message in websocket.sent if isinstance(message, bytes))
        metadata_bytes = struct.unpack("<I", encoded[8:12])[0]
        audio_metadata = json.loads(encoded[12 : 12 + metadata_bytes])
        await adapter._handle_gateway_event(
            {
                "t": "cam_meta",
                "res": "XGA",
                "fps": 0,
                "counter_base": 31,
                "origin": "audio",
                "origin_id": 7,
                **identity,
            }
        )
        await adapter._handle_gateway_frame(
            {
                **identity,
                "frame_type": CAMERA_JPEG_FRAME_TYPE,
                "counter": 31,
                "payload": b"\xff\xd8\xff\xd9",
            }
        )
        observation = next(
            json.loads(message)["observation"]
            for message in websocket.sent
            if isinstance(message, str)
            and json.loads(message).get("type") == "environment.observation"
        )

        self.assertEqual(
            observation["metadata"]["audioUtteranceId"],
            audio_metadata["utteranceId"],
        )
        self.assertEqual(
            observation["visual"]["metadata"]["audioUtteranceId"],
            audio_metadata["utteranceId"],
        )
        self.assertEqual(observation["metadata"]["robotId"], "test-body")
        self.assertEqual(observation["metadata"]["epoch"], 2)
        self.assertEqual(
            audio_metadata["utteranceId"],
            "audio:test-body:2:7",
        )
        self.assertTrue(audio_metadata["wakeTriggered"])
        self.assertEqual(gateway.calls, [])

    async def test_non_audio_body_event_name_is_preserved_in_environment_state(self) -> None:
        gateway = FakeGateway()
        adapter = EnvironmentAdapter(
            gateway,  # type: ignore[arg-type]
            EnvironmentAdapterConfig(receipt_path=":memory:", token="adapter-secret"),
        )
        websocket = FakeWebSocket()
        adapter._websocket = websocket  # type: ignore[assignment]

        await adapter._handle_gateway_event(
            {"t": "event", "name": "orientation_fault", "robot_id": "test-body", "epoch": 1}
        )

        message = json.loads(websocket.sent[0])
        self.assertEqual(
            message["observation"]["state"]["bodyEvent"]["name"],
            "orientation_fault",
        )

    async def test_body_event_does_not_cause_a_gateway_snapshot_command(self) -> None:
        gateway = FakeGateway()
        adapter = EnvironmentAdapter(
            gateway,  # type: ignore[arg-type]
            EnvironmentAdapterConfig(receipt_path=":memory:", token="adapter-secret"),
        )
        websocket = FakeWebSocket()
        adapter._websocket = websocket  # type: ignore[assignment]

        await adapter._handle_gateway_event(
            {
                "t": "event",
                "name": "orientation_fault",
                "robot_id": "test-body",
                "epoch": 4,
                "counter": 22,
            }
        )
        observation = next(
            json.loads(message)["observation"]
            for message in websocket.sent
            if isinstance(message, str)
            and json.loads(message).get("type") == "environment.observation"
        )
        self.assertEqual(
            observation["state"]["bodyEvent"]["name"],
            "orientation_fault",
        )
        self.assertNotIn("visual", observation)
        self.assertEqual(gateway.calls, [])

    async def test_vad_close_clears_microphone_meter_without_enqueuing_observation(self) -> None:
        gateway = FakeGateway()
        adapter = EnvironmentAdapter(
            gateway,  # type: ignore[arg-type]
            EnvironmentAdapterConfig(receipt_path=":memory:", token="adapter-secret"),
        )
        websocket = FakeWebSocket()
        adapter._websocket = websocket  # type: ignore[assignment]

        await adapter._handle_gateway_event(
            {"t": "event", "name": "vad_close", "robot_id": "test-body", "epoch": 1}
        )

        telemetry = json.loads(websocket.sent[0])
        self.assertEqual(telemetry["telemetry"]["kind"], "audio.level")
        self.assertEqual(telemetry["telemetry"]["level"], 0.0)
        self.assertEqual(len(websocket.sent), 1)

    async def test_robot_status_uses_diagnostic_telemetry_not_an_observation(self) -> None:
        gateway = FakeGateway()
        adapter = EnvironmentAdapter(
            gateway,  # type: ignore[arg-type]
            EnvironmentAdapterConfig(receipt_path=":memory:", token="adapter-secret"),
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
                "output_ready": False,
                "output_armed": False,
                "output_fault": 1,
                "power_monitor_ready": False,
                "status_received_at": "2026-10-14T23:00:00+00:00",
            }
        )

        message = json.loads(websocket.sent[0])
        self.assertEqual(message["type"], "environment.telemetry")
        self.assertEqual(message["telemetry"]["kind"], "robot.status")
        self.assertTrue(message["telemetry"]["camera_ready"])
        self.assertEqual(message["telemetry"]["mic_drops"], 4)
        for key, value in {"output_ready": False, "output_armed": False, "output_fault": 1,
                "power_monitor_ready": False, "status_received_at": "2026-10-14T23:00:00+00:00"}.items():
            self.assertEqual(message["telemetry"][key], value)
        self.assertNotIn("observation", message)

    async def test_servo_feedback_retains_its_sample_on_the_selected_body_telemetry_path(self) -> None:
        gateway = FakeGateway()
        adapter = EnvironmentAdapter(
            gateway,  # type: ignore[arg-type]
            EnvironmentAdapterConfig(receipt_path=":memory:", token="adapter-secret"),
        )
        websocket = FakeWebSocket()
        adapter._websocket = websocket  # type: ignore[assignment]
        sample = {
            "enabled": True, "usable": False, "scan": 59906, "clock_us": 1302014762,
            "calibrated_mask": 4095, "unavailable_mask": 4, "clipped_mask": 0,
            "below_calibration_mask": 0, "above_calibration_mask": 0,
            "adc_error": "ESP_OK", "supply_voltage_available": False,
            "signal_millivolts": [None if i == 2 else 1000 + i for i in range(12)],
        }
        for robot_id, epoch in [("other-body", 1), ("test-body", 0)]:
            await adapter._handle_gateway_event({
                "t": "servo_feedback", "robot_id": robot_id, "epoch": epoch, "data": sample,
            })
        self.assertEqual(websocket.sent, [], "Unrelated or old body sessions cannot supply selected feedback")
        for current in [sample, {**sample, "scan": 59907, "clock_us": 1303014762,
                                 "usable": True, "unavailable_mask": 0}]:
            await adapter._handle_gateway_event({
                "t": "servo_feedback", "robot_id": "test-body", "epoch": 1, "data": current,
            })
            message = json.loads(websocket.sent[-1])
            self.assertEqual(message["type"], "environment.telemetry")
            self.assertEqual(message["telemetry"]["kind"], "robot.status")
            self.assertEqual(message["telemetry"]["robot_id"], "test-body")
            self.assertEqual(message["telemetry"]["epoch"], 1)
            self.assertEqual(message["telemetry"]["servo_feedback"], current)
            self.assertNotIn("observation", message)
            self.assertNotIn("received_at", message["telemetry"]["servo_feedback"])
        self.assertEqual(len(websocket.sent), 2)
        self.assertEqual(gateway.calls, [], "Feedback telemetry does not command the body")

    async def test_microphone_level_telemetry_is_throttled_without_relaying_pcm(self) -> None:
        gateway = FakeGateway()
        now = 0.0
        adapter = EnvironmentAdapter(
            gateway,  # type: ignore[arg-type]
            EnvironmentAdapterConfig(receipt_path=":memory:", token="adapter-secret"),
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
        first_task = adapter._microphone_level_task
        self.assertIsNotNone(first_task)
        await first_task
        now = 0.11
        await adapter._handle_gateway_frame({**frame, "counter": 12})
        second_task = adapter._microphone_level_task
        self.assertIsNotNone(second_task)
        await second_task

        self.assertEqual(len(websocket.sent), 2)
        first = json.loads(websocket.sent[0])
        self.assertEqual(first["telemetry"]["kind"], "audio.level")
        self.assertEqual(first["telemetry"]["level"], 0.5)
        self.assertNotIn("payload", first["telemetry"])

    async def test_slow_microphone_telemetry_does_not_block_robot_frames(self) -> None:
        gateway = FakeGateway()
        now = 0.0
        adapter = EnvironmentAdapter(
            gateway,  # type: ignore[arg-type]
            EnvironmentAdapterConfig(receipt_path=":memory:", token="adapter-secret"),
            clock=lambda: now,
        )
        websocket = BlockingWebSocket()
        adapter._websocket = websocket  # type: ignore[assignment]
        frame = {
            "robot_id": "test-body",
            "epoch": 1,
            "frame_type": MIC_PCM_FRAME_TYPE,
            "counter": 10,
            "payload": struct.pack("<320h", *([1200] * 320)),
        }

        await asyncio.wait_for(adapter._handle_gateway_frame(frame), timeout=0.05)
        await asyncio.wait_for(websocket.send_started.wait(), timeout=0.05)
        now = 0.11
        await asyncio.wait_for(
            adapter._handle_gateway_frame({**frame, "counter": 11}),
            timeout=0.05,
        )

        task = adapter._microphone_level_task
        self.assertIsNotNone(task)
        websocket.release_send.set()
        await task
        self.assertEqual(len(websocket.sent), 1)

    async def test_maximum_duration_emits_one_truncated_utterance_until_vad_closes(self) -> None:
        gateway = FakeGateway()
        adapter = EnvironmentAdapter(
            gateway,  # type: ignore[arg-type]
            EnvironmentAdapterConfig(receipt_path=":memory:",
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
            EnvironmentAdapterConfig(receipt_path=":memory:", token="adapter-secret"),
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
            EnvironmentAdapterConfig(receipt_path=":memory:", token="adapter-secret"),
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
            EnvironmentAdapterConfig(receipt_path=":memory:", token="")


if __name__ == "__main__":
    unittest.main()

class GoalLocomotionBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_depth_demand_uses_selected_body_and_connection_owns_cleanup(self):
        from unittest.mock import AsyncMock
        from websockets.legacy.server import serve
        from websockets.legacy.client import connect
        adapter = EnvironmentAdapter(FakeGateway(), EnvironmentAdapterConfig(token="fixture", receipt_path=":memory:"))
        self.addCleanup(adapter.receipts.close)
        adapter.depth_demand = AsyncMock(return_value={"enabled": True})
        async with serve(adapter.handler, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            async with connect(f"ws://127.0.0.1:{port}") as ws:
                await ws.send(json.dumps({"type": "bridge.connect", "version": 1, "token": "fixture"}))
                self.assertEqual(json.loads(await ws.recv())["type"], "bridge.ready")
                await ws.send(json.dumps({"type": "environment.visual.read", "version": 1,
                    "requestId": "depth-one", "sessionId": adapter.config.session_id,
                    "operation": "depthDemand", "consumerId": "execution-one", "enabled": True}))
                result = json.loads(await ws.recv())
                self.assertEqual(result["vision"]["consumerId"], "execution-one")
                self.assertTrue(result["vision"]["enabled"])
                enabled = adapter.depth_demand.await_args.args
                self.assertEqual(enabled[0], "test-body")
                self.assertTrue(enabled[2])
        self.assertEqual(adapter.depth_demand.await_args.args, (enabled[0], enabled[1], False))
        self.assertEqual(adapter._depth_consumers, {})
        self.assertEqual(adapter.gateway.calls, [])

    async def test_naked_gait_aliases_cannot_dispatch_but_internal_translation_remains(self):
        gateway = FakeGateway()
        adapter = EnvironmentAdapter(gateway, EnvironmentAdapterConfig(token="fixture", receipt_path=":memory:"))
        self.addCleanup(adapter.receipts.close)
        for action in [
            {"type": "move", "direction": "forward"},
            *[{"type": "robotCommand", "command": command} for command in
              ("walk", "walk forward", "reverse", "turn around", "run", "walk_slow", "crawl", "crab")],
        ]:
            self.assertIsNotNone(translate_environment_action(action))
            result = await adapter.handle_action({"id": "raw", **action})
            self.assertEqual(result["type"], "rejected")
            self.assertEqual(result["message"], "locomotion_goal_required")
        self.assertEqual(gateway.calls, [])

    async def test_yaw_unwrap_retains_sample_identity_and_resets_on_lost_evidence(self):
        import math
        adapter = EnvironmentAdapter(FakeGateway(), EnvironmentAdapterConfig(token="fixture", receipt_path=":memory:"),
            utcnow=lambda: datetime(2026, 10, 15, tzinfo=timezone.utc))
        self.addCleanup(adapter.receipts.close)
        def robot(angle, timestamp, fresh=True, boot=1):
            return {"epoch": 4, "status": {"imu": {"available": True, "fresh": fresh, "frame": "body_nominal",
                "boot_id": boot, "timestamp_us": timestamp, "received_at": "2026-10-15T00:00:00Z",
                "orientation_wxyz": [math.cos(math.radians(angle)/2), 0, 0, math.sin(math.radians(angle)/2)]}}}
        first = adapter._yaw_measurement("robot", robot(170, 1))
        next_sample = adapter._yaw_measurement("robot", robot(-170, 2))
        self.assertAlmostEqual(next_sample["degrees"] - first["degrees"], 20)
        self.assertEqual(first["referenceId"], next_sample["referenceId"])
        self.assertEqual(adapter._yaw_measurement("robot", robot(-170, 2)), next_sample)
        self.assertFalse(adapter._yaw_measurement("robot", robot(-160, 3, False))["available"])
        self.assertNotEqual(adapter._yaw_measurement("robot", robot(-150, 4))["referenceId"], first["referenceId"])
        self.assertNotEqual(adapter._yaw_measurement("robot", robot(-150, 5, boot=2))["referenceId"], first["referenceId"])
        stale = adapter._yaw_measurement("robot", {**robot(-150, 6, boot=2), "connection_state": "stale"})
        self.assertFalse(stale["available"])
        self.assertEqual(stale["reason"], "body_connection_stale")
        self.assertFalse(adapter._yaw_measurement("robot", None)["available"])

    async def test_old_fresh_imu_expires_while_other_control_traffic_remains_online(self):
        now = datetime(2026, 10, 15, tzinfo=timezone.utc)
        adapter = EnvironmentAdapter(FakeGateway(), EnvironmentAdapterConfig(token="fixture", receipt_path=":memory:"),
            utcnow=lambda: now)
        self.addCleanup(adapter.receipts.close)
        robot = {"epoch": 4, "connection_state": "online", "heartbeat_age_ms": 0,
            "status": {"imu": {"available": True, "fresh": True, "frame": "body_nominal",
                "boot_id": 1, "timestamp_us": 1, "received_at": now.isoformat(),
                "orientation_wxyz": [1, 0, 0, 0]}}}
        first = adapter._yaw_measurement("robot", robot)
        self.assertTrue(first["available"])
        self.assertEqual(first["expiresAt"], (now + timedelta(seconds=CONTROL_STALE_SECONDS)).isoformat())
        now += timedelta(seconds=CONTROL_STALE_SECONDS / 2)
        repeated = adapter._yaw_measurement("robot", robot)
        self.assertTrue(repeated["available"])
        self.assertEqual(repeated["expiresAt"], first["expiresAt"])
        now += timedelta(seconds=CONTROL_STALE_SECONDS / 2)
        expired = adapter._yaw_measurement("robot", robot)
        self.assertFalse(expired["available"])
        self.assertEqual(expired["reason"], "body_orientation_expired")
        self.assertEqual(expired["expiresAt"], first["expiresAt"])
        self.assertNotIn("robot", adapter._locomotion_yaw)
        robot["status"]["imu"].update({"received_at": now.isoformat(), "timestamp_us": 2})
        resumed = adapter._yaw_measurement("robot", robot)
        self.assertTrue(resumed["available"])
        self.assertNotEqual(resumed["referenceId"], first["referenceId"])
        now += timedelta(seconds=CONTROL_STALE_SECONDS)
        robot["status"]["imu"].update({"received_at": now.isoformat(), "timestamp_us": 3})
        after_unobserved_gap = adapter._yaw_measurement("robot", robot)
        self.assertTrue(after_unobserved_gap["available"])
        self.assertNotEqual(after_unobserved_gap["referenceId"], resumed["referenceId"])
        robot["status"]["imu"]["fresh"] = False
        self.assertFalse(adapter._yaw_measurement("robot", robot)["available"])

    async def test_ground_range_uses_exact_selected_point_without_motion(self):
        gateway = FakeGateway()
        adapter = EnvironmentAdapter(gateway, EnvironmentAdapterConfig(token="fixture", receipt_path=":memory:"))
        self.addCleanup(adapter.receipts.close)
        socket = FakeWebSocket()
        adapter._websocket = socket
        calls = []
        async def ground_range(frame_id, point, source_frame):
            calls.append((frame_id, point, source_frame))
            return {"available": True, "frameId": frame_id, "groundContact": point, "rangeMetres": 1.2,
                "source": "calibrated-ground-plane", "referenceId": "reference"}
        adapter.selected_ground_range = ground_range
        await adapter._read_camera_visual({"version": 1, "requestId": "read", "sessionId": adapter.config.session_id,
            "operation": "groundRange", "frameId": "exact-frame", "groundContact": {"x": .3, "y": .8},
            "sourceFrame": {"frameId": "exact-frame", "jpeg": "retained-jpeg", "epoch": 1}}, websocket=socket)
        self.assertEqual(calls, [("exact-frame", {"x": .3, "y": .8}, {"frameId": "exact-frame", "jpeg": "retained-jpeg", "epoch": 1})])
        self.assertNotIn("sourceFrame", adapter._ground_range_selection)
        result = json.loads(socket.sent[-1])["vision"]["locomotionMeasurement"]["target"]
        self.assertEqual(result["rangeMetres"], 1.2)
        self.assertEqual(gateway.calls, [])

    async def test_measurement_events_use_existing_telemetry_with_independent_sensor_availability(self):
        gateway = FakeGateway()
        adapter = EnvironmentAdapter(gateway, EnvironmentAdapterConfig(token="fixture", receipt_path=":memory:"))
        self.addCleanup(adapter.receipts.close)
        adapter._websocket = FakeWebSocket()
        robot_id = adapter._selected_robot()[0]
        adapter.locomotion_measurement = lambda _robot: {"available": False, "reason": "uncalibrated",
            "robotId": robot_id, "source": "calibrated-ground-plane"}
        await adapter._handle_gateway_event({"t": "locomotion_measurement", "robot_id": robot_id, "epoch": 1})
        message = json.loads(adapter._websocket.sent[-1])
        self.assertEqual(message["type"], "environment.telemetry")
        measurement = message["telemetry"]["locomotionMeasurement"]
        self.assertFalse(measurement["position"]["available"])
        self.assertIn("yaw", measurement)
        self.assertEqual(measurement["position"]["sessionId"], adapter.config.session_id)
        self.assertEqual(gateway.calls, [])

    async def test_depth_preview_stays_in_camera_owner_not_bridge_measurements(self):
        gateway = FakeGateway()
        adapter = EnvironmentAdapter(gateway, EnvironmentAdapterConfig(token="fixture", receipt_path=":memory:"))
        self.addCleanup(adapter.receipts.close)
        adapter._websocket = FakeWebSocket()
        robot_id, robot = adapter._selected_robot()
        source = {"available": True, "robotId": robot_id, "epoch": robot.get("epoch"),
                  "frameTimestamp": "2026-10-22T23:01:00Z", "xMetres": 1.25,
                  "depthPreview": "data:image/png;base64," + "a" * 86000}
        adapter.locomotion_measurement = lambda _: source
        position = adapter._observation()["state"]["locomotionMeasurement"]["position"]
        self.assertNotIn("depthPreview", position)
        self.assertEqual(position["xMetres"], source["xMetres"])
        self.assertEqual(position["observedAt"], source["frameTimestamp"])
        await adapter._handle_gateway_event({"t": "locomotion_measurement", "robot_id": robot_id, "epoch": robot.get("epoch")})
        telemetry = json.loads(adapter._websocket.sent[-1])["telemetry"]
        self.assertEqual(telemetry["locomotionMeasurement"]["position"], position)
        self.assertEqual(len(source["depthPreview"]), 86022, "dashboard's source preview remains intact")
        self.assertEqual(gateway.calls, [])

    async def test_measurement_from_previous_body_epoch_is_not_current_progress(self):
        gateway = FakeGateway()
        gateway.status = lambda: {"robots": {"robot": {"connected": True, "epoch": 8,
            "model": "v2-12servo", "features": [], "status": {}}}}
        adapter = EnvironmentAdapter(gateway, EnvironmentAdapterConfig(token="fixture", receipt_path=":memory:", robot_id="robot"))
        self.addCleanup(adapter.receipts.close)
        old = {"available": True, "robotId": "robot", "epoch": 7, "referenceId": "old", "rangeMetres": 1}
        adapter.locomotion_measurement = lambda _: old
        adapter._ground_range_measurement = old
        measurement = adapter._observation()["state"]["locomotionMeasurement"]
        for field in ("position", "target"):
            self.assertFalse(measurement[field]["available"])
            self.assertEqual(measurement[field]["referenceId"], "old")
            self.assertEqual(measurement[field]["reason"], "measurement_session_changed")
        self.assertTrue(old["available"], "recorded source measurement remains unchanged")

    async def test_actual_camera_metric_accessor_and_range_reach_adapter_with_provenance(self):
        from gateway.plugins import CameraFramePlugin
        from Emulator.tests.test_ground_plane import GroundPlaneTests
        fixture = GroundPlaneTests()
        fixture.setUp()
        fixture.owner._publish('robot', fixture.identity, fixture.initial, {'ambiguous': False})
        gateway = FakeGateway()
        gateway.status = lambda: {"robots": {"robot": {"connected": True, "connection_state": "online", "epoch": 1,
            "model": "v2-12servo", "features": [], "status": {}}}}
        gateway.clock = lambda: 0.0
        gateway.unsubscribe_frames = lambda callback: gateway.frame_callbacks.remove(callback)
        camera = CameraFramePlugin(gateway, lambda _: None, robot_id='robot')
        camera._ground_plane = fixture.owner
        camera._metric_latest['robot'] = fixture.owner.measurements['robot']
        adapter = EnvironmentAdapter(gateway, EnvironmentAdapterConfig(token='fixture', receipt_path=':memory:', robot_id='robot'))
        adapter.locomotion_measurement = camera.locomotion_measurement
        adapter.selected_ground_range = camera.selected_ground_range
        adapter._websocket = FakeWebSocket()
        try:
            position = adapter._observation()['state']['locomotionMeasurement']['position']
            self.assertTrue(position['available'])
            self.assertEqual(position['referenceId'], 'reference')
            self.assertEqual(position['robotId'], 'robot')
            self.assertAlmostEqual(position['xMetres'], 0)
            point = fixture.project(fixture.initial)[12] / [640, 480]
            await adapter._read_camera_visual({'version': 1, 'sessionId': adapter.config.session_id,
                'operation': 'groundRange', 'frameId': 'frame0', 'groundContact': {'x': float(point[0]), 'y': float(point[1])}})
            target = json.loads(adapter._websocket.sent[-1])['vision']['locomotionMeasurement']['target']
            self.assertTrue(target['available'])
            self.assertEqual(target['referenceFrameId'], 'frame0')
            self.assertEqual(target['groundContact'], {'x': float(point[0]), 'y': float(point[1])})
            self.assertEqual(target['robotId'], 'robot')
            self.assertEqual(target['sessionId'], adapter.config.session_id)
            self.assertEqual(gateway.calls, [])
        finally:
            await camera.aclose()
            adapter.receipts.close()

    async def test_camera_only_frames_publish_without_recognition_or_metric_calibration(self):
        from unittest.mock import AsyncMock
        from gateway.plugins import CameraFramePlugin
        gateway = FakeGateway()
        now = 10.0
        robot = {"connected": True, "connection_state": "online", "epoch": 1,
            "model": "v2-12servo", "features": [], "status": {}}
        gateway.status = lambda: {"robots": {"robot": robot}}
        gateway.clock = lambda: now
        gateway.unsubscribe_frames = lambda callback: gateway.frame_callbacks.remove(callback)
        camera = CameraFramePlugin(gateway, None, robot_id="robot", max_frame_age_s=1.5)
        camera._metric_call = AsyncMock(return_value={"available": False, "robotId": "robot", "epoch": 1,
            "reason": "No measured calibration"})
        adapter = EnvironmentAdapter(gateway, EnvironmentAdapterConfig(token="fixture", receipt_path=":memory:", robot_id="robot"))
        adapter.locomotion_measurement = camera.locomotion_measurement
        adapter._websocket = FakeWebSocket()
        published = []
        async def publish(event):
            published.append(event)
            await adapter._handle_gateway_event(event)
        gateway._publish_event = publish
        try:
            await camera._handle_frame({"frame_type": CAMERA_JPEG_FRAME_TYPE, "robot_id": "robot",
                "epoch": 1, "counter": 4, "received_at": now, "payload": b"fixture-jpeg"})
            await camera._metric_queue.join()
            measurement = adapter._observation()["state"]["locomotionMeasurement"]
            self.assertFalse(camera.recognition_status()["configured"])
            self.assertFalse(measurement["position"]["available"])
            raw = measurement["camera"]
            self.assertTrue(raw["available"])
            self.assertEqual(raw["frameId"], "ainekio-camera-fixture-gateway-robot-1-4")
            self.assertEqual(raw["sessionId"], adapter.config.session_id)
            await camera._handle_frame({"frame_type": CAMERA_JPEG_FRAME_TYPE, "robot_id": "robot",
                "epoch": 2, "counter": 99, "received_at": now, "payload": b"old-session-jpeg"})
            await camera._metric_queue.join()
            self.assertEqual(camera.camera_measurement("robot")["frameId"], raw["frameId"])
            self.assertAlmostEqual((datetime.fromisoformat(raw["expiresAt"]) - datetime.fromisoformat(raw["observedAt"])).total_seconds(), 1.5)
            self.assertTrue(any(json.loads(value).get("telemetry", {}).get("locomotionMeasurement", {}).get("camera", {}).get("available")
                for value in adapter._websocket.sent))
            now += 2
            self.assertFalse(adapter._observation()["state"]["locomotionMeasurement"]["camera"]["available"])
            now = 10
            robot["epoch"] = 2
            self.assertFalse(adapter._observation()["state"]["locomotionMeasurement"]["camera"]["available"])
            self.assertEqual(gateway.calls, [])
        finally:
            await camera.aclose()
            adapter.receipts.close()

    async def test_goal_crab_direction_retains_sideways_primitive_without_steering(self):
        for direction, wire in [('left', 'side_l'), ('right', 'side_r'), ('forward', 'fwd'), ('back', 'back')]:
            translated = translate_environment_action({'type': 'move', 'gait': 'crab', 'speed': 40, 'continuous': True,
                'locomotionGoal': {'kind': 'distance', 'direction': direction, 'metres': 1, 'tolerance': .1}}, model='v2-12servo')
            self.assertEqual(translated.params['dir'], wire)
            self.assertNotIn('forward', translated.params)
            self.assertNotIn('turn', translated.params)

    async def test_incomplete_goal_cannot_disguise_raw_gait_start(self):
        gateway = FakeGateway()
        adapter = EnvironmentAdapter(gateway, EnvironmentAdapterConfig(token='fixture', receipt_path=':memory:'))
        self.addCleanup(adapter.receipts.close)
        for goal in ({'kind': 'distance'}, {'kind': 'relativeTurn', 'degrees': 90},
                     {'kind': 'visual', 'target': 'window'}, {'kind': 'follow'}, {'kind': ['distance']}):
            result = await adapter.handle_action({'id': 'malformed', 'type': 'move', 'direction': 'forward', 'locomotionGoal': goal})
            self.assertEqual(result['type'], 'rejected')
            self.assertEqual(result['message'], 'locomotion_goal_required')
        self.assertEqual(gateway.calls, [])

    async def test_wire_goal_contract_retains_all_five_approved_variants(self):
        from gateway.environment_adapter.translation import valid_locomotion_goal
        target = {'frameId': 'frame', 'frameTimestamp': '2026-10-15T00:00:00Z',
                  'box': {'x': .2, 'y': .3, 'width': .3, 'height': .4}, 'groundContact': {'x': .3, 'y': .7}}
        goals = [
            {'kind': 'distance', 'direction': 'left', 'metres': .5, 'tolerance': .05},
            {'kind': 'relativeTurn', 'degrees': 450, 'tolerance': 2},
            {'kind': 'approach', 'target': target, 'proximity': {'kind': 'metric', 'metres': .5, 'tolerance': .1}},
            {'kind': 'follow', 'target': target, 'proximity': {'kind': 'imageRelative', 'boxHeight': .5, 'tolerance': .05}, 'endingCondition': 'until cancelled'},
            {'kind': 'visual', 'target': 'window', 'completionCriteria': 'reduced glare'},
        ]
        for goal in goals:
            self.assertTrue(valid_locomotion_goal(goal), goal)

class AvailabilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_watch_authentication_availability_and_no_control_side_effects(self):
        gateway = FakeGateway()
        adapter = EnvironmentAdapter(gateway, EnvironmentAdapterConfig(token="watch-token", session_id="test-session", receipt_path=":memory:"))
        async with serve(adapter.handler, "127.0.0.1", 0) as server:
            url = f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}"
            async with connect(url) as watcher:
                await watcher.send(json.dumps({"type": "bridge.watch", "version": 1, "token": "watch-token"}))
                availability = json.loads(await watcher.recv())
                self.assertEqual(availability, {"type": "bridge.availability", "version": 1,
                    "sessionId": "test-session", "gatewayInstance": "fixture-gateway", "robotId": "test-body", "connected": True})
                self.assertIsNone(adapter._websocket)
                self.assertFalse(adapter._bridge_ready)
                self.assertEqual(gateway.calls, [])
                async with connect(url) as control:
                    await control.send(json.dumps({"type": "bridge.connect", "version": 1, "token": "watch-token"}))
                    self.assertEqual(json.loads(await control.recv())["type"], "bridge.ready")
                    active = adapter._websocket
                    async with connect(url) as second_watcher:
                        await second_watcher.send(json.dumps({"type": "bridge.watch", "version": 1, "token": "watch-token"}))
                        self.assertEqual(json.loads(await second_watcher.recv())["type"], "bridge.availability")
                        self.assertIs(adapter._websocket, active)
                        self.assertTrue(adapter._bridge_ready)
                        self.assertEqual(gateway.calls, [])
                gateway.status = lambda: {"robots": {}}
                await adapter._handle_gateway_event({"t": "connection", "status": "disconnected", "robot_id": "test-body"})
                self.assertFalse(json.loads(await watcher.recv())["connected"])
            async with connect(url) as invalid:
                await invalid.send(json.dumps({"type": "bridge.watch", "version": 1, "token": "incorrect"}))
                with self.assertRaises(ConnectionClosedError):
                    await invalid.recv()
                self.assertEqual(invalid.close_code, 4001)
