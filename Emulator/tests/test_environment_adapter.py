from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone

from gateway.environment_adapter import (
    EnvironmentAdapter,
    EnvironmentAdapterConfig,
    translate_environment_action,
)
from protocol.binary_helpers import CAMERA_JPEG_FRAME_TYPE
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

    async def request_snap(self, **kwargs: object) -> int:
        self.calls.append(("snap", kwargs))
        return 9

    async def wait_terminal(self, sequence: int, **kwargs: object) -> dict[str, object]:
        self.calls.append(("wait", (sequence, kwargs)))
        return {"t": "done", "seq": sequence}

    async def publish_transcript(self, transcript: dict[str, object]) -> None:
        self.transcripts.append(transcript)

    def status(self) -> dict[str, object]:
        return {"profile": "home", "robots": {"test-body": {"connected": True}}}


class FakeWebSocket:
    def __init__(self) -> None:
        self.closed = False
        self.sent: list[str] = []

    async def send(self, payload: str) -> None:
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

        self.assertEqual(websocket.sent, [])

    def test_adapter_requires_a_bounded_secret(self) -> None:
        with self.assertRaisesRegex(ValueError, "token"):
            EnvironmentAdapterConfig(token="")


if __name__ == "__main__":
    unittest.main()
