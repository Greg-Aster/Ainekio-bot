from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .types import MotionCommand, RobotCommand, ServoFrame


SESAME_PROVISIONAL_SERVO_ORDER = ("R1", "R2", "L1", "L2", "R4", "R3", "L3", "L4")
MIN_SERVO_ANGLE = 0.0
MAX_SERVO_ANGLE = 180.0


@dataclass(frozen=True)
class SequenceStep:
    targets: Mapping[str, float]
    hold_ms: int = 100


SEQUENCES: Mapping[RobotCommand, tuple[SequenceStep, ...]] = {
    RobotCommand.REST: (
        SequenceStep({"R1": 90, "R2": 90, "L1": 90, "L2": 90, "R4": 90, "R3": 90, "L3": 90, "L4": 90}),
    ),
    RobotCommand.STAND: (
        SequenceStep({"R1": 90, "R2": 70, "L1": 90, "L2": 110, "R4": 100, "R3": 90, "L3": 90, "L4": 80}),
    ),
    RobotCommand.IDLE: (
        SequenceStep({"R1": 90, "R2": 78, "L1": 90, "L2": 102, "R4": 98, "R3": 90, "L3": 90, "L4": 82}, 160),
        SequenceStep({"R1": 90, "R2": 74, "L1": 90, "L2": 106, "R4": 102, "R3": 90, "L3": 90, "L4": 78}, 160),
    ),
    RobotCommand.STOP: (
        SequenceStep({"R1": 90, "R2": 75, "L1": 90, "L2": 105, "R4": 100, "R3": 90, "L3": 90, "L4": 80}),
    ),
    RobotCommand.WALK: (
        SequenceStep({"R1": 72, "R2": 68, "L1": 108, "L2": 112, "R4": 104, "R3": 82, "L3": 98, "L4": 76}, 90),
        SequenceStep({"R1": 108, "R2": 72, "L1": 72, "L2": 108, "R4": 96, "R3": 98, "L3": 82, "L4": 84}, 90),
    ),
    RobotCommand.BACKWARD: (
        SequenceStep({"R1": 108, "R2": 68, "L1": 72, "L2": 112, "R4": 104, "R3": 98, "L3": 82, "L4": 76}, 90),
        SequenceStep({"R1": 72, "R2": 72, "L1": 108, "L2": 108, "R4": 96, "R3": 82, "L3": 98, "L4": 84}, 90),
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
        SequenceStep({"R1": 90, "R2": 70, "L1": 90, "L2": 110, "R4": 50, "R3": 120, "L3": 90, "L4": 80}, 120),
        SequenceStep({"R1": 90, "R2": 70, "L1": 90, "L2": 110, "R4": 80, "R3": 60, "L3": 90, "L4": 80}, 120),
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
