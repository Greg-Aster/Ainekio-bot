"""Offline calibration-aware gesture authoring in a separate model copy.

Use --baseline for the retained sources, --root for the candidate copy and
--calibration for a locally saved joint readback. This changes source poses,
never firmware limits or saved servo calibration. Run native and interpolation
validation before adopting the resulting files. NumPy/SciPy are required.
"""
import argparse, json, copy, importlib.util, sys, hashlib
from pathlib import Path
import numpy as np
from scipy.optimize import least_squares

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--baseline", type=Path, required=True)
parser.add_argument("--root", type=Path, required=True)
parser.add_argument("--calibration", type=Path, required=True)
parser.add_argument("--commands", nargs="+", required=True)
parser.add_argument("--refresh-only", action="store_true")
args = parser.parse_args()
BASE = args.baseline.resolve()
ROOT = args.root.resolve()
spec = importlib.util.spec_from_file_location("ref", BASE / "motions/walk/reference.py")
ref = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ref)
legs = ["FL", "FR", "RL", "RR"]
cfg = json.loads((BASE / "geometry.json").read_text())
pivot = np.array(cfg["continuous_walk"]["body_rotation_pivot_mm"])
cal = json.loads(args.calibration.read_text())
js = cal.get("calibration", cal)["joints"]
bounds = np.empty((4, 3, 2))
for j in js:
    sign = -1 if j["invert"] else 1
    a = [
        np.radians(
            j["home_cd"] / 100 + (us - j["home_us"]) / (sign * j["us_per_degree"])
        )
        for us in (400, 2900)
    ]
    bounds[j["id"] // 3, j["id"] % 3] = sorted(a)


def author(command):
    precise = command in ("sit", "crouch", "point", "nod")
    continuous = command in ("worm", "shake")
    evaluations = 200 if precise else 100 if continuous else 50
    ftol = 1e-10 if precise else 1e-8 if continuous else 1e-7
    folder = BASE / "motions/gestures" / command
    out = ROOT / "motions/gestures" / command
    source = json.loads((folder / "source.json").read_text())
    old = copy.deepcopy(source["samples"])
    rows = source["samples"]
    m = ref.Mechanism(cfg)
    post = folder / "posture.json"
    hp = (
        folder / json.loads(post.read_text())["contact_hulls_file"]
        if post.exists()
        else BASE / "motions/gestures/sit/posture-hulls.npz"
    )
    with np.load(hp) as hulls:
        m.hulls = {l: hulls["sole_" + l].copy() for l in legs}
        bh = hulls["body"].copy()
    prev = None
    cache = {}
    maxerr = 0.0
    changed = 0
    for index, (row, original) in enumerate(zip(rows, old)):
        body = np.array(original["body_translation_world_mm"], float)
        e = np.array(original["body_rotation_euler_xyz_rad"], float)
        qold = np.array(original["actuator_angles_rad"])
        xy = np.array(original["foot_bolt_world_mm"])[:, :2]
        z = np.array(original["sole_clearance_mm"])
        target = np.array(original["foot_bolt_world_mm"])
        active = np.array(original["contact_active"], bool)
        if command in ("worm", "shake", "shrug"):
            z = np.maximum(z, 0.0)
        key = json.dumps(
            [
                np.round(body, 10 if precise else 5).tolist(),
                np.round(e, 10 if precise else 7).tolist(),
                np.round(qold, 10 if precise else 7).tolist(),
                active.tolist(),
            ]
        )
        if key in cache:
            b, ee, q = cache[key]
        elif np.all(qold >= bounds[:, :, 0]) and np.all(qold <= bounds[:, :, 1]):
            b = body
            ee = e
            q = qold
        else:
            m.body_euler = e
            rotations = (
                [m.pose(l, qold[i], body)[0] for i, l in enumerate(legs)]
                if command == "sit"
                else []
            )
            prior = qold if prev is None else np.array(prev["actuator_angles_rad"])

            def residual(v):
                b = body.copy()
                b[[0, 2]] += v[:2]
                ee = e + np.array([0.0, v[2], 0.0])
                m.body_euler = ee
                q = v[3:].reshape(4, 3)
                errors = []
                for i, l in enumerate(legs):
                    try:
                        R, T = m.pose(l, q[i], b)
                        pt = R @ np.array(cfg["legs"][l]["foot_reference_local_mm"]) + T
                        height = float((m.hulls[l] @ R[2] + T[2]).min())
                        errors.extend(
                            np.r_[pt[:2] - xy[i], height - z[i]] * 1000
                            if active[i]
                            else (pt - target[i])
                        )
                        errors.append(min(0.0, height) * 1000)
                        if command == "sit" and i < 2 and active[i]:
                            errors.extend((R[:, 0] - rotations[i][:, 0]) * 1000)
                    except ValueError:
                        errors.extend(
                            [1000 + v[3 + 3 * i] * 0.1]
                            * (7 if command == "sit" and i < 2 and active[i] else 4)
                        )
                B = ref.rz(ee[2]) @ ref.ry(ee[1]) @ ref.rx(ee[0])
                floor = ((bh - pivot) @ B.T + pivot)[:, 2].min() + b[2]
                return np.r_[
                    errors,
                    v[:2] * (0.02 if continuous else 0.002),
                    v[2] * (1.0 if continuous else 0.1),
                    (q - qold).ravel() * (0.05 if continuous else 0.01),
                    (q - prior).ravel() * (0.01 if continuous else 0.005),
                    min(0.0, floor) * 1000,
                ]

            pitch_bound = 0.5
            lo = np.r_[-100.0, -100.0, -pitch_bound, bounds[:, :, 0].ravel() + 1e-8]
            hi = np.r_[100.0, 100.0, pitch_bound, bounds[:, :, 1].ravel() - 1e-8]
            start = np.r_[
                0.0,
                0.0,
                0.0,
                np.clip(qold, bounds[:, :, 0] + 1e-6, bounds[:, :, 1] - 1e-6).ravel(),
            ]
            if prev is not None and not continuous:
                pb = np.array(prev["body_translation_world_mm"])
                pe = np.array(prev["body_rotation_euler_xyz_rad"])
                start = np.r_[
                    pb[[0, 2]] - body[[0, 2]],
                    pe[1] - e[1],
                    np.array(prev["actuator_angles_rad"]).ravel(),
                ]
            start = np.clip(start, lo + 1e-10, hi - 1e-10)
            fit = least_squares(
                residual,
                start,
                bounds=(lo, hi),
                max_nfev=evaluations,
                xtol=1e-10,
                ftol=ftol,
                gtol=1e-10,
                diff_step=1e-5,
            )
            b = body.copy()
            b[[0, 2]] += fit.x[:2]
            ee = e + np.array([0.0, fit.x[2], 0.0])
            q = fit.x[3:].reshape(4, 3)
            m.body_euler = ee
            err = 0.0
            for i, l in enumerate(legs):
                if active[i]:
                    err = max(
                        err,
                        float(abs(m.reference(l, q[i], b)[:2] - xy[i]).max()),
                        abs(float(m.vertices(l, q[i], b)[:, 2].min()) - z[i]),
                    )
            if err > 0.001:
                raise ValueError(
                    (command, index, original["time_s"], err, fit.fun[:16].tolist())
                )
            maxerr = max(maxerr, err)
            changed += 1
            cache[key] = (b, ee, q)
        row["body_translation_world_mm"] = b.tolist()
        row["body_rotation_euler_xyz_rad"] = ee.tolist()
        row["actuator_angles_rad"] = q.tolist()
        prev = row
        row["target_foot_reference_xy_mm"] = original.get(
            "target_foot_reference_xy_mm", xy.tolist()
        )
        row["target_sole_clearance_mm"] = original.get(
            "target_sole_clearance_mm", z.tolist()
        )
        if index % 30 == 0:
            print(
                command,
                original["time_s"],
                "changed",
                changed,
                "error",
                maxerr,
                flush=True,
            )
    q = np.array([x["actuator_angles_rad"] for x in rows])
    report = dict(
        changed_samples=changed,
        maximum_planted_fit_error_mm=maxerr,
        maximum_joint_step_degrees=float(np.degrees(abs(np.diff(q, axis=0))).max()),
        pulse_window_us=[400, 2900],
        baseline_source_sha256=hashlib.sha256(
            (folder / "source.json").read_bytes()
        ).hexdigest(),
        hardware_qualified=False,
    )
    source["metadata"]["calibrated_motion_revision"] = report
    (out / "source.json").write_text(json.dumps(source, separators=(",", ":")) + "\n")
    print("DONE", command, report, flush=True)


def author_wave():
    source = json.loads(((BASE / "motions/gestures") / "wave/source.json").read_text())
    old = copy.deepcopy(source["samples"])
    rows = source["samples"]
    sit = json.loads(((ROOT / "motions/gestures") / "sit/source.json").read_text())[
        "samples"
    ]
    old_sit = json.loads(((BASE / "motions/gestures") / "sit/source.json").read_text())[
        "samples"
    ]
    delta = np.array(sit[360]["actuator_angles_rad"]) - np.array(
        old_sit[360]["actuator_angles_rad"]
    )
    keys = [
        "body_translation_world_mm",
        "body_rotation_euler_xyz_rad",
        "actuator_angles_rad",
        "contact_active",
    ]
    for i, row in enumerate(rows):
        if i <= 360:
            for k in keys:
                row[k] = copy.deepcopy(sit[i][k])
        elif i >= 1464:
            for k in keys:
                row[k] = copy.deepcopy(sit[max(0, 1824 - i)][k])
        else:
            for k in keys[:3]:
                row[k] = copy.deepcopy(sit[360][k])
            row["actuator_angles_rad"][2] = (
                np.array(old[i]["actuator_angles_rad"][2]) + delta[2]
            ).tolist()
    source["metadata"]["calibrated_motion_revision"] = dict(
        method="Preserve exact reauthored Sit entry/exit and three supporting legs; translate the waving arm joint path by the seated pose correction.",
        baseline_source_sha256=hashlib.sha256(
            ((BASE / "motions/gestures") / "wave/source.json").read_bytes()
        ).hexdigest(),
        pulse_window_us=[400, 2900],
        hardware_qualified=False,
    )
    ((ROOT / "motions/gestures") / "wave/source.json").write_text(
        json.dumps(source, separators=(",", ":")) + "\n"
    )
    print("Wave retains exact new Sit prefix/reverse and supporting legs.")


def refresh(commands):
    from scipy.spatial.transform import Rotation

    sys.path.insert(0, str(ROOT / "tools"))
    from remap_reviewed_clips import refresh_metrics
    from retarget_clips import load_reference

    family = ROOT / "motions/gestures"
    read = lambda p: json.loads(p.read_text())
    write = lambda p, v: p.write_text(
        json.dumps(v, separators=(",", ":"), allow_nan=False) + "\n"
    )
    digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    for name in commands:
        folder = family / name
        source = read(folder / "source.json")
        rows = source["samples"]
        if name == "upright":
            rows[:361] = copy.deepcopy(
                read(family / "sit/source.json")["samples"][:361]
            )
        for row in rows:
            e = row["body_rotation_euler_xyz_rad"]
            q = Rotation.from_euler("xyz", e).as_quat()
            row["body_orientation_world_quaternion_wxyz"] = [q[3], *q[:3]]
            row.pop("body_yaw_rad", None)
            row["body_yaw_world_rad"] = e[2]
        write(folder / "source.json", source)
        refresh_metrics(ROOT, [name])
        source = read(folder / "source.json")
        rows = source["samples"]
        revision = source["metadata"]["calibrated_motion_revision"]
        source["metadata"]["generator"] = (
            "tools/author_supported_upright.py"
            if name == "upright"
            else "tools/author_calibrated_clips.py"
        )
        baseline = read(BASE / "motions/gestures" / name / "source.json")
        original = baseline["samples"]
        source["metadata"]["baseline_validation"] = baseline["validation"]
        q = np.array([r["actuator_angles_rad"] for r in rows])
        times = np.array([r["time_s"] for r in rows])
        cfg = read(ROOT / "geometry.json")
        m = load_reference(ROOT).Mechanism(cfg)
        minimum_input = 180.0
        air_error = 0.0
        for row, old in zip(rows, original):
            for i, angles in enumerate(row["actuator_angles_rad"]):
                D, P, E, beta, height = m.planar(angles)
                u = P - m.C
                rod = E - P
                area = abs(u[0] * rod[1] - u[1] * rod[0])
                minimum_input = min(
                    minimum_input,
                    float(np.degrees(np.arcsin(np.clip(area / (m.r * m.L), 0, 1)))),
                )
                if not row["contact_active"][i]:
                    air_error = max(
                        air_error,
                        float(
                            np.linalg.norm(
                                np.array(row["foot_bolt_world_mm"][i])
                                - old["foot_bolt_world_mm"][i]
                            )
                        ),
                    )
                    row["target_foot_reference_xy_mm"][i] = row["foot_bolt_world_mm"][
                        i
                    ][:2]
                    row["target_sole_clearance_mm"][i] = row["sole_clearance_mm"][i]
        revision["maximum_airborne_target_change_mm"] = air_error
        v = source["validation"]
        v = {
            k: v[k]
            for k in [
                "motion_end_s",
                "min_sole_z_mm",
                "min_body_z_mm",
                "minimum_closure_height_mm",
                "maximum_adjacent_joint_step_degrees",
                "maximum_planted_target_error_mm",
                "min_support_margin_after_sit_mm",
                "final_front_reach_mm",
            ]
            if k in v
        }
        v.update(
            command=name,
            geometry_id=cfg["geometry_id"],
            samples=len(rows),
            duration_s=times[-1],
            sample_hz=120,
            minimum_sole_height_mm=v["min_sole_z_mm"],
            minimum_body_ground_clearance_mm=v["min_body_z_mm"],
            minimum_closure_triangle_height_mm=v["minimum_closure_height_mm"],
            minimum_input_toggle_clearance_deg=minimum_input,
            minimum_support_margin_mm=min(
                r["support_margin_mm"]
                for r in rows
                if r["support_margin_mm"] is not None
            ),
            peak_joint_speed_deg_s=float(
                np.degrees(abs(np.gradient(q, times, axis=0))).max()
            ),
            joint_min_deg=np.degrees(q.min(0)).tolist(),
            joint_max_deg=np.degrees(q.max(0)).tolist(),
            maximum_body_translation_difference_mm=float(
                np.linalg.norm(
                    np.array([r["body_translation_world_mm"] for r in rows])
                    - np.array([r["body_translation_world_mm"] for r in original]),
                    axis=1,
                ).max()
            ),
            maximum_body_pitch_difference_deg=float(
                np.degrees(
                    abs(
                        np.array([r["body_rotation_euler_xyz_rad"] for r in rows])
                        - np.array([r["body_rotation_euler_xyz_rad"] for r in original])
                    )
                ).max()
            ),
            hardware_qualified=False,
            collision_checked=False,
            calibration_qualified=False,
            timing_preserved=True,
            contact_schedule_preserved=True,
        )
        source["validation"] = v
        write(folder / "validation.json", v)
        write(folder / "source.json", source)
        p = folder / "reviewed.json"
        if p.exists():
            v = read(p)
            for i, r in enumerate(v["samples"]):
                r["euler"] = rows[i * 4]["body_rotation_euler_xyz_rad"]
            v["calibrated_motion_revision"] = revision
            write(p, v)
        p = folder / "posture.json"
        if p.exists():
            v = read(p)
            v["calibrated_motion_revision"] = revision
            if name == "sit":
                v["terminal_solver_seed_rad"] = {
                    l: rows[360]["actuator_angles_rad"][i]
                    for i, l in enumerate(["FL", "FR"])
                }
                v["body_lift_mm"] = rows[360]["body_translation_world_mm"][2]
                baseline_posture = read(BASE / "motions/gestures/sit/posture.json")
                v["baseline_contact_fit"] = {
                    k: baseline_posture[k]
                    for k in [
                        "lower_leg_angle_above_floor_deg",
                        "contact_fit",
                        "geometry_remap_note",
                    ]
                    if k in baseline_posture
                }
                for key in v["baseline_contact_fit"]:
                    v.pop(key, None)
                v["rear_sole_orientation_preserved"] = True
                v[
                    "description"
                ] = "Stepped Sit with planted support positions preserved; body pitch and joints refitted to the installed calibration."
            if name == "crouch":
                v["body_z_mm"] = rows[-1]["body_translation_world_mm"][2]
            if name == "point":
                v["extended_joint_offsets_rad"] = rows[600]["actuator_angles_rad"][2]
                v["extension_waypoints_rad"] = [
                    rows[360]["actuator_angles_rad"][2],
                    rows[504]["actuator_angles_rad"][2],
                ]
            if name == "wave":
                v["lift_joint_offsets_deg"] = np.degrees(
                    rows[504]["actuator_angles_rad"][2]
                ).tolist()
                v["extended_joint_offsets_deg"] = np.degrees(
                    rows[696]["actuator_angles_rad"][2]
                ).tolist()
            if name == "upright":
                v["front_extended_angles_rad_by_leg"] = {
                    l: rows[-1]["actuator_angles_rad"][i]
                    for i, l in enumerate(["FL", "FR", "RL", "RR"])
                    if i >= 2
                }
                v["upright_pitch_deg"] = float(
                    np.degrees(rows[-1]["body_rotation_euler_xyz_rad"][1])
                )
                v["brace_pitch_deg"] = float(
                    np.degrees(rows[1440]["body_rotation_euler_xyz_rad"][1])
                )
                v["brace_shift_x_mm"] = (
                    rows[1440]["body_translation_world_mm"][0]
                    - rows[360]["body_translation_world_mm"][0]
                )
                v[
                    "description"
                ] = "Experimental stepped Sit, front-foot replacement, rearward support transfer and calibrated rear-leg rise."
                v[
                    "rear_support_policy"
                ] = "Preserve the planted rear foot reference XY and broad sole orientation through the rise. Provisional COM stays inside the modeled supporting soles; loaded balance is unqualified."
            if "base_motion" in v:
                b = v["base_motion"]
                b["source_sha256"] = digest(folder / b["source_file"])
                b["posture_sha256"] = digest(folder / b["posture_file"])
            write(p, v)
        manifest = read(folder / "manifest.json")
        manifest.update(
            source_sha256=digest(folder / "source.json"),
            source_validation=source["validation"],
            entry_actuator_angles_rad=rows[0]["actuator_angles_rad"],
            final_actuator_angles_rad=rows[-1]["actuator_angles_rad"],
        )
        if "semantic_end_seconds" in manifest:
            manifest["semantic_final_actuator_angles_rad"] = rows[
                round(manifest["semantic_end_seconds"] * 120)
            ]["actuator_angles_rad"]
            manifest["playlist_final_actuator_angles_rad"] = rows[-1][
                "actuator_angles_rad"
            ]
        if p.exists():
            manifest["posture_sha256"] = digest(p)
        if (folder / "reviewed.json").exists():
            manifest["reviewed_sha256"] = digest(folder / "reviewed.json")
        write(folder / "manifest.json", manifest)
        contract = read(folder / "execution-contract.json")
        contract["entry"]["joint_angles_rad"] = rows[0]["actuator_angles_rad"]
        terminal = round(
            manifest.get("semantic_end_seconds", manifest["duration_seconds"]) * 120
        )
        contract["completion"]["joint_angles_rad"] = rows[terminal][
            "actuator_angles_rad"
        ]
        for f in contract["source_files"]:
            p = folder / Path(f["path"]).name
            if p.exists():
                f["sha256"] = digest(p)
        write(folder / "execution-contract.json", contract)
    cat = read(family / "catalog.json")
    for item in cat["commands"]:
        if item["command"] not in commands:
            continue
        for name in item["sha256"]:
            p = family / item["command"] / name
            if p.exists():
                item["sha256"][name] = digest(p)
    write(family / "catalog.json", cat)


if not args.refresh_only:
    for command in args.commands:
        if command == "wave":
            author_wave()
        elif command == "upright":
            raise ValueError(
                "Use author_supported_upright.py for the revised supported rise"
            )
        else:
            author(command)
refresh(args.commands)
