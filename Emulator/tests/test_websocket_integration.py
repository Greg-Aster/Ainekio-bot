from __future__ import annotations

import json
import unittest
from collections.abc import Mapping

import websockets

from emulator.body import BodySession, PortableCore
from emulator.body.client import BodyClientConfig, HandshakeRejected, ProtocolV1BodyClient
from gateway.server import GatewayStub, GatewayStubConfig
from Emulator.tests.support import build_core_library


class ImmediateMotionBackend:
    async def execute(self, message: Mapping[str, object], *, session_id: str) -> None:
        return None

    async def stop(self, sequence: int, *, session_id: str) -> None:
        return None


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


if __name__ == "__main__":
    unittest.main()
