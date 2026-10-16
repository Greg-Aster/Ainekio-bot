"""Author the approved 60-degree rear-leg Upright rise offline.

The candidate model supplies calibrated_transfer_seeds in Upright's posture.json.
The baseline supplies the retained Sit/foot-placement choreography. Keep these
copies separate. --work holds intermediate contact fits; --stage allows resuming
that authoring work. Validate source interpolation, compiled pulse bounds and
native body execution before adopting generated assets. No hardware is driven.
"""
import argparse, json, copy, sys, hashlib, subprocess
from pathlib import Path
import numpy as np
from scipy.optimize import least_squares

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--baseline", type=Path, required=True)
parser.add_argument("--root", type=Path, required=True)
parser.add_argument("--calibration", type=Path, required=True)
parser.add_argument("--work", type=Path, required=True)
parser.add_argument("--stage", choices=["fit", "retime", "rise", "all"], default="all")
args = parser.parse_args()
BASE = args.baseline.resolve()
ROOT = args.root.resolve()
work = args.work.resolve()
work.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(BASE / "tools"))
from retarget_clips import load_reference

ref = load_reference(BASE)
cfg = json.loads((BASE / "geometry.json").read_text())
m = ref.Mechanism(cfg)
legs = ["FL", "FR", "RL", "RR"]
hs = np.load(BASE / "motions/gestures/sit/posture-hulls.npz")
m.hulls = {l: hs["sole_" + l] for l in legs}
bh = hs["body"]
pivot = np.array(cfg["continuous_walk"]["body_rotation_pivot_mm"])
source = json.loads((BASE / "motions/gestures/upright/source.json").read_text())
old = source["samples"]
rows = copy.deepcopy(old)
sit = json.loads((ROOT / "motions/gestures/sit/source.json").read_text())["samples"]
rows[:361] = copy.deepcopy(sit[:361])
keys = {360: rows[360]}
cal = json.loads(args.calibration.read_text())
js = cal.get("calibration", cal)["joints"]
bounds = np.empty((4, 3, 2))
for j in js:
    sign = -1 if j["invert"] else 1
    bounds[j["id"] // 3, j["id"] % 3] = sorted(
        np.radians(
            j["home_cd"] / 100
            + (np.array([400, 2900]) - j["home_us"]) / (sign * j["us_per_degree"])
        )
    )
for seed in json.loads((ROOT / "motions/gestures/upright/posture.json").read_text())[
    "calibrated_transfer_seeds"
]:
    index = seed["sample_index"]
    row = copy.deepcopy(old[index])
    row.update({k: v for k, v in seed.items() if k != "sample_index"})
    keys[index] = row
keys[720] = keys[600]
knots = sorted(keys)
m.body_euler = np.array(rows[360]["body_rotation_euler_xyz_rad"])
rearR = [
    m.pose(
        l, rows[360]["actuator_angles_rad"][i], rows[360]["body_translation_world_mm"]
    )[0]
    for i, l in enumerate(legs[:2])
]
previous = rows[360]


