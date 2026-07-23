from __future__ import annotations

import asyncio
import unittest

import websockets

import gateway.server.__main__ as gateway_main


class GatewayHandshakeTimeoutTests(unittest.IsolatedAsyncioTestCase):
    async def test_incomplete_websocket_handshake_is_closed(self) -> None:
        original_timeout = gateway_main.WEBSOCKET_OPEN_TIMEOUT_SECONDS
        gateway_main.WEBSOCKET_OPEN_TIMEOUT_SECONDS = 0.05
        try:
            async with websockets.serve(
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
