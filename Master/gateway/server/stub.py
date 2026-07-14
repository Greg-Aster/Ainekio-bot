from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from protocol.control_v1 import PROTOCOL_VERSION, ProtocolValidationError, validate_control_message


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

        self.last_hello = hello
        self.epoch += 1
        await self._send(
            websocket,
            {
                "t": "welcome",
                "ver": PROTOCOL_VERSION,
                "epoch": self.epoch,
                "profile": self.config.profile,
            },
        )

        for command in self.commands:
            await self._run_command(websocket, command)
        await websocket.close(code=1000, reason="stub command script complete")

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
        needs_done = command.get("t") == "intent"
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