def fit_prefix():
    previous = rows[360]
    for n in range(361, 1441):
        row = rows[n]
        t = n / 120
        start = max(x for x in knots if x < n)
        end = min(x for x in knots if x >= n)
        u = ref.smooth((n - start) / (end - start))
        left, right = keys[start], keys[end]
        body = (1 - u) * np.array(left["body_translation_world_mm"]) + u * np.array(
            right["body_translation_world_mm"]
        )
        e = (1 - u) * np.array(left["body_rotation_euler_xyz_rad"]) + u * np.array(
            right["body_rotation_euler_xyz_rad"]
        )
        qtarget = (1 - u) * np.array(left["actuator_angles_rad"]) + u * np.array(
            right["actuator_angles_rad"]
        )
        active = row["contact_active"]
        xy = np.array(old[n]["foot_bolt_world_mm"])[:, :2]
        air_z = 8 * ref.bump((n - start) / (end - start))
        prior = np.array(previous["actuator_angles_rad"])

        def residual(v):
            b = body.copy()
            b[[0, 2]] += v[:2]
            ee = e + np.array([0, v[2], 0])
            m.body_euler = ee
            q = v[3:].reshape(4, 3)
            errors = []
            support = []
            for i, l in enumerate(legs):
                try:
                    R, T = m.pose(l, q[i], b)
                    p = R @ np.array(cfg["legs"][l]["foot_reference_local_mm"]) + T
                    vs = m.hulls[l] @ R.T + T
                    height = vs[:, 2].min()
                    errors.extend(
                        np.r_[p[:2] - xy[i], height] * 1000
                        if active[i]
                        else np.r_[(p[:2] - xy[i]), (height - air_z) * 1000]
                    )
                    errors.append(min(0, height) * 1000)
                    if i < 2:
                        errors.extend((R[:, 0] - rearR[i][:, 0]) * 1000)
                    if active[i]:
                        support.extend(vs[vs[:, 2] < height + 0.5])
                except ValueError:
                    a = m.a0 + q[i, 1]
                    theta = m.t0 + q[i, 2]
                    D = m.O + m.A * np.array([np.cos(a), np.sin(a)])
                    P = m.C + m.r * np.array([np.cos(theta), np.sin(theta)])
                    d = np.linalg.norm(P - D)
                    gap = max(abs(m.L - m.b) + 1e-4 - d, d - (m.L + m.b - 1e-4), 0)
                    errors.extend([1000 + gap * 1000] * (7 if i < 2 else 4))
            B = ref.ry(ee[1])
            floor = ((bh - pivot) @ B[2] + pivot[2]).min() + b[2]
            try:
                margin = ref.margin((b + pivot)[:2], support)
            except Exception:
                margin = -1000
            return np.r_[
                errors,
                v[:2] * 0.1,
                v[2] * 5,
                (q - qtarget).ravel() * 0.3,
                (q - prior).ravel() * 0.05,
                min(0, floor) * 1000,
                min(0, margin - 0.1) * 1000,
            ]

        lo = np.r_[-50, -50, -0.5, bounds[:, :, 0].ravel() + 1e-7]
        hi = np.r_[50, 50, 0.5, bounds[:, :, 1].ravel() - 1e-7]
        pb = np.array(previous["body_translation_world_mm"])
        pe = np.array(previous["body_rotation_euler_xyz_rad"])
        seed = np.r_[pb[[0, 2]] - body[[0, 2]], pe[1] - e[1], prior.ravel()]
        seed = np.clip(seed, lo + 1e-9, hi - 1e-9)
        fit = least_squares(
            residual,
            seed,
            bounds=(lo, hi),
            max_nfev=80,
            xtol=1e-10,
            ftol=1e-8,
            gtol=1e-10,
            diff_step=1e-5,
        )
        b = body.copy()
        b[[0, 2]] += fit.x[:2]
        ee = e + np.array([0, fit.x[2], 0])
        q = fit.x[3:].reshape(4, 3)
        m.body_euler = ee
        err = max(
            max(
                abs(m.reference(l, q[i], b)[:2] - xy[i]).max(),
                abs(m.vertices(l, q[i], b)[:, 2].min()),
            )
            for i, l in enumerate(legs)
            if active[i]
        )
        if err > 0.001:
            raise ValueError((t, err, fit.fun[:22]))
        row.update(
            body_translation_world_mm=b.tolist(),
            body_rotation_euler_xyz_rad=ee.tolist(),
            actuator_angles_rad=q.tolist(),
        )
        previous = row
        if n % 120 == 0:
            (work / "supported-upright-prefix.json").write_text(
                json.dumps(rows[: n + 1])
            )
            print(t, "ground", err, "body", b, "pitch", np.degrees(ee[1]), flush=True)
    rows[1440] = copy.deepcopy(keys[1440])
    (work / "supported-upright-prefix.json").write_text(json.dumps(rows[:1441]))
    print("PREFIX DONE", flush=True)


