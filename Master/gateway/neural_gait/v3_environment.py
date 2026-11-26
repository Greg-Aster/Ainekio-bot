"""Exact CAD-backed closed-chain 4-bar MuJoCo MJCF builder for V3 (v3-12servo, Option A-1, DS3225 PRO).

All coordinates, 4-bar linkage dimensions, and link masses come from
`Slave/software/models/v3-12servo/geometry.json` (exported from v3-2.blend, scene 'v3').
Simulation masses (2.85 kg total) and DS3225 PRO 7.4V torque-speed curves are
explicit CAD/datasheet estimates (`mass_measured: false`), not physical qualification.
"""
from __future__ import annotations

import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[3]
V3_GEOMETRY_PATH = REPO_ROOT / "Slave/software/models/v3-12servo/geometry.json"

# Canonical map-2 12-DOF ordering (matches v2-12servo & v3_model.h)
V3_LEGS = ("rear_left", "rear_right", "front_left", "front_right")
V3_JOINTS = (
    "rear_left_shoulder", "rear_left_carrier", "rear_left_crank",
    "rear_right_shoulder", "rear_right_carrier", "rear_right_crank",
    "front_left_shoulder", "front_left_carrier", "front_left_crank",
    "front_right_shoulder", "front_right_carrier", "front_right_crank",
)

V3_SHOULDER_LIMITS_RAD = (math.radians(-30.0), math.radians(30.0))
V3_CARRIER_LIMITS_RAD = (math.radians(-40.0), math.radians(50.0))
V3_CRANK_LIMITS_RAD = (math.radians(-50.0), math.radians(50.0))

# DS3225 PRO (270 deg, 7.4V HV coreless) actuator envelope
V3_SERVO_EFFORT_NM = 3.43
V3_SERVO_NO_LOAD_RAD_S = 13.9626  # 800 deg/s (0.075 s / 60 deg @ 7.4V)
V3_SERVO_KP = 18.0
V3_SERVO_KV = 0.35


def load_v3_geometry() -> dict:
    return json.loads(V3_GEOMETRY_PATH.read_text())


def _txt(vals) -> str:
    return " ".join(f"{float(v):.8g}" for v in vals)


def _yquat(angle_rad: float) -> str:
    return _txt([math.cos(0.5 * angle_rad), 0.0, math.sin(0.5 * angle_rad), 0.0])


def _rot_y(angle_rad: float, v: tuple[float, float, float]) -> tuple[float, float, float]:
    c, s = math.cos(angle_rad), math.sin(angle_rad)
    return (c * v[0] + s * v[2], v[1], -s * v[0] + c * v[2])


