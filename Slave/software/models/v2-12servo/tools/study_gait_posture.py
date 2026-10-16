"""Compare body-height candidates using the native command path in a temporary copy.

This is offline kinematic evaluation, not learned feedback or physical walking.
Source models, installed calibration and robot firmware are never modified.
Requires the same NumPy/SciPy environment as audit_gait.py and a C toolchain.
"""
import argparse
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from audit_gait import digest, measure, scenarios


def command(args):
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)


def study(source, heights, names, hz):
    geometry = json.loads((source / "geometry.json").read_text())
    profile = json.loads((source / "servo_profile.json").read_text())
    baseline = json.loads((source / "motions/locomotion/config.json").read_text())
    report = dict(
        schema="ainekio.posture-study.v1",
        generated_utc=datetime.now(timezone.utc).isoformat(),
        evidence="Offline native commanded trajectories; no measured motion, torque or training.",
        hardware_qualified=False, geometry_id=geometry["geometry_id"], sample_hz=hz,
        source_sha256={name: digest(source / name) for name in (
            "geometry.json", "servo_profile.json", "motion.c", "walk_kinematics.c",
            "motions/locomotion/config.json", "motions/locomotion/sole-profile.json")},
        source_regression_margins=baseline["leverage_validation"], candidates=[])
    with tempfile.TemporaryDirectory(prefix="ainekio-posture-") as temporary:
        software = Path(temporary) / "software"
        root = software / "models/v2-12servo"
        shutil.copytree(source, root, ignore=shutil.ignore_patterns("__pycache__", ".git", "build"))
        shutil.copytree(source.parent.parent / "core", software / "core")
        build = Path(temporary) / "native"
        command(["cmake", "-S", str(root), "-B", str(build),
                 "-DCMAKE_BUILD_TYPE=Release", f"-DPython3_EXECUTABLE={sys.executable}"])
        for height in heights:
            config = copy.deepcopy(baseline)
            config["walk"]["body_z_mm"] = height
            path = root / "motions/locomotion/config.json"
            path.write_text(json.dumps(config, indent=2) + "\n")
            path = root / "motions/walk/manifest.json"
            manifest = json.loads(path.read_text())
            manifest["sha256"]["../locomotion/config.json"] = digest(root / "motions/locomotion/config.json")
            path.write_text(json.dumps(manifest, indent=2) + "\n")
            command(["cmake", "--build", str(build), "--target", "v2_walk_command", "-j4"])
            binary = build / "v2_walk_command"
            candidate = dict(body_z_mm=height, binary_sha256=digest(binary),
                             config_sha256=digest(root / "motions/locomotion/config.json"), cases={})
            for name, params, updates in scenarios():
                if name not in names:
                    continue
                initial = dict(t="intent", seq=1, name="walk", steps=0, **params)
                events = [(ms, dict(initial, **changes, update=1, seq=i + 2))
                          for i, (ms, changes) in enumerate(updates)]
                events.append((20000, dict(initial, speed=0, update=1, seq=len(events) + 2)))
                wire = json.dumps(initial) + "\n" + "".join(
                    f"{ms} {json.dumps(c)}\n" for ms, c in events)
                run = subprocess.run([str(binary), "40000", str(hz)],
                                     input=wire, text=True, capture_output=True)
                rows = [json.loads(line) for line in run.stdout.splitlines()]
                result = measure(rows, geometry, profile, baseline["leverage_validation"]) if rows else {}
                result.update(sampler_returncode=run.returncode, sampler_error=run.stderr.strip(),
                              initial=initial, updates=[dict(at_ms=ms, command=c) for ms, c in events])
                candidate["cases"][name] = result
            report["candidates"].append(candidate)
            print(f"body_z={height:g} mm: {len(candidate['cases'])} cases evaluated", flush=True)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True, help="Complete candidate model; needs sibling ../../core")
    parser.add_argument("--heights", type=float, nargs="+", default=[-12, -10, -8, -6, -4, -2, 0, 2])
    parser.add_argument("--case", action="append", choices=[name for name, _, _ in scenarios()])
    parser.add_argument("--hz", type=int, choices=[25, 50, 100, 120], default=50)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    names = args.case or ["walk/fwd", "walk/reverse_curve", "walk/steering_update"]
    result = study(args.root.resolve(), args.heights, names, args.hz)
    result["study_sha256"] = digest(Path(__file__))
    args.out.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
