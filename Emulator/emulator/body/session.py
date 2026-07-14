from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Mapping
from time import monotonic
from typing import Protocol

from protocol.control_v1 import (
    INTENT_NAMES,
    MAX_SEQUENCE,
    ProtocolValidationError,
    validate_control_message,
)

from .core import CoreLifecycle, CoreRejection, PortableCore


EmitControl = Callable[[dict[str, object]], Awaitable[None]]

_BODY_COMMAND_TYPES = frozenset(
    {
        "intent",
        "stop",
        "tts",
        "cam",
        "snap",
        "mic",
        "profile",
        "state",
        "mode",
        "servo",
        "limits",
        "pose_save",
        "cal_save",
    }
)
_PHASE_ONE_MOVEMENT = frozenset({"stand", "neutral", "walk"})
_REJECTION_CODES = {
    CoreRejection.STALE: "stale",
    CoreRejection.MODE: "mode",
    CoreRejection.UNSAFE: "unsafe",
    CoreRejection.BUSY: "busy",
    CoreRejection.MALFORMED: "malformed",
}
_STATE_NAMES = ("active", "idle", "dozing", "deep-sleep", "failsafe")
_PROFILE_NAMES = ("home", "tether")
_STOP_BACKEND_WAIT_SECONDS = 0.05


class MotionBackend(Protocol):
    async def execute(self, message: Mapping[str, object], *, session_id: str) -> None:
        ...

    async def stop(self, sequence: int, *, session_id: str) -> None:
        ...