def build_v3_xml(geo: dict | None = None, *, floor: bool = True, foot_radius_m: float = 0.015) -> str:
    """Build exact closed-chain 4-bar MuJoCo MJCF for V3 Option A-1."""
    if geo is None:
        geo = load_v3_geometry()

    lk = geo["linkage_mm"]
    L_car = lk["carrier"] / 1000.0
    L_crk = lk["crank"] / 1000.0
    L_pk = lk["pickup"] / 1000.0
    L_rod = lk["rod"] / 1000.0
    a0 = float(lk["alpha_zero_rad"])
    t0 = float(lk["theta_zero_rad"])
    b_off = float(lk["beta_offset_rad"])

    z_sh_world = float(geo["standing_shoulder_height_mm"]) / 1000.0  # 0.1809336 m
    sh_z_robot = 140.0  # mm
    lm = geo["link_masses_kg"]

    root = ET.Element("mujoco", model="ainekio-v3-option-a1")
    ET.SubElement(root, "compiler", angle="radian", autolimits="true")
    ET.SubElement(
        root,
        "option",
        timestep="0.002",
        integrator="implicitfast",
        solver="Newton",
        iterations="30",
    )

    default = ET.SubElement(root, "default")
    ET.SubElement(default, "joint", damping="0.015", armature="0.0012", frictionloss="0.01")
    ET.SubElement(default, "geom", friction="1.0 0.005 0.0001", condim="3", margin="0")

    world = ET.SubElement(root, "worldbody")
    if floor:
        ET.SubElement(world, "geom", name="floor", type="plane", size="6 6 0.05", rgba="0.30 0.34 0.38 1")
    ET.SubElement(world, "light", pos="0 0 3", dir="0 0 -1")

    # Torso origin sits at robot shoulder axis height (0, 0, z_sh_world)
    torso = ET.SubElement(world, "body", name="torso", pos=_txt([0.0, 0.0, z_sh_world]))
    ET.SubElement(torso, "freejoint", name="root")
    com_mm = geo["torso_com_in_robot_mm"]
    com_m = [com_mm[0] / 1000.0, com_mm[1] / 1000.0, (com_mm[2] - sh_z_robot) / 1000.0]
    ET.SubElement(
        torso,
        "inertial",
        pos=_txt(com_m),
        mass=f"{float(lm['torso']) - 0.048:.6g}",
        diaginertia="0.0105 0.0225 0.0245",
    )
    # Main Komatsu chassis core (true +-46mm width between shoulders so 4-bar thighs/knees are fully visible!)
    ET.SubElement(
        torso,
        "geom",
        name="torso_chassis",
        type="box",
        pos="0.008 0.0 0.005",
        size="0.165 0.046 0.054",
        contype="1",
        conaffinity="1",
        rgba="0.88 0.64 0.08 1",
    )
    # Front visor / face plate indicator (+X forward)
    ET.SubElement(
        torso,
        "geom",
        name="torso_face",
        type="box",
        pos="0.174 0.0 0.012",
        size="0.006 0.036 0.030",
        contype="0",
        conaffinity="0",
        rgba="0.10 0.12 0.16 1",
    )
    # Upper dorsal radiator visual/collision cap
    ET.SubElement(
        torso,
        "geom",
        name="torso_dorsal",
        type="box",
        pos="-0.020 0.0 0.070",
        size="0.125 0.040 0.022",
        contype="1",
        conaffinity="1",
        rgba="0.22 0.24 0.27 1",
    )
    ET.SubElement(torso, "site", name="imu", pos="-0.0966 -0.0016 -0.0223", size="0.004")

    tendons = ET.SubElement(root, "tendon")
    equality = ET.SubElement(root, "equality")
    actuators = ET.SubElement(root, "actuator")
    sensors = ET.SubElement(root, "sensor")
    ET.SubElement(sensors, "gyro", name="imu_gyro", site="imu")
    ET.SubElement(sensors, "accelerometer", name="imu_accel", site="imu")

    mech = geo.get("leg_mechanics", {})
    knee_spring_k = float(mech.get("knee_spiral_spring_nm_rad", 0.167))
    rod_solref = mech.get("servo_saver_solref", [0.006, 0.9])
    ankle_level_mode = mech.get("ankle_leveling", "double-parallelogram-1to1")
    ankle_solref = mech.get("ankle_level_solref", [0.006, 0.95])
    ankle_damping = float(mech.get("ankle_damping_nm_s_rad", 0.004))
    ankle_range = mech.get("ankle_range_rad", [-0.48, 0.48])

    for leg_name in V3_LEGS:
        lg = geo["legs"][leg_name]
        sh_mm = lg["shoulder_in_robot_mm"]
        sh_m = [sh_mm[0] / 1000.0, sh_mm[1] / 1000.0, (sh_mm[2] - sh_z_robot) / 1000.0]
        O_m = [v / 1000.0 for v in lg["carrier_in_shoulder_mm"]]
        C_m = [v / 1000.0 for v in lg["crank_in_shoulder_mm"]]
        roll_sign = float(lg["shoulder_roll_sign"])
        b0 = float(lg["beta_zero_rad"])
        g0 = float(lg["gamma_zero_rad"])
        sole_k_m = tuple(v / 1000.0 for v in lg["sole_center_in_knee_mm"])
        ankle_k_mm = lg.get("ankle_pivot_in_knee_mm", [106.5, -43.05 * roll_sign, -4.5])
        ankle_k_m = tuple(v / 1000.0 for v in ankle_k_mm)
        # Transform sole & ankle centers from Blender Knee frame into passive_pickup frame: rot_y(beta_offset)
        sole_pk = _rot_y(b_off, sole_k_m)
        ankle_pk = _rot_y(b_off, ankle_k_m)
        sole_in_ankle = tuple(sole_pk[i] - ankle_pk[i] for i in range(3))

        # Pad center raised by sole half-height along world +Z at neutral (so flat bottom hits sole_z = 0)
        # World +Z in passive_pickup / foot_body neutral frame is rot_y(+b0) @ (0, 0, 1)
        sole_half_h = 0.008  # 16mm thick flat crawler sole pad (60mm L x 38mm W)
        up_pk = _rot_y(+b0, (0.0, 0.0, 1.0))
        sole_box_center = [sole_in_ankle[i] + sole_half_h * up_pk[i] for i in range(3)]

        # 1. Shoulder roll body (carries 2x DS3225 PRO servos + hip bracket)
        sh_body = ET.SubElement(torso, "body", name=f"{leg_name}_shoulder_body", pos=_txt(sh_m))
        ET.SubElement(
            sh_body,
            "joint",
            name=f"{leg_name}_shoulder",
            type="hinge",
            axis=_txt([roll_sign, 0.0, 0.0]),
            range=_txt(V3_SHOULDER_LIMITS_RAD),
        )
        ET.SubElement(
            sh_body,
            "geom",
            name=f"{leg_name}_hip_bracket",
            type="box",
            pos=_txt([(O_m[0] + C_m[0]) * 0.5, O_m[1] * 0.5, -0.010]),
            size="0.036 0.016 0.026",
            mass=f"{float(lm['shoulder_bracket']):.6g}",
            contype="0",
            conaffinity="0",
            rgba="0.18 0.20 0.24 1",
        )

        # 2. Carrier body (O -> D, length 54 mm)
        car_body = ET.SubElement(
            sh_body, "body", name=f"{leg_name}_carrier_body", pos=_txt(O_m), quat=_yquat(-a0)
        )
        ET.SubElement(
            car_body,
            "joint",
            name=f"{leg_name}_carrier",
            type="hinge",
            axis="0 -1 0",
            range=_txt(V3_CARRIER_LIMITS_RAD),
        )
        ET.SubElement(
            car_body,
            "geom",
            name=f"{leg_name}_carrier_link",
            type="capsule",
            fromto=_txt([0.0, 0.0, 0.0, L_car, 0.0, 0.0]),
            size="0.008",
            mass=f"{float(lm['carrier']):.6g}",
            contype="0",
            conaffinity="0",
            rgba="0.85 0.62 0.08 1",
        )

        # 3. Passive lower-leg / pickup body hinged at Knee (D) with integrated PETG knee spiral spring
        pk_body = ET.SubElement(
            car_body,
            "body",
            name=f"{leg_name}_pickup_body",
            pos=_txt([L_car, 0.0, 0.0]),
            quat=_yquat(-(b0 - a0)),
        )
        ET.SubElement(
            pk_body,
            "joint",
            name=f"passive_{leg_name}_pickup",
            type="hinge",
            axis="0 -1 0",
            stiffness=f"{knee_spring_k:.6g}",
            springref="0",
            damping="0.003",
            armature="0.00005",
            frictionloss="0.002",
        )
        ET.SubElement(
            pk_body,
            "geom",
            name=f"{leg_name}_pickup_link",
            type="capsule",
            fromto=_txt([0.0, 0.0, 0.0, L_pk, 0.0, 0.0]),
            size="0.005",
            mass="0.012",
            contype="0",
            conaffinity="0",
            rgba="0.32 0.35 0.39 1",
        )
        # Knee drum axle spanning horizontally from inboard knee D to outboard shin plane (shows real Komatsu knee!)
        ET.SubElement(
            pk_body,
            "geom",
            name=f"{leg_name}_knee_drum",
            type="capsule",
            fromto=_txt([0.0, 0.0, 0.0, 0.0, ankle_pk[1], 0.0]),
            size="0.016",
            mass="0.012",
            contype="0",
            conaffinity="0",
            rgba="0.22 0.25 0.29 1",
        )
        # Vertical shin running cleanly in the outboard plane from knee drum to real ankle pivot F
        ET.SubElement(
            pk_body,
            "geom",
            name=f"{leg_name}_shin_link",
            type="capsule",
            fromto=_txt([0.0, ankle_pk[1], 0.0, ankle_pk[0], ankle_pk[1], ankle_pk[2]]),
            size="0.012",
            mass=f"{max(0.01, float(lm['lower_leg_and_foot']) * 0.50 - 0.012):.6g}",
            contype="0",
            conaffinity="0",
            rgba="0.85 0.62 0.08 1",
        )
        # Ankle pivot hub visual
        ET.SubElement(
            pk_body,
            "geom",
            name=f"{leg_name}_ankle_hub",
            type="sphere",
            pos=_txt(ankle_pk),
            size="0.011",
            mass="0.0001",
            contype="0",
            conaffinity="0",
            rgba="0.30 0.34 0.40 1",
        )

        # 3b. Pivoting Split-Toe Crawler Foot body hinged at Ankle Pivot (F) + Double-Parallelogram self-leveling!
        foot_body = ET.SubElement(
            pk_body,
            "body",
            name=f"{leg_name}_foot_body",
            pos=_txt(ankle_pk),
        )
        ET.SubElement(
            foot_body,
            "joint",
            name=f"passive_{leg_name}_ankle",
            type="hinge",
            axis="0 -1 0",
            range=_txt(ankle_range),
            damping=f"{ankle_damping:.6g}",
            armature="0.00004",
            frictionloss="0.002",
        )
        ET.SubElement(
            foot_body,
            "geom",
            name=f"{leg_name}_foot",
            type="box",
            pos=_txt(sole_box_center),
            quat=_yquat(+b0),
            size="0.030 0.019 0.008",
            mass=f"{float(lm['lower_leg_and_foot']) * 0.50:.6g}",
            contype="1",
            conaffinity="1",
            rgba="0.14 0.15 0.17 1",
        )
        ET.SubElement(foot_body, "site", name=f"{leg_name}_foot", pos=_txt(sole_in_ankle), size="0.005")

        if ankle_level_mode == "double-parallelogram-1to1":
            # Exact kinematic 2-stage double-parallelogram equality: q_carrier + q_pickup + q_ankle = 0
            # Keeps crawler foot sole parallel to chassis throughout stride with realistic elastic compliance!
            t_el = ET.SubElement(tendons, "fixed", name=f"{leg_name}_ankle_level")
            ET.SubElement(t_el, "joint", joint=f"{leg_name}_carrier", coef="1")
            ET.SubElement(t_el, "joint", joint=f"passive_{leg_name}_pickup", coef="1")
            ET.SubElement(t_el, "joint", joint=f"passive_{leg_name}_ankle", coef="1")
            ET.SubElement(
                equality,
                "tendon",
                name=f"{leg_name}_ankle_level_eq",
                tendon1=f"{leg_name}_ankle_level",
                polycoef="0 1 0 0 0",
                solref=_txt(ankle_solref),
                solimp="0.98 0.995 0.001",
            )

        # 4. Crank body (C -> P, length 22 mm)
        crk_body = ET.SubElement(
            sh_body, "body", name=f"{leg_name}_crank_body", pos=_txt(C_m), quat=_yquat(-t0)
        )
        ET.SubElement(
            crk_body,
            "joint",
            name=f"{leg_name}_crank",
            type="hinge",
            axis="0 -1 0",
            range=_txt(V3_CRANK_LIMITS_RAD),
        )
        ET.SubElement(
            crk_body,
            "geom",
            name=f"{leg_name}_crank_link",
            type="capsule",
            fromto=_txt([0.0, 0.0, 0.0, L_crk, 0.0, 0.0]),
            size="0.006",
            mass=f"{float(lm['crank']):.6g}",
            contype="0",
            conaffinity="0",
            rgba="0.55 0.58 0.62 1",
        )

        # 5. Passive connecting rod (P -> E, 56 mm Preloaded PETG Servo-Saver Strut)
        rod_body = ET.SubElement(
            crk_body,
            "body",
            name=f"{leg_name}_rod_body",
            pos=_txt([L_crk, 0.0, 0.0]),
            quat=_yquat(-(g0 - t0)),
        )
        ET.SubElement(
            rod_body,
            "joint",
            name=f"passive_{leg_name}_rod",
            type="hinge",
            axis="0 -1 0",
            damping="0.001",
            armature="0.00003",
            frictionloss="0.001",
        )
        ET.SubElement(
            rod_body,
            "geom",
            name=f"{leg_name}_rod_link",
            type="capsule",
            fromto=_txt([0.0, 0.0, 0.0, L_rod, 0.0, 0.0]),
            size="0.004",
            mass=f"{float(lm['rod']):.6g}",
            contype="0",
            conaffinity="0",
            rgba="0.65 0.68 0.72 1",
        )

        # 6. Exact 4-bar loop closure at joint E (with Servo-Saver Strut compliance solref)
        ET.SubElement(
            equality,
            "connect",
            name=f"{leg_name}_loop",
            body1=f"{leg_name}_pickup_body",
            body2=f"{leg_name}_rod_body",
            anchor=_txt([L_pk, 0.0, 0.0]),
            solref=_txt(rod_solref),
            solimp="0.99 0.999 0.0005",
        )

        # 7. Position actuators (DS3225 PRO 7.4V: 3.43 Nm, 800 deg/s)
        for j_suffix, lims in (
            ("shoulder", V3_SHOULDER_LIMITS_RAD),
            ("carrier", V3_CARRIER_LIMITS_RAD),
            ("crank", V3_CRANK_LIMITS_RAD),
        ):
            jname = f"{leg_name}_{j_suffix}"
            ET.SubElement(
                actuators,
                "position",
                name=jname,
                joint=jname,
                kp=f"{V3_SERVO_KP:.4g}",
                kv=f"{V3_SERVO_KV:.4g}",
                ctrlrange=_txt(lims),
                forcerange=_txt([-V3_SERVO_EFFORT_NM, V3_SERVO_EFFORT_NM]),
            )

    return ET.tostring(root, encoding="unicode")
