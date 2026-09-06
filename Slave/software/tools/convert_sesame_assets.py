#!/usr/bin/env python3
"""Convert the retained Sesame C headers into bounded Ainekio v1 assets."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path


JOINT_LABELS = ("R1", "R2", "L1", "L2", "R4", "R3", "L3", "L4")
JOINT_IDS = {label: index for index, label in enumerate(JOINT_LABELS)}
JOINT_MAP_VERSION = 1
FRAME_DELAY_MS = 100
WALK_CYCLES = 5
TURN_CYCLES = 10
MOTOR_CURRENT_DELAY_MS = 20
WAVE_SUPPORT_MOVE_MS = 120
WAVE_SUPPORT_SETTLE_MS = 500
TURN_FRAME_MS = 220
TURN_CYCLE_ESTIMATE_DEGREES = 15
MACARENA_BEAT_MS = 460
MACARENA_CYCLES = 2
SALSA_BEAT_MS = 380
SALSA_FORWARD_BACK_CYCLES = 2
SALSA_SIDE_CYCLES = 2
OWNER_MOTION_NAMES = (
    "sit",
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
)
OWNER_MOTION_EXPRESSION_SCALE = {
    "sit": 1.0,
    "nod": 2.0,
    "celebrate": 1.0,
    "stretch": 1.5,
    "macarena": 1.0,
    "salsa": 1.0,
    "surprised": 1.0,
    "sad": 1.5,
    "curious": 0.75,
    "turn_left_45": 0.75,
    "turn_right_45": 0.75,
    "turn_left_90": 0.75,
    "turn_right_90": 0.75,
    "turn_left_180": 0.75,
    "turn_right_180": 0.75,
    "walk_slow": 1.0,
    "run": 1.0,
    "number_one": 1.0,
    "number_two": 1.0,
}
OWNER_MOTION_METADATA = {
    "sit": {"design": "owner_authored_held_pose", "face": "bored"},
    "nod": {"design": "owner_authored", "face": "nod"},
    "celebrate": {
        "design": "owner_authored_cute_pose_all_leg_wave",
        "face": "celebrate",
    },
    "stretch": {"design": "owner_authored", "face": "stretch"},
    "macarena": {
        "design": "owner_authored_counted_choreography",
        "face": "macarena",
        "choreography": "two_16_count_cycles",
        "adaptation": "front_arm_sequence_with_bounded_hip_turn_cue",
    },
    "salsa": {
        "design": "owner_authored_counted_choreography",
        "face": "salsa",
        "choreography": "two_forward_back_basics_then_two_side_basics",
        "timing": "steps_1_2_3_and_5_6_7_with_holds_4_and_8",
    },
    "surprised": {"design": "owner_authored", "face": "surprised_motion"},
    "sad": {"design": "owner_authored", "face": "sad_motion"},
    "curious": {
        "design": "owner_authored_open_loop_scan",
        "face": "curious",
        "calibration": "initial_estimate_requires_physical_tuning",
    },
    "turn_left_45": {
        "design": "owner_authored_open_loop_turn",
        "face": "turn_left_90",
        "calibration": "initial_estimate_requires_physical_tuning",
    },
    "turn_right_45": {
        "design": "owner_authored_open_loop_turn",
        "face": "turn_right_90",
        "calibration": "initial_estimate_requires_physical_tuning",
    },
    "turn_left_90": {
        "design": "owner_authored_open_loop_turn",
        "face": "turn_left_90",
        "calibration": "initial_estimate_requires_physical_tuning",
    },
    "turn_right_90": {
        "design": "owner_authored_open_loop_turn",
        "face": "turn_right_90",
        "calibration": "initial_estimate_requires_physical_tuning",
    },
    "turn_left_180": {
        "design": "owner_authored_open_loop_turn",
        "face": "turn_left_90",
        "calibration": "initial_estimate_requires_physical_tuning",
    },
    "turn_right_180": {
        "design": "owner_authored_open_loop_turn",
        "face": "turn_right_90",
        "calibration": "initial_estimate_requires_physical_tuning",
    },
    "walk_slow": {
        "design": "derived_from_walk_forward",
        "face": "walk_slow",
        "cadence": "slow",
    },
    "run": {
        "design": "derived_from_walk_forward",
        "face": "run",
        "cadence": "brisk",
    },
    "number_one": {
        "design": "derived_from_bow_and_point_rear_leg_lift",
        "face": "number_one",
        "heading": "estimated_right_15_degrees",
        "balance": "full_bow_front_with_point_style_support",
        "calibration": "initial_estimate_requires_physical_tuning",
    },
    "number_two": {
        "design": "owner_authored_rear_squat",
        "face": "number_two",
        "balance": "mirrored_rear_leg_fold",
        "calibration": "initial_estimate_requires_physical_tuning",
    },
}
OWNER_FACE_NAMES = (
    "bored",
    "nod",
    "celebrate",
    "stretch",
    "macarena",
    "salsa",
    "surprised_motion",
    "sad_motion",
    "curious",
    "turn_left_90",
    "turn_right_90",
    "walk_slow",
    "run",
    "number_one",
    "number_two",
)
MAX_MOTION_FRAMES = 256
MAX_FACE_FRAMES = 6
FACE_BYTES = 128 * 64 // 8
MOTION_BINARY_MAGIC = b"AMOT"
MOTION_BINARY_VERSION = 1
MOTION_BINARY_HEADER = struct.Struct("<4sBBBBHHBBHII")
MOTION_FACE_MODES = {"once": 0, "loop": 1, "boomerang": 2}

MOTION_FUNCTIONS = {
    "rest": "runRestPose",
    "stand": "runStandPose",
    "wave": "runWavePose",
    "dance": "runDancePose",
    "swim": "runSwimPose",
    "point": "runPointPose",
    "pushup": "runPushupPose",
    "bow": "runBowPose",
    "cute": "runCutePose",
    "freaky": "runFreakyPose",
    "worm": "runWormPose",
    "shake": "runShakePose",
    "shrug": "runShrugPose",
    "dead": "runDeadPose",
    "crab": "runCrabPose",
    "walk_forward": "runWalkPose",
    "walk_backward": "runWalkBackward",
    "turn_left": "runTurnLeft",
    "turn_right": "runTurnRight",
}

REQUIRED_FACES = (
    "walk", "rest", "swim", "dance", "wave", "point", "stand", "cute",
    "pushup", "freaky", "bow", "worm", "shake", "shrug", "dead", "crab",
    "default", "idle", "idle_blink", "happy", "talk_happy", "sad", "talk_sad",
    "angry", "talk_angry", "surprised", "talk_surprised", "sleepy", "talk_sleepy",
    "love", "talk_love", "excited", "talk_excited", "confused", "talk_confused",
    "thinking", "talk_thinking",
)

FACE_MODE_OVERRIDES = {
    "rest": "boomerang",
    "point": "boomerang",
    "dead": "boomerang",
    "dance": "loop",
    "idle": "loop",
    "idle_blink": "once",
}

TOKEN_PATTERN = re.compile(
    r'setFaceWithMode\("(?P<face>[a-z0-9_]+)",\s*FACE_ANIM_(?P<mode>[A-Z]+)\)'
    r'|setServoAngle\((?P<joint>[A-Z][0-9]|[0-7]),\s*(?P<angle>[0-9]+)\)'
    r'|delayWithFace\((?P<delay>[0-9]+|frameDelay)\)'
    r'|pressingCheck\([^,]+,\s*(?P<press_delay>[0-9]+|frameDelay)\)'
    r'|runStandPose\((?P<stand_face>[01])\)'
)


@dataclass(frozen=True)
class SourcePaths:
    motion_header: Path
    face_header: Path
    firmware_source: Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reference-root",
        type=Path,
        default=Path("docs/sesame-robot/firmware"),
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("Slave/software/assets/seed"),
    )
    args = parser.parse_args()
    sources = SourcePaths(
        args.reference_root / "movement-sequences.h",
        args.reference_root / "face-bitmaps.h",
        args.reference_root / "sesame-firmware-main.ino",
    )
    convert_assets(sources, args.output_root)
    return 0


def convert_assets(sources: SourcePaths, output_root: Path) -> None:
    motion_text = sources.motion_header.read_text(encoding="utf-8")
    face_text = sources.face_header.read_text(encoding="utf-8")
    firmware_text = sources.firmware_source.read_text(encoding="utf-8")
    functions = _extract_functions(motion_text)
    motions = [
        _apply_owner_motion_adjustments(
            _convert_motion(name, functions[function_name])
        )
        for name, function_name in MOTION_FUNCTIONS.items()
    ]
    motions.extend(_owner_motion_assets())
    motion_manifest = {
        "schema_version": 1,
        "joint_map": _joint_contract(),
        "source": {
            "path": _source_label(sources.motion_header),
            "sha256": _sha256(sources.motion_header),
            "frame_delay_ms": FRAME_DELAY_MS,
            "walk_cycles": WALK_CYCLES,
            "turn_cycles": TURN_CYCLES,
            "motor_current_delay_ms": MOTOR_CURRENT_DELAY_MS,
        },
        "owner_adjustments": {
            "wave_arm_joint": "L3",
            "wave_support_move_ms": WAVE_SUPPORT_MOVE_MS,
            "wave_support_settle_ms": WAVE_SUPPORT_SETTLE_MS,
            "turn_frame_ms": TURN_FRAME_MS,
            "turn_cycle_estimate_degrees": TURN_CYCLE_ESTIMATE_DEGREES,
            "macarena_beat_ms": MACARENA_BEAT_MS,
            "macarena_cycles": MACARENA_CYCLES,
            "salsa_beat_ms": SALSA_BEAT_MS,
            "salsa_forward_back_cycles": SALSA_FORWARD_BACK_CYCLES,
            "salsa_side_cycles": SALSA_SIDE_CYCLES,
        },
        "owner_motions": {
            name: {
                **metadata,
                "expression_scale": OWNER_MOTION_EXPRESSION_SCALE[name],
            }
            for name, metadata in OWNER_MOTION_METADATA.items()
        },
        "assets": motions,
    }
    _write_json(output_root / "motions-v1.json", motion_manifest)
    binary_entries = []
    for motion in motions:
        payload = _encode_motion_binary(motion)
        relative = Path("motions") / f"{motion['name']}.amot"
        destination = output_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)
        binary_entries.append(
            {
                "name": motion["name"],
                "path": str(relative),
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    _write_json(
        output_root / "motions-bin-v1.json",
        {
            "schema_version": MOTION_BINARY_VERSION,
            "joint_map": _joint_contract(),
            "assets": binary_entries,
        },
    )

    arrays = _extract_face_arrays(face_text)
    fps = _extract_face_fps(firmware_text)
    face_root = output_root / "faces"
    faces = []
    for name in REQUIRED_FACES:
        source_name = name
        alias = None
        frames = _face_frames(arrays, source_name)
        if not frames and name in {"default", "stand"}:
            source_name = "idle"
            alias = "idle"
            frames = _face_frames(arrays, source_name)
        if not frames:
            raise RuntimeError(f"required face {name!r} has no source bitmap")
        frame_paths = []
        for index, payload in enumerate(frames):
            relative = Path("faces") / name / f"{index}.bin"
            destination = output_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(payload)
            frame_paths.append(str(relative))
        entry: dict[str, object] = {
            "name": name,
            "width": 128,
            "height": 64,
            "fps": fps.get(name, 1),
            "mode": FACE_MODE_OVERRIDES.get(name, "once"),
            "frames": frame_paths,
        }
        if alias is not None:
            entry["source_alias"] = alias
        faces.append(entry)
    for owner_face in _owner_face_assets():
        name = str(owner_face["name"])
        frame_paths = []
        for index, payload in enumerate(owner_face["frames"]):
            relative = Path("faces") / name / f"{index}.bin"
            destination = output_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(payload)
            frame_paths.append(str(relative))
        faces.append(
            {
                "name": name,
                "width": 128,
                "height": 64,
                "fps": owner_face["fps"],
                "mode": owner_face["mode"],
                "frames": frame_paths,
                "source": "ainekio_owner_authored_bitmap",
            }
        )
    face_manifest = {
        "schema_version": 1,
        "source": {
            "bitmap_path": _source_label(sources.face_header),
            "bitmap_sha256": _sha256(sources.face_header),
            "runtime_path": _source_label(sources.firmware_source),
            "runtime_sha256": _sha256(sources.firmware_source),
        },
        "owner_faces": list(OWNER_FACE_NAMES),
        "faces": faces,
    }
    _write_json(output_root / "faces-v1.json", face_manifest)

    tones = (
        ("greeting_1", 440.0, 1600),
        ("setup_required", 330.0, 1280),
        ("wifi_connected", 660.0, 1280),
    )
    audio_assets = []
    for name, frequency, sample_count in tones:
        relative = Path("audio") / f"{name}.pcm"
        path = output_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        samples = [
            int(3000 * math.sin(2.0 * math.pi * frequency * sample / 16000.0))
            for sample in range(sample_count)
        ]
        path.write_bytes(struct.pack(f"<{len(samples)}h", *samples))
        audio_assets.append(
            {
                "name": name,
                "path": str(relative),
                "samples": len(samples),
                "kind": "generated_test_tone",
            }
        )
    _write_json(
        output_root / "audio-v1.json",
        {
            "schema_version": 1,
            "sample_rate": 16000,
            "format": "s16le-mono",
            "assets": audio_assets,
        },
    )


def _extract_functions(source: str) -> dict[str, str]:
    functions: dict[str, str] = {}
    for match in re.finditer(r"inline\s+void\s+(\w+)\s*\([^)]*\)\s*\{", source):
        start = match.end() - 1
        end = _matching(source, start, "{", "}")
        functions[match.group(1)] = source[start + 1 : end]
    missing = set(MOTION_FUNCTIONS.values()) - set(functions)
    if missing:
        raise RuntimeError(f"source motion functions are missing: {sorted(missing)}")
    return functions


def _convert_motion(name: str, body: str) -> dict[str, object]:
    movement_cycles = (
        WALK_CYCLES
        if name in {"walk_forward", "walk_backward"}
        else TURN_CYCLES
    )
    expanded = _expand_loops(_strip_comments(body), movement_cycles)
    frames: list[dict[str, object]] = []
    face_cues: list[dict[str, object]] = []
    targets: list[tuple[int, float]] = []

    def flush(hold_ms: int) -> None:
        nonlocal targets
        if not targets:
            return
        duration_ms = hold_ms + len(targets) * MOTOR_CURRENT_DELAY_MS
        if not 20 <= duration_ms <= 5000:
            raise RuntimeError(f"motion {name} has invalid frame duration {duration_ms}")
        frames.append(
            {
                "duration_ms": duration_ms,
                "targets": [[joint_id, degrees] for joint_id, degrees in targets],
            }
        )
        targets = []

    def apply_stand(show_face: bool) -> None:
        targets.extend(
            (
                (0, 135.0),
                (1, 45.0),
                (2, 45.0),
                (3, 135.0),
                (4, 0.0),
                (5, 180.0),
                (6, 0.0),
                (7, 180.0),
            )
        )
        if show_face:
            face_cues.append({"frame": len(frames), "name": "stand", "mode": "once"})

    for token in TOKEN_PATTERN.finditer(expanded):
        if token.group("face") is not None:
            face_cues.append(
                {
                    "frame": len(frames),
                    "name": _normalize_face_name(token.group("face")),
                    "mode": token.group("mode").lower(),
                }
            )
        elif token.group("joint") is not None:
            joint_value = token.group("joint")
            joint_id = int(joint_value) if joint_value.isdigit() else JOINT_IDS[joint_value]
            if any(existing_id == joint_id for existing_id, _ in targets):
                flush(0)
            targets.append((joint_id, float(token.group("angle"))))
        elif token.group("delay") is not None or token.group("press_delay") is not None:
            value = token.group("delay") or token.group("press_delay")
            flush(FRAME_DELAY_MS if value == "frameDelay" else int(value))
        elif token.group("stand_face") is not None:
            apply_stand(token.group("stand_face") == "1")
    flush(0)

    if not 1 <= len(frames) <= MAX_MOTION_FRAMES:
        raise RuntimeError(f"motion {name} expanded to {len(frames)} frames")
    for frame in frames:
        ids = [target[0] for target in frame["targets"]]
        if len(ids) != len(set(ids)) or any(joint_id not in range(8) for joint_id in ids):
            raise RuntimeError(f"motion {name} contains an invalid joint map")
        if any(not 0.0 <= target[1] <= 180.0 for target in frame["targets"]):
            raise RuntimeError(f"motion {name} contains an out-of-range source angle")

    return {
        "name": name,
        "joint_map_version": JOINT_MAP_VERSION,
        "repeat_count": 1,
        # The retained Sesame functions already contain their terminal pose.
        # Re-applying it in the runtime adds motion and delay not present in
        # the original firmware.
        "return_pose": None,
        "sequential_servo_timing": True,
        "face_cues": face_cues,
        "frames": frames,
    }


def _apply_owner_motion_adjustments(
    motion: dict[str, object],
) -> dict[str, object]:
    if motion["name"] != "wave":
        return motion

    frames = motion["frames"]
    cues = motion["face_cues"]
    if not isinstance(frames, list) or not isinstance(cues, list):
        raise RuntimeError("wave motion has invalid collections")

    setup_index = 1
    expected_targets = [[4, 80.0], [6, 180.0], [3, 90.0], [0, 100.0]]
    setup_frame = frames[setup_index] if len(frames) > setup_index else None
    if not isinstance(setup_frame, dict) or setup_frame.get("targets") != expected_targets:
        raise RuntimeError("wave source setup changed; owner balance override needs review")

    original_duration_ms = int(setup_frame["duration_ms"])
    original_hold_ms = original_duration_ms - (
        len(expected_targets) * MOTOR_CURRENT_DELAY_MS
    )
    support_targets = [target for target in expected_targets if target[0] != 6]
    arm_targets = [target for target in expected_targets if target[0] == 6]
    frames[setup_index : setup_index + 1] = [
        {
            "duration_ms": WAVE_SUPPORT_MOVE_MS,
            "targets": support_targets,
        },
        {
            "duration_ms": WAVE_SUPPORT_SETTLE_MS,
            "targets": support_targets,
        },
        {
            "duration_ms": original_hold_ms + MOTOR_CURRENT_DELAY_MS,
            "targets": arm_targets,
        },
    ]
    for cue in cues:
        if int(cue["frame"]) > setup_index:
            cue["frame"] = int(cue["frame"]) + 2
    return motion


def _owner_motion_assets() -> list[dict[str, object]]:
    stand_targets = [
        [0, 135.0],
        [1, 45.0],
        [2, 45.0],
        [3, 135.0],
        [4, 0.0],
        [5, 180.0],
        [6, 0.0],
        [7, 180.0],
    ]

    def frame(duration_ms: int, targets: list[list[float | int]]) -> dict[str, object]:
        return {"duration_ms": duration_ms, "targets": targets}

    def repeated(
        pattern: list[tuple[int, list[list[float | int]]]],
        count: int,
    ) -> list[dict[str, object]]:
        return [frame(duration_ms, targets) for _ in range(count) for duration_ms, targets in pattern]

    def sequence(
        name: str,
        face: str,
        steps: list[dict[str, object]],
        *,
        face_mode: str = "once",
        final_ms: int = 420,
    ) -> dict[str, object]:
        scale = OWNER_MOTION_EXPRESSION_SCALE[name]
        expanded_steps = []
        stand_degrees = {int(joint_id): float(degrees) for joint_id, degrees in stand_targets}
        for step in steps:
            expanded_targets = []
            for joint_id, degrees in step["targets"]:
                stand_degrees_for_joint = stand_degrees[int(joint_id)]
                expanded_degrees = stand_degrees_for_joint + (
                    float(degrees) - stand_degrees_for_joint
                ) * scale
                expanded_targets.append(
                    [int(joint_id), round(max(0.0, min(180.0, expanded_degrees)), 1)]
                )
            expanded_steps.append(frame(int(step["duration_ms"]), expanded_targets))
        frames = [
            frame(360, stand_targets),
            *expanded_steps,
            frame(final_ms, stand_targets),
        ]
        return {
            "name": name,
            "face_cues": [
                {"frame": 0, "name": face, "mode": face_mode},
                {"frame": len(frames) - 1, "name": "stand", "mode": "once"},
            ],
            "frames": frames,
        }

    def full_pose(overrides: dict[int, float]) -> list[list[float | int]]:
        return [
            [int(joint_id), overrides.get(int(joint_id), float(degrees))]
            for joint_id, degrees in stand_targets
        ]

    left_turn_pattern = [
        (TURN_FRAME_MS, [[5, 145.0], [7, 145.0]]),
        (TURN_FRAME_MS, [[0, 165.0], [3, 165.0]]),
        (TURN_FRAME_MS, [[5, 180.0], [7, 180.0]]),
        (TURN_FRAME_MS, [[0, 135.0], [3, 135.0]]),
        (TURN_FRAME_MS, [[4, 35.0], [6, 35.0]]),
        (TURN_FRAME_MS, [[1, 75.0], [2, 75.0]]),
        (TURN_FRAME_MS, [[4, 0.0], [6, 0.0]]),
        (TURN_FRAME_MS, [[1, 45.0], [2, 45.0]]),
    ]
    right_turn_pattern = [
        (TURN_FRAME_MS, [[4, 35.0], [6, 35.0]]),
        (TURN_FRAME_MS, [[1, 15.0], [2, 15.0]]),
        (TURN_FRAME_MS, [[4, 0.0], [6, 0.0]]),
        (TURN_FRAME_MS, [[1, 45.0], [2, 45.0]]),
        (TURN_FRAME_MS, [[5, 145.0], [7, 145.0]]),
        (TURN_FRAME_MS, [[0, 105.0], [3, 105.0]]),
        (TURN_FRAME_MS, [[5, 180.0], [7, 180.0]]),
        (TURN_FRAME_MS, [[0, 135.0], [3, 135.0]]),
    ]
    # One cycle of the established right turn after its 0.75 expression scale.
    # Keeping these effective targets explicit lets number_one use unscaled,
    # symmetric balance poses for the remainder of the emote.
    right_turn_15_pattern = [
        (TURN_FRAME_MS, [[4, 26.2], [6, 26.2]]),
        (TURN_FRAME_MS, [[1, 22.5], [2, 22.5]]),
        (TURN_FRAME_MS, [[4, 0.0], [6, 0.0]]),
        (TURN_FRAME_MS, [[1, 45.0], [2, 45.0]]),
        (TURN_FRAME_MS, [[5, 153.8], [7, 153.8]]),
        (TURN_FRAME_MS, [[0, 112.5], [3, 112.5]]),
        (TURN_FRAME_MS, [[5, 180.0], [7, 180.0]]),
        (TURN_FRAME_MS, [[0, 135.0], [3, 135.0]]),
    ]
    forward_gait_setup = [
        [5, 135.0], [6, 45.0], [1, 100.0], [2, 25.0],
    ]

    def forward_gait_pattern(
        short_frame_ms: int,
        long_frame_ms: int,
    ) -> list[tuple[int, list[list[float | int]]]]:
        # This is the retained walk_forward lift, sweep, plant, and transfer
        # order. Cadence variants must preserve the working joint topology.
        return [
            (short_frame_ms, [[5, 135.0], [6, 0.0]]),
            (long_frame_ms, [[7, 135.0], [3, 90.0], [4, 0.0], [0, 180.0]]),
            (short_frame_ms, [[1, 45.0], [2, 90.0]]),
            (short_frame_ms, [[4, 45.0], [7, 180.0]]),
            (long_frame_ms, [[5, 180.0], [6, 45.0], [1, 90.0], [2, 0.0]]),
            (short_frame_ms, [[3, 135.0], [0, 90.0]]),
        ]

    slow_walk_pattern = forward_gait_pattern(280, 360)
    run_pattern = forward_gait_pattern(110, 140)
    macarena_cycle = [
        # 1-4: right/left front arms out, then the palm-up equivalents.
        (MACARENA_BEAT_MS, full_pose({0: 150.0, 5: 135.0})),
        (MACARENA_BEAT_MS, full_pose({0: 150.0, 2: 30.0, 5: 135.0, 6: 45.0})),
        (MACARENA_BEAT_MS, full_pose({0: 150.0, 2: 30.0, 5: 90.0, 6: 45.0})),
        (MACARENA_BEAT_MS, full_pose({0: 150.0, 2: 30.0, 5: 90.0, 6: 90.0})),
        # 5-8: cross to shoulders, then move behind the head.
        (MACARENA_BEAT_MS, full_pose({0: 100.0, 2: 30.0, 5: 120.0, 6: 90.0})),
        (MACARENA_BEAT_MS, full_pose({0: 100.0, 2: 80.0, 5: 120.0, 6: 60.0})),
        (MACARENA_BEAT_MS, full_pose({0: 85.0, 2: 80.0, 5: 145.0, 6: 60.0})),
        (MACARENA_BEAT_MS, full_pose({0: 85.0, 2: 95.0, 5: 145.0, 6: 35.0})),
        # 9-12: opposite hips, then the rear-pocket equivalents.
        (MACARENA_BEAT_MS, full_pose({0: 115.0, 2: 95.0, 5: 165.0, 6: 35.0})),
        (MACARENA_BEAT_MS, full_pose({0: 115.0, 2: 65.0, 5: 165.0, 6: 15.0})),
        (MACARENA_BEAT_MS, full_pose({0: 140.0, 2: 65.0, 5: 175.0, 6: 15.0})),
        (MACARENA_BEAT_MS, full_pose({0: 140.0, 2: 40.0, 5: 175.0, 6: 5.0})),
        # 13-16: hip sway, center, and a bounded visual turn cue.
        (MACARENA_BEAT_MS, full_pose({0: 140.0, 1: 60.0, 2: 40.0, 3: 120.0, 4: 25.0, 5: 175.0, 6: 5.0, 7: 160.0})),
        (MACARENA_BEAT_MS, full_pose({0: 140.0, 1: 30.0, 2: 40.0, 3: 150.0, 4: 5.0, 5: 175.0, 6: 5.0, 7: 180.0})),
        (MACARENA_BEAT_MS, full_pose({0: 140.0, 1: 55.0, 2: 40.0, 3: 125.0, 4: 20.0, 5: 175.0, 6: 5.0, 7: 165.0})),
        (MACARENA_BEAT_MS, full_pose({0: 145.0, 1: 35.0, 2: 55.0, 3: 125.0, 4: 20.0, 5: 165.0, 6: 15.0, 7: 160.0})),
    ]
    salsa_center = full_pose({
        0: 130.0, 1: 50.0, 2: 40.0, 3: 130.0,
        4: 15.0, 5: 165.0, 6: 15.0, 7: 165.0,
    })
    salsa_forward_back_basic = [
        (SALSA_BEAT_MS, full_pose({0: 130.0, 1: 60.0, 2: 25.0, 3: 130.0, 4: 30.0, 5: 165.0, 6: 50.0, 7: 165.0})),
        (SALSA_BEAT_MS, full_pose({0: 125.0, 1: 52.0, 2: 38.0, 3: 130.0, 4: 18.0, 5: 155.0, 6: 25.0, 7: 165.0})),
        (SALSA_BEAT_MS, salsa_center),
        (SALSA_BEAT_MS, salsa_center),
        (SALSA_BEAT_MS, full_pose({0: 150.0, 1: 50.0, 2: 40.0, 3: 120.0, 4: 15.0, 5: 130.0, 6: 15.0, 7: 145.0})),
        (SALSA_BEAT_MS, full_pose({0: 142.0, 1: 50.0, 2: 45.0, 3: 128.0, 4: 15.0, 5: 150.0, 6: 20.0, 7: 158.0})),
        (SALSA_BEAT_MS, salsa_center),
        (SALSA_BEAT_MS, salsa_center),
    ]
    salsa_side_basic = [
        (SALSA_BEAT_MS, full_pose({0: 115.0, 1: 65.0, 2: 35.0, 3: 125.0, 4: 35.0, 5: 155.0, 6: 25.0, 7: 155.0})),
        (SALSA_BEAT_MS, full_pose({0: 125.0, 1: 55.0, 2: 40.0, 3: 130.0, 4: 22.0, 5: 160.0, 6: 20.0, 7: 160.0})),
        (SALSA_BEAT_MS, salsa_center),
        (SALSA_BEAT_MS, salsa_center),
        (SALSA_BEAT_MS, full_pose({0: 140.0, 1: 55.0, 2: 65.0, 3: 115.0, 4: 20.0, 5: 160.0, 6: 45.0, 7: 145.0})),
        (SALSA_BEAT_MS, full_pose({0: 135.0, 1: 50.0, 2: 52.0, 3: 125.0, 4: 18.0, 5: 165.0, 6: 28.0, 7: 155.0})),
        (SALSA_BEAT_MS, salsa_center),
        (SALSA_BEAT_MS, salsa_center),
    ]

    # Keep the front legs in their established stand geometry and fold the
    # mirrored rear pair by the same 60-degree excursion toward neutral.
    sit_targets = [
        [0, 135.0], [1, 45.0], [2, 45.0], [3, 135.0],
        [4, 60.0], [5, 180.0], [6, 0.0], [7, 120.0],
    ]
    motions = [
        {
            "name": "sit",
            "face_cues": [
                {"frame": 0, "name": "bored", "mode": "boomerang"},
            ],
            "frames": [
                frame(650, sit_targets),
                frame(800, sit_targets),
            ],
        },
        sequence(
            "nod",
            "nod",
            [
                frame(280, [[5, 142.0], [6, 38.0]]),
                frame(220, [[5, 142.0], [6, 38.0]]),
                frame(260, [[5, 180.0], [6, 0.0]]),
                frame(160, [[5, 180.0], [6, 0.0]]),
                frame(280, [[5, 142.0], [6, 38.0]]),
                frame(220, [[5, 142.0], [6, 38.0]]),
                frame(260, [[5, 180.0], [6, 0.0]]),
            ],
        ),
        sequence(
            "celebrate",
            "celebrate",
            [
                # Ease through the midpoint before reaching the exact full-body
                # lying pose established by the legacy cute motion.
                frame(500, full_pose({
                    0: 157.5, 1: 32.5, 2: 22.5, 3: 147.5,
                    4: 90.0, 5: 90.0, 6: 90.0, 7: 90.0,
                })),
                frame(650, full_pose({
                    0: 180.0, 1: 20.0, 2: 0.0, 3: 160.0,
                    4: 180.0, 5: 0.0, 6: 180.0, 7: 0.0,
                })),
                # Lift all four distal leg joints, then alternate diagonals so
                # every leg participates in the celebratory wave.
                frame(500, [[4, 150.0], [5, 30.0], [6, 150.0], [7, 30.0]]),
                *repeated(
                    [
                        (420, [[4, 175.0], [5, 45.0], [6, 135.0], [7, 5.0]]),
                        (420, [[4, 135.0], [5, 5.0], [6, 175.0], [7, 45.0]]),
                    ],
                    3,
                ),
                frame(450, [[4, 150.0], [5, 30.0], [6, 150.0], [7, 30.0]]),
                frame(500, [[4, 180.0], [5, 0.0], [6, 180.0], [7, 0.0]]),
            ],
            face_mode="loop",
            final_ms=650,
        ),
        sequence(
            "stretch",
            "stretch",
            [
                frame(420, [[1, 55.0], [3, 125.0], [4, 25.0], [7, 155.0]]),
                frame(600, [[0, 165.0], [2, 15.0], [5, 120.0], [6, 60.0]]),
                frame(900, [[0, 165.0], [2, 15.0], [5, 120.0], [6, 60.0]]),
                frame(400, [[5, 108.0], [6, 72.0]]),
                frame(700, [[5, 108.0], [6, 72.0]]),
                frame(450, [[0, 150.0], [2, 30.0], [5, 135.0], [6, 45.0]]),
            ],
            final_ms=500,
        ),
        sequence(
            "macarena",
            "macarena",
            repeated(macarena_cycle, MACARENA_CYCLES),
            face_mode="loop",
            final_ms=600,
        ),
        sequence(
            "salsa",
            "salsa",
            [
                *repeated(salsa_forward_back_basic, SALSA_FORWARD_BACK_CYCLES),
                *repeated(salsa_side_basic, SALSA_SIDE_CYCLES),
            ],
            face_mode="loop",
            final_ms=600,
        ),
        sequence(
            "surprised",
            "surprised_motion",
            [
                # Start from the established dead pose: all four arm joints flat.
                frame(500, [[4, 90.0], [5, 90.0], [6, 90.0], [7, 90.0]]),
                frame(650, [[4, 90.0], [5, 90.0], [6, 90.0], [7, 90.0]]),
                # R3 and L3 are the front pair. Their orientation mirrors the
                # R4/L4 pair used by the established cute wave.
                frame(500, [[5, 0.0], [6, 180.0]]),
                *repeated(
                    [
                        (340, [[5, 0.0], [6, 135.0]]),
                        (340, [[5, 45.0], [6, 180.0]]),
                    ],
                    3,
                ),
                frame(450, [[5, 90.0], [6, 90.0]]),
            ],
            final_ms=500,
        ),
        sequence(
            "sad",
            "sad_motion",
            [
                frame(700, [[0, 155.0], [1, 50.0], [2, 25.0], [3, 130.0], [4, 10.0], [5, 125.0], [6, 55.0], [7, 170.0]]),
                frame(900, [[0, 155.0], [1, 50.0], [2, 25.0], [3, 130.0], [4, 10.0], [5, 125.0], [6, 55.0], [7, 170.0]]),
                frame(500, [[0, 145.0], [2, 20.0], [5, 120.0], [6, 60.0]]),
                frame(500, [[0, 145.0], [2, 20.0], [5, 120.0], [6, 60.0]]),
                frame(500, [[0, 160.0], [2, 35.0], [5, 135.0], [6, 45.0]]),
                frame(500, [[0, 160.0], [2, 35.0], [5, 135.0], [6, 45.0]]),
            ],
            final_ms=700,
        ),
        sequence(
            "curious",
            "curious",
            [
                *repeated(right_turn_pattern, 2),
                frame(500, stand_targets),
                *repeated(left_turn_pattern, 2),
                frame(650, stand_targets),
                *repeated(left_turn_pattern, 2),
                frame(500, stand_targets),
                *repeated(right_turn_pattern, 2),
                frame(650, stand_targets),
                frame(500, [[0, 127.0], [2, 37.0], [5, 160.0], [6, 20.0]]),
                frame(650, [[0, 127.0], [2, 37.0], [5, 160.0], [6, 20.0]]),
            ],
            face_mode="boomerang",
            final_ms=600,
        ),
        sequence(
            "turn_left_45",
            "turn_left_90",
            repeated(left_turn_pattern, 3),
            face_mode="loop",
            final_ms=600,
        ),
        sequence(
            "turn_right_45",
            "turn_right_90",
            repeated(right_turn_pattern, 3),
            face_mode="loop",
            final_ms=600,
        ),
        sequence(
            "turn_left_90",
            "turn_left_90",
            repeated(left_turn_pattern, 6),
            face_mode="loop",
            final_ms=600,
        ),
        sequence(
            "turn_right_90",
            "turn_right_90",
            repeated(right_turn_pattern, 6),
            face_mode="loop",
            final_ms=600,
        ),
        sequence(
            "turn_left_180",
            "turn_left_90",
            repeated(left_turn_pattern, 12),
            face_mode="loop",
            final_ms=700,
        ),
        sequence(
            "turn_right_180",
            "turn_right_90",
            repeated(right_turn_pattern, 12),
            face_mode="loop",
            final_ms=700,
        ),
        sequence(
            "walk_slow",
            "walk_slow",
            [
                frame(360, forward_gait_setup),
                *repeated(slow_walk_pattern, 3),
            ],
            face_mode="loop",
            final_ms=500,
        ),
        sequence(
            "run",
            "run",
            [
                frame(140, forward_gait_setup),
                *repeated(run_pattern, 6),
            ],
            face_mode="loop",
            final_ms=360,
        ),
        sequence(
            "number_one",
            "number_one",
            [
                *repeated(right_turn_15_pattern, 1),
                # Enter the established bow through its upper-joint pose while
                # beginning the right-rear support transfer.
                frame(650, full_pose({
                    0: 180.0, 1: 75.0, 2: 0.0, 4: 40.0,
                })),
                # Use the bow's exact front geometry and the point pose's
                # established R2/R4 support targets.
                frame(650, full_pose({
                    0: 180.0, 1: 100.0, 2: 0.0, 4: 80.0,
                    5: 90.0, 6: 90.0,
                })),
                frame(500, full_pose({
                    0: 180.0, 1: 100.0, 2: 0.0, 4: 80.0,
                    5: 90.0, 6: 90.0,
                })),
                frame(450, full_pose({
                    0: 180.0, 1: 100.0, 2: 0.0, 3: 110.0,
                    4: 80.0, 5: 90.0, 6: 90.0, 7: 120.0,
                })),
                # Mirror point's 145-degree distal lift onto back-left L4;
                # L2 follows point's established 90-degree joint target.
                frame(700, full_pose({
                    0: 180.0, 1: 100.0, 2: 0.0, 3: 90.0,
                    4: 80.0, 5: 90.0, 6: 90.0, 7: 35.0,
                })),
                frame(1000, full_pose({
                    0: 180.0, 1: 100.0, 2: 0.0, 3: 90.0,
                    4: 80.0, 5: 90.0, 6: 90.0, 7: 35.0,
                })),
                frame(600, full_pose({
                    0: 180.0, 1: 100.0, 2: 0.0, 3: 110.0,
                    4: 80.0, 5: 90.0, 6: 90.0, 7: 120.0,
                })),
                frame(420, full_pose({
                    0: 180.0, 1: 100.0, 2: 0.0, 4: 80.0,
                    5: 90.0, 6: 90.0,
                })),
            ],
            face_mode="loop",
            final_ms=600,
        ),
        sequence(
            "number_two",
            "number_two",
            [
                # Fold both rear pairs by equal mirrored excursions so the
                # rump lowers without introducing a side-to-side lean.
                frame(520, full_pose({1: 60.0, 3: 120.0, 4: 35.0, 7: 145.0})),
                frame(650, full_pose({1: 75.0, 3: 105.0, 4: 60.0, 7: 120.0})),
                frame(800, full_pose({1: 75.0, 3: 105.0, 4: 60.0, 7: 120.0})),
                frame(420, full_pose({1: 80.0, 3: 100.0, 4: 65.0, 7: 115.0})),
                frame(420, full_pose({1: 75.0, 3: 105.0, 4: 60.0, 7: 120.0})),
                frame(600, full_pose({1: 75.0, 3: 105.0, 4: 60.0, 7: 120.0})),
                frame(500, full_pose({1: 60.0, 3: 120.0, 4: 35.0, 7: 145.0})),
            ],
            face_mode="boomerang",
            final_ms=600,
        ),
    ]

    if tuple(str(motion["name"]) for motion in motions) != OWNER_MOTION_NAMES:
        raise RuntimeError("owner motion catalog order drifted")

    for motion in motions:
        frames = motion["frames"]
        if not isinstance(frames, list) or not 1 <= len(frames) <= MAX_MOTION_FRAMES:
            raise RuntimeError(f"owner motion {motion['name']} has invalid frames")
        for frame in frames:
            targets = frame["targets"]
            duration_ms = frame["duration_ms"]
            if type(duration_ms) is not int or not 20 <= duration_ms <= 5000:
                raise RuntimeError(f"owner motion {motion['name']} has an invalid duration")
            ids = [target[0] for target in targets]
            if len(ids) != len(set(ids)) or any(joint_id not in range(8) for joint_id in ids):
                raise RuntimeError(f"owner motion {motion['name']} has an invalid joint map")
            if any(not 0.0 <= target[1] <= 180.0 for target in targets):
                raise RuntimeError(f"owner motion {motion['name']} has an invalid target")
        motion.update(
            {
                "joint_map_version": JOINT_MAP_VERSION,
                "repeat_count": 1,
                "return_pose": None,
                "sequential_servo_timing": False,
            }
        )
    return motions


def _owner_face_assets() -> list[dict[str, object]]:
    settings = {
        "bored": (2, "boomerang"),
        "nod": (3, "boomerang"),
        "celebrate": (5, "loop"),
        "stretch": (2, "boomerang"),
        "macarena": (5, "loop"),
        "salsa": (5, "loop"),
        "surprised_motion": (4, "boomerang"),
        "sad_motion": (2, "boomerang"),
        "curious": (3, "boomerang"),
        "turn_left_90": (3, "loop"),
        "turn_right_90": (3, "loop"),
        "walk_slow": (2, "boomerang"),
        "run": (5, "loop"),
        "number_one": (4, "loop"),
        "number_two": (3, "boomerang"),
    }
    assets = []
    for name in OWNER_FACE_NAMES:
        fps, mode = settings[name]
        frames = [_draw_owner_face(name, variant) for variant in range(2)]
        if any(len(payload) != FACE_BYTES for payload in frames):
            raise RuntimeError(f"owner face {name} has an invalid frame size")
        if any(not any(payload) for payload in frames):
            raise RuntimeError(f"owner face {name} rendered blank")
        assets.append({"name": name, "fps": fps, "mode": mode, "frames": frames})
    return assets


def _draw_owner_face(name: str, variant: int) -> bytes:
    canvas = bytearray(FACE_BYTES)

    def line(points: list[tuple[int, int]], width: int = 2) -> None:
        for start, end in zip(points, points[1:]):
            _bitmap_line(canvas, *start, *end, width=width)

    def smile() -> None:
        line([(45, 43), (52, 48), (63, 51), (75, 48), (83, 42)], 2)

    def closed_eyes(offset: int = 0) -> None:
        line([(25, 26 + offset), (35, 22 + offset), (45, 26 + offset)], 2)
        line([(83, 26 + offset), (93, 22 + offset), (103, 26 + offset)], 2)

    def round_eyes(pupil_shift: int = 0) -> None:
        for center_x in (36, 92):
            _bitmap_circle(canvas, center_x, 25, 10, width=2)
            _bitmap_circle(canvas, center_x + pupil_shift, 26, 3, filled=True)

    if name == "bored":
        eye_y = 23 + variant
        line([(25, eye_y), (36, eye_y + 2), (46, eye_y)], 2)
        line([(82, eye_y), (92, eye_y + 2), (103, eye_y)], 2)
        _bitmap_circle(canvas, 36, eye_y + 5, 2, filled=True)
        _bitmap_circle(canvas, 92, eye_y + 5, 2, filled=True)
        line([(47, 48 + variant), (63, 47 + variant), (81, 48 + variant)], 2)
    elif name == "nod":
        closed_eyes(variant)
        smile()
        line([(61, 10 + variant), (64, 13 + variant), (67, 10 + variant)], 1)
    elif name == "celebrate":
        radius = 8 + variant
        for center_x in (36, 92):
            _bitmap_star(canvas, center_x, 24, radius)
        smile()
        _bitmap_star(canvas, 64, 10 + (variant * 2), 4)
    elif name == "stretch":
        closed_eyes(variant)
        _bitmap_circle(canvas, 64, 46, 8 + variant, width=2)
        line([(12, 16), (18, 12), (24, 16)], 1)
    elif name == "macarena":
        closed_eyes()
        smile()
        _bitmap_music_note(canvas, 15, 17 + (variant * 3), mirrored=False)
        _bitmap_music_note(canvas, 111, 14 + ((1 - variant) * 3), mirrored=True)
    elif name == "salsa":
        line([(25, 25), (36, 22), (46, 25)], 2)
        _bitmap_circle(canvas, 92, 25, 9, width=2)
        _bitmap_circle(canvas, 94 - (variant * 3), 26, 3, filled=True)
        smile()
        _bitmap_music_note(canvas, 16, 13 + (variant * 4), mirrored=False)
    elif name == "surprised_motion":
        round_eyes(0)
        _bitmap_circle(canvas, 64, 48, 8 + variant, width=2)
        if variant:
            for start, end in [((17, 12), (11, 7)), ((111, 12), (117, 7)), ((64, 8), (64, 2))]:
                _bitmap_line(canvas, *start, *end, width=2)
    elif name == "sad_motion":
        line([(25, 17), (36, 22), (46, 20)], 2)
        line([(82, 20), (92, 22), (103, 17)], 2)
        _bitmap_circle(canvas, 36, 28, 3, filled=True)
        _bitmap_circle(canvas, 92, 28, 3, filled=True)
        line([(45, 52), (54, 45), (64, 42), (74, 45), (83, 52)], 2)
        tear_y = 35 + (variant * 6)
        _bitmap_line(canvas, 102, tear_y, 102, tear_y + 6, width=2)
        _bitmap_circle(canvas, 102, tear_y + 7, 2, filled=True)
    elif name == "curious":
        pupil_shift = -4 if variant == 0 else 4
        round_eyes(pupil_shift)
        line([(25, 13 + variant), (45, 9 + variant)], 2)
        line([(83, 9 + (1 - variant)), (103, 13 + (1 - variant))], 2)
        _bitmap_circle(canvas, 64, 48, 4, width=2)
    elif name in {"turn_left_90", "turn_right_90"}:
        round_eyes(-2 if name == "turn_left_90" else 2)
        direction = -1 if name == "turn_left_90" else 1
        center_x = 64 + (variant * direction * 4)
        _bitmap_arrow(canvas, center_x, 48, direction)
    elif name == "walk_slow":
        line([(25, 24 + variant), (46, 24 + variant)], 3)
        line([(82, 24 + variant), (103, 24 + variant)], 3)
        line([(52, 47), (64, 49), (76, 47)], 2)
    elif name == "run":
        line([(23, 16 + variant), (46, 23 + variant)], 3)
        line([(82, 23 + variant), (105, 16 + variant)], 3)
        _bitmap_circle(canvas, 37, 28, 4, filled=True)
        _bitmap_circle(canvas, 91, 28, 4, filled=True)
        line([(46, 45), (57, 50), (70, 50), (82, 44)], 2)
        _bitmap_line(canvas, 8 + (variant * 4), 31, 18 + (variant * 4), 31, width=2)
    elif name == "number_one":
        # Cheeky wink, tongue, and animated droplets for the pet-like hydrant
        # gag without putting protocol text on the small display.
        line([(25, 26), (35, 22), (45, 26)], 2)
        _bitmap_circle(canvas, 92, 25, 9, width=2)
        _bitmap_circle(canvas, 94 + (variant * 2), 26, 3, filled=True)
        line([(44, 43), (53, 48), (64, 50), (76, 47), (83, 42)], 2)
        _bitmap_circle(canvas, 64, 51 + variant, 5, width=2)
        line([(61, 53), (67, 53)], 1)
        droplet_y = 39 + (variant * 4)
        for droplet_x, offset_y in ((108, 0), (116, 7), (122, 14)):
            line([
                (droplet_x, droplet_y + offset_y - 3),
                (droplet_x - 2, droplet_y + offset_y + 1),
                (droplet_x, droplet_y + offset_y + 3),
                (droplet_x + 2, droplet_y + offset_y + 1),
                (droplet_x, droplet_y + offset_y - 3),
            ], 1)
    elif name == "number_two":
        # Pinched eyes, tense brows, clenched teeth, and a moving sweat drop.
        line([(23, 17), (36, 22), (47, 17)], 3)
        line([(81, 17), (92, 22), (105, 17)], 3)
        line([(25, 29), (36, 25), (46, 29)], 2)
        line([(82, 29), (92, 25), (103, 29)], 2)
        line([(49, 43), (79, 43), (79, 55), (49, 55), (49, 43)], 2)
        for tooth_x in (57, 64, 71):
            _bitmap_line(canvas, tooth_x, 44, tooth_x, 54, width=1)
        _bitmap_line(canvas, 50, 49, 78, 49, width=1)
        sweat_y = 27 + (variant * 6)
        line([(112, sweat_y - 5), (109, sweat_y), (112, sweat_y + 4), (115, sweat_y), (112, sweat_y - 5)], 1)
    else:
        raise RuntimeError(f"unknown owner face {name}")

    return bytes(canvas)


def _bitmap_pixel(canvas: bytearray, x: int, y: int) -> None:
    if 0 <= x < 128 and 0 <= y < 64:
        canvas[(y * 16) + (x // 8)] |= 0x80 >> (x % 8)


def _bitmap_line(
    canvas: bytearray,
    x0: int,
    y0: int,
    x1: int,
    y1: int,
    *,
    width: int = 1,
) -> None:
    dx = abs(x1 - x0)
    step_x = 1 if x0 < x1 else -1
    dy = -abs(y1 - y0)
    step_y = 1 if y0 < y1 else -1
    error = dx + dy
    while True:
        radius = max(0, width - 1)
        for offset_y in range(-radius, radius + 1):
            for offset_x in range(-radius, radius + 1):
                if abs(offset_x) + abs(offset_y) <= radius:
                    _bitmap_pixel(canvas, x0 + offset_x, y0 + offset_y)
        if x0 == x1 and y0 == y1:
            break
        twice_error = 2 * error
        if twice_error >= dy:
            error += dy
            x0 += step_x
        if twice_error <= dx:
            error += dx
            y0 += step_y


def _bitmap_circle(
    canvas: bytearray,
    center_x: int,
    center_y: int,
    radius: int,
    *,
    width: int = 1,
    filled: bool = False,
) -> None:
    outer_squared = radius * radius
    inner_radius = max(0, radius - width)
    inner_squared = inner_radius * inner_radius
    for y in range(center_y - radius, center_y + radius + 1):
        for x in range(center_x - radius, center_x + radius + 1):
            squared = ((x - center_x) ** 2) + ((y - center_y) ** 2)
            if squared <= outer_squared and (filled or squared >= inner_squared):
                _bitmap_pixel(canvas, x, y)


def _bitmap_star(canvas: bytearray, center_x: int, center_y: int, radius: int) -> None:
    for x1, y1, x2, y2 in [
        (center_x - radius, center_y, center_x + radius, center_y),
        (center_x, center_y - radius, center_x, center_y + radius),
        (center_x - radius + 2, center_y - radius + 2, center_x + radius - 2, center_y + radius - 2),
        (center_x - radius + 2, center_y + radius - 2, center_x + radius - 2, center_y - radius + 2),
    ]:
        _bitmap_line(canvas, x1, y1, x2, y2, width=2)


def _bitmap_music_note(
    canvas: bytearray,
    x: int,
    y: int,
    *,
    mirrored: bool,
) -> None:
    direction = -1 if mirrored else 1
    _bitmap_line(canvas, x, y, x, y + 13, width=2)
    _bitmap_line(canvas, x, y, x + (8 * direction), y + 3, width=2)
    _bitmap_circle(canvas, x - (3 * direction), y + 15, 4, filled=True)


def _bitmap_arrow(canvas: bytearray, center_x: int, center_y: int, direction: int) -> None:
    tail_x = center_x - (18 * direction)
    head_x = center_x + (18 * direction)
    _bitmap_line(canvas, tail_x, center_y, head_x, center_y, width=3)
    _bitmap_line(canvas, head_x, center_y, head_x - (9 * direction), center_y - 8, width=3)
    _bitmap_line(canvas, head_x, center_y, head_x - (9 * direction), center_y + 8, width=3)


def _expand_loops(source: str, movement_cycles: int) -> str:
    output = []
    cursor = 0
    loop_pattern = re.compile(r"\bfor\s*\(\s*int\s+(\w+)\s*=\s*0\s*;\s*\1\s*<\s*(\d+|walkCycles)\s*;[^)]*\)")
    while True:
        match = loop_pattern.search(source, cursor)
        if match is None:
            output.append(source[cursor:])
            break
        output.append(source[cursor : match.start()])
        body_start = match.end()
        while body_start < len(source) and source[body_start].isspace():
            body_start += 1
        if source[body_start] == "{":
            body_end = _matching(source, body_start, "{", "}")
            body = source[body_start + 1 : body_end]
            cursor = body_end + 1
        else:
            body_end = source.find(";", body_start)
            if body_end < 0:
                raise RuntimeError("unterminated source for-loop")
            body = source[body_start : body_end + 1]
            cursor = body_end + 1
        count = movement_cycles if match.group(2) == "walkCycles" else int(match.group(2))
        variable = match.group(1)
        for index in range(count):
            expanded = re.sub(
                rf"setServoAngle\(\s*{re.escape(variable)}\s*,",
                f"setServoAngle({index},",
                body,
            )
            output.append(_expand_loops(expanded, movement_cycles))
    return "".join(output)


def _encode_motion_binary(motion: dict[str, object]) -> bytes:
    name = str(motion["name"]).encode("ascii")
    return_pose_value = motion["return_pose"]
    return_pose = b"" if return_pose_value is None else str(return_pose_value).encode("ascii")
    frames = motion["frames"]
    cues = motion["face_cues"]
    if not isinstance(frames, list) or not isinstance(cues, list):
        raise RuntimeError("motion encoder received invalid collections")
    if len(cues) > 16:
        raise RuntimeError(f"motion {motion['name']} has too many face cues")

    body = bytearray(name)
    body.extend(return_pose)
    for cue in cues:
        cue_name = str(cue["name"]).encode("ascii")
        mode = MOTION_FACE_MODES.get(str(cue["mode"]))
        if mode is None or len(cue_name) > 32:
            raise RuntimeError(f"motion {motion['name']} has an invalid face cue")
        body.extend(struct.pack("<HBB", int(cue["frame"]), mode, len(cue_name)))
        body.extend(cue_name)
    for frame in frames:
        targets = frame["targets"]
        if not isinstance(targets, list):
            raise RuntimeError(f"motion {motion['name']} has invalid targets")
        body.extend(struct.pack("<HB", int(frame["duration_ms"]), len(targets)))
        for joint_id, degrees in targets:
            centidegrees = int(round(float(degrees) * 100.0))
            if not 0 <= centidegrees <= 18000:
                raise RuntimeError(f"motion {motion['name']} has an invalid target")
            body.extend(struct.pack("<BH", int(joint_id), centidegrees))

    flags = (1 if return_pose else 0) | (
        2 if motion.get("sequential_servo_timing") else 0
    )
    header = MOTION_BINARY_HEADER.pack(
        MOTION_BINARY_MAGIC,
        MOTION_BINARY_VERSION,
        JOINT_MAP_VERSION,
        int(motion["repeat_count"]),
        flags,
        len(frames),
        len(cues),
        len(name),
        len(return_pose),
        0,
        len(body),
        zlib.crc32(body) & 0xFFFFFFFF,
    )
    return header + body


def _extract_face_arrays(source: str) -> dict[str, bytes]:
    arrays: dict[str, bytes] = {}
    pattern = re.compile(
        r"const\s+unsigned\s+char\s+epd_bitmap_([a-z0-9_]+)\s*\[\s*\]\s*PROGMEM\s*=\s*\{(.*?)\};",
        re.DOTALL,
    )
    for match in pattern.finditer(source):
        payload = bytes(int(value, 16) for value in re.findall(r"0x([0-9a-fA-F]{2})", match.group(2)))
        if len(payload) != FACE_BYTES:
            raise RuntimeError(f"face {match.group(1)!r} has {len(payload)} bytes")
        arrays[match.group(1)] = payload
    if not arrays:
        raise RuntimeError("no face bitmap arrays were found")
    return arrays


def _face_frames(arrays: dict[str, bytes], name: str) -> list[bytes]:
    normalized = "defualt" if name == "default" else name
    frames = []
    base = arrays.get(normalized)
    if base is not None:
        frames.append(base)
    for index in range(1, MAX_FACE_FRAMES):
        frame = arrays.get(f"{normalized}_{index}")
        if frame is not None:
            frames.append(frame)
    return frames


def _extract_face_fps(source: str) -> dict[str, int]:
    block_match = re.search(r"const FaceFpsEntry faceFpsEntries\[\]\s*=\s*\{(.*?)\};", source, re.DOTALL)
    if block_match is None:
        raise RuntimeError("face FPS table is missing")
    result = {
        _normalize_face_name(name): int(value)
        for name, value in re.findall(r'\{\s*"([a-z0-9_]+)"\s*,\s*(\d+)\s*\}', block_match.group(1))
    }
    if any(not 1 <= value <= 30 for value in result.values()):
        raise RuntimeError("face FPS table is out of bounds")
    return result


def _matching(source: str, start: int, opening: str, closing: str) -> int:
    depth = 0
    for index in range(start, len(source)):
        if source[index] == opening:
            depth += 1
        elif source[index] == closing:
            depth -= 1
            if depth == 0:
                return index
    raise RuntimeError(f"unmatched {opening!r} in source")


def _strip_comments(source: str) -> str:
    source = re.sub(r"//.*", "", source)
    return re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)


def _normalize_face_name(name: str) -> str:
    return "default" if name == "defualt" else name


def _joint_contract() -> dict[str, object]:
    return {
        "version": JOINT_MAP_VERSION,
        "joints": [
            {"id": joint_id, "label": label}
            for joint_id, label in enumerate(JOINT_LABELS)
        ],
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_label(path: Path) -> str:
    parts = path.parts
    if "docs" in parts:
        return str(Path(*parts[parts.index("docs") :]))
    return path.name


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
