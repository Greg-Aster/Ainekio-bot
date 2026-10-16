"""Map offline native gait samples through a device's saved joint calibration.

Input calibration is a readback, not permission to move. No device connection or
settings write occurs. Pulse comparisons use the source profile's declared
window; the PCA timer's representable range is reported separately.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess

import numpy as np

from audit_gait import digest, measure, scenarios


def map_rows(rows, joints):
    # Native CLI emits CAD RL,RR,FL,FR. Firmware model IDs use FL,FR,RL,RR.
    q = np.asarray([r["q"] for r in rows]).reshape(-1, 4, 3)[:, [2, 3, 0, 1], :]
    # Match walk_kinematics.c's float frame boundary before the double mapper.
    centidegrees = (q.reshape(-1, 12) * float(np.float32(5729.577951308232))).astype(np.float32)
    pulses = np.zeros(centidegrees.shape)
    for j in joints:
        if j["channel"] < 0:
            continue
        sign = -1 if j["invert"] else 1
        pulses[:, j["id"]] = j["home_us"] + sign * (
            (centidegrees[:, j["id"]].astype(float) - j["home_cd"]) / 100
        ) * j["us_per_degree"]
    # C lround rounds halfway away from zero. Values outside representable timer
    # or uint16 ranges remain visible in this offline report, never clamped.
    return centidegrees, np.copysign(np.floor(np.abs(pulses) + .5), pulses)


def audit(root, binary, calibration_path, joint_speed, hz):
    data = json.loads(calibration_path.read_text())
    calibration = data.get("calibration", data)
    joints = sorted(calibration["joints"], key=lambda j: j["id"])
    if [j["id"] for j in joints] != list(range(12)):
        raise ValueError("Expected all twelve device joint records")
    cfg = json.loads((root / "geometry.json").read_text())
    profile = json.loads((root / "servo_profile.json").read_text())
    model = json.loads((root / "model.json").read_text())
    margins = json.loads((root / "motions/locomotion/config.json").read_text())["leverage_validation"]
    low, high = profile["pulse_range_us"]
    report = dict(
        schema="ainekio.calibrated-gait-audit.v1",
        generated_utc=datetime.now(timezone.utc).isoformat(),
        evidence="Live saved mapping applied to offline targets; shaft pose and travel are unmeasured.",
        hardware_qualified=False, geometry_id=cfg["geometry_id"],
        assumption="Installed servo angle zeros must match the model; readback alone does not prove horn indexing.",
        sample_hz=hz, joint_speed_limit_degrees_s=joint_speed,
        calibration_sha256=digest(calibration_path), binary_sha256=digest(binary),
        tool_sha256=digest(Path(__file__)),
        source_sha256={name: digest(root / name) for name in (
            "geometry.json", "model.json", "servo_profile.json", "motion.c",
            "walk_kinematics.c", "motions/locomotion/config.json", "motions/run/config.json")},
        declared_source_pulse_window_us=[low, high],
        window_scope="Source profile review window, not measured installed shaft travel or a runtime restriction.",
        timer_representable_pulse_window_us=[calibration.get("pulse_min_us"), calibration.get("pulse_max_us")],
        device_mapping=[{k: j[k] for k in ("id", "channel", "home_us", "home_cd", "invert", "us_per_degree")}
                        for j in joints], cases={})
    for name, params, updates in scenarios():
        initial = dict(t="intent", seq=1, name="walk", steps=0, **params)
        events = [(ms, dict(initial, **changes, update=1, seq=i + 2))
                  for i, (ms, changes) in enumerate(updates)]
        events.append((20000, dict(initial, speed=0, update=1, seq=len(events) + 2)))
        wire = json.dumps(initial) + "\n" + "".join(f"{ms} {json.dumps(c)}\n" for ms, c in events)
        run = subprocess.run([str(binary), "40000", str(hz), str(joint_speed)],
                             input=wire, capture_output=True, text=True)
        rows = [json.loads(line) for line in run.stdout.splitlines()]
        case = dict(initial=initial, updates=[dict(at_ms=ms, command=c) for ms, c in events],
                    sampler_returncode=run.returncode, sampler_error=run.stderr.strip())
        if rows:
            case.update(measure(rows, cfg, profile, margins))
            angles, pulses = map_rows(rows, joints)
            case["mapped_joints"] = []
            for j in joints:
                if j["channel"] < 0:
                    continue
                i = j["id"]
                first, last = int(pulses[:, i].argmin()), int(pulses[:, i].argmax())
                def witness(index):
                    return dict(ms=rows[index]["ms"], phase=rows[index]["phase"],
                                model_degrees=float(angles[index, i]) / 100,
                                pulse_us=int(pulses[index, i]))
                case["mapped_joints"].append(dict(
                    id=i, name=model["joints"][i]["name"], channel=j["channel"],
                    first_target_us=int(pulses[0, i]), minimum=witness(first), maximum=witness(last),
                    samples_below_source_window=int((pulses[:, i] < low).sum()),
                    samples_above_source_window=int((pulses[:, i] > high).sum())))
        report["cases"][name] = case
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary", type=Path)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--calibration", type=Path, required=True)
    parser.add_argument("--joint-speed", type=float, required=True, help="Read from the device; degrees/s")
    parser.add_argument("--hz", type=int, choices=[25, 50, 100, 120], default=50)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    report = audit(args.root.resolve(), args.binary.resolve(), args.calibration, args.joint_speed, args.hz)
    args.out.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(f"Wrote {len(report['cases'])} calibrated offline cases to {args.out}")
