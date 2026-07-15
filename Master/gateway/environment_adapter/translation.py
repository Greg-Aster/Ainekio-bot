from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping


SEED_EMOTES = frozenset(
    {
        "rest",
        "stand",
        "wave",
        "dance",
        "swim",
        "point",
        "pushup",
        "bow",
        "cute",
        "freaky",
        "worm",
        "shake",
        "shrug",
        "dead",
        "crab",
    }
)


@dataclass(frozen=True)
class BridgeAction:
    kind: str
    name: str | None = None
    params: dict[str, object] = field(default_factory=dict)


def translate_environment_action(action: Mapping[str, object]) -> BridgeAction | None:
    action_type = _normalized(action.get("type"))
    if action_type == "sendtext":
        text = action.get("text")
        if not isinstance(text, str) or not text.strip():
            return None
        return BridgeAction("text", params={"text": text[:4096]})
    if action_type == "stop":
        return BridgeAction("stop")
    if action_type == "move":
        return _translate_move(action)
    if action_type != "robotcommand":
        return None

    command = _normalized(action.get("command"))
    aliases = {
        "idle": "neutral",
        "rest": "sit",
        "back": "backward",
        "reverse": "backward",
        "walkbackward": "backward",
        "walkforward": "walk",
        "forward": "walk",
        "turnleft": "left",
        "turnright": "right",
        "pushups": "pushup",
        "playdead": "dead",
        "die": "dead",
    }
    command = aliases.get(command, command)
    if command == "stop":
        return BridgeAction("stop")
    if command in {"stand", "neutral", "sit"}:
        return BridgeAction("intent", command)
    if command in {"walk", "backward", "left", "right"}:
        direction = {
            "walk": "fwd",
            "backward": "back",
            "left": "turn_l",
            "right": "turn_r",
        }[command]
        return BridgeAction(
            "intent",
            "walk",
            {"dir": direction, "steps": _bounded_steps(action.get("units"))},
        )
    if command in SEED_EMOTES:
        return BridgeAction("intent", "emote", {"asset": command})
    return None


def _translate_move(action: Mapping[str, object]) -> BridgeAction | None:
    direction = _normalized(action.get("direction") or "forward")
    directions = {
        "forward": "fwd",
        "ahead": "fwd",
        "up": "fwd",
        "back": "back",
        "backward": "back",
        "down": "back",
        "left": "turn_l",
        "turnleft": "turn_l",
        "right": "turn_r",
        "turnright": "turn_r",
    }
    wire_direction = directions.get(direction)
    if wire_direction is None:
        return None
    return BridgeAction(
        "intent",
        "walk",
        {"dir": wire_direction, "steps": _bounded_steps(action.get("units"))},
    )


def _normalized(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip().lower().replace("-", "").replace("_", "").replace(" ", "")


def _bounded_steps(value: object) -> int:
    if type(value) not in {int, float}:
        return 1
    return max(1, min(10, int(value)))
