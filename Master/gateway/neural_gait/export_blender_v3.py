"""Export V3 Option A-1 (DS3225 PRO 12-servo) CAD geometry from v3-2.blend (scene 'v3').

Run inside Blender (or via `blender --background v3-2.blend --python export_blender_v3.py`).
Generates:
  - Slave/software/models/v3-12servo/geometry.json
  - Slave/software/models/v3-12servo/model.json
  - Slave/software/models/v3-12servo/servo_profile.json
  - Slave/software/models/v3-12servo/simulation/assembly.json
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import bpy
import mathutils

REPO_ROOT = Path("/home/greggles/Ainekio")
OUT_DIR = REPO_ROOT / "Slave/software/models/v3-12servo"

# Exact Option A-1 4-bar linkage parameters from v3-2.blend (scene 'v3') drivers
V3_LINKAGE_MM = {
    "carrier": 54.0,
    "crank": 22.0,
    "pickup": 46.0,
    "rod": 56.0,
    "lower_leg_nominal": 135.0,
    "alpha_zero_rad": -2.202809465985,
    "theta_zero_rad": 3.055204643652,
    "beta_offset_rad": math.pi + 0.42568580,
    "separation_min_mm": 10.5,
    "separation_max_mm": 101.5,
}

# Verified non-singular 4-bar workspace bounds (sin(transmission) >= 0.237 everywhere)
V3_JOINT_LIMITS_DEG = {
    "shoulder": [-30.0, 30.0],
    "carrier": [-40.0, 50.0],
    "crank": [-50.0, 50.0],
}

# Canonical 12-joint map-2 ordering (matches v2-12servo)
V3_LEGS_ORDERED = (
    ("rear_left", "RL", -1.0, 0),
    ("rear_right", "RR", +1.0, 3),
    ("front_left", "FL", -1.0, 6),
    ("front_right", "FR", +1.0, 9),
)


def _r3(vec) -> list[float]:
    return [round(float(vec[0]), 4), round(float(vec[1]), 4), round(float(vec[2]), 4)]


def export_v3() -> None:
    scene = bpy.data.scenes.get("v3")
    if scene is None:
        raise RuntimeError("Scene 'v3' not found in active Blender file")
    orig = bpy.data.objects.get("V3 | Robot Origin")
    if orig is None:
        raise RuntimeError("Object 'V3 | Robot Origin' not found in scene 'v3'")

    inv_orig = orig.matrix_world.inverted()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "simulation").mkdir(parents=True, exist_ok=True)

    legs_json = {}
    sole_zmins = []
    # Temporarily mute live ankle leveling constraints whose rest reference is posed (not CAD neutral 0,0,0)
    muted_ankle_constraints = []
    for _, cad_leg, _, _ in V3_LEGS_ORDERED:
        ank_empty = bpy.data.objects.get(f"V3 | {cad_leg} | Ankle Axis (F)")
        if ank_empty is not None:
            for c in ank_empty.constraints:
                if not c.mute:
                    c.mute = True
                    muted_ankle_constraints.append(c)
    if muted_ankle_constraints:
        bpy.context.view_layer.update()

    try:
        for phys_name, cad_leg, roll_sign, base_id in V3_LEGS_ORDERED:
            sh = bpy.data.objects[f"V3 | {cad_leg} | Shoulder Origin"]
            car = bpy.data.objects[f"V3 | {cad_leg} | Carrier Axis (O)"]
            crk = bpy.data.objects[f"V3 | {cad_leg} | Crank Axis (C)"]
            knee = bpy.data.objects[f"V3 | {cad_leg} | Knee Axis (D)"]
            foot = bpy.data.objects[f"V3 | {cad_leg} | Komatsu - Sloped Split-Toe Crawler Foot"]
            inv_k = knee.matrix_world.inverted()

            w_pts = [inv_orig @ (foot.matrix_world @ v.co) for v in foot.data.vertices]
            zmin = min(p.z for p in w_pts)
            sole_zmins.append(zmin)
            sole_pts = [p for p in w_pts if p.z <= zmin + 2.0]
            sole_center_robot = mathutils.Vector(
                (
                    sum(p.x for p in sole_pts) / len(sole_pts),
                    sum(p.y for p in sole_pts) / len(sole_pts),
                    zmin,
                )
            )
            sole_center_knee = inv_k @ (orig.matrix_world @ sole_center_robot)

            # Extract front/rear/inner/outer sole corners in knee local frame for accurate contact pad
            sole_k = [inv_k @ (orig.matrix_world @ p) for p in sole_pts]
            kx_min, kx_max = min(p.x for p in sole_k), max(p.x for p in sole_k)
            ky_min, ky_max = min(p.y for p in sole_k), max(p.y for p in sole_k)
            kz_min, kz_max = min(p.z for p in sole_k), max(p.z for p in sole_k)

            # Compute exact neutral beta0 from linkage equation
            ox, oz = float(car.location.x), float(car.location.z)
            cx, cz = float(crk.location.x), float(crk.location.z)
            a0 = V3_LINKAGE_MM["alpha_zero_rad"]
            t0 = V3_LINKAGE_MM["theta_zero_rad"]
            dx = ox + V3_LINKAGE_MM["carrier"] * math.cos(a0)
            dz = oz + V3_LINKAGE_MM["carrier"] * math.sin(a0)
            px = cx + V3_LINKAGE_MM["crank"] * math.cos(t0)
            pz = cz + V3_LINKAGE_MM["crank"] * math.sin(t0)
            wx, wz = px - dx, pz - dz
            d = math.hypot(wx, wz)
            along = (V3_LINKAGE_MM["pickup"] ** 2 - V3_LINKAGE_MM["rod"] ** 2 + d * d) / (2.0 * d)
            h = math.sqrt(max(0.0, V3_LINKAGE_MM["pickup"] ** 2 - along * along))
            ex = dx + (along * wx - h * wz) / d
            ez = dz + (along * wz + h * wx) / d
            beta0 = math.atan2(ez - dz, ex - dx)
            gamma0 = math.atan2(ez - pz, ex - px)

            legs_json[phys_name] = {
                "cad_leg": cad_leg,
                "joint_ids": [base_id, base_id + 1, base_id + 2],
                "shoulder_roll_sign": roll_sign,
                "shoulder_in_robot_mm": _r3(sh.location),
                "carrier_in_shoulder_mm": _r3(car.location),
                "crank_in_shoulder_mm": _r3(crk.location),
                "knee_neutral_in_shoulder_mm": _r3(knee.location),
                "knee_neutral_rot_y_deg": round(math.degrees(knee.rotation_euler[1]), 4),
                "beta_zero_rad": round(beta0, 8),
                "gamma_zero_rad": round(gamma0, 8),
                "sole_center_in_knee_mm": _r3(sole_center_knee),
                "sole_center_in_robot_mm": _r3(sole_center_robot),
                "sole_knee_bounds_mm": {
                    "min": [round(kx_min, 3), round(ky_min, 3), round(kz_min, 3)],
                    "max": [round(kx_max, 3), round(ky_max, 3), round(kz_max, 3)],
                },
                "ankle_pivot_in_knee_mm": [106.5, round(-43.05 * roll_sign, 4), -4.5],
                "limits_deg": V3_JOINT_LIMITS_DEG,
            }
    finally:
        for c in muted_ankle_constraints:
            c.mute = False
        if muted_ankle_constraints:
            bpy.context.view_layer.update()

    sole_z = sum(sole_zmins) / len(sole_zmins)
    shoulder_z = 140.0
    standing_shoulder_height_mm = round(shoulder_z - sole_z, 4)

    # Belly hull clearance & overall visible torso bounding box
    belly = bpy.data.objects.get("Belly Hull | 01 - Main Shell")
    belly_pts = [inv_orig @ (belly.matrix_world @ mathutils.Vector(c)) for c in belly.bound_box]
    belly_z_min = min(p.z for p in belly_pts)
    belly_clearance_mm = round(belly_z_min - sole_z, 4)

    geometry = {
        "model": "v3-12servo",
        "geometry_id": "v3-p4-ds3225pro-optA1-ankle-20261122",
        "source_file": str(bpy.data.filepath),
        "scene": "v3",
        "units": "mm",
        "axes": "+X forward, +Y left, +Z up",
        "neutral_sole_z_in_robot_mm": round(sole_z, 4),
        "standing_shoulder_height_mm": standing_shoulder_height_mm,
        "standing_belly_clearance_mm": belly_clearance_mm,
        "torso_com_in_robot_mm": [4.0, 0.0, 140.0],
        "mass_kg": 2.97,
        "mass_measured": False,
        "mass_basis": (
            "Estimated from v3-2.blend (scene 'v3') Komatsu shell + Option A-1 functional leg CAD "
            "(PETG knee flat spiral spring, preloaded PETG servo-saver connecting rod, 2-stage "
            "double-parallelogram self-leveling ankle linkage + outboard compliant ankle damper) + "
            "12x DS3225 PRO (720g) + 4x 21700 2S2P (280g) + Radxa Dragon Q6A/Armor (160g) + "
            "ESP32-P4/PCA9685/CD74HC4067/MSP2807/IMU/wiring (~260g). Update when physically weighed."
        ),
        "link_masses_kg": {
            "torso": 1.75,
            "shoulder_bracket": 0.145,
            "carrier": 0.046,
            "crank": 0.012,
            "rod": 0.015,
            "lower_leg_and_foot": 0.088,
        },
        "leg_mechanics": {
            "knee_spiral_spring_nm_rad": 0.167,
            "servo_saver_rod_preload_n": 22.0,
            "servo_saver_rod_stroke_mm": 1.3,
            "servo_saver_solref": [0.006, 0.9],
            "ankle_leveling": "double-parallelogram-1to1",
            "ankle_level_solref": [0.006, 0.95],
            "ankle_damping_nm_s_rad": 0.004,
            "ankle_range_rad": [-0.48, 0.48],
        },
        "servo_specs": {
            "model": "DSServo DS3225 PRO (270 deg, HV coreless)",
            "voltage_v": 7.4,
            "stall_torque_nm": 3.43,
            "no_load_speed_rad_s": 13.9626,
            "no_load_speed_deg_s": 800.0,
            "travel_deg": 270.0,
            "pulse_min_us": 500,
            "pulse_max_us": 2500,
            "pulse_center_us": 1500,
            "us_per_degree": 7.4074,
            "weight_g": 60.0,
        },
        "linkage_mm": V3_LINKAGE_MM,
        "legs": legs_json,
    }
    (OUT_DIR / "geometry.json").write_text(json.dumps(geometry, indent=2) + "\n")

    joints = []
    for phys_name, cad_leg, roll_sign, base_id in V3_LEGS_ORDERED:
        joints.extend(
            [
                {
                    "id": base_id,
                    "name": f"{phys_name}_shoulder",
                    "cad_leg": cad_leg,
                    "actuator": "h_Part002",
                    "positive_body_axis": "+X" if roll_sign > 0 else "-X",
                    "pca_channel": base_id,
                },
                {
                    "id": base_id + 1,
                    "name": f"{phys_name}_carrier",
                    "cad_leg": cad_leg,
                    "actuator": "alpha_Part006",
                    "positive_body_axis": "-Y",
                    "pca_channel": base_id + 1,
                },
                {
                    "id": base_id + 2,
                    "name": f"{phys_name}_crank",
                    "cad_leg": cad_leg,
                    "actuator": "theta_Part005",
                    "positive_body_axis": "-Y",
                    "pca_channel": base_id + 2,
                },
            ]
        )

    model_doc = {
        "model": "v3-12servo",
        "geometry_id": geometry["geometry_id"],
        "joint_map": "v3-option-a1-54-22-46-56-20261121",
        "position_units": "signed centidegrees from CAD neutral (h=0, alpha=0, theta=0)",
        "zero": "CAD neutral standing pose (shoulder height 180.93 mm above ground).",
        "joints": joints,
        "servo_profile": "servo_profile.json",
    }
    (OUT_DIR / "model.json").write_text(json.dumps(model_doc, indent=2) + "\n")

    servo_profile = {
        "profile_id": "ds3225pro-270-v3-p4",
        "model": "v3-12servo",
        "servo": "DSServo DS3225 PRO 25kg Coreless (270 deg)",
        "nominal_voltage_v": 7.4,
        "pulse_min_us": 500,
        "pulse_max_us": 2500,
        "pulse_center_us": 1500,
        "us_per_degree": 7.4074,
        "no_load_speed_deg_s": 800.0,
        "stall_torque_nm": 3.43,
        "measured_on_hardware": False,
    }
    (OUT_DIR / "servo_profile.json").write_text(json.dumps(servo_profile, indent=2) + "\n")

    assembly = {
        "model": "v3-12servo",
        "geometry_id": geometry["geometry_id"],
        "torso_box_half_extents_m": [0.165, 0.068, 0.052],
        "torso_box_center_in_robot_m": [0.008, 0.0, 0.140],
        "foot_pad_size_m": [0.032, 0.020, 0.012],
        "mass_kg": geometry["mass_kg"],
        "mass_measured": False,
    }
    (OUT_DIR / "simulation/assembly.json").write_text(json.dumps(assembly, indent=2) + "\n")
    print(f"Exported V3 geometry ({geometry['geometry_id']}) to {OUT_DIR}")


if __name__ == "__main__":
    export_v3()
