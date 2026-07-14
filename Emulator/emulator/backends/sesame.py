from __future__ import annotations

import asyncio
from typing import Mapping

from .sesame_shim import SimulatorShimClient


_STATIONARY_COMMANDS = {
    "stand": ("stand", "run stand"),
    "neutral": ("stand", "run stand"),
}
_WALK_PROFILES = {
    "fwd": ("walk", "run walk", 1.0, 0.0, 840),
    "back": ("backward", "rn wb", -1.0, 0.0, 840),
    "turn_l": ("left", "rn tl", 0.0, 1.0, 250),
    "turn_r": ("right", "rn tr", 0.0, -1.0, 250),
}


class SesameMotionBackend:
    def __init__(self, shim_url: str = "http://127.0.0.1:8788") -> None:
        self._shim = SimulatorShimClient(shim_url)
        self.last_publish_error: str | None = None

    async def execute(self, message: Mapping[str, object], *, session_id: str) -> None:
        payload, duration_ms = _renderer_payload(message, session_id=session_id)

        try:
            await asyncio.to_thread(self._shim.publish_motion, payload)
            self.last_publish_error = None
        except RuntimeError as error:
            self.last_publish_error = str(error)
            raise

        await asyncio.sleep(duration_ms / 1000.0)

    async def stop(self, sequence: int, *, session_id: str) -> None:
        await self.execute({"t": "stop", "seq": sequence}, session_id=session_id)


def _renderer_payload(
    message: Mapping[str, object],
    *,
    session_id: str,
) -> tuple[dict[str, object], int]:
    message_type = message.get("t")
    if message_type == "stop":
        command = "stop"
        simulator_command = "run stand"
        units = None
        root_motion = None
        duration_ms = 140
        intent = "stop"
    elif message_type == "intent":
        intent = str(message["name"])
        if intent in _STATIONARY_COMMANDS:
            command, simulator_command = _STATIONARY_COMMANDS[intent]
            units = None
            root_motion = None
            duration_ms = 140
        elif intent == "walk":
            direction = str(message["dir"])
            command, simulator_command, forward, yaw, duration_ms = _WALK_PROFILES[direction]
            units = int(message["steps"])
            root_motion = {
                "forward": forward,
                "strafe": 0.0,
                "yaw": yaw,
                "speed": 1.0,
                "duration_ms": max(250, min(1500, units * 150)),
            }
        else:
            raise RuntimeError(f"intent {intent!r} is not implemented in emulator phase 1")
    else:
        raise RuntimeError("message is not a motion command")

    return (
        {
            "schemaVersion": 1,
            "source": "protocol-v1-emulator",
            "actionId": f"{session_id}:{message['seq']}",
            "sessionId": session_id,
            "command": command,
            "simulatorCommand": simulator_command,
            "units": units,
            "rootMotion": root_motion,
            "frames": [],
            "protocolSequence": message["seq"],
            "protocolIntent": intent,
        },
        duration_ms,
    )
