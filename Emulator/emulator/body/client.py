from __future__ import annotations

import asyncio
import json
import random
from dataclasses import dataclass
from time import monotonic
from typing import Any

import websockets
from websockets.exceptions import ConnectionClosed

from protocol.control_v1 import PROTOCOL_VERSION, validate_control_message

from .session import BodySession


MAX_WEBSOCKET_MESSAGE_BYTES = (120 * 1024) + 5
PING_AFTER_SECONDS = 2.0
FAILSAFE_AFTER_SECONDS = 3.0


class HandshakeRejected(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(f"gateway rejected body handshake: {code}")
        self.code = code


@dataclass(frozen=True)
class BodyClientConfig:
    endpoint: str
    robot_id: str
    auth_token: str
    firmware_version: str = "0.1.0-host"


class ProtocolV1BodyClient:
    def __init__(self, config: BodyClientConfig, session: BodySession) -> None:
        self._config = config
        self._session = session

    async def run_once(self) -> None:
        async with websockets.connect(
            self._config.endpoint,
            max_size=MAX_WEBSOCKET_MESSAGE_BYTES,
            max_queue=32,
            ping_interval=None,
            close_timeout=1,
            open_timeout=5,
        ) as websocket:
            send_lock = asyncio.Lock()
            last_sent = monotonic()

            async def emit(message: dict[str, object]) -> None:
                nonlocal last_sent
                validate_control_message(message)
                encoded = json.dumps(message, separators=(",", ":"))
                async with send_lock:
                    await websocket.send(encoded)
                    last_sent = monotonic()

            await emit(
                {
                    "t": "hello",
                    "ver": PROTOCOL_VERSION,
                    "fw": self._config.firmware_version,
                    "id": self._config.robot_id,
                    "auth": self._config.auth_token,
                }
            )
            welcome = await _receive_control(websocket)
            if welcome.get("t") == "err":
                raise HandshakeRejected(str(welcome.get("code")))
            if welcome.get("t") != "welcome":
                raise RuntimeError("gateway did not send welcome after hello")
            await self._session.begin(welcome)

            last_received = monotonic()
            next_status = monotonic()
            try:
                while True:
                    now = monotonic()
                    if now - last_received >= FAILSAFE_AFTER_SECONDS:
                        await self._session.enter_failsafe()
                        await websocket.close(code=1011, reason="control timeout")
                        raise RuntimeError("gateway control liveness timeout")
                    if now - last_sent >= PING_AFTER_SECONDS:
                        await emit({"t": "ping"})
                    if now >= next_status:
                        await emit(self._session.status())
                        interval = 5.0 if self._session.profile == "home" else 30.0
                        next_status = now + interval

                    try:
                        raw = await asyncio.wait_for(websocket.recv(), timeout=0.1)
                    except asyncio.TimeoutError:
                        continue
                    if isinstance(raw, bytes):
                        continue

                    last_received = monotonic()
                    await self._session.handle_raw(raw, emit)
            except ConnectionClosed:
                await self._session.enter_failsafe()
            finally:
                await self._session.close()

    async def run_forever(self) -> None:
        delay = 1.0
        while True:
            try:
                await self.run_once()
                delay = 1.0
            except HandshakeRejected:
                raise
            except asyncio.CancelledError:
                raise
            except Exception:
                pass

            jittered = delay * random.uniform(0.8, 1.2)
            await asyncio.sleep(jittered)
            delay = min(30.0, delay * 2.0)


async def _receive_control(websocket: Any) -> dict[str, object]:
    raw = await asyncio.wait_for(websocket.recv(), timeout=3.0)
    if not isinstance(raw, str):
        raise RuntimeError("expected a WebSocket text control frame")
    message = json.loads(raw)
    validate_control_message(message)
    if not isinstance(message, dict):
        raise RuntimeError("control frame must contain one JSON object")
    return message