def retime_prefix():
    path = json.loads((work / "supported-upright-prefix.json").read_text())
    rows = copy.deepcopy(path)
    for first, last in [(360, 600), (600, 720), (720, 960), (960, 1440)]:
        segment = path[first : last + 1]
        qa = np.array([r["actuator_angles_rad"] for r in segment])
        ba = np.array([r["body_translation_world_mm"] for r in segment])
        ea = np.array([r["body_rotation_euler_xyz_rad"] for r in segment])
        arc = np.r_[0, np.cumsum(np.max(abs(np.diff(qa, axis=0)), axis=(1, 2)))]
        for n in range(first + 1, last):
            distance = ref.smooth((n - first) / (last - first)) * arc[-1]
            i = min(
                int(np.searchsorted(arc, distance, side="right")) - 1, len(segment) - 2
            )
            i = max(0, i)
            u = (distance - arc[i]) / max(arc[i + 1] - arc[i], 1e-20)
            b = (1 - u) * ba[i] + u * ba[i + 1]
            e = (1 - u) * ea[i] + u * ea[i + 1]
            target = (1 - u) * qa[i] + u * qa[i + 1]
            row = rows[n]
            active = row["contact_active"]
            xy = np.array(old[n]["foot_bolt_world_mm"])[:, :2]

            def residual(v):
                body = b.copy()
                body[[0, 2]] += v[:2]
                ee = e + np.array([0, v[2], 0])
                m.body_euler = ee
                q = v[3:].reshape(4, 3)
                err = []
                support = []
                for j, l in enumerate(legs):
                    R, T = m.pose(l, q[j], body)
                    p = R @ np.array(cfg["legs"][l]["foot_reference_local_mm"]) + T
                    vs = m.hulls[l] @ R.T + T
                    z = vs[:, 2].min()
                    err.extend(
                        np.r_[p[:2] - xy[j], z] * 1000
                        if active[j]
                        else (q[j] - target[j]) * 10
                    )
                    err.append(min(0, z) * 1000)
                    if j < 2:
                        err.extend((R[:, 0] - rearR[j][:, 0]) * 1000)
                    if active[j]:
                        support.extend(vs[vs[:, 2] < z + 0.5])
                floor = ((bh - pivot) @ ref.ry(ee[1])[2] + pivot[2]).min() + body[2]
                margin = ref.margin((body + pivot)[:2], support)
                return np.r_[
                    err,
                    v[:2] * 0.1,
                    v[2] * 5,
                    (q - target).ravel(),
                    min(0, floor) * 1000,
                    min(0, margin - 0.1) * 1000,
                ]

            lo = np.r_[-20, -20, -0.3, bounds[:, :, 0].ravel() + 1e-8]
            hi = np.r_[20, 20, 0.3, bounds[:, :, 1].ravel() - 1e-8]
            seed = np.r_[0, 0, 0, target.ravel()]
            seed = np.clip(seed, lo + 1e-10, hi - 1e-10)
            fit = least_squares(
                residual,
                seed,
                bounds=(lo, hi),
                max_nfev=50,
                xtol=1e-10,
                ftol=1e-8,
                gtol=1e-10,
                diff_step=1e-5,
            )
            b[[0, 2]] += fit.x[:2]
            e[1] += fit.x[2]
            q = fit.x[3:].reshape(4, 3)
            m.body_euler = e
            error = max(
                max(
                    abs(m.reference(l, q[j], b)[:2] - xy[j]).max(),
                    abs(m.vertices(l, q[j], b)[:, 2].min()),
                )
                for j, l in enumerate(legs)
                if active[j]
            )
            if error > 0.001:
                raise ValueError((n, error))
            row.update(
                body_translation_world_mm=b.tolist(),
                body_rotation_euler_xyz_rad=e.tolist(),
                actuator_angles_rad=q.tolist(),
            )
        print("retimed", first / 120, last / 120, flush=True)
    (work / "upright-retimed-prefix.json").write_text(json.dumps(rows))
    print(
        "max step",
        np.degrees(
            abs(np.diff(np.array([r["actuator_angles_rad"] for r in rows]), axis=0))
        ).max(),
        flush=True,
    )


