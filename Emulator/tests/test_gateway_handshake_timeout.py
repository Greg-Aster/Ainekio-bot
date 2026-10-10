from __future__ import annotations

import asyncio
import unittest

import websockets

import gateway.server.__main__ as gateway_main


class GatewayHandshakeTimeoutTests(unittest.IsolatedAsyncioTestCase):
    async def test_environment_accepts_full_speech_without_changing_robot_frame_budget(self) -> None:
        async def receive(websocket, _path):
            try:
                payload = await websocket.recv()
                await websocket.send(str(len(payload)))
            except websockets.exceptions.ConnectionClosed:
                pass

        async with gateway_main.serve(
            receive, "127.0.0.1", 0,
            create_protocol=gateway_main.BoundedHandshakeProtocol,
            max_size=gateway_main.MAX_WEBSOCKET_MESSAGE_BYTES,
            ping_interval=None,
        ) as server:
            port = server.sockets[0].getsockname()[1]
            # Three minutes of speech must fit without a whole-reply cap.
            # The robot endpoint still receives small individual media frames.
            payload = bytes(180_000 * 32 + 4096 + 12)
            async with websockets.connect(f"ws://127.0.0.1:{port}/environment") as ws:
                await ws.send(payload)
                self.assertEqual(await ws.recv(), str(len(payload)))
            async with websockets.connect(f"ws://127.0.0.1:{port}/robot") as ws:
                await ws.send(payload)
                with self.assertRaises(websockets.exceptions.ConnectionClosedError) as closed:
                    await ws.recv()
                self.assertEqual(closed.exception.code, 1009)

    async def test_incomplete_websocket_handshake_is_closed(self) -> None:
        original_timeout = gateway_main.WEBSOCKET_OPEN_TIMEOUT_SECONDS
        gateway_main.WEBSOCKET_OPEN_TIMEOUT_SECONDS = 0.05
        try:
            async with gateway_main.serve(
                lambda _websocket, _path: asyncio.Future(),
                "127.0.0.1",
                0,
                create_protocol=gateway_main.BoundedHandshakeProtocol,
                ping_interval=None,
            ) as server:
                port = server.sockets[0].getsockname()[1]
                reader, writer = await asyncio.open_connection("127.0.0.1", port)
                response = await asyncio.wait_for(reader.read(), timeout=0.5)
                self.assertTrue(reader.at_eof())
                self.assertIn(b"Connection: close", response)
                writer.close()
                await writer.wait_closed()
        finally:
            gateway_main.WEBSOCKET_OPEN_TIMEOUT_SECONDS = original_timeout


if __name__ == "__main__":
    unittest.main()
