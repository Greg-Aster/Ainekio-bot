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
WALK_CYCLES = 10
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
        _convert_motion(name, functions[function_name])
        for name, function_name in MOTION_FUNCTIONS.items()
    ]
    motion_manifest = {
        "schema_version": 1,
        "joint_map": _joint_contract(),
        "source": {
            "path": _source_label(sources.motion_header),
            "sha256": _sha256(sources.motion_header),
            "frame_delay_ms": FRAME_DELAY_MS,
            "walk_cycles": WALK_CYCLES,
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
    face_manifest = {
        "schema_version": 1,
        "source": {
            "bitmap_path": _source_label(sources.face_header),
            "bitmap_sha256": _sha256(sources.face_header),
            "runtime_path": _source_label(sources.firmware_source),
            "runtime_sha256": _sha256(sources.firmware_source),
        },
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
    expanded = _expand_loops(_strip_comments(body))
    frames: list[dict[str, object]] = []
    face_cues: list[dict[str, object]] = []
    targets: dict[int, float] = {}

    def flush(duration_ms: int) -> None:
        nonlocal targets
        if not targets:
            return
        if not 20 <= duration_ms <= 5000:
            raise RuntimeError(f"motion {name} has invalid frame duration {duration_ms}")
        frames.append(
            {
                "duration_ms": duration_ms,
                "targets": [[joint_id, targets[joint_id]] for joint_id in sorted(targets)],
            }
        )
        targets = {}

    def apply_stand(show_face: bool) -> None:
        targets.update({0: 135.0, 1: 45.0, 2: 45.0, 3: 135.0, 4: 0.0, 5: 180.0, 6: 0.0, 7: 180.0})
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
            targets[joint_id] = float(token.group("angle"))
        elif token.group("delay") is not None or token.group("press_delay") is not None:
            value = token.group("delay") or token.group("press_delay")
            flush(FRAME_DELAY_MS if value == "frameDelay" else int(value))
        elif token.group("stand_face") is not None:
            apply_stand(token.group("stand_face") == "1")
    flush(20)

    if not 1 <= len(frames) <= MAX_MOTION_FRAMES:
        raise RuntimeError(f"motion {name} expanded to {len(frames)} frames")
    for frame in frames:
        ids = [target[0] for target in frame["targets"]]
        if len(ids) != len(set(ids)) or any(joint_id not in range(8) for joint_id in ids):
            raise RuntimeError(f"motion {name} contains an invalid joint map")
        if any(not 0.0 <= target[1] <= 180.0 for target in frame["targets"]):
            raise RuntimeError(f"motion {name} contains an out-of-range source angle")

    final_targets = {target[0]: target[1] for target in frames[-1]["targets"]}
    return_pose = "stand" if final_targets == {0: 135.0, 1: 45.0, 2: 45.0, 3: 135.0, 4: 0.0, 5: 180.0, 6: 0.0, 7: 180.0} else None
    return {
        "name": name,
        "joint_map_version": JOINT_MAP_VERSION,
        "repeat_count": 1,
        "return_pose": return_pose,
        "face_cues": face_cues,
        "frames": frames,
    }


def _expand_loops(source: str) -> str:
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
        count = WALK_CYCLES if match.group(2) == "walkCycles" else int(match.group(2))
        variable = match.group(1)
        for index in range(count):
            expanded = re.sub(
                rf"setServoAngle\(\s*{re.escape(variable)}\s*,",
                f"setServoAngle({index},",
                body,
            )
            output.append(_expand_loops(expanded))
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

    flags = 1 if return_pose else 0
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
