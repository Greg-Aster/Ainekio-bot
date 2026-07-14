from __future__ import annotations

import asyncio
import json
import unittest
from collections.abc import Mapping

import websockets

from emulator.body import BodySession, PortableCore
from emulator.body.client import (
    MAX_WEBSOCKET_MESSAGE_BYTES,
    BodyClientConfig,
    HandshakeRejected,
    ProtocolV1BodyClient,
)
from emulator.body.media import MAX_JPEG_BYTES, FixtureCameraSource
from gateway.server import GatewayStub, GatewayStubConfig
from protocol.binary_helpers import SPEAKER_PCM_FRAME_TYPE, encode_binary_frame
from Emulator.tests.support import build_core_library


class ImmediateMotionBackend:
    async def execute(self, message: Mapping[str, object], *, session_id: str) -> None:
        return None

    async def stop(self, sequence: int, *, session_id: str) -> None:
        return None


class ControlledMotionBackend:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def execute(self, message: Mapping[str, object], *, session_id: str) -> None:
        self.started.set()
        await self.release.wait()

    async def stop(self, sequence: int, *, session_id: str) -> None:
        return None


class BlockingDispatchSession(BodySession):
    def __init__(
        self,
        core: PortableCore,
        backend: ImmediateMotionBackend,
        **kwargs: object,
    ) -> None:
        super().__init__(core, backend, **kwargs)
        self.dispatch_started = asyncio.Event()
        self.release_dispatch = asyncio.Event()

    async def handle_raw(
        self,
        raw: str,
        emit: object,
        emit_binary: object = None,
    ) -> None:
        self.dispatch_started.set()
        await self.release_dispatch.wait()


class WebSocketIntegrationTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.library_path = build_core_library()

    async def test_body_initiates_authenticated_session_and_completes_motion(self) -> None:
        stub = GatewayStub(
            GatewayStubConfig(auth_token="test-token"),
            commands=({"t": "intent", "seq": 1, "name": "stand"},),
        )
        core = PortableCore(self.library_path)
        session = BodySession(core, ImmediateMotionBackend())

        async with websockets.serve(stub.handler, "127.0.0.1", 0, ping_interval=None) as server:
            port = server.sockets[0].getsockname()[1]
            client = ProtocolV1BodyClient(
                BodyClientConfig(
                    endpoint=f"ws://127.0.0.1:{port}/robot",
                    robot_id="ainekio-test-01",
                    auth_token="test-token",
                ),
                session,
            )
            await client.run_once()

        self.assertEqual(stub.last_hello["id"], "ainekio-test-01")
        self.assertEqual(
            stub.responses,
            [{"t": "ack", "seq": 1}, {"t": "done", "seq": 1}],
        )
        core.close()

    async def test_wrong_token_is_rejected(self) -> None:
        stub = GatewayStub(GatewayStubConfig(auth_token="correct-token"))
        core = PortableCore(self.library_path)
        session = BodySession(core, ImmediateMotionBackend())

        async with websockets.serve(stub.handler, "127.0.0.1", 0, ping_interval=None) as server:
            port = server.sockets[0].getsockname()[1]
            client = ProtocolV1BodyClient(
                BodyClientConfig(
                    endpoint=f"ws://127.0.0.1:{port}/robot",
                    robot_id="ainekio-test-01",
                    auth_token="wrong-token",
                ),
                session,
            )
            with self.assertRaises(HandshakeRejected):
                await client.run_once()

        core.close()

    async def test_gateway_rejects_unsupported_version_with_close_4002(self) -> None:
        stub = GatewayStub(GatewayStubConfig(auth_token="test-token"))

        async with websockets.serve(stub.handler, "127.0.0.1", 0, ping_interval=None) as server:
            port = server.sockets[0].getsockname()[1]
            async with websockets.connect(
                f"ws://127.0.0.1:{port}/robot", ping_interval=None
            ) as websocket:
                await websocket.send(
                    json.dumps(
                        {
                            "t": "hello",
                            "ver": 2,
                            "fw": "test",
                            "id": "ainekio-test-01",
                            "auth": "test-token",
                        }
                    )
                )
                self.assertEqual(json.loads(await websocket.recv()), {"t": "err", "code": "ver"})
                await websocket.wait_closed()
                self.assertEqual(websocket.close_code, 4002)

    async def test_sleep_lifecycle_closes_cleanly_and_returns_scaled_delay(self) -> None:
        responses: list[dict[str, object]] = []
        close_codes: list[int | None] = []
        connection_times: list[float] = []
        reconnected = asyncio.Event()

        async def sleep_gateway(websocket: object, path: str) -> None:
            self.assertEqual(path, "/robot")
            await websocket.recv()
            connection_times.append(asyncio.get_running_loop().time())
            epoch = len(connection_times)
            await websocket.send(
                json.dumps(
                    {"t": "welcome", "ver": 1, "epoch": epoch, "profile": "home"}
                )
            )
            if epoch > 1:
                reconnected.set()
                await websocket.close(code=1000, reason="reconnect observed")
                return
            await websocket.send(
                json.dumps(
                    {"t": "state", "seq": 1, "name": "sleep", "sleep_s": 60}
                )
            )
            try:
                while True:
                    raw = await websocket.recv()
                    if isinstance(raw, bytes):
                        continue
                    message = json.loads(raw)
                    if message.get("t") == "ping":
                        await websocket.send(json.dumps({"t": "pong"}))
                    else:
                        responses.append(message)
            except websockets.ConnectionClosed:
                close_codes.append(websocket.close_code)

        core = PortableCore(self.library_path)
        session = BodySession(core, ImmediateMotionBackend())

        async with websockets.serve(
            sleep_gateway,
            "127.0.0.1",
            0,
            ping_interval=None,
        ) as server:
            port = server.sockets[0].getsockname()[1]
            client = ProtocolV1BodyClient(
                BodyClientConfig(
                    endpoint=f"ws://127.0.0.1:{port}/robot",
                    robot_id="ainekio-test-01",
                    auth_token="test-token",
                    sleep_time_scale=0.001,
                ),
                session,
            )
            client_task = asyncio.create_task(client.run_forever())
            await asyncio.wait_for(reconnected.wait(), timeout=1.0)
            client_task.cancel()
            await asyncio.gather(client_task, return_exceptions=True)

        lifecycle = [
            response
            for response in responses
            if response.get("t") in {"ack", "done", "cancelled", "nak"}
        ]
        self.assertEqual(
            lifecycle,
            [
                {"t": "ack", "seq": 1, "sleep_s": 60},
                {"t": "done", "seq": 1},
            ],
        )
        final_statuses = [
            response
            for response in responses
            if response.get("t") == "status" and response.get("state") == "deep-sleep"
        ]
        self.assertEqual(len(final_statuses), 1)
        self.assertEqual(close_codes, [1000])
        self.assertEqual(len(connection_times), 2)
        scaled_delay = connection_times[1] - connection_times[0]
        self.assertGreaterEqual(scaled_delay, 0.04)
        self.assertLess(scaled_delay, 0.25)
        core.close()

    async def test_new_authenticated_socket_replaces_old_session(self) -> None:
        stub = GatewayStub(
            GatewayStubConfig(auth_token="test-token"),
            commands=({"t": "intent", "seq": 1, "name": "stand"},),
        )
        hello = {
            "t": "hello",
            "ver": 1,
            "fw": "test",
            "id": "ainekio-test-01",
            "auth": "test-token",
        }

        async with websockets.serve(stub.handler, "127.0.0.1", 0, ping_interval=None) as server:
            port = server.sockets[0].getsockname()[1]
            endpoint = f"ws://127.0.0.1:{port}/robot"
            async with websockets.connect(endpoint, ping_interval=None) as first:
                await first.send(json.dumps(hello))
                first_welcome = json.loads(await first.recv())
                await first.recv()

                async with websockets.connect(endpoint, ping_interval=None) as second:
                    await second.send(json.dumps(hello))
                    second_welcome = json.loads(await second.recv())
                    second_command = json.loads(await second.recv())

                    await first.wait_closed()
                    self.assertEqual(first.close_code, 4000)
                    self.assertNotEqual(first_welcome["epoch"], second_welcome["epoch"])

                    await second.send(json.dumps({"t": "ack", "seq": 1}))
                    await second.send(json.dumps({"t": "done", "seq": 1}))
                    self.assertEqual(second_command["seq"], 1)
                    await second.wait_closed()

        self.assertEqual(stub.reconnect_cancellations, [{"seq": 1, "code": "reconnect"}])

    async def test_oversized_control_frame_closes_into_failsafe(self) -> None:
        close_codes: list[int | None] = []

        async def oversized_gateway(websocket: object, path: str) -> None:
            self.assertEqual(path, "/robot")
            await websocket.recv()
            await websocket.send(
                json.dumps({"t": "welcome", "ver": 1, "epoch": 1, "profile": "home"})
            )
            await websocket.send("x" * (MAX_WEBSOCKET_MESSAGE_BYTES + 1))
            await websocket.wait_closed()
            close_codes.append(websocket.close_code)

        core = PortableCore(self.library_path)
        session = BodySession(core, ImmediateMotionBackend())
        async with websockets.serve(
            oversized_gateway,
            "127.0.0.1",
            0,
            ping_interval=None,
        ) as server:
            port = server.sockets[0].getsockname()[1]
            client = ProtocolV1BodyClient(
                BodyClientConfig(
                    endpoint=f"ws://127.0.0.1:{port}/robot",
                    robot_id="ainekio-test-01",
                    auth_token="test-token",
                ),
                session,
            )
            await client.run_once()

        self.assertEqual(close_codes, [1009])
        self.assertEqual(core.state, 4)
        self.assertFalse(core.servos_attached)
        core.close()

    async def test_stop_bypasses_saturated_control_queue(self) -> None:
        stop_acknowledged = asyncio.Event()
        close_codes: list[int | None] = []
        stop_latencies: list[float] = []
        max_camera_received = asyncio.Event()
        core = PortableCore(self.library_path)
        session = BlockingDispatchSession(
            core,
            ImmediateMotionBackend(),
            camera_source=FixtureCameraSource(
                b"\xff\xd8" + bytes(MAX_JPEG_BYTES - 4) + b"\xff\xd9"
            ),
        )
        session._camera_settings = {"on": True, "fps": 10, "res": "VGA"}

        async def flooding_gateway(websocket: object, path: str) -> None:
            self.assertEqual(path, "/robot")
            await websocket.recv()
            await websocket.send(
                json.dumps({"t": "welcome", "ver": 1, "epoch": 1, "profile": "home"})
            )
            while not max_camera_received.is_set():
                initial = await websocket.recv()
                if isinstance(initial, bytes) and len(initial) == MAX_JPEG_BYTES + 5:
                    max_camera_received.set()
            await websocket.send(json.dumps({"t": "profile", "seq": 1, "name": "home"}))
            await asyncio.wait_for(session.dispatch_started.wait(), timeout=1.0)
            for sequence in range(2, 34):
                await websocket.send(
                    json.dumps({"t": "profile", "seq": sequence, "name": "home"})
                )
            stop_sent_at = asyncio.get_running_loop().time()
            await websocket.send(json.dumps({"t": "stop", "seq": 34}))
            await websocket.send(json.dumps({"t": "profile", "seq": 35, "name": "home"}))

            try:
                while True:
                    raw = await websocket.recv()
                    if isinstance(raw, bytes):
                        if len(raw) == MAX_JPEG_BYTES + 5:
                            max_camera_received.set()
                        continue
                    response = json.loads(raw)
                    if response.get("t") == "ack" and response.get("seq") == 34:
                        stop_latencies.append(
                            asyncio.get_running_loop().time() - stop_sent_at
                        )
                        stop_acknowledged.set()
            except websockets.ConnectionClosed:
                close_codes.append(websocket.close_code)

        async with websockets.serve(
            flooding_gateway,
            "127.0.0.1",
            0,
            ping_interval=None,
        ) as server:
            port = server.sockets[0].getsockname()[1]
            client = ProtocolV1BodyClient(
                BodyClientConfig(
                    endpoint=f"ws://127.0.0.1:{port}/robot",
                    robot_id="ainekio-test-01",
                    auth_token="test-token",
                ),
                session,
            )
            await client.run_once()

        self.assertTrue(stop_acknowledged.is_set())
        self.assertTrue(max_camera_received.is_set())
        self.assertLess(stop_latencies[0], 0.1)
        self.assertEqual(close_codes, [1013])
        self.assertEqual(core.state, 4)
        self.assertFalse(core.servos_attached)
        core.close()

    async def test_disconnect_mid_motion_fails_safe_and_reconnect_resets_epoch(self) -> None:
        connection_count = 0
        backend = ControlledMotionBackend()
        core = PortableCore(self.library_path)
        session = BodySession(core, backend)

        async def reconnecting_gateway(websocket: object, path: str) -> None:
            nonlocal connection_count
            self.assertEqual(path, "/robot")
            connection_count += 1
            epoch = connection_count
            await websocket.recv()
            await websocket.send(
                json.dumps({"t": "welcome", "ver": 1, "epoch": epoch, "profile": "home"})
            )
            command = (
                {"t": "intent", "seq": 1, "name": "walk", "dir": "fwd", "steps": 10}
                if epoch == 1
                else {"t": "intent", "seq": 1, "name": "stand"}
            )
            await websocket.send(json.dumps(command))
            while True:
                response = json.loads(await websocket.recv())
                if response.get("t") == "ack" and response.get("seq") == 1:
                    if epoch == 1:
                        await websocket.close(code=1011, reason="injected disconnect")
                        return
                if epoch == 2 and response.get("t") == "done" and response.get("seq") == 1:
                    await websocket.close(code=1000, reason="test complete")
                    return

        async with websockets.serve(
            reconnecting_gateway,
            "127.0.0.1",
            0,
            ping_interval=None,
        ) as server:
            port = server.sockets[0].getsockname()[1]
            client = ProtocolV1BodyClient(
                BodyClientConfig(
                    endpoint=f"ws://127.0.0.1:{port}/robot",
                    robot_id="ainekio-test-01",
                    auth_token="test-token",
                ),
                session,
            )

            await client.run_once()
            self.assertTrue(backend.started.is_set())
            self.assertEqual(core.state, 4)
            self.assertFalse(core.servos_attached)
            self.assertIsNone(session.active_sequence)

            backend.release.set()
            await client.run_once()

        self.assertEqual(connection_count, 2)
        core.close()

    async def test_tts_end_cannot_overtake_earlier_speaker_frame(self) -> None:
        responses: list[dict[str, object]] = []

        async def tts_gateway(websocket: object, path: str) -> None:
            self.assertEqual(path, "/robot")
            await websocket.recv()
            await websocket.send(
                json.dumps({"t": "welcome", "ver": 1, "epoch": 1, "profile": "home"})
            )
            await websocket.send(json.dumps({"t": "tts", "seq": 1, "op": "start"}))
            await websocket.send(
                encode_binary_frame(SPEAKER_PCM_FRAME_TYPE, 0, bytes(640))
            )
            await websocket.send(json.dumps({"t": "tts", "seq": 2, "op": "end"}))

            while True:
                response = json.loads(await websocket.recv())
                if response.get("t") in {"ack", "done", "cancelled", "nak"}:
                    responses.append(response)
                if response.get("t") == "done" and response.get("seq") == 1:
                    await websocket.close(code=1000, reason="test complete")
                    return

        core = PortableCore(self.library_path)
        session = BodySession(core, ImmediateMotionBackend())
        async with websockets.serve(
            tts_gateway,
            "127.0.0.1",
            0,
            ping_interval=None,
        ) as server:
            port = server.sockets[0].getsockname()[1]
            client = ProtocolV1BodyClient(
                BodyClientConfig(
                    endpoint=f"ws://127.0.0.1:{port}/robot",
                    robot_id="ainekio-test-01",
                    auth_token="test-token",
                ),
                session,
            )
            await client.run_once()

        self.assertEqual(
            responses,
            [
                {"t": "ack", "seq": 1},
                {"t": "ack", "seq": 2},
                {"t": "done", "seq": 1},
            ],
        )
        core.close()


if __name__ == "__main__":
    unittest.main()
