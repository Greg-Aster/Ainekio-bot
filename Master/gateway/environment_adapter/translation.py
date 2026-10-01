from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Mapping

from protocol.control_v1 import (
    validate_walk_controls,
    ProtocolValidationError,
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
        "number_one",
        "number_two",
    }
)

# This is the gateway-owned semantic capability catalog presented to MetaHuman.
# Descriptions explain physical effects to the selector LLM; translation below
# remains the sole authority for converting the selected exact name to the body
# protocol. Generic seed descriptions are deliberately literal rather than
# inventing behavior not guaranteed by the named motion asset.
ROBOT_COMMAND_DESCRIPTIONS: dict[str, str] = {
    **{
        command: f"perform the preprogrammed {command.replace('_', ' ')} motion"
        for command in SEED_EMOTES
    },
    "stop": "stop the current body motion",
    "sit": "lower into the preprogrammed held sitting pose",
    "stand": "stand normally on all four feet",
    "neutral": "move into the body-control neutral pose",
    "rest": "move into the preprogrammed rest pose",
    "wave": "raise and wave one leg, then return to stand",
    "dance": "alternate paired legs in a rhythmic dance, then return to stand",
    "swim": "paddle the upper leg joints in a swimming-like motion, then return to stand",
    "point": "hold an asymmetric pointing pose, then return to stand",
    "pushup": "lower the front body for repeated push-ups, then return to stand",
    "bow": "lower the front body into a sustained bow, then return to stand",
    "cute": "move into a low expressive pose and wave the rear legs, then return to stand",
    "freaky": "move into a low asymmetric pose and pulse one leg, then return to stand",
    "worm": "lower the body and alternately undulate all legs, then return to stand",
    "shake": "shake the rear leg pair, then return to stand",
    "shrug": "flatten then lift all distal legs in a shrug-like gesture, then return to stand",
    "dead": "lower all distal legs into a flat play-dead pose and hold it",
    "crab": "perform an alternating crab-like leg motion, then return to stand",
    "nod": "perform the preprogrammed shallow nodding gesture, then return to stand",
    "celebrate": "lower into a full-body pose and wave all four legs, then return to stand",
    "stretch": "extend diagonal and front leg pairs in a stretch, then return to stand",
    "macarena": "perform two cycles of Macarena-style front-leg choreography, then return to stand",
    "salsa": "perform forward-back and side-to-side salsa steps, then return to stand",
    "surprised": "lower into a flat pose and wave the front legs, then return to stand",
    "sad": "hold and sway through a lowered sad pose, then return to stand",
    "walk": "walk forward; optional units choose the requested step count",
    "backward": "walk backward; optional units choose the requested step count",
    "left": "turn left approximately 45 degrees",
    "right": "turn right approximately 45 degrees",
    "turn_left_45": "turn left approximately 45 degrees",
    "turn_right_45": "turn right approximately 45 degrees",
    "turn_left_90": "turn left approximately 90 degrees",
    "turn_right_90": "turn right approximately 90 degrees",
    "turn_left_180": "turn left approximately 180 degrees",
    "turn_right_180": "turn right approximately 180 degrees",
    "walk_slow": "walk forward using the preprogrammed slow gait",
    "run": "move forward using the preprogrammed brisk gait",
    "curious": "perform the preprogrammed left-right scanning and curious pose motion",
    "number_one": "perform the bow-supported rear-leg-lift number-one gesture",
    "number_two": "perform the mirrored rear-leg-squat number-two gesture",
    "#1": "alias for the bow-supported rear-leg-lift number-one gesture",
    "#2": "alias for the mirrored rear-leg-squat number-two gesture",
}

# Preserve the actual V1 catalog when a legacy body cannot declare its assets.
# New model-specific names require an explicit body_commands_v1 declaration.
LEGACY_ROBOT_COMMANDS = tuple(sorted(ROBOT_COMMAND_DESCRIPTIONS))
DECLARED_EMOTES = {
    "lay_down": "lower into the grounded wide lying pose and hold; distinct from Rest and Play Dead",
    "upright": "experimental motion: sit, brace the front legs backward, then rise onto the rear lower legs and hold upright",
    "crouch": "squat on all four feet and hold the body above the floor",
    "turn_left_15": "turn left approximately 15 degrees",
    "turn_right_15": "turn right approximately 15 degrees",
}
DECLARED_GAITS = {"crawl": "walk continuously with the body low above the floor; supports direction, Speed, stride and cadence"}
from gateway.body_capabilities import CRAB_DIRECTIONS

