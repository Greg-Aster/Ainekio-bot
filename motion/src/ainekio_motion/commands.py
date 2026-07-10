from __future__ import annotations

from typing import Mapping

from .types import MotionCommand, RobotCommand, RootMotionIntent, now_ms


SUPPORTED_COMMANDS = frozenset(command.value for command in RobotCommand)
SIMULATOR_COMMANDS = {
    RobotCommand.WALK: "run walk",
    RobotCommand.BACKWARD: "rn wb",
    RobotCommand.TURN_LEFT: "rn tl",
    RobotCommand.TURN_RIGHT: "rn tr",
    RobotCommand.STAND: "run stand",
    RobotCommand.STOP: "run stand",
    RobotCommand.IDLE: "run stand",
    RobotCommand.REST: "run rest",
    RobotCommand.WAVE: "rn wv",
    RobotCommand.POINT: "rn pt",
    RobotCommand.DANCE: "rn dn",
    RobotCommand.SWIM: "rn sw",
    RobotCommand.CUTE: "rn ct",
    RobotCommand.PUSHUP: "rn pu",
    RobotCommand.FREAKY: "rn fk",
    RobotCommand.BOW: "rn bw",
    RobotCommand.WORM: "rn wm",
    RobotCommand.SHAKE: "rn sk",
    RobotCommand.SHRUG: "rn sg",
    RobotCommand.DEAD: "rn dd",
    RobotCommand.CRAB: "rn cb",
}


def parse_robot_command(value: object) -> RobotCommand | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "turn_left": "left",
        "turn_right": "right",
        "walk_backward": "backward",
        "walkbackward": "backward",
        "walk_forward": "walk",
        "walkforward": "walk",
        "forward": "walk",
        "back": "backward",
        "reverse": "backward",
        "push_up": "pushup",
        "push_ups": "pushup",
        "pushups": "pushup",
        "play_dead": "dead",
        "die": "dead",
        "turnleft": "left",
        "turnright": "right",
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

    if action_type == "robotcommand":
        command = parse_robot_command(action.get("command"))
        if command is None:
            return None
        duration_ms = _duration_for_action(action)
        root = _root_motion_for_command(command, duration_ms=duration_ms)
        simulator_command = str(action.get("simulatorCommand") or SIMULATOR_COMMANDS.get(command) or "").strip()
        units = action.get("units")
        metadata = {
            **(action.get("metadata") if isinstance(action.get("metadata"), dict) else {}),
            **({"simulatorCommand": simulator_command} if simulator_command else {}),
            **({"units": int(units)} if isinstance(units, (int, float)) else {}),
        }
        return MotionCommand(
            command,
            issued_at_ms=base_time,
            ttl_ms=ttl_ms,
            lease_id=str(lease_id) if lease_id else None,
            root_motion=root,
            source="environment-bridge",
            metadata=metadata,
        )

    if action_type == "stop":
        return MotionCommand(
            RobotCommand.STOP,
            issued_at_ms=base_time,
            ttl_ms=ttl_ms,
            lease_id=str(lease_id) if lease_id else None,
            metadata={"simulatorCommand": SIMULATOR_COMMANDS[RobotCommand.STOP]},
            source="environment-bridge",
        )

    if action_type != "move":
        return None

    direction = str(action.get("direction", "forward")).strip().lower()
    duration_ms = _duration_for_action(action)
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
        metadata={"simulatorCommand": SIMULATOR_COMMANDS[command]},
    )


def _duration_for_action(action: Mapping[str, object]) -> int:
    duration = action.get("duration_ms") or action.get("durationMs")
    if isinstance(duration, (int, float)):
        return int(duration)
    units = action.get("units")
    if isinstance(units, (int, float)):
        return max(250, min(1500, int(units) * 150))
    return 400


def _root_motion_for_command(command: RobotCommand, *, duration_ms: int) -> RootMotionIntent | None:
    if command == RobotCommand.WALK:
        return RootMotionIntent(forward=1.0, duration_ms=duration_ms)
    if command == RobotCommand.BACKWARD:
        return RootMotionIntent(forward=-1.0, duration_ms=duration_ms)
    if command == RobotCommand.TURN_LEFT:
        return RootMotionIntent(yaw=1.0, duration_ms=duration_ms)
    if command == RobotCommand.TURN_RIGHT:
        return RootMotionIntent(yaw=-1.0, duration_ms=duration_ms)
    return None
