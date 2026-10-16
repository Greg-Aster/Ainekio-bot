"""Measure native gait commands without changing their paths or regression floors.

Build v2_walk_command from --root first. Reports are offline target evidence,
not measured displacement, contact, torque, or installed calibration.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess

import numpy as np

from validate_locomotion import leverage_report
from retarget_clips import load_reference


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def scenarios():
    for gait in ("walk", "crawl", "run"):
        for direction in ("fwd", "back", "turn_l", "turn_r"):
            yield f"{gait}/{direction}", dict(gait=gait, dir=direction, speed=100), []
    for direction in ("fwd", "back", "side_l", "side_r", "turn_l", "turn_r"):
        yield f"crab/{direction}", dict(gait="crab", dir=direction, speed=100), []
    for direction in ("fwd", "back", "turn_l", "turn_r"):
        yield f"run/full/{direction}", dict(gait="run", dir=direction, speed=200), []
    yield "walk/curve", dict(gait="walk", dir="fwd", speed=100, forward=100, turn=50), []
    yield "walk/reverse_curve", dict(gait="walk", dir="fwd", speed=100, forward=-100, turn=-50), []
    yield "walk/steering_update", dict(gait="walk", dir="fwd", speed=100, forward=100, turn=0), [
        (6000, dict(forward=75, turn=75)), (12000, dict(forward=-75, turn=-75))]
    yield "walk/run_transition", dict(gait="walk", dir="fwd", speed=50), [
        (6000, dict(speed=200)), (12000, dict(speed=75))]


def measure(rows, cfg, profile, margins):
    q = np.asarray([row["q"] for row in rows]).reshape(-1, 4, 3)
    contact = np.asarray([row["grounded"] for row in rows], dtype=bool)
    times = np.asarray([row["ms"] for row in rows]) / 1000
    body = np.asarray([row["body"] for row in rows])
    feet = np.asarray([row["feet"] for row in rows])
    pulses = np.asarray(profile["pulse_reference_us"]) + (
        np.rad2deg(q) - np.asarray(profile["center_degrees"])) * profile["us_per_degree"]
    moving = np.asarray([row["phase"] >= 4 and row["ms"] < 20000 for row in rows])
    supports = contact.sum(axis=1)[moving]
    planted = contact[:-1] & contact[1:]
    drift = np.linalg.norm(np.diff(feet[:, :, :2], axis=0), axis=2)[planted]
    result = dict(
        samples=len(rows), sampled_seconds=float(times[-1]),
        finish_completed=rows[-1]["complete"], final_contacts=rows[-1]["grounded"],
        target_body_translation_delta_mm=(body[-1] - body[0]).tolist(),
        target_yaw_change_degrees=float(np.rad2deg(rows[-1]["euler"][2] - rows[0]["euler"][2])),
        body_translation_z_range_mm=[float(body[:, 2].min()), float(body[:, 2].max())],
        support_sample_window="phase >= 4, time < 20 s; target contact schedule, not sensed contact",
        support_sample_counts={str(n): int((supports == n).sum()) for n in range(5)},
        maximum_planted_target_xy_step_mm=float(drift.max()) if drift.size else None,
        reference_unmirrored_pulse_span_us=[float(pulses.min()), float(pulses.max())],
        reference_pulse_scope="Shared source mounting references only; installed signs, offsets and limits were not read.",
        minimum_clock_scale=float(min(row["clock_scale"] for row in rows)),
        peak_sampled_joint_speed_degrees_s=float((np.rad2deg(abs(np.diff(q, axis=0))) /
            np.diff(times)[:, None, None]).max()) if len(rows) > 1 else None,
    )
    # Measure with zero floors, then explicitly compare to the unchanged source
    # requirements. Impossible closure/branch crossings still produce an error.
    try:
        measured = leverage_report(cfg, q, contact, dict.fromkeys(margins, 0.))
        result["leverage"] = measured
        below = {}
        for key, required in margins.items():
            if key == "scope":
                continue
            actual = measured.get("minimum_straightening_clearance_mm" if key == "straightening_clearance_min_mm" else key)
            if actual is not None and actual < required:
                below[key] = dict(measured=actual, required=required)
        result["below_source_regression_margins"] = below
    except ValueError as error:
        result["linkage_error"] = str(error)
    return result


def evaluate_geometry(rows, root, gait):
    """Replay commanded joints on another linkage at the commanded chassis pose."""
    cfg = json.loads((root / "geometry.json").read_text())
    model = load_reference(root).Mechanism(cfg)
    bare = json.loads((root/'motions/locomotion/walk-contact.json').read_text())['sole_hull_local_mm']
    model.hulls = {leg: np.asarray(bare) for leg in cfg['leg_order']}
    errors, stance_heights, failures = [], [], 0
    for row in rows:
        model.body_euler = np.asarray(row["euler"])
        for leg, q, target, grounded in zip(cfg["leg_order"], np.asarray(row["q"]).reshape(4, 3), row["feet"], row["grounded"]):
            try:
                point = model.reference(leg, q, row["body"])
                height = float(model.vertices(leg, q, row["body"])[:, 2].min())
            except ValueError:
                failures += 1
                continue
            errors.append(float(np.linalg.norm(point[:2] - np.asarray(target[:2]))))
            if grounded:
                stance_heights.append(height)
    return dict(geometry_id=cfg["geometry_id"], geometry_sha256=digest(root / "geometry.json"),
        assumptions="Same motor angle zeros and commanded chassis pose; no physical tracking or calibration measurement.",
        unclosed_leg_samples=failures,
        maximum_foot_xy_target_error_mm=max(errors) if errors else None,
        declared_stance_full_sole_z_range_mm=[min(stance_heights), max(stance_heights)] if stance_heights else None)


def audit(root, binary, hz, evaluate_root=None):
    cfg = json.loads((root / "geometry.json").read_text())
    profile = json.loads((root / "servo_profile.json").read_text())
    margins = json.loads((root / "motions/locomotion/config.json").read_text())["leverage_validation"]
    report = dict(schema="ainekio.gait-research.v1", generated_utc=datetime.now(timezone.utc).isoformat(),
        geometry_id=cfg["geometry_id"], hardware_qualified=False, sample_hz=hz,
        evidence="Native command target sampling; no physical robot commands or measurements.",
        generator_sha256=digest(Path(__file__)),
        binary_sha256=digest(binary),
        source_sha256={name: digest(root / name) for name in (
            "geometry.json", "servo_profile.json", "motion.c", "walk_kinematics.c",
            "motions/locomotion/config.json", "motions/locomotion/crab.json", "motions/locomotion/walk-contact.json", "motions/locomotion/sole-profile.json", "motions/run/config.json")},
        source_regression_margins=margins, cases={})
    for name, params, updates in scenarios():
        initial = dict(t="intent", seq=1, name="walk", steps=0, **params)
        events = [(ms, dict(initial, **changes, update=1, seq=i + 2))
                  for i, (ms, changes) in enumerate(updates)]
        finish = dict(initial, speed=0, update=1, seq=len(events) + 2)
        events.append((20000, finish))
        wire = json.dumps(initial) + "\n" + "".join(f"{ms} {json.dumps(command)}\n" for ms, command in events)
        run = subprocess.run([str(binary), "40000", str(hz)], input=wire, text=True, capture_output=True, check=False)
        rows = [json.loads(line) for line in run.stdout.splitlines()]
        case = dict(initial=initial, updates=[dict(at_ms=ms, command=c) for ms, c in events],
                    sampler_returncode=run.returncode, sampler_error=run.stderr.strip())
        if rows:
            case.update(measure(rows, cfg, profile, margins))
            if evaluate_root:
                case["alternate_geometry"] = evaluate_geometry(rows, evaluate_root, params["gait"])
        report["cases"][name] = case
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary", type=Path)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--hz", type=int, choices=(25, 50, 100, 120), default=50)
    parser.add_argument("--evaluate-root", type=Path, help="Also replay the native joint commands on this alternate linkage")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    report = audit(args.root.resolve(), args.binary.resolve(), args.hz, args.evaluate_root)
    args.out.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(f"Wrote {len(report['cases'])} offline cases to {args.out}")
