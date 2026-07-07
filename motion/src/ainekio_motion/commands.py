from __future__ import annotations

from typing import Mapping

from .types import MotionCommand, RobotCommand, RootMotionIntent, now_ms


SUPPORTED_COMMANDS = frozenset(command.value for command in RobotCommand)


def parse_robot_command(value: object) -> RobotCommand | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower().replace("-", "_")
    aliases = {
        "turn_left": "left",
        "turn_right": "right",
        "walk_backward": "backward",
        "walkbackward": "backward",
    }
    normalized = aliases.get(normalized, normalized)
    try:
        return RobotCommand(normalized)
    except ValueError:
        return None


def translate_environment_action(
    action: Mapping[str, object],
    *,
    issued_at_ms: int | None = None,
    default_ttl_ms: int = 1200,
) -> MotionCommand | None:
    """Translate generic environment intent into robot motion.

    Body-specific commands should be added here or in a Megameal/bridge adapter,
    not tunneled through generic action metadata.
    """

    action_type = str(action.get("type", "")).strip().lower()
    base_time = issued_at_ms if issued_at_ms is not None else now_ms()
    ttl_ms = int(action.get("ttl_ms") or action.get("ttlMs") or default_ttl_ms)
    lease_id = action.get("lease_id") or action.get("leaseId")

    if action_type == "stop":
        return MotionCommand(
            RobotCommand.STOP,
            issued_at_ms=base_time,
            ttl_ms=ttl_ms,
            lease_id=str(lease_id) if lease_id else None,
            source="environment-bridge",
        )

    if action_type != "move":
        return None

    direction = str(action.get("direction", "forward")).strip().lower()
    duration_ms = int(action.get("duration_ms") or action.get("durationMs") or 400)
    speed = float(action.get("speed") or 1.0)

    if direction in {"forward", "ahead", "up"}:
        command = RobotCommand.WALK
        root = RootMotionIntent(forward=1.0, speed=speed, duration_ms=duration_ms)
    elif direction in {"back", "backward", "down"}:
        command = RobotCommand.BACKWARD
        root = RootMotionIntent(forward=-1.0, speed=speed, duration_ms=duration_ms)
    elif direction in {"left", "turn_left"}:
        command = RobotCommand.TURN_LEFT
        root = RootMotionIntent(yaw=1.0, speed=speed, duration_ms=duration_ms)
    elif direction in {"right", "turn_right"}:
        command = RobotCommand.TURN_RIGHT
        root = RootMotionIntent(yaw=-1.0, speed=speed, duration_ms=duration_ms)
    else:
        return None

    return MotionCommand(
        command,
        issued_at_ms=base_time,
        ttl_ms=ttl_ms,
        lease_id=str(lease_id) if lease_id else None,
        root_motion=root,
        source="environment-bridge",
    )
