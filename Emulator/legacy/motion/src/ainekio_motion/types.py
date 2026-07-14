from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from time import monotonic_ns
from typing import Mapping


def now_ms() -> int:
    return monotonic_ns() // 1_000_000


class RobotCommand(StrEnum):
    REST = "rest"
    STAND = "stand"
    IDLE = "idle"
    STOP = "stop"
    WALK = "walk"
    BACKWARD = "backward"
    TURN_LEFT = "left"
    TURN_RIGHT = "right"
    WAVE = "wave"
    POINT = "point"
    DANCE = "dance"
    SWIM = "swim"
    CUTE = "cute"
    PUSHUP = "pushup"
    FREAKY = "freaky"
    BOW = "bow"
    WORM = "worm"
    SHAKE = "shake"
    SHRUG = "shrug"
    DEAD = "dead"
    CRAB = "crab"


LOCOMOTION_COMMANDS = {
    RobotCommand.WALK,
    RobotCommand.BACKWARD,
    RobotCommand.TURN_LEFT,
    RobotCommand.TURN_RIGHT,
}


@dataclass(frozen=True)
class RootMotionIntent:
    """World-space movement intent for virtual/game adapters."""

    forward: float = 0.0
    strafe: float = 0.0
    yaw: float = 0.0
    speed: float = 1.0
    duration_ms: int = 400


@dataclass(frozen=True)
class MotionCommand:
    command: RobotCommand
    issued_at_ms: int = field(default_factory=now_ms)
    ttl_ms: int = 1200
    lease_id: str | None = None
    face: str | None = None
    root_motion: RootMotionIntent | None = None
    source: str = "local"
    metadata: Mapping[str, object] = field(default_factory=dict)

    def expires_at_ms(self) -> int:
        return self.issued_at_ms + self.ttl_ms

    def is_expired(self, at_ms: int | None = None) -> bool:
        return (at_ms if at_ms is not None else now_ms()) > self.expires_at_ms()


@dataclass(frozen=True)
class ServoFrame:
    servo: str
    angle: float
    at_ms: int


@dataclass(frozen=True)
class JointTelemetry:
    command: RobotCommand
    joints: Mapping[str, float]
    root_motion: RootMotionIntent | None
    at_ms: int
