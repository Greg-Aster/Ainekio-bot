from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Mapping

from protocol.control_v1 import (
    MOTION_PLAN_JOINT_MAP,
    MOTION_PLAN_MAX_CENTIDEGREES,
    MOTION_PLAN_MAX_FRAMES,
    MOTION_PLAN_MAX_FRAME_MS,
    MOTION_PLAN_MAX_TOTAL_MS,
    MOTION_PLAN_MIN_FRAME_MS,
)
from protocol.joints_v1 import JOINT_LABELS


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
        "nod",
        "celebrate",
        "stretch",
        "macarena",
        "salsa",
        "surprised",
        "sad",
        "curious",
        "turn_left_45",
        "turn_right_45",
        "turn_left_90",
        "turn_right_90",
        "turn_left_180",
        "turn_right_180",
        "walk_slow",
        "run",
    }
)

SUPPORTED_ROBOT_COMMANDS = tuple(
    sorted(
        {
            "stop",
            "sit",
            "stand",
            "neutral",
            "walk",
            "backward",
            "left",
            "right",
            *SEED_EMOTES,
        }
    )
)

@dataclass(frozen=True)
class BridgeAction:
    kind: str
    name: str | None = None
    params: dict[str, object] = field(default_factory=dict)


def translate_environment_action(action: Mapping[str, object]) -> BridgeAction | None:
    action_type = _normalized(action.get("type"))
    if action_type == "captureimage":
        return BridgeAction("snapshot", "captureImage")
    if action_type == "sendtext":
        text = action.get("text")
        if not isinstance(text, str) or not text.strip():
            return None
        return BridgeAction("text", params={"text": text[:4096]})
    if action_type == "stop":
        return BridgeAction("stop")
    if action_type == "move":
        return _translate_move(action)
    if action_type == "robotmotionplan":
        return _translate_motion_plan(action)
    if action_type != "robotcommand":
        return None

    command = _normalized(action.get("command"))
    aliases = {
        "idle": "neutral",
        "sitdown": "sit",
        "takeaseat": "sit",
        "haveaseat": "sit",
        "back": "backward",
        "reverse": "backward",
        "walkbackward": "backward",
        "walkforward": "walk",
        "forward": "walk",
        "turnleft": "left",
        "turnright": "right",
        "leftquarterturn": "turnleft45",
        "rightquarterturn": "turnright45",
        "quarterturnleft": "turnleft45",
        "quarterturnright": "turnright45",
        "turnleftquarterturn": "turnleft45",
        "turnrightquarterturn": "turnright45",
        "turnleftonequarterturn": "turnleft45",
        "turnrightonequarterturn": "turnright45",
        "lefthalfturn": "turnleft90",
        "righthalfturn": "turnright90",
        "halfturnleft": "turnleft90",
        "halfturnright": "turnright90",
        "turnlefthalfturn": "turnleft90",
        "turnrighthalfturn": "turnright90",
        "turnleftonehalfturn": "turnleft90",
        "turnrightonehalfturn": "turnright90",
        "turnleft45degrees": "turnleft45",
        "turnright45degrees": "turnright45",
        "turnleft90degrees": "turnleft90",
        "turnright90degrees": "turnright90",
        "turnleft180degrees": "turnleft180",
        "turnright180degrees": "turnright180",
        "turnaround": "turnright180",
        "lookaround": "curious",
        "pushups": "pushup",
        "playdead": "dead",
        "die": "dead",
    }
    command = aliases.get(command, command)
    if command == "stop":
        return BridgeAction("stop")
    if command in {"stand", "neutral", "sit"}:
        return BridgeAction("intent", command)
    if command in {"left", "right"}:
        return BridgeAction(
            "intent",
            "emote",
            {"asset": f"turn_{command}_45"},
        )
    if command in {"walk", "backward"}:
        direction = {
            "walk": "fwd",
            "backward": "back",
        }[command]
        return BridgeAction(
            "intent",
            "walk",
            {"dir": direction, "steps": _bounded_steps(action.get("units"))},
        )
    emote_asset = next(
        (asset for asset in SEED_EMOTES if _normalized(asset) == command),
        None,
    )
    if emote_asset is not None:
        return BridgeAction("intent", "emote", {"asset": emote_asset})
    return None


def _translate_motion_plan(action: Mapping[str, object]) -> BridgeAction | None:
    raw_frames = action.get("frames")
    if not isinstance(raw_frames, list) or not 1 <= len(raw_frames) <= MOTION_PLAN_MAX_FRAMES:
        return None
    frames: list[object] = []
    total_duration_ms = 0
    label_to_id = {label: joint_id for joint_id, label in enumerate(JOINT_LABELS)}
    for raw_frame in raw_frames:
        if not isinstance(raw_frame, Mapping):
            return None
        duration_ms = raw_frame.get("durationMs")
        targets = raw_frame.get("targets")
        if (
            type(duration_ms) is not int
            or not MOTION_PLAN_MIN_FRAME_MS <= duration_ms <= MOTION_PLAN_MAX_FRAME_MS
            or not isinstance(targets, list)
            or len(targets) != len(JOINT_LABELS)
        ):
            return None
        total_duration_ms += duration_ms
        if total_duration_ms > MOTION_PLAN_MAX_TOTAL_MS:
            return None
        compact_targets: list[int | None] = [None] * len(JOINT_LABELS)
        for target in targets:
            if not isinstance(target, Mapping):
                return None
            joint = target.get("joint")
            degrees = target.get("degrees")
            if (
                not isinstance(joint, str)
                or joint not in label_to_id
                or type(degrees) not in {int, float}
                or not math.isfinite(float(degrees))
            ):
                return None
            joint_id = label_to_id[joint]
            if compact_targets[joint_id] is not None:
                return None
            scaled = float(degrees) * 100.0
            centidegrees = round(scaled)
            if (
                abs(scaled - centidegrees) > 1e-6
                or not 0 <= centidegrees <= MOTION_PLAN_MAX_CENTIDEGREES
            ):
                return None
            compact_targets[joint_id] = centidegrees
        if any(target is None for target in compact_targets):
            return None
        frames.append([duration_ms, compact_targets])

    end = action.get("endPose", "hold")
    if end not in {"hold", "stand", "neutral"}:
        return None
    return BridgeAction(
        "motion_plan",
        "freestyle",
        {
            "map": MOTION_PLAN_JOINT_MAP,
            "frames": frames,
            "end": end,
        },
    )


def _translate_move(action: Mapping[str, object]) -> BridgeAction | None:
    direction = _normalized(action.get("direction") or "forward")
    if direction in {"left", "turnleft", "right", "turnright"}:
        side = "left" if direction in {"left", "turnleft"} else "right"
        return BridgeAction(
            "intent",
            "emote",
            {"asset": f"turn_{side}_45"},
        )
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
