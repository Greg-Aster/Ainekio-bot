"""Compile the retained geometric source into the P4's local timed trajectory.

Standard Python only. No Blender, IK, networking or servo defaults at build time.
The closing loop row is a boundary knot, never an additional timed interval.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path


def harmonic(a: float, b: float) -> float:
    return 2 * a * b / (a + b) if a * b > 0 else 0.0


def load_motion(root: Path) -> tuple[dict, dict, dict, dict]:
    manifest = json.loads((root / "motions/walk/manifest.json").read_text())
    source_path = root / "motions/walk/source.json"
    if hashlib.sha256(source_path.read_bytes()).hexdigest() != manifest["source_sha256"]:
        raise ValueError("walk source changed without updating its provenance")
    if hashlib.sha256((root / "geometry.json").read_bytes()).hexdigest() != manifest["geometry_sha256"]:
        raise ValueError("walk geometry does not match its manifest")
    source = json.loads(source_path.read_text())
    model = json.loads((root / "model.json").read_text())
    contract = json.loads((root / "motions/walk/loop-contract.json").read_text())
    expected_legs = ["FL", "FR", "RL", "RR"]
    expected_axes = ["h_Part002", "alpha_Part006", "theta_Part005"]
    if (model["model"] != "v2-12servo" or len(model["joints"]) != 12
        or source["metadata"]["leg_order"] != expected_legs
        or source["metadata"]["joint_order"] != expected_axes
        or source["metadata"]["angle_units"] != "radian"
        or source["metadata"]["position_units"] != "mm"
        or source["metadata"]["time_units"] != "second"):
        raise ValueError("incompatible model, joint order or units")
    for i, joint in enumerate(model["joints"]):
        if joint["id"] != i or joint["cad_leg"] != expected_legs[i // 3] or joint["actuator"] != expected_axes[i % 3]:
            raise ValueError("joint definition disagrees with the source order")
    hz = manifest["source_sample_hz"]
    if hz != 120 or contract["intervals_per_cycle"] != 480 or contract["period_seconds"] != 4:
        raise ValueError("unexpected loop timing")
    if contract["angle_offset_per_cycle_rad"] != 0 or contract["closing_endpoint_row"] != 480:
        raise ValueError("unsupported repetition contract")
    positions = []
    for i, sample in enumerate(source["samples"]):
        if abs(sample["time_s"] - i / hz) > 1e-8:
            raise ValueError("nonuniform or reordered source samples")
        angles = sample["actuator_angles_rad"]
        if len(angles) != 4 or any(len(leg) != 3 for leg in angles):
            raise ValueError("walk must supply every joint in every sample")
        row = [math.degrees(v) * 100 for leg in angles for v in leg]
        if not all(math.isfinite(v) for v in row):
            raise ValueError("nonfinite actuator angle")
        positions.append(row)
    slopes = [[(b-a)*hz for a,b in zip(left,right)] for left,right in zip(positions, positions[1:])]
    velocities = [[0.0]*12] + [[harmonic(a,b) for a,b in zip(left,right)]
                              for left,right in zip(slopes,slopes[1:])] + [[0.0]*12]
    sections = {}
    for name in ("entry", "loop", "exit"):
        start, end = manifest[f"{name}_source_seconds"]
        lo, hi = round(start*hz), round(end*hz)
        if lo < 0 or hi <= lo or hi >= len(positions) or abs(lo/hz-start) > 1e-8 or abs(hi/hz-end) > 1e-8:
            raise ValueError("invalid section boundaries")
        sections[name] = {"positions": [p[:] for p in positions[lo:hi+1]],
                          "velocities": [v[:] for v in velocities[lo:hi+1]],
                          "duration_us": round((end-start)*1e6)}
    loop = sections["loop"]
    if len(loop["positions"]) != 481:
        raise ValueError("loop must contain 480 intervals plus its closing knot")
    seam = loop["positions"][0]
    for boundary in (loop["positions"][-1], sections["entry"]["positions"][-1], sections["exit"]["positions"][0]):
        if max(abs(a-b) for a,b in zip(seam,boundary)) > 1e-6:
            raise ValueError("entry, loop and exit are not phase matched")
    tangents = [harmonic((b-a)*hz, (d-c)*hz) for a,b,c,d in zip(
        loop["positions"][0], loop["positions"][1], loop["positions"][-2], loop["positions"][-1])]
    # Snap only the source's floating-point closure residue (below 1e-8 deg).
    # Common seam tangents implement the exported loop's C1 contract.
    for section, index in ((loop,0), (loop,-1), (sections["entry"],-1), (sections["exit"],0)):
        section["positions"][index] = seam[:]
        section["velocities"][index] = tangents[:]
    return model, manifest, sections, source


def compile_walk(root: Path, out: Path) -> None:
    model, manifest, sections, _ = load_motion(root)
    out.mkdir(parents=True, exist_ok=True)
    header = ['/* Generated from the versioned V2 walk source; do not edit. */',
              '#ifndef AINEKIO_V2_WALK_DATA_H', '#define AINEKIO_V2_WALK_DATA_H',
              '#include "ainekio/v2_motion.h"', '#define V2_SAMPLE_HZ 120U']
    code = ['/* Generated by tools/compile_walk.py. Positions: CAD centidegrees. */', '#include "walk_data.h"',
            f'const char ainekio_v2_walk_id[] = {json.dumps(manifest["gait_id"])};',
            f'const bool ainekio_v2_walk_hardware_qualified = {str(manifest["hardware_qualified"]).lower()};',
            'const ainekio_v2_joint_t ainekio_v2_joints[AINEKIO_V2_JOINT_COUNT] = {']
    for joint in model["joints"]:
        code.append('    {' + ', '.join(json.dumps(joint[k]) for k in ("name", "cad_leg", "actuator", "positive_body_axis")) + '},')
    code.append('};')
    def floats(row: list[float]) -> str:
        return '{' + ','.join(f'{value:.9e}F' for value in row) + '}'
    for name, section in sections.items():
        count = len(section["positions"])
        header.extend([f'#define V2_{name.upper()}_COUNT {count}U',
                       f'#define V2_{name.upper()}_US UINT64_C({section["duration_us"]})',
                       f'extern const ainekio_v2_knot_t v2_walk_{name}[V2_{name.upper()}_COUNT];'])
        code.append(f'const ainekio_v2_knot_t v2_walk_{name}[V2_{name.upper()}_COUNT] = {{')
        code.extend('    {' + floats(p) + ',' + floats(v) + '},' for p,v in zip(section["positions"],section["velocities"]))
        code.append('};')
    header.append('#endif')
    (out / 'walk_data.h').write_text('\n'.join(header)+'\n')
    (out / 'walk_data.c').write_text('\n'.join(code)+'\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    compile_walk(args.root, args.out)