# Keep the V1 Crab asset and descriptions. V2 advertises ongoing gait commands.
DECLARED_GAITS.update({name: "ongoing wide-stance walking; Speed, stride, cadence and Finish" for name in CRAB_DIRECTIONS if name != "crab"})
V2_COMMAND_DESCRIPTIONS = {
    "left": "ongoing gait turn left; supports Speed, stride, cadence and Finish; optional units choose finite cycles",
    "right": "ongoing gait turn right; supports Speed, stride, cadence and Finish; optional units choose finite cycles",
    "run": "bound with front and rear leg pairs; automatic Speed above 100 to 200 selects Run, 0 finishes",
    "worm": "two slow, deep whole-body waves, then return to standing",
    "shrug": "sit, lift and open the front arms in a shrug, then return to standing",
    "dead": "collapse into Play Dead with outstretched front arms and grounded lower legs; hold",
    **{name: "ongoing wide-stance " + {"side_l":"sideways left", "side_r":"sideways right", "fwd":"forward", "back":"backward", "turn_l":"turning left", "turn_r":"turning right"}[direction] + "; supports Speed, stride, cadence and Finish" for name,direction in CRAB_DIRECTIONS.items()},
}
ROBOT_COMMAND_DESCRIPTIONS.update(DECLARED_EMOTES)
ROBOT_COMMAND_DESCRIPTIONS.update(DECLARED_GAITS)
ROBOT_COMMAND_DESCRIPTIONS.update({
    "walk": "walk forward; continuous=true runs until stopped; optional speed or stride and rate controls",
    "backward": "walk backward; continuous=true runs until stopped; optional speed or stride and rate controls",
    "left": "turn left 45 degrees, or continuously with continuous=true; supports walking controls",
    "right": "turn right 45 degrees, or continuously with continuous=true; supports walking controls",
})
SUPPORTED_ROBOT_COMMANDS = tuple(sorted(ROBOT_COMMAND_DESCRIPTIONS))

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
        return _translate_move(action, model=model)
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
        "turnleft15degrees": "turnleft15",
        "turnright15degrees": "turnright15",
        "turnleft45degrees": "turnleft45",
        "turnright45degrees": "turnright45",
        "turnleft90degrees": "turnleft90",
        "turnright90degrees": "turnright90",
        "turnleft180degrees": "turnleft180",
        "turnright180degrees": "turnright180",
        "turnaround": "turnright180",
        "lookaround": "curious",
        "#1": "numberone",
        "#2": "numbertwo",
        "number1": "numberone",
        "number2": "numbertwo",
        "pushups": "pushup",
        "playdead": "dead",
        "laydown": "laydown",
        "liedown": "laydown",
        "crableft": "crab",
        "die": "dead",
    }
    command = aliases.get(command, command)
    if command == "stop":
        return BridgeAction("stop")
    if command in {"stand", "neutral", "sit"}:
        return BridgeAction("intent", command)
    crab = next((name for name in CRAB_DIRECTIONS if _normalized(name) == command), None)
    if crab and (model == "v2-12servo" or crab != "crab"):
        direction = action.get("direction", CRAB_DIRECTIONS[crab])
        direction = {"forward":"fwd", "backward":"back", "left":"side_l", "right":"side_r", "turn_left":"turn_l", "turn_right":"turn_r"}.get(direction, direction) if isinstance(direction, str) else None
        if direction not in CRAB_DIRECTIONS.values(): return None
        return BridgeAction("intent", "walk", _walk_params({**action, "gait":"crab", "continuous":action.get("continuous", True)}, direction))
    if command == "run" and model == "v2-12servo":
        defaults = {} if "stride" in action or "rate" in action else {"speed":150}
        # Use the automatic family so Speed can return to Walk in the same
        # command. Explicit advanced Run remains available through gait=run.
        params = _walk_params({**defaults, **action, "gait":"run" if "stride" in action or "rate" in action else "walk", "continuous":action.get("continuous", True)}, "fwd")
        return BridgeAction("intent", "walk", params)
    if command == "crawl":
        direction = action.get("direction", "fwd")
        direction = {"forward":"fwd", "backward":"back", "left":"turn_l", "right":"turn_r"}.get(direction, direction) if isinstance(direction, str) else None
        if direction not in {"fwd", "back", "turn_l", "turn_r"}:return None
        return BridgeAction("intent", "walk", _walk_params({**action, "gait":"crawl", "continuous":action.get("continuous", True)}, direction))
    if command in {"left", "right"}:
        return _translate_turn(action, command, model=model)
    if command in {"walk", "backward"}:
        direction = {
            "walk": "fwd",
            "backward": "back",
        }[command]
        return BridgeAction(
            "intent",
            "walk",
            _walk_params(action, direction),
        )
    emote_asset = next(
        (asset for asset in SEED_EMOTES | DECLARED_EMOTES.keys() if _normalized(asset) == command),
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


def _translate_move(action: Mapping[str, object], *, model: str | None = None) -> BridgeAction | None:
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
    if model == "v2-12servo" or _locomotion_requested(action):
        return BridgeAction("intent", "walk", _walk_params(action, "turn_l" if side == "left" else "turn_r"))
    return BridgeAction("intent", "emote", {"asset": f"turn_{side}_45"})


def _locomotion_requested(action: Mapping[str, object]) -> bool:
    return action.get("continuous") is True or any(k in action for k in ("speed", "stride", "rate", "gait", "update"))


def _walk_params(action: Mapping[str, object], direction: str) -> dict[str, object]:
    if "continuous" in action and type(action["continuous"]) is not bool:
        raise ProtocolValidationError("type:continuous")
    params = {"dir": direction, "steps": 0 if action.get("continuous") else _bounded_steps(action.get("units"))}
    for key in ("speed", "stride", "rate", "forward", "turn", "update", "gait", "speed_percent", "stride_percent", "motion_rate"):
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
