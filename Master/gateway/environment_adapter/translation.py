from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Mapping

from gateway.body_capabilities import CRAB_DIRECTIONS
from protocol.control_v1 import ProtocolValidationError, validate_walk_controls

LOCOMOTION_GAIT_COMMANDS = frozenset({"walk", "backward", "left", "right", "crawl", "run", *CRAB_DIRECTIONS})


@dataclass(frozen=True)
class BridgeAction:
    kind: str
    name: str | None = None
    params: dict[str, object] = field(default_factory=dict)


def translate_environment_action(action: Mapping[str, object], *, model: str | None = None) -> BridgeAction | None:
    try:
        return _translate_environment_action(action, model=model)
    except ProtocolValidationError:
        return None


def _translate_environment_action(action: Mapping[str, object], *, model: str | None = None) -> BridgeAction | None:
    if "continuous" in action and type(action["continuous"]) is not bool:
        raise ProtocolValidationError("type:continuous")
    if "detach" in action and type(action["detach"]) is not bool:
        raise ProtocolValidationError("type:detach")
    action_type = _normalized(action.get("type"))
    if action_type == "requestmotion":
        description = action.get("description")
        return (BridgeAction("request_motion", "requestMotion", {"description": description.strip()})
                if isinstance(description, str) and description.strip() else None)
    if action_type == "faceexpression":
        expression = action.get("expression")
        if action.get("displayRelease") is not True and (not isinstance(expression, str) or not expression.strip()):
            return None
        params = {"expr": expression.strip()} if isinstance(expression, str) and expression.strip() else {}
        for source, target in (("displayToken", "token"), ("displayIfToken", "if_token"), ("displayTimeoutMs", "timeout_ms"),
                               ("displayBackground", "background"), ("displayRelease", "release")):
            if source in action and action[source] is not None:
                params[target] = action[source]
        return BridgeAction("intent", "face", params)
    if action_type == "captureimage":
        return BridgeAction("snapshot", "captureImage")
    if action_type == "sendtext":
        text = action.get("text")
        if not isinstance(text, str) or not text.strip():
            return None
        return BridgeAction("text", params={"text": text})
    if action_type in {"stop", "release"}:
        detach = action_type == "release" or action.get("detach") is True
        return BridgeAction("stop", "release", {"detach": True}) if detach else BridgeAction("stop")
    if action_type == "move":
        return _translate_move(action, model=model)
    return None


def _translate_move(action: Mapping[str, object], *, model: str | None = None) -> BridgeAction | None:
    goal = action.get("locomotionGoal")
    if model == "v2-12servo" and action.get("gait") == "crab" and isinstance(goal, Mapping) and goal.get("kind") == "distance":
        direction = {"forward": "fwd", "back": "back", "left": "side_l", "right": "side_r"}.get(goal.get("direction"))
        return BridgeAction("intent", "walk", _walk_params(action, direction)) if direction else None
    direction = _normalized(action.get("direction") or "forward")
    if direction in {"left", "turnleft", "right", "turnright"}:
        side = "left" if direction in {"left", "turnleft"} else "right"
        return _translate_turn(action, side, model=model)
    directions = {
        "forward": "fwd",
        "ahead": "fwd",
        "up": "fwd",
        "back": "back",
        "backward": "back",
        "down": "back",
    }
    wire_direction = directions.get(direction)
    if wire_direction is None:
        return None
    return BridgeAction(
        "intent",
        "walk",
        _walk_params(action, wire_direction),
    )


def _translate_turn(action: Mapping[str, object], side: str, *, model: str | None) -> BridgeAction:
    if model == "v2-12servo":
        # Bare V2 turns are ongoing; an explicit cycle count remains available.
        action = {**action, "continuous": action.get("continuous", "units" not in action)}
    return BridgeAction("intent", "walk", _walk_params(action, "turn_l" if side == "left" else "turn_r"))


def _walk_params(action: Mapping[str, object], direction: str) -> dict[str, object]:
    if "continuous" in action and type(action["continuous"]) is not bool:
        raise ProtocolValidationError("type:continuous")
    params = {"dir": direction, "steps": 0 if action.get("continuous") else _bounded_steps(action.get("units"))}
    for key in ("speed", "stride", "rate", "forward", "turn", "lateral", "update", "gait", "speed_percent", "stride_percent", "motion_rate"):
        if key in action:
            params[key] = action[key]
    validate_walk_controls(params)
    return params


def _normalized(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip().lower().replace("-", "").replace("_", "").replace(" ", "")


def _bounded_steps(value: object) -> int:
    if type(value) not in {int, float}:
        return 1
    return max(1, min(10, int(value)))


def is_locomotion_translation(action: BridgeAction) -> bool:
    return action.kind == "intent" and action.name == "walk"


def locomotion_commands(commands: list[str], model: str | None = None) -> list[str]:
    del model
    return [command for command in commands if command in LOCOMOTION_GAIT_COMMANDS]


def valid_locomotion_goal(goal: object) -> bool:
    """Validate the same goal payload admitted by Core; never choose its meaning."""
    from datetime import datetime
    number = lambda value: type(value) in (int, float) and math.isfinite(value)
    positive = lambda value: number(value) and value > 0
    text = lambda value: isinstance(value, str) and bool(value.strip())
    if not isinstance(goal, Mapping):
        return False
    kind = goal.get("kind")
    if kind == "distance":
        return goal.get("direction") in ("forward", "back", "left", "right") and positive(goal.get("metres")) and positive(goal.get("tolerance"))
    if kind == "relativeTurn":
        return number(goal.get("degrees")) and positive(goal.get("tolerance"))
    if kind == "visual":
        return text(goal.get("target")) and text(goal.get("completionCriteria"))
    if kind not in ("approach", "follow"):
        return False
    target, proximity = goal.get("target"), goal.get("proximity")
    if not isinstance(target, Mapping) or not isinstance(proximity, Mapping) or not text(target.get("frameId")):
        return False
    try:
        datetime.fromisoformat(target.get("frameTimestamp"))
    except (ValueError, TypeError):
        return False
    box = target.get("box")
    if not isinstance(box, Mapping) or not all(number(box.get(key)) and 0 <= box[key] <= 1 for key in ("x", "y", "width", "height")):
        return False
    if box["width"] <= 0 or box["height"] <= 0 or box["x"] + box["width"] > 1.000001 or box["y"] + box["height"] > 1.000001:
        return False
    if not positive(proximity.get("tolerance")):
        return False
    if proximity.get("kind") == "metric":
        point = target.get("groundContact")
        if not positive(proximity.get("metres")) or not isinstance(point, Mapping) or not all(number(point.get(key)) and 0 <= point[key] <= 1 for key in ("x", "y")):
            return False
    elif proximity.get("kind") != "imageRelative" or not positive(proximity.get("boxHeight")) or proximity["boxHeight"] > 1:
        return False
    return kind != "follow" or text(goal.get("endingCondition"))
