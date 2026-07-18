from __future__ import annotations

import asyncio
from typing import Mapping

from .sesame_shim import SimulatorShimClient


_STATIONARY_COMMANDS = {
    "sit": ("sit", "run rest", 400),
    "stand": ("stand", "run stand", 140),
    "neutral": ("stand", "run stand", 140),
}
_WALK_PROFILES = {
    "fwd": ("walk", "run walk", 1.0, 0.0, 840),
    "back": ("backward", "rn wb", -1.0, 0.0, 840),
    "turn_l": ("left", "rn tl", 0.0, 1.0, 250),
    "turn_r": ("right", "rn tr", 0.0, -1.0, 250),
}
_EMOTE_COMMANDS = {
    "rest": ("sit", "run rest", 400),
    "stand": ("stand", "run stand", 140),
    "wave": ("wave", "rn wv", 1200),
    "dance": ("dance", "rn dn", 1800),
    "swim": ("swim", "rn sw", 1800),
    "point": ("point", "rn pt", 1000),
    "pushup": ("pushup", "rn pu", 1800),
    "bow": ("bow", "rn bw", 1200),
    "cute": ("cute", "rn ct", 1200),
    "freaky": ("freaky", "rn fk", 1800),
    "worm": ("worm", "rn wm", 1800),
    "shake": ("shake", "rn sk", 1200),
    "shrug": ("shrug", "rn sg", 1200),
    "dead": ("dead", "rn dd", 1800),
    "crab": ("crab", "rn cb", 1800),
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
        frames: object = []
        end_pose: object = None
    elif message_type == "motion_plan":
        intent = "motion_plan"
        command = "freestyle"
        simulator_command = None
        units = None
        root_motion = None
        frames = message.get("_motion_plan_frames", [])
        end_pose = message.get("end")
        duration_ms = sum(
            int(frame.get("duration_ms", 0))
            for frame in frames
            if isinstance(frame, dict)
        ) if isinstance(frames, list) else 0
    elif message_type == "intent":
        intent = str(message["name"])
        if intent in _STATIONARY_COMMANDS:
            command, simulator_command, duration_ms = _STATIONARY_COMMANDS[intent]
            units = None
            root_motion = None
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
        elif intent == "emote":
            asset = str(message["asset"])
            try:
                command, simulator_command, duration_ms = _EMOTE_COMMANDS[asset]
            except KeyError as exc:
                raise RuntimeError(f"emote asset {asset!r} is unavailable") from exc
            units = None
            root_motion = None
        else:
            raise RuntimeError(f"intent {intent!r} has no Sesame renderer mapping")
        frames = message.get("_motion_asset_frames", [])
        end_pose = None
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
            "frames": frames,
            "jointMapVersion": message.get("_joint_map_version"),
            "endPose": end_pose,
            "protocolSequence": message["seq"],
            "protocolIntent": intent,
        },
        duration_ms,
    )