def finish_rise():
    from scipy.optimize import brentq

    prefix = json.loads((work / "upright-retimed-prefix.json").read_text())
    rows[:1441] = copy.deepcopy(prefix)
    start = rows[1440]
    body0 = np.array(start["body_translation_world_mm"])
    p0 = start["body_rotation_euler_xyz_rad"][1]
    q0 = np.array(start["actuator_angles_rad"])
    delta = m.planar(q0[0])[3] - p0
    anchors = np.array(old[360]["foot_bolt_world_mm"])[:2, :2]
    geom = cfg["legs"]["FL"]
    S = np.array(geom["shoulder_world"])
    M = np.array(geom["mechanism_local"])
    hull = m.hulls["FL"]
    point = np.array(geom["foot_reference_local_mm"])
    aa = np.arange(bounds[0, 1, 0] + 1e-6, bounds[0, 1, 1] - 1e-6, np.radians(0.02))
    Dall = m.O + m.A * np.c_[np.cos(m.a0 + aa), np.sin(m.a0 + aa)]
    maxstep = 0
    for n in range(1441, 2401):
        t = n / 120
        u = ref.smooth((t - 12) / 8)
        pitch = p0 + (-np.pi / 3 - p0) * u
        beta = pitch + delta
        desiredx = body0[0] + (-65 - body0[0]) * u
        E = Dall + m.b * np.array([np.cos(beta), np.sin(beta)])
        w = E - m.C
        d = np.linalg.norm(w, axis=1)
        co = (m.r * m.r + d * d - m.L * m.L) / (2 * m.r * d)
        theta = np.arctan2(w[:, 1], w[:, 0]) - np.arccos(np.clip(co, -1, 1)) - m.t0
        theta = (theta + np.pi) % (2 * np.pi) - np.pi
        P = m.C + m.r * np.c_[np.cos(m.t0 + theta), np.sin(m.t0 + theta)]
        arm = P - Dall
        cross = arm[:, 0] * (E - Dall)[:, 1] - arm[:, 1] * (E - Dall)[:, 0]
        valid = (
            (abs(co) < 1)
            & (theta > bounds[0, 2, 0])
            & (theta < bounds[0, 2, 1])
            & (cross * m.p["assembly_branch"] > 0)
        )
        B = ref.ry(pitch)
        base = B @ S[:3, :3] @ M[:3, :3]
        R = base @ ref.ry(m.b0 - beta)
        T = (
            pivot
            + B @ (S[:3, 3] + S[:3, :3] @ M[:3, 3] - pivot)
            + np.c_[Dall[:, 0], np.zeros(len(aa)), Dall[:, 1]] @ base.T
        )
        height = (hull @ R[2]).min()
        near = hull[hull @ R[2] < height + 0.5] @ R[0]
        margin = np.minimum(-near.min() - T[:, 0], near.max() + T[:, 0])
        bodies = np.c_[
            anchors[0, 0] - (R @ point)[0] - T[:, 0],
            anchors[0, 1] - (R @ point)[1] - T[:, 1],
            -height - T[:, 2],
        ]
        floor = ((bh - pivot) @ B[2] + pivot[2]).min() + bodies[:, 2]
        valid &= (margin > 0.1) & (floor > 0)
        if not valid.any():
            raise ValueError(("no supported rear pose", t))
        j = int(np.argmin(np.where(valid, abs(bodies[:, 0] - desiredx), np.inf)))

        def pose(a):
            D = m.O + m.A * np.array([np.cos(m.a0 + a), np.sin(m.a0 + a)])
            E = D + m.b * np.array([np.cos(beta), np.sin(beta)])
            w = E - m.C
            d = np.linalg.norm(w)
            co = (m.r * m.r + d * d - m.L * m.L) / (2 * m.r * d)
            theta = np.arctan2(w[1], w[0]) - np.arccos(co) - m.t0
            theta = (theta + np.pi) % (2 * np.pi) - np.pi
            q = np.array([0, a, theta])
            m.body_euler = np.array([0, pitch, 0])
            p = m.reference("FL", q, np.zeros(3))
            vs = m.vertices("FL", q, np.zeros(3))
            b = np.r_[anchors[0] - p[:2], -vs[:, 2].min()]
            return q, b

        a = aa[j]
        if (
            0 < j < len(aa) - 1
            and valid[j - 1]
            and valid[j + 1]
            and (bodies[j - 1, 0] - desiredx) * (bodies[j + 1, 0] - desiredx) < 0
        ):
            a = brentq(
                lambda value: pose(value)[1][0] - desiredx,
                aa[j - 1],
                aa[j + 1],
                xtol=1e-12,
            )
        rear, b = pose(a)
        q = np.array([rear, rear, q0[2], q0[3]])
        fit = least_squares(
            lambda v: np.r_[
                m.reference("FR", v, b)[:2] - anchors[1],
                m.vertices("FR", v, b)[:, 2].min(),
            ],
            rear,
            bounds=(bounds[1, :, 0], bounds[1, :, 1]),
            max_nfev=25,
            xtol=1e-11,
            ftol=1e-11,
            gtol=1e-11,
        )
        q[1] = fit.x
        if t <= 14:
            v = ref.smooth((t - 12) / 2)
            target = np.radians([8, 15, -40])
            q[2:] = (1 - v) * q0[2:] + v * target
        else:
            v = ref.smooth((t - 14) / 6)
            q[2:] = (1 - v) * np.radians([8, 15, -40]) + v * np.radians([8, 20, -20])
        for i in [2, 3]:
            if m.vertices(legs[i], q[i], b)[:, 2].min() < 0:
                target = q[i].copy()
                fit = least_squares(
                    lambda value: np.r_[
                        (value - target) * 0.01,
                        min(0, m.vertices(legs[i], value, b)[:, 2].min()) * 1000,
                    ],
                    target,
                    bounds=(bounds[i, :, 0], bounds[i, :, 1]),
                    max_nfev=50,
                    xtol=1e-11,
                    ftol=1e-11,
                    gtol=1e-11,
                )
                q[i] = fit.x
        row = rows[n]
        row.update(
            body_translation_world_mm=b.tolist(),
            body_rotation_euler_xyz_rad=[0, pitch, 0],
            actuator_angles_rad=q.tolist(),
            contact_active=[True, True, False, False],
        )
        maxstep = max(
            maxstep,
            float(
                np.degrees(abs(q - np.array(rows[n - 1]["actuator_angles_rad"]))).max()
            ),
        )
        if n % 120 == 0:
            print(
                t,
                "body",
                b,
                "pitch",
                np.degrees(pitch),
                "front sole",
                min(m.vertices(legs[i], q[i], b)[:, 2].min() for i in [2, 3]),
                flush=True,
            )
    for n in range(2401, len(rows)):
        held = copy.deepcopy(rows[2400])
        held["time_s"] = n / 120
        held["phase"] = "hold"
        rows[n] = held
    source["samples"] = rows
    source["metadata"]["calibrated_motion_revision"] = dict(
        method="Contact-constrained seated entry, arc-length reparameterization of each existing phase, then a broad-sole supported rear-leg rise to 60 degrees.",
        baseline_source_sha256=hashlib.sha256(
            (BASE / "motions/gestures/upright/source.json").read_bytes()
        ).hexdigest(),
        pulse_window_us=[400, 2900],
        upright_pitch_deg=-60,
        maximum_joint_step_degrees=float(
            np.degrees(
                abs(np.diff(np.array([r["actuator_angles_rad"] for r in rows]), axis=0))
            ).max()
        ),
        hardware_qualified=False,
    )
    (ROOT / "motions/gestures/upright/source.json").write_text(
        json.dumps(source, separators=(",", ":")) + "\n"
    )
    print("DONE", source["metadata"]["calibrated_motion_revision"], flush=True)


if args.stage in ("fit", "all"):
    fit_prefix()
if args.stage in ("retime", "all"):
    retime_prefix()
if args.stage in ("rise", "all"):
    finish_rise()
    subprocess.run(
        [
            sys.executable,
            str(Path(__file__).with_name("author_calibrated_clips.py")),
            "--baseline",
            str(BASE),
            "--root",
            str(ROOT),
            "--calibration",
            str(args.calibration),
            "--commands",
            "upright",
            "--refresh-only",
        ],
        check=True,
    )
