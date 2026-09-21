"""Compile retained finite turns and gestures. Standard Python only.

Store positions once; the model derives the supplied harmonic tangents from
adjacent knots. All clips use one sampler and retain the recorded 120 Hz timing.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_turns(root: Path) -> list[dict]:
    family = root / "motions/turns"
    catalog = json.loads((family / "catalog.json").read_text())
    model = json.loads((root / "model.json").read_text())
    legs = ["FL", "FR", "RL", "RR"]
    axes = ["h_Part002", "alpha_Part006", "theta_Part005"]
    if model["model"] != "v2-12servo" or len(model["joints"]) != 12:
        raise ValueError("incompatible turn model")
    for i, joint in enumerate(model["joints"]):
        if joint["id"] != i or joint["cad_leg"] != legs[i // 3] or joint["actuator"] != axes[i % 3]:
            raise ValueError("model joint order disagrees with the turn source")
    entries = catalog["commands"]
    if len(entries) != 8 or len({e["command"] for e in entries}) != 8:
        raise ValueError("turn family must contain eight independent commands")
    geometry_hash, sole_hash = digest(root / "geometry.json"), digest(family / "sole-hulls.npz")
    turns = []
    for entry in entries:
        command = entry["command"]
        match = re.fullmatch(r"turn_(left|right)_(15|45|90|180)", command)
        if not match or entry["path"] != f"commands/{command}":
            raise ValueError("invalid turn command/path")
        folder = family / entry["path"]
        manifest = json.loads((folder / "manifest.json").read_text())
        source = json.loads((folder / "source.json").read_text())
        schema = json.loads((folder / "schema.json").read_text())
        metadata = source["metadata"]
        if (digest(folder / "source.json") != manifest["source_sha256"]
            or manifest["source_sha256"] != entry["source_sha256"]
            or manifest["geometry_sha256"] != geometry_hash or manifest["sole_hulls_sha256"] != sole_hash):
            raise ValueError(f"{command}: source or geometry provenance mismatch")
        if (manifest["command"] != command or metadata["configuration"]["command"] != command
            or manifest["wire"] != {"t": "intent", "name": "emote", "asset": command}
            or metadata["leg_order"] != legs or metadata["joint_order"] != axes
            or schema["leg_order"] != legs or schema["joint_order"] != axes
            or metadata["angle_units"] != "radian" or metadata["position_units"] != "mm"
            or metadata["time_units"] != "second"):
            raise ValueError(f"{command}: incompatible command, joint order or units")
        hz = manifest["source_sample_hz"]
        duration = manifest["duration_seconds"]
        if (hz != 120 or metadata["configuration"]["sample_hz"] != hz or schema["source_sample_hz"] != hz
            or not math.isfinite(duration) or not 0 < duration <= 35
            or duration != entry["duration_s"]
            or len(source["samples"]) != round(duration * hz) + 1
            or len(source["samples"]) != manifest["sample_count"] or len(source["samples"]) != entry["samples"]):
            raise ValueError(f"{command}: invalid sample count or timing")
        turn_start, turn_end = manifest["turn_source_seconds"]
        if not 0 <= turn_start < turn_end <= duration:
            raise ValueError(f"{command}: invalid turn interval")
        heading = int(match[2]) * (1 if match[1] == "left" else -1)
        if heading != manifest["heading_change_degrees"] or heading != entry["heading_degrees"]:
            raise ValueError(f"{command}: heading/name mismatch")
        positions = []
        for i, sample in enumerate(source["samples"]):
            if not math.isfinite(sample["time_s"]) or abs(sample["time_s"] - i / hz) > 1e-8:
                raise ValueError(f"{command}: nonuniform or reordered samples")
            angles = sample["actuator_angles_rad"]
            if len(angles) != 4 or any(len(leg) != 3 for leg in angles):
                raise ValueError(f"{command}: every sample must supply all twelve joints")
            row = [math.degrees(value) * 100 for leg in angles for value in leg]
            if not all(math.isfinite(value) for value in row):
                raise ValueError(f"{command}: nonfinite angle")
            positions.append(row)
        yaw = source["samples"][-1]["body_yaw_world_rad"] - source["samples"][0]["body_yaw_world_rad"]
        if not math.isfinite(yaw) or abs(math.degrees(yaw) - heading) > 1e-6:
            raise ValueError(f"{command}: recorded heading does not match the command")
        if (source["samples"][-1]["actuator_angles_rad"] != manifest["final_actuator_angles_rad"]
            or any(abs(value) > 1e-6 for value in positions[0])):
            raise ValueError(f"{command}: recorded entry/final pose mismatch")
        if catalog["hardware_qualified"] is not False or manifest["hardware_qualified"] is not False:
            raise ValueError("research source import cannot grant hardware readiness")
        turns.append(dict(command=command, manifest=manifest, positions=positions,
                          duration_s=duration, start_s=turn_start, end_s=turn_end, phase='AINEKIO_V2_TURN'))
    return turns


def load_gestures(root: Path) -> list[dict]:
    family = root / "motions/gestures"
    catalog = json.loads((family / "catalog.json").read_text())
    policy_hash = digest(family / "execution-policy.json")
    geometry_hash = digest(root / "geometry.json")
    sole_hash = digest(root / "motions/turns/sole-hulls.npz")
    if catalog["hardware_qualified"] is not False or catalog["policy_sha256"] != policy_hash:
        raise ValueError("gesture readiness or execution policy mismatch")
    gestures = []
    for entry in catalog["commands"]:
        command = entry["command"]
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,31}", command) or entry["path"] != command:
            raise ValueError("invalid gesture command/path")
        folder = family / command
        for name in ("source.json", "manifest.json", "schema.json", "execution-contract.json"):
            if digest(folder / name) != entry["sha256"][name]:
                raise ValueError(f"{command}: {name} provenance mismatch")
        manifest = json.loads((folder / "manifest.json").read_text())
        source = json.loads((folder / "source.json").read_text())
        schema = json.loads((folder / "schema.json").read_text())
        contract = json.loads((folder / "execution-contract.json").read_text())
        metadata = source["metadata"]
        wire = {"t": "intent", "name": "sit"} if command == "sit" else {
            "t": "intent", "name": "emote", "asset": command}
        legs, axes = ["FL", "FR", "RL", "RR"], ["h_Part002", "alpha_Part006", "theta_Part005"]
        if (manifest["command"] != command or metadata["configuration"]["command"] != command
            or schema["command"] != command or contract["command"] != command
            or manifest["wire"] != wire or contract["wire"] != wire
            or manifest["gait_id"] != contract["gait_id"]
            or manifest["source_sha256"] != entry["sha256"]["source.json"]
            or manifest["geometry_sha256"] != geometry_hash or manifest["sole_hulls_sha256"] != sole_hash
            or contract["policy_sha256"] != policy_hash):
            raise ValueError(f"{command}: command, source or geometry mismatch")
        for document in (metadata, schema, contract):
            if document["leg_order"] != legs or document["joint_order"] != axes:
                raise ValueError(f"{command}: incompatible joint order")
        if (metadata["angle_units"] != "radian" or metadata["position_units"] != "mm"
            or metadata["time_units"] != "second"
            or contract["source_units"] != {"angle": "radian", "position": "mm", "time": "second"}):
            raise ValueError(f"{command}: incompatible units")
        binds = {record["path"]: record["sha256"] for record in contract["source_files"]}
        for name in ("source.json", "manifest.json"):
            if binds.get(f'{entry["handoff"]}/{name}') != entry["sha256"][name]:
                raise ValueError(f"{command}: timing contract bound to a different source")
        duration, hz = manifest["duration_seconds"], manifest["source_sample_hz"]
        if (hz != 120 or metadata["configuration"]["sample_hz"] != hz or schema["sample_hz"] != hz
            or contract["source_sample_hz"] != hz or not math.isfinite(duration) or not 0 < duration <= 60
            or len(source["samples"]) != round(duration * hz) + 1
            or len(source["samples"]) != manifest["sample_count"]):
            raise ValueError(f"{command}: invalid sample count or timing")
        positions = []
        for i, sample in enumerate(source["samples"]):
            if not math.isfinite(sample["time_s"]) or abs(sample["time_s"] - i / hz) > 1e-8:
                raise ValueError(f"{command}: nonuniform or reordered samples")
            angles = sample["actuator_angles_rad"]
            if len(angles) != 4 or any(len(leg) != 3 for leg in angles):
                raise ValueError(f"{command}: every sample must supply all twelve joints")
            row = [math.degrees(value) * 100 for leg in angles for value in leg]
            if not all(math.isfinite(value) for value in row):
                raise ValueError(f"{command}: nonfinite angle")
            positions.append(row)
        # Newer handoffs distinguish the command's completion from an optional
        # playlist recovery. Only the command interval belongs in firmware.
        semantic = "semantic_end_seconds" in manifest
        command_end = manifest["semantic_end_seconds"] if semantic else duration
        if (not math.isfinite(command_end) or not 0 < command_end <= duration
            or abs(command_end * hz - round(command_end * hz)) > 1e-8):
            raise ValueError(f"{command}: invalid semantic completion time")
        terminal_knot = round(command_end * hz)
        final_key = "semantic_final_actuator_angles_rad" if semantic else "final_actuator_angles_rad"
        playlist_key = "playlist_final_actuator_angles_rad" if semantic else final_key
        if semantic and (command_end != contract["completion"]["semantic_end_s"]
                         or command_end != schema["semantic_end_s"]
                         or schema["optional_demonstration_recovery"] != (command_end < duration)
                         or contract["completion"]["optional_demo_recovery_end_s"] !=
                            (duration if command_end < duration else None)):
            raise ValueError(f"{command}: semantic completion contract mismatch")
        if (source["samples"][0]["actuator_angles_rad"] != contract["entry"]["joint_angles_rad"]
            or source["samples"][terminal_knot]["actuator_angles_rad"] != contract["completion"]["joint_angles_rad"]
            or source["samples"][terminal_knot]["actuator_angles_rad"] != manifest[final_key]
            or source["samples"][-1]["actuator_angles_rad"] != manifest[playlist_key]
            or any(abs(value) > 1e-6 for value in positions[0])):
            raise ValueError(f"{command}: recorded entry/final pose mismatch")
        phases, cursor = contract["phases"], 0.0
        demonstration = contract["timing_profiles"]["demonstration"]["duration_s"]
        if not phases or len({p["id"] for p in phases}) != len(phases) or set(demonstration) != {p["id"] for p in phases}:
            raise ValueError(f"{command}: invalid phase identifiers")
        for phase in phases:
            start, end = phase["source_interval_s"]
            if (not all(math.isfinite(v) for v in (start, end)) or abs(start-cursor) > 1e-8
                or not start < end <= duration or not math.isfinite(demonstration[phase["id"]])
                or abs(demonstration[phase["id"]] - (end-start)) > 1e-8):
                raise ValueError(f"{command}: demonstration phase timing mismatch")
            if semantic:
                role = "command" if end <= command_end else "optional_demonstration_recovery"
                if (start < command_end < end or phase["execution_role"] != role):
                    raise ValueError(f"{command}: phase crosses semantic completion or has incorrect execution role")
            cursor = end
        motion_end = manifest["source_validation"]["motion_end_s"] if semantic else manifest["motion_end_seconds"]
        if cursor != duration or not math.isfinite(motion_end) or not 0 < motion_end <= duration:
            raise ValueError(f"{command}: incomplete phase coverage")
        if (manifest["hardware_qualified"] is not False or contract["hardware_ready"] is not False
            or manifest["actuator_calibration"] is not None):
            raise ValueError("research source import cannot grant hardware readiness")
        gestures.append(dict(command=command, manifest=manifest, positions=positions[:terminal_knot+1],
                             duration_s=command_end, start_s=0, end_s=min(command_end, motion_end), phase='AINEKIO_V2_CLIP'))
    return gestures


def compile_clips(root: Path, out: Path) -> None:
    clips = load_turns(root) + load_gestures(root)
    if len(clips) > 62 or len({c['command'] for c in clips}) != len(clips):
        raise ValueError("duplicate command or body declaration limit exceeded")
    out.mkdir(parents=True, exist_ok=True)
    header = '''/* Generated from retained finite motion sources; do not edit. */
#ifndef AINEKIO_V2_CLIP_DATA_H
#define AINEKIO_V2_CLIP_DATA_H
#include "ainekio/v2_motion.h"
#define V2_CLIP_SAMPLE_HZ 120U
typedef struct {
    const float (*positions)[AINEKIO_V2_JOINT_COUNT];
    size_t count;
    uint64_t active_start_us, active_end_us;
    ainekio_v2_phase_t active_phase;
} ainekio_v2_clip_track_t;
extern const ainekio_v2_clip_track_t v2_clip_tracks[];
#endif
'''
    code = ['/* Generated by tools/compile_clips.py. Signed CAD centidegrees. */', '#include "clip_data.h"']
    for i, clip in enumerate(clips):
        code.append(f'static const float clip_{i}_positions[][AINEKIO_V2_JOINT_COUNT] = {{')
        code.extend('    {' + ','.join(f'{value:.9e}F' for value in row) + '},' for row in clip['positions'])
        code.append('};')
    code.append('const ainekio_v2_clip_t ainekio_v2_clips[] = {')
    for clip in clips:
        manifest = clip['manifest']
        intent = 'AINEKIO_INTENT_SIT' if manifest['wire']['name'] == 'sit' else 'AINEKIO_INTENT_EMOTE'
        code.append('    {' + ','.join((json.dumps(clip['command']), json.dumps(manifest['gait_id']), intent,
                    f'UINT64_C({round(clip["duration_s"] * 1e6)})', str(manifest.get('heading_change_degrees', 0)), 'false')) + '},')
    code.extend(['};', 'const size_t ainekio_v2_clip_count = sizeof(ainekio_v2_clips) / sizeof(ainekio_v2_clips[0]);',
                 'const ainekio_v2_clip_track_t v2_clip_tracks[] = {'])
    for i, clip in enumerate(clips):
        start, end, phase = clip['start_s'], clip['end_s'], clip['phase']
        code.append(f'    {{clip_{i}_positions, {len(clip["positions"])}U, UINT64_C({round(start * 1e6)}), UINT64_C({round(end * 1e6)}), {phase}}},')
    code.append('};')
    (out / 'clip_data.h').write_text(header)
    (out / 'clip_data.c').write_text('\n'.join(code) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    compile_clips(args.root, args.out)
