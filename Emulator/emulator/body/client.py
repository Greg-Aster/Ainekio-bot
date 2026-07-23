from __future__ import annotations

import asyncio
import json
import random
from dataclasses import dataclass
from time import monotonic
from typing import Any

import websockets
from websockets.exceptions import ConnectionClosed

from protocol.control_v1 import (
    MOTION_PLAN_FEATURE,
    PROTOCOL_VERSION,
    validate_control_message,
)

from .session import BodySession
from emulator.faults import EmulatorFaultController


MAX_WEBSOCKET_MESSAGE_BYTES = (120 * 1024) + 5
# Keep emulator liveness identical to the physical controller: a heartbeat each
# second and a local failsafe after four seconds without gateway control.
PING_AFTER_SECONDS = 1.0
FAILSAFE_AFTER_SECONDS = 4.0
CONTROL_QUEUE_DEPTH = 32


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
    sleep_time_scale: float = 1.0

    def __post_init__(self) -> None:
        if not 0.0 < self.sleep_time_scale <= 1.0:
            raise ValueError("sleep_time_scale must be greater than zero and at most one")


class ProtocolV1BodyClient:
    def __init__(
        self,
        config: BodyClientConfig,
        session: BodySession,
        faults: EmulatorFaultController | None = None,
    ) -> None:
        self._config = config
        self._session = session
        self._faults = faults

    async def run_once(self) -> float | None:
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

            async def emit_binary(frame: bytes) -> None:
                nonlocal last_sent
                async with send_lock:
                    await websocket.send(frame)
                    last_sent = monotonic()

            await emit(
                {
                    "t": "hello",
                    "ver": PROTOCOL_VERSION,
                    "fw": self._config.firmware_version,
                    "id": self._config.robot_id,
                    "auth": self._config.auth_token,
                    "features": [MOTION_PLAN_FEATURE],
                }
            )
            welcome = await _receive_control(websocket)
            if welcome.get("t") == "err":
                raise HandshakeRejected(str(welcome.get("code")))
            if welcome.get("t") != "welcome":
                raise RuntimeError("gateway did not send welcome after hello")
            await self._session.begin(welcome)

            command_queue: asyncio.Queue[str] = asyncio.Queue(maxsize=CONTROL_QUEUE_DEPTH)
            last_received = monotonic()
            next_status = monotonic()
            sleep_delay: float | None = None

            async def receive_controls() -> None:
                nonlocal last_received
                while True:
                    raw = await websocket.recv()
                    if isinstance(raw, bytes):
                        await command_queue.join()
                        await self._session.handle_binary(raw, emit)
                        continue
                    last_received = monotonic()

                    try:
                        candidate = json.loads(raw)
                    except (json.JSONDecodeError, UnicodeError):
                        candidate = None
                    if isinstance(candidate, dict) and candidate.get("t") == "stop":
                        await self._session.handle(candidate, emit, emit_binary)
                        continue

                    try:
                        command_queue.put_nowait(raw)
                    except asyncio.QueueFull:
                        await websocket.close(code=1013, reason="control queue overflow")
                        return

            async def process_controls() -> None:
                nonlocal sleep_delay
                while True:
                    raw = await command_queue.get()
                    try:
                        if self._faults is not None:
                            delay = self._faults.snapshot().control_stall_ms / 1000.0
                            if delay:
                                await asyncio.sleep(delay)
                        await self._session.handle_raw(raw, emit, emit_binary)
                        sleep_seconds = self._session.take_sleep_request()
                        if sleep_seconds is not None:
                            sleep_delay = sleep_seconds * self._config.sleep_time_scale
                            await websocket.close(code=1000, reason="deep sleep")
                            return
                    finally:
                        command_queue.task_done()

            async def service_session() -> None:
                nonlocal next_status, sleep_delay
                while True:
                    now = monotonic()
                    if now - last_received >= FAILSAFE_AFTER_SECONDS:
                        await websocket.close(code=1011, reason="control timeout")
                        raise RuntimeError("gateway control liveness timeout")
                    if self._faults is not None and self._faults.take_drop_link():
                        await websocket.close(code=1011, reason="injected link drop")
                        return
                    if self._faults is not None and self._faults.take_malformed_control():
                        await self._session.handle_raw("{malformed", emit, emit_binary)
                    if now - last_sent >= PING_AFTER_SECONDS:
                        await emit({"t": "ping"})
                    if now >= next_status:
                        await emit(self._session.status())
                        interval = 5.0 if self._session.profile == "home" else 30.0
                        next_status = now + interval
                    await self._session.service_media(emit, emit_binary)
                    sleep_seconds = self._session.take_sleep_request()
                    if sleep_seconds is not None:
                        await emit(self._session.status())
                        sleep_delay = sleep_seconds * self._config.sleep_time_scale
                        await websocket.close(code=1000, reason="battery deep sleep")
                        return
                    await asyncio.sleep(0.02)

            tasks = {
                asyncio.create_task(receive_controls(), name="ainekio-control-rx"),
                asyncio.create_task(process_controls(), name="ainekio-control-dispatch"),
                asyncio.create_task(service_session(), name="ainekio-session-service"),
            }
            try:
                done, _pending = await asyncio.wait(
                    tasks,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in done:
                    task.result()
            except ConnectionClosed:
                pass
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                if sleep_delay is None:
                    await self._session.enter_failsafe()
                await self._session.close()
            return sleep_delay

    async def run_forever(self) -> None:
        delay = 1.0
        while True:
            try:
                sleep_delay = await self.run_once()
                delay = 1.0
                if sleep_delay is not None:
                    await asyncio.sleep(sleep_delay)
                    continue
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
