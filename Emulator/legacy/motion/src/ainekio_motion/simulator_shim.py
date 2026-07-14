from __future__ import annotations

from dataclasses import asdict
from typing import Any

from emulator.backends.sesame_shim import (
    DEFAULT_SHIM_URL,
    MotionHub,
    SimulatorShimClient,
    SimulatorShimHandler,
    SimulatorShimServer,
    main,
    run_server,
)

from .types import MotionCommand, ServoFrame


def build_motion_payload(
    *,
    action_id: str | None,
    session_id: str,
    command: MotionCommand,
    frames: list[ServoFrame],
) -> dict[str, Any]:
    """Format an old motion-package result for the shared host renderer."""

    simulator_command = command.metadata.get("simulatorCommand")
    units = command.metadata.get("units")
    return {
        "schemaVersion": 1,
        "source": "ainekio-adapter",
        "actionId": action_id,
        "sessionId": session_id,
        "command": command.command.value,
        "simulatorCommand": simulator_command if isinstance(simulator_command, str) else None,
        "units": units if isinstance(units, int) else None,
        "rootMotion": asdict(command.root_motion) if command.root_motion else None,
        "frames": [asdict(frame) for frame in frames],
    }


__all__ = [
    "DEFAULT_SHIM_URL",
    "MotionHub",
    "SimulatorShimClient",
    "SimulatorShimHandler",
    "SimulatorShimServer",
    "build_motion_payload",
    "main",
    "run_server",
]


if __name__ == "__main__":
    raise SystemExit(main())
