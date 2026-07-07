from __future__ import annotations

from dataclasses import dataclass, field

from .sequences import SequenceEngine
from .types import JointTelemetry, MotionCommand, ServoFrame


@dataclass
class VirtualBackend:
    sequence_engine: SequenceEngine = field(default_factory=SequenceEngine)
    telemetry: list[JointTelemetry] = field(default_factory=list)

    def apply(self, command: MotionCommand, *, start_ms: int = 0) -> list[ServoFrame]:
        frames = self.sequence_engine.render(command, start_ms=start_ms)
        joints = {frame.servo: frame.angle for frame in frames}
        at_ms = frames[-1].at_ms if frames else start_ms
        self.telemetry.append(
            JointTelemetry(
                command=command.command,
                joints=joints,
                root_motion=command.root_motion,
                at_ms=at_ms,
            )
        )
        return frames


class DisabledPca9685Backend:
    def __init__(self, *, hardware_enabled: bool = False) -> None:
        self.hardware_enabled = hardware_enabled

    def apply(self, command: MotionCommand, *, start_ms: int = 0) -> list[ServoFrame]:
        if not self.hardware_enabled:
            raise RuntimeError("PCA9685 hardware backend is disabled by config")
        raise NotImplementedError("PCA9685 hardware driver is deferred until hardware validation")
