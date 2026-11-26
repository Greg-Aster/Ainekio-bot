"""MuJoCo embodiment and kinematics for the redesigned V1 8-servo P4 quadruped.

Built directly from the authoritative CAD export:
  Slave/software/models/v1-8servo/geometry.json

Coordinate frame: +X forward, +Y left, +Z up.
Frozen map-1 joint order (matching Slave/software/models/v1-8servo/include/ainekio/v1_model.h):
  0: R1 (front_right_hip)
  1: R2 (rear_right_hip)
  2: L1 (front_left_hip)
  3: L2 (rear_left_hip)
  4: R4 (rear_right_knee)
  5: R3 (front_right_knee)
  6: L3 (front_left_knee)
  7: L4 (rear_left_knee)

Signed V1 model angle convention (100% left-right mirror symmetric, +1 mirror sign for all 8 joints):
  - 0 rad = standing neutral
  - +hip  swings foot forward (+X): rot_z = neutral_yaw + hip_sign * hip (limits [-45, +45] deg)
  - +knee lifts/splays foot outward & upward: rot_y = -knee (limits [-15, +115] deg)
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import mujoco
import numpy as np

V1_ROOT = Path(__file__).resolve().parents[3] / "Slave/software/models/v1-8servo"
V1_GEOMETRY_PATH = V1_ROOT / "geometry.json"

V1_LEGS = ("front_right", "rear_right", "front_left", "rear_left")
V1_JOINTS = (
    "front_right_hip",   # 0: R1
    "rear_right_hip",    # 1: R2
    "front_left_hip",    # 2: L1
    "rear_left_hip",     # 3: L2
    "rear_right_knee",   # 4: R4
    "front_right_knee",  # 5: R3
    "front_left_knee",   # 6: L3
    "rear_left_knee",    # 7: L4
)
V1_JOINT_CODES = ("R1", "R2", "L1", "L2", "R4", "R3", "L3", "L4")
V1_HIP_INDICES = (0, 1, 2, 3)
V1_KNEE_INDICES = (4, 5, 6, 7)

# Left-right mirror permutation in frozen map-1 order:
#   FR(0,5) <-> FL(2,6),  RR(1,4) <-> RL(3,7)
# Because +hip always swings forward and +knee always lifts outward/upward,
# ALL 8 joint mirror signs are +1.0!
V1_JOINT_MIRROR_PERM = (2, 3, 0, 1, 7, 6, 5, 4)
V1_JOINT_MIRROR_SIGN = (1.0,) * 8
V1_LEG_MIRROR_PERM = (2, 3, 0, 1)  # FR<->FL, RR<->RL

V1_FOOT_RADIUS_M = 0.0045  # 4.5 mm radius rubber/PLA blade foot tip


def load_v1_geometry() -> dict[str, Any]:
    return json.loads(V1_GEOMETRY_PATH.read_text())


def _z_quat_wxyz(deg: float) -> str:
    rad = math.radians(deg) * 0.5
    return f"{math.cos(rad):.8f} 0 0 {math.sin(rad):.8f}"


def build_v1_xml(
    geometry: dict[str, Any] | None = None,
    *,
    include_floor: bool = True,
    friction: tuple[float, float, float] = (0.95, 0.015, 0.002),
    armature: float = 0.0002,
    damping: float = 0.002,
    frictionloss: float = 0.001,
    kp: float = 2.0,
    kv: float = 0.035,
    torque_nm: float = 0.18,
) -> str:
    """Build a crisp, fast, CAD-accurate MuJoCo XML for V1 8-servo P4 robot.

    Note: Mass (0.376 kg total) is CAD-estimated (mass_measured=false) until weighed.
    Actuator speed/torque reflect full MG90S specifications (0.216 Nm stall, 10.47 rad/s).
    """
    geo = geometry or load_v1_geometry()
    stand_z = float(geo["standing_root_height_mm"]) * 1e-3
    masses = geo["link_masses_kg"]
    m_torso = float(masses["torso"])
    m_upper = float(masses["upper_leg"])
    m_lower = float(masses["lower_leg"])
    imu_mm = geo["imu_site"]["position_body_mm"]
    imu_pos = f"{imu_mm[0]*1e-3:.6f} {imu_mm[1]*1e-3:.6f} {imu_mm[2]*1e-3:.6f}"
    fric_str = f"{friction[0]:.4f} {friction[1]:.4f} {friction[2]:.4f}"

    leg_xml_parts: list[str] = []
    actuator_xml_parts: list[str] = []

    for leg_name in V1_LEGS:
        leg = geo["legs"][leg_name]
        hip_mm = leg["hip_in_body_mm"]
        knee_mm = leg["knee_in_hip_mm"]
        foot_mm = leg["foot_in_knee_mm"]
        yaw_deg = float(leg["neutral_yaw_deg"])
        hip_sign = float(leg["hip_sign"])
        hip_lo, hip_hi = (math.radians(v) for v in leg["hip_limits_deg"])
        knee_lo, knee_hi = (math.radians(v) for v in leg["knee_limits_deg"])

        hx, hy, hz = (v * 1e-3 for v in hip_mm)
        kx, ky, kz = (v * 1e-3 for v in knee_mm)
        fx, fy, fz = (v * 1e-3 for v in foot_mm)
        # Place the hemispherical foot tip sphere center so its bottom tangent
        # lands exactly on foot_in_knee_mm (Z = 0.000 m at standing neutral).
        foot_center_z = fz + V1_FOOT_RADIUS_M
        # Upper-leg capsule from hip hub to knee servo housing
        ux0, uy0, uz0 = 0.004, 0.0, 0.004
        ux1, uy1, uz1 = kx, ky, kz
        # Lower-leg blade capsule from knee horn to just above foot tip sphere
        lx0, ly0, lz0 = 0.0, fy, 0.0
        lx1, ly1, lz1 = fx, fy, foot_center_z + 0.003

        leg_xml_parts.append(f"""
      <body name="{leg_name}_upper" pos="{hx:.6f} {hy:.6f} {hz:.6f}" quat="{_z_quat_wxyz(yaw_deg)}">
        <inertial pos="{kx*0.5:.6f} {ky*0.5:.6f} {kz*0.5:.6f}" mass="{m_upper:.5f}" diaginertia="3.5e-6 3.5e-6 4.5e-6"/>
        <joint name="{leg_name}_hip" type="hinge" axis="0 0 {hip_sign:.1f}" range="{hip_lo:.6f} {hip_hi:.6f}" armature="{armature:.6f}" damping="{damping:.5f}" frictionloss="{frictionloss:.5f}"/>
        <geom name="{leg_name}_upper_col" type="capsule" fromto="{ux0:.6f} {uy0:.6f} {uz0:.6f} {ux1:.6f} {uy1:.6f} {uz1:.6f}" size="0.0095" rgba="0.88 0.45 0.12 1" contype="1" conaffinity="1"/>
        <body name="{leg_name}_lower" pos="{kx:.6f} {ky:.6f} {kz:.6f}">
          <inertial pos="{fx*0.45:.6f} {fy:.6f} {fz*0.45:.6f}" mass="{m_lower:.5f}" diaginertia="1.6e-6 1.6e-6 0.4e-6"/>
          <joint name="{leg_name}_knee" type="hinge" axis="0 -1 0" range="{knee_lo:.6f} {knee_hi:.6f}" armature="{armature:.6f}" damping="{damping:.5f}" frictionloss="{frictionloss:.5f}"/>
          <geom name="{leg_name}_blade_col" type="capsule" fromto="{lx0:.6f} {ly0:.6f} {lz0:.6f} {lx1:.6f} {ly1:.6f} {lz1:.6f}" size="0.0040" rgba="0.92 0.92 0.94 1" contype="1" conaffinity="1"/>
          <geom name="{leg_name}_foot_geom" type="sphere" pos="{fx:.6f} {fy:.6f} {foot_center_z:.6f}" size="{V1_FOOT_RADIUS_M:.5f}" friction="{fric_str}" solref="0.012 1.0" solimp="0.95 0.99 0.001" rgba="0.18 0.18 0.22 1" contype="1" conaffinity="1"/>
          <site name="{leg_name}_foot" pos="{fx:.6f} {fy:.6f} {fz:.6f}" size="0.003" rgba="0.2 0.9 0.3 1"/>
        </body>
      </body>""")

    # Actuators strictly in frozen V1 map-1 order (0..7)
    for jname in V1_JOINTS:
        is_hip = jname.endswith("_hip")
        lo, hi = (math.radians(-45.0), math.radians(45.0)) if is_hip else (math.radians(-15.0), math.radians(115.0))
        actuator_xml_parts.append(
            f'    <position name="{jname}_act" joint="{jname}" kp="{kp:.4f}" kv="{kv:.4f}" '
            f'ctrlrange="{lo:.6f} {hi:.6f}" forcerange="-{torque_nm:.4f} {torque_nm:.4f}"/>'
        )

    floor_xml = (
        '    <geom name="floor" type="plane" size="10 10 0.05" '
        f'friction="{fric_str}" solref="0.012 1.0" rgba="0.78 0.80 0.84 1"/>\n'
        if include_floor
        else ""
    )

    xml = f"""<mujoco model="ainekio_v1_8servo_p4">
  <compiler angle="radian" coordinate="local" autolimits="true"/>
  <option timestep="0.002" integrator="implicitfast" iterations="20" solver="Newton"/>
  <default>
    <geom condim="3" friction="{fric_str}" margin="0"/>
  </default>
  <worldbody>
{floor_xml}    <body name="torso" pos="0 0 {stand_z:.6f}">
      <freejoint name="root"/>
      <!-- CAD-estimated torso mass 0.270 kg; envelope 126.7 x 92.0 x 41.5 mm -->
      <inertial pos="-0.0024 0.0 0.0040" mass="{m_torso:.5f}" diaginertia="0.00024 0.00039 0.00052"/>
      <geom name="torso_chassis" type="box" pos="-0.0024 0.0 0.0067" size="0.060 0.043 0.0195" rgba="0.22 0.26 0.34 1" contype="1" conaffinity="1"/>
      <site name="imu" pos="{imu_pos}" size="0.004" rgba="0.9 0.2 0.2 1"/>
{''.join(leg_xml_parts)}
    </body>
  </worldbody>
  <actuator>
{chr(10).join(actuator_xml_parts)}
  </actuator>
  <sensor>
    <framequat name="imu_quat" objtype="site" objname="imu"/>
    <gyro name="imu_gyro" site="imu"/>
    <accelerometer name="imu_accel" site="imu"/>
  </sensor>
</mujoco>
"""
    return xml


def v1_standing_foot_check() -> dict[str, Any]:
    """Quick kinematic sanity check: verify standing neutral foot positions match geometry.json."""
    geo = load_v1_geometry()
    model = mujoco.MjModel.from_xml_string(build_v1_xml(geo))
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    out = {}
    for leg in V1_LEGS:
        sid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_SITE, f"{leg}_foot")
        world_mm = data.site_xpos[sid] * 1e3
        expected_body = np.array(geo["legs"][leg]["foot_in_body_stand_mm"])
        expected_world = expected_body + np.array([0.0, 0.0, float(geo["standing_root_height_mm"])])
        err_mm = float(np.linalg.norm(world_mm - expected_world))
        out[leg] = {
            "world_mm": [round(float(v), 3) for v in world_mm],
            "expected_world_mm": [round(float(v), 3) for v in expected_world],
            "err_mm": round(err_mm, 4),
        }
    return out


if __name__ == "__main__":
    print(json.dumps(v1_standing_foot_check(), indent=2))