class BodySession:
    def __init__(self, core: PortableCore, motion_backend: MotionBackend) -> None:
        self._core = core
        self._motion_backend = motion_backend
        self._epoch = 0
        self._session_id = "disconnected"
        self._started_at = monotonic()
        self._active_sequence: int | None = None
        self._active_task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()

    async def begin(self, welcome: Mapping[str, object]) -> None:
        validate_control_message(welcome)
        if welcome.get("t") != "welcome":
            raise RuntimeError("session must begin with a welcome message")

        await self._cancel_active()
        self._epoch = int(welcome["epoch"])
        self._session_id = f"protocol-v1:{self._epoch}"
        self._core.begin_session(self._epoch, str(welcome["profile"]))

    async def handle_raw(self, raw: str, emit: EmitControl) -> None:
        try:
            message = json.loads(raw)
        except (json.JSONDecodeError, UnicodeError):
            await emit({"t": "nak", "code": "malformed"})
            return
        await self.handle(message, emit)

    async def handle(self, message: object, emit: EmitControl) -> None:
        try:
            validate_control_message(message)
        except ProtocolValidationError:
            await emit(_validation_nak(message))
            return

        if not isinstance(message, Mapping):
            await emit({"t": "nak", "code": "malformed"})
            return

        message_type = message.get("t")
        if message_type == "ping":
            await emit({"t": "pong"})
            return
        if message_type not in _BODY_COMMAND_TYPES:
            await emit(_validation_nak(message))
            return

        if message_type == "stop":
            await self._handle_stop(message, emit)
            return

        if message_type == "intent" and message.get("name") in _PHASE_ONE_MOVEMENT:
            await self._handle_movement(message, emit)
            return

        sequence = int(message["seq"])
        rejection = self._core.claim_sequence(sequence)
        if rejection == CoreRejection.NONE:
            await emit(
                {
                    "t": "nak",
                    "seq": sequence,
                    "code": "busy",
                    "msg": "capability unavailable in emulator phase 1",
                }
            )
        else:
            await emit(_decision_nak(sequence, rejection))

    async def _handle_movement(
        self, message: Mapping[str, object], emit: EmitControl
    ) -> None:
        sequence = int(message["seq"])
        async with self._lock:
            busy = self._active_task is not None
        if busy:
            rejection = self._core.claim_sequence(sequence)
            if rejection == CoreRejection.NONE:
                await emit({"t": "nak", "seq": sequence, "code": "busy"})
            else:
                await emit(_decision_nak(sequence, rejection))
            return

        decision = self._core.accept(message)
        if not decision.accepted:
            await emit(_decision_nak(sequence, decision.rejection))
            return

        await emit({"t": "ack", "seq": sequence})
        if decision.lifecycle != CoreLifecycle.ACK_THEN_DONE:
            return

        async with self._lock:
            self._active_sequence = sequence
            self._active_task = asyncio.create_task(
                self._run_movement(sequence, dict(message), emit),
                name=f"ainekio-motion-{sequence}",
            )

    async def _handle_stop(
        self, message: Mapping[str, object], emit: EmitControl
    ) -> None:
        sequence = int(message["seq"])
        decision = self._core.accept(message)
        cancelled_sequence = await self._cancel_active()
        if not decision.accepted:
            await emit(_decision_nak(sequence, decision.rejection))
            return

        stop_task = asyncio.create_task(
            self._motion_backend.stop(sequence, session_id=self._session_id),
            name=f"ainekio-stop-{sequence}",
        )
        await emit({"t": "ack", "seq": sequence})
        if cancelled_sequence is not None:
            await emit({"t": "cancelled", "seq": cancelled_sequence, "code": "stop"})
        try:
            await asyncio.wait_for(stop_task, timeout=_STOP_BACKEND_WAIT_SECONDS)
        except (asyncio.TimeoutError, Exception):
            # The portable core has already detached motion. Renderer transport
            # must never delay or invalidate the stop path.
            pass

    async def _run_movement(
        self,
        sequence: int,
        message: Mapping[str, object],
        emit: EmitControl,
    ) -> None:
        try:
            await self._motion_backend.execute(message, session_id=self._session_id)
        except asyncio.CancelledError:
            return
        except Exception:
            async with self._lock:
                if self._active_sequence == sequence:
                    self._active_sequence = None
                    self._active_task = None
            await emit({"t": "cancelled", "seq": sequence, "code": "overflow"})
            return

        async with self._lock:
            if self._active_sequence != sequence:
                return
            self._active_sequence = None
            self._active_task = None
        await emit({"t": "done", "seq": sequence})

    async def enter_failsafe(self) -> None:
        self._core.enter_failsafe()
        await self._cancel_active()

    async def close(self) -> None:
        await self._cancel_active()

    async def wait_until_idle(self) -> None:
        async with self._lock:
            task = self._active_task
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)

    def status(self, *, rssi: int = -40) -> dict[str, object]:
        state_index = self._core.state
        state = _STATE_NAMES[state_index] if 0 <= state_index < len(_STATE_NAMES) else "failsafe"
        return {
            "t": "status",
            "vbat": 8.0,
            "rssi": rssi,
            "state": state,
            "uptime": int(monotonic() - self._started_at),
            "heap": 0,
            "sd": False,
            "cam_drops": 0,
            "spk_underruns": 0,
            "mic_drops": 0,
        }

    @property
    def profile(self) -> str:
        profile_index = self._core.profile
        if 0 <= profile_index < len(_PROFILE_NAMES):
            return _PROFILE_NAMES[profile_index]
        return "home"

    @property
    def active_sequence(self) -> int | None:
        return self._active_sequence

    async def _cancel_active(self) -> int | None:
        async with self._lock:
            sequence = self._active_sequence
            task = self._active_task
            self._active_sequence = None
            self._active_task = None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        return sequence


def _decision_nak(sequence: int, rejection: CoreRejection) -> dict[str, object]:
    return {
        "t": "nak",
        "seq": sequence,
        "code": _REJECTION_CODES.get(rejection, "malformed"),
    }


def _validation_nak(message: object) -> dict[str, object]:
    if isinstance(message, Mapping):
        sequence = message.get("seq")
        if (
            message.get("t") == "intent"
            and isinstance(message.get("name"), str)
            and message.get("name") not in INTENT_NAMES
            and type(sequence) is int
            and 1 <= sequence <= MAX_SEQUENCE
        ):
            return {"t": "nak", "seq": sequence, "code": "unknown"}
        if type(sequence) is int and 1 <= sequence <= MAX_SEQUENCE:
            return {"t": "nak", "seq": sequence, "code": "malformed"}
    return {"t": "nak", "code": "malformed"}
