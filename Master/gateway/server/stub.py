from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from protocol.control_v1 import PROTOCOL_VERSION, ProtocolValidationError, validate_control_message
from websockets.exceptions import ConnectionClosed


@dataclass(frozen=True)
class GatewayStubConfig:
    auth_token: str
    profile: str = "home"


@dataclass
class GatewayStub:
    config: GatewayStubConfig
    commands: Sequence[dict[str, object]] = field(default_factory=tuple)
    responses: list[dict[str, object]] = field(default_factory=list, init=False)
    last_hello: dict[str, object] | None = field(default=None, init=False)
    epoch: int = field(default=0, init=False)
    reconnect_cancellations: list[dict[str, object]] = field(default_factory=list, init=False)
    _active: dict[str, Any] = field(default_factory=dict, init=False, repr=False)
    _active_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)

    async def handler(self, websocket: Any, path: str) -> None:
        if path != "/robot":
            await websocket.close(code=1008, reason="wrong endpoint")
            return

        try:
            hello = await self._receive_hello(websocket)
        except Exception:
            await websocket.close(code=1002, reason="malformed hello")
            return

        if hello.get("ver") != PROTOCOL_VERSION:
            await self._send(websocket, {"t": "err", "code": "ver"})
            await websocket.close(code=4002, reason="unsupported protocol version")
            return
        if hello.get("auth") != self.config.auth_token:
            await self._send(websocket, {"t": "err", "code": "auth"})
            await websocket.close(code=4001, reason="authentication failed")
            return

        robot_id = str(hello["id"])
        async with self._active_lock:
            previous = self._active.get(robot_id)
            self.epoch += 1
            epoch = self.epoch
            self._active[robot_id] = websocket
        if previous is not None and previous is not websocket:
            await previous.close(code=4000, reason="new authenticated connection")

        self.last_hello = hello
        await self._send(
            websocket,
            {
                "t": "welcome",
                "ver": PROTOCOL_VERSION,
                "epoch": epoch,
                "profile": self.config.profile,
            },
        )

        active_sequence: int | None = None
        try:
            for command in self.commands:
                sequence = command.get("seq")
                active_sequence = sequence if type(sequence) is int else None
                await self._run_command(websocket, command)
                active_sequence = None
            await websocket.close(code=1000, reason="stub command script complete")
        except ConnectionClosed:
            if websocket.close_code == 4000 and active_sequence is not None:
                self.reconnect_cancellations.append(
                    {"seq": active_sequence, "code": "reconnect"}
                )
        finally:
            async with self._active_lock:
                if self._active.get(robot_id) is websocket:
                    del self._active[robot_id]

    async def _receive_hello(self, websocket: Any) -> dict[str, object]:
        raw = await asyncio.wait_for(websocket.recv(), timeout=3.0)
        if not isinstance(raw, str):
            raise RuntimeError("hello must be a text frame")
        value = json.loads(raw)
        if not isinstance(value, dict) or value.get("t") != "hello":
            raise RuntimeError("first body message must be hello")
        try:
            validate_control_message(value)
        except ProtocolValidationError as error:
            # Preserve a syntactically valid unsupported version long enough to
            # return the required protocol error and close code.
            if error.reason != "range:ver" or type(value.get("ver")) is not int:
                raise
        return value

    async def _run_command(
        self, websocket: Any, command: Mapping[str, object]
    ) -> None:
        validate_control_message(command)
        await self._send(websocket, command)
        needs_done = _command_needs_done(command)
        acknowledged = False

        while True:
            response = await self._receive_control(websocket)
            response_type = response.get("t")
            if response_type == "ping":
                await self._send(websocket, {"t": "pong"})
                continue
            if command.get("t") == "ping" and response_type == "pong":
                return
            if response_type in {"status", "event", "cam_meta", "pong"}:
                continue

            self.responses.append(response)
            if response_type == "nak":
                return
            if response.get("seq") != command.get("seq"):
                continue
            if response_type == "ack":
                acknowledged = True
                if not needs_done:
                    return
            elif response_type in {"done", "cancelled"} and acknowledged:
                return

    @staticmethod
    async def _receive_control(websocket: Any) -> dict[str, object]:
        raw = await asyncio.wait_for(websocket.recv(), timeout=10.0)
        if not isinstance(raw, str):
            raise RuntimeError("expected control text frame")
        value = json.loads(raw)
        validate_control_message(value)
        if not isinstance(value, dict):
            raise RuntimeError("control frame must be a JSON object")
        return value

    @staticmethod
    async def _send(websocket: Any, message: Mapping[str, object]) -> None:
        validate_control_message(message)
        await websocket.send(json.dumps(message, separators=(",", ":")))


def build_phase_one_commands(names: Sequence[str]) -> list[dict[str, object]]:
    commands: list[dict[str, object]] = []
    for sequence, name in enumerate(names, start=1):
        if name in {"stand", "neutral"}:
            commands.append({"t": "intent", "seq": sequence, "name": name})
        elif name == "walk":
            commands.append(
                {"t": "intent", "seq": sequence, "name": "walk", "dir": "fwd", "steps": 2}
            )
        elif name == "stop":
            commands.append({"t": "stop", "seq": sequence})
        else:
            raise ValueError(f"unsupported phase-1 stub command: {name}")
    return commands


def _command_needs_done(command: Mapping[str, object]) -> bool:
    message_type = command.get("t")
    return (
        message_type in {"intent", "snap"}
        or (message_type == "tts" and command.get("op") == "start")
        or (message_type == "state" and command.get("name") == "sleep")
    )
