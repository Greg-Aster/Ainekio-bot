from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .types import MotionCommand, RobotCommand, ServoFrame


SESAME_PROVISIONAL_SERVO_ORDER = ("R1", "R2", "L1", "L2", "R4", "R3", "L3", "L4")
MIN_SERVO_ANGLE = 0.0
MAX_SERVO_ANGLE = 180.0

SESAME_STAND = {"R1": 135, "R2": 45, "L1": 45, "L2": 135, "R4": 0, "R3": 180, "L3": 0, "L4": 180}
SESAME_REST = {"R1": 90, "R2": 90, "L1": 90, "L2": 90, "R4": 90, "R3": 90, "L3": 90, "L4": 90}


@dataclass(frozen=True)
class SequenceStep:
    targets: Mapping[str, float]
    hold_ms: int = 100


SEQUENCES: Mapping[RobotCommand, tuple[SequenceStep, ...]] = {
    RobotCommand.REST: (
        SequenceStep(SESAME_REST),
    ),
    RobotCommand.STAND: (
        SequenceStep(SESAME_STAND),
    ),
    RobotCommand.IDLE: (
        SequenceStep(SESAME_STAND, 160),
    ),
    RobotCommand.STOP: (
        SequenceStep(SESAME_STAND),
    ),
    RobotCommand.WALK: (
        SequenceStep(SESAME_STAND, 100),
        SequenceStep({"R3": 135, "L3": 0}, 100),
        SequenceStep({"L4": 135, "L2": 90, "R4": 0, "R1": 180}, 100),
        SequenceStep({"R2": 45, "L1": 90}, 100),
        SequenceStep({"R4": 45, "L4": 180}, 100),
        SequenceStep({"R3": 180, "L3": 45, "R2": 90, "L1": 0}, 100),
        SequenceStep({"L2": 135, "R1": 90}, 100),
        SequenceStep(SESAME_STAND, 100),
    ),
    RobotCommand.BACKWARD: (
        SequenceStep(SESAME_STAND, 100),
        SequenceStep({"R3": 135, "L3": 0}, 100),
        SequenceStep({"L4": 135, "L2": 135, "R4": 0, "R1": 90}, 100),
        SequenceStep({"R2": 90, "L1": 0}, 100),
        SequenceStep({"R4": 45, "L4": 180}, 100),
        SequenceStep({"R3": 180, "L3": 45, "R2": 45, "L1": 90}, 100),
        SequenceStep({"L2": 90, "R1": 180}, 100),
        SequenceStep(SESAME_STAND, 100),
    ),
    RobotCommand.TURN_LEFT: (
        SequenceStep({"R1": 72, "R2": 70, "L1": 72, "L2": 110, "R4": 100, "R3": 82, "L3": 82, "L4": 80}, 110),
        SequenceStep({"R1": 108, "R2": 70, "L1": 108, "L2": 110, "R4": 100, "R3": 98, "L3": 98, "L4": 80}, 110),
    ),
    RobotCommand.TURN_RIGHT: (
        SequenceStep({"R1": 108, "R2": 70, "L1": 108, "L2": 110, "R4": 100, "R3": 98, "L3": 98, "L4": 80}, 110),
        SequenceStep({"R1": 72, "R2": 70, "L1": 72, "L2": 110, "R4": 100, "R3": 82, "L3": 82, "L4": 80}, 110),
    ),
    RobotCommand.WAVE: (
        SequenceStep(SESAME_STAND, 200),
        SequenceStep({"R4": 80, "L3": 180, "L2": 60, "R1": 100}, 200),
        SequenceStep({"L3": 180}, 300),
        SequenceStep({"L3": 100}, 300),
        SequenceStep({"L3": 180}, 300),
        SequenceStep(SESAME_STAND, 100),
    ),
}


class SequenceEngine:
    def __init__(self, *, motor_stagger_ms: int = 20) -> None:
        self.motor_stagger_ms = motor_stagger_ms

    def render(self, command: MotionCommand, *, start_ms: int = 0) -> list[ServoFrame]:
        steps = SEQUENCES.get(command.command, SEQUENCES[RobotCommand.IDLE])
        frames: list[ServoFrame] = []
        cursor_ms = start_ms
        for step in steps:
            for offset, servo in enumerate(SESAME_PROVISIONAL_SERVO_ORDER):
                if servo not in step.targets:
                    continue
                frames.append(
                    ServoFrame(
                        servo=servo,
                        angle=_clamp_angle(step.targets[servo]),
                        at_ms=cursor_ms + offset * self.motor_stagger_ms,
                    )
                )
            cursor_ms += step.hold_ms
        return frames


def _clamp_angle(value: float) -> float:
    return max(MIN_SERVO_ANGLE, min(MAX_SERVO_ANGLE, float(value)))
