"""Read-only V1-8Servo (ESP32-P4 redesigned) CAD assembly exporter, executed inside Blender.

Call export(directory). Evaluated mesh copies are triangulated for transport;
the active scene ('v1'), source polygons, pose, visibility and file are never changed.
"""
from __future__ import annotations

import json
import math
from pathlib import Path


# Frozen V1 map-1 joint order (matching Slave/software/protocol/joints_v1.py):
#   0: R1 (FR Hip),  1: R2 (RR Hip),  2: L1 (FL Hip),  3: L2 (RL Hip),
#   4: R4 (RR Knee), 5: R3 (FR Knee), 6: L3 (FL Knee), 7: L4 (RL Knee)
V1_LEGS = [
    ("FR", "front_right", "R1", "R3", 0, 5, -45.0, +1.0, 135.0, 180.0),
    ("RR", "rear_right",  "R2", "R4", 1, 4, -135.0, +1.0,  45.0,   0.0),
    ("FL", "front_left",  "L1", "L3", 2, 6,  +45.0, -1.0,  45.0,   0.0),
    ("RL", "rear_left",   "L2", "L4", 3, 7, +135.0, -1.0, 135.0, 180.0),
]

# Estimated link masses (kg) derived from v3-2.blend CAD volumes (PLA ~0.62-0.75 g/cm^3 effective)
# + known electronics/servo/cell masses. Explicitly marked mass_measured=False until weighed.
ESTIMATED_MASS_KG = {
    "torso": 0.270,
    "upper_leg": 0.022,  # PLA arm+cup+cap ~5g + MG90S knee servo 13.4g + bearing/hardware 3.6g
    "lower_leg": 0.0045,  # PLA blade leg 4.26 cm^3
}
TOTAL_ESTIMATED_MASS_KG = (
    ESTIMATED_MASS_KG["torso"]
    + 4 * ESTIMATED_MASS_KG["upper_leg"]
    + 4 * ESTIMATED_MASS_KG["lower_leg"]
)


def export(model_dir: str | Path) -> dict:
    import bpy
    import numpy as np
    from mathutils import Vector

    scene = bpy.context.scene
    if scene.name != "v1":
        raise ValueError(f"Expected active scene 'v1', got '{scene.name}'")

    model_dir = Path(model_dir)
    sim_dir = model_dir / "simulation"
    sim_dir.mkdir(parents=True, exist_ok=True)

    dg = bpy.context.evaluated_depsgraph_get()
    root = scene.objects["V1 | Robot Root"].evaluated_get(dg)
    root_mw = root.matrix_world.copy()
    root_inv = root_mw.inverted()

    # 1. Extract exact 8-DOF leg frames & kinematics in Robot Root body frame (mm)
    legs_geom = {}
    frames = {}
    for cad, phys, hj_lbl, kj_lbl, h_id, k_id, neutral_yaw_deg, hip_sign, stand_h, stand_k in V1_LEGS:
        hj = scene.objects[f"V1 | Joint {hj_lbl} ({cad} Hip)"].evaluated_get(dg)
        kj = scene.objects[f"V1 | Joint {kj_lbl} ({cad} Knee)"].evaluated_get(dg)
        ll = next(
            o for o in scene.objects
            if f"V1 | {cad} | Lower Leg" in o.name and "Parked" not in o.name and o.type == "MESH"
        ).evaluated_get(dg)

        hp_b = root_inv @ hj.matrix_world.to_translation()
        kp_b = root_inv @ kj.matrix_world.to_translation()
        kp_h = hj.matrix_world.inverted() @ kj.matrix_world.to_translation()

        ll_me = ll.to_mesh()
        try:
            w_vs = [ll.matrix_world @ v.co for v in ll_me.vertices]
            min_z = min(v.z for v in w_vs)
            patch = [v for v in w_vs if v.z <= min_z + 0.5]
            foot_w = sum(patch, Vector()) / len(patch)
            foot_w.z = min_z
        finally:
            ll.to_mesh_clear()

        foot_b = root_inv @ foot_w
        foot_k = kj.matrix_world.inverted() @ foot_w
        foot_h = hj.matrix_world.inverted() @ foot_w

        # Local frames relative to Robot Root (mm)
        h_mat_b = np.asarray(root_inv @ hj.matrix_world, dtype=np.float64)
        k_mat_b = np.asarray(root_inv @ kj.matrix_world, dtype=np.float64)
        frames[f"{phys}_hip"] = h_mat_b.tolist()
        frames[f"{phys}_knee"] = k_mat_b.tolist()

        legs_geom[phys] = {
            "cad_leg": cad,
            "hip_joint_id": h_id,
            "knee_joint_id": k_id,
            "hip_label": hj_lbl,
            "knee_label": kj_lbl,
            "neutral_yaw_deg": neutral_yaw_deg,
            "hip_sign": hip_sign,  # rot_z_rad = rad(neutral_yaw_deg + hip_sign * q_hip_deg)
            "knee_sign": -1.0,     # rot_y_rad = rad(-q_knee_deg); +q_knee lifts foot outward & up
            "hip_in_body_mm": [round(hp_b.x, 4), round(hp_b.y, 4), round(hp_b.z, 4)],
            "knee_in_hip_mm": [round(kp_h.x, 4), round(kp_h.y, 4), round(kp_h.z, 4)],
            "knee_in_body_mm": [round(kp_b.x, 4), round(kp_b.y, 4), round(kp_b.z, 4)],
            "foot_in_knee_mm": [round(foot_k.x, 4), round(foot_k.y, 4), round(foot_k.z, 4)],
            "foot_in_hip_mm": [round(foot_h.x, 4), round(foot_h.y, 4), round(foot_h.z, 4)],
            "foot_in_body_stand_mm": [round(foot_b.x, 4), round(foot_b.y, 4), round(foot_b.z, 4)],
            "hip_limits_deg": [-45.0, 45.0],
            "knee_limits_deg": [-15.0, 115.0],
            "blender_stand_deg": {"hip": stand_h, "knee": stand_k},
        }

    # 2. Sensor reference poses in Robot Root body frame (mm)
    sensor_refs = {}
    for sname in ("V1 | IMU - GY-LSM6DS3", "V1 | Camera - Arducam B0066", "V1 | Display - 0.96in SSD1306 OLED"):
        so = scene.objects.get(sname)
        if so is None:
            continue
        se = so.evaluated_get(dg)
        sme = se.to_mesh()
        try:
            pts_b = np.array([root_inv @ (se.matrix_world @ v.co) for v in sme.vertices], dtype=np.float64)
            sensor_refs[sname] = {
                "bounds_body_mm": [pts_b.min(0).round(4).tolist(), pts_b.max(0).round(4).tolist()],
                "center_body_mm": pts_b.mean(0).round(4).tolist(),
                "matrix_body": np.asarray(root_inv @ se.matrix_world, dtype=np.float64).tolist(),
            }
        finally:
            se.to_mesh_clear()

    # 3. Export triangulated visual/collision meshes for active V1 collections (excluding Parked/Pre-P4/Wiring harnesses)
    active_collections = [
        "V1 | Shell and Frame",
        "V1 | Electronics and Mounts",
        "V1 | Legs",
        "V1 | Servos (MG90S Reference)",
    ]
    candidates = {}
    for cname in active_collections:
        col = bpy.data.collections.get(cname)
        if col is None:
            continue
        for o in col.all_objects:
            candidates[o.name] = o

    # Map each object to its owning MuJoCo rigid body:
    #   torso | {phys}_upper_leg | {phys}_lower_leg
    cad_to_phys = {cad: phys for cad, phys, *_ in V1_LEGS}
    joint_owner_map = {}
    for cad, phys, hj_lbl, kj_lbl, *_ in V1_LEGS:
        joint_owner_map[f"V1 | Joint {hj_lbl} ({cad} Hip)"] = f"{phys}_upper_leg"
        joint_owner_map[f"V1 | Joint {kj_lbl} ({cad} Knee)"] = f"{phys}_lower_leg"

    def resolve_owner(obj):
        p = obj
        while p is not None:
            if p.name in joint_owner_map:
                return joint_owner_map[p.name]
            p = p.parent
        return "torso"

    arrays = {}
    objects_meta = []
    excluded = []
    for name, obj in sorted(candidates.items()):
        if obj.type != "MESH" or obj.hide_viewport or obj.hide_render or "Parked" in name:
            excluded.append({"name": name, "reason": "non-mesh, hidden, or parked"})
            continue
        owner = resolve_owner(obj)
        ev = obj.evaluated_get(dg)
        me = ev.to_mesh()
        try:
            me.calc_loop_triangles()
            # Express ALL exported vertices in Robot Root body frame (mm) so root=(0,0,0)!
            m_b = root_inv @ ev.matrix_world
            verts = np.array([m_b @ v.co for v in me.vertices], dtype=np.float64)
            faces = np.array([t.vertices for t in me.loop_triangles], dtype=np.int32)
            if not len(faces):
                continue
            if m_b.determinant() < 0:
                faces = faces[:, ::-1]
            key = f"mesh_{len(objects_meta):03d}"
            arrays[key + "_vertices"] = verts
            arrays[key + "_faces"] = faces
            color = [0.4, 0.4, 0.4, 1.0]
            mat = obj.active_material
            if mat:
                color = list(mat.diffuse_color)
                if mat.use_nodes:
                    bsdf = next((n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
                    if bsdf:
                        color = [float(x) for x in bsdf.inputs["Base Color"].default_value]
            objects_meta.append({
                "key": key,
                "name": name,
                "body": owner,
                "rgba": color,
                "vertices": int(len(verts)),
                "triangles": int(len(faces)),
            })
        finally:
            ev.to_mesh_clear()

    np.savez_compressed(sim_dir / "assembly.npz", **arrays)

    stand_height_mm = round(float(root_mw.to_translation().z - min(
        l["foot_in_body_stand_mm"][2] + root_mw.to_translation().z for l in legs_geom.values()
    )), 4)

    geometry_doc = {
        "model": "v1-8servo",
        "geometry_id": "v1-p4-clockspring-20261121",
        "source_file": bpy.data.filepath,
        "scene": scene.name,
        "units": "mm",
        "axes": "+X forward, +Y left, +Z up",
        "standing_root_height_mm": stand_height_mm,
        "mass_kg": round(TOTAL_ESTIMATED_MASS_KG, 4),
        "mass_measured": False,
        "mass_basis": "Estimated from v3-2.blend CAD volumes (PLA) + MG90S/ESP32-P4/PCA9685/14500 component weights; update when physically weighed.",
        "link_masses_kg": ESTIMATED_MASS_KG,
        "servo_specs": {
            "model": "MG90S",
            "stall_torque_nm": 0.216,   # ~2.2 kg-cm @ 5V
            "no_load_speed_rad_s": 10.47,  # ~600 deg/s (0.10 s / 60 deg @ 5V)
            "pulse_min_us": 500,
            "pulse_max_us": 2500,
            "pulse_center_us": 1500,
            "us_per_degree": 11.111,
        },
        "legs": legs_geom,
        "imu_site": {
            "position_body_mm": sensor_refs["V1 | IMU - GY-LSM6DS3"]["center_body_mm"],
            "position_measured": False,
            "basis": "CAD GY-LSM6DS3 PCB envelope center in Robot Root frame",
        },
        "camera_site": {
            "position_body_mm": sensor_refs["V1 | Camera - Arducam B0066"]["center_body_mm"],
            "forward_body": [1.0, 0.0, 0.0],
            "up_body": [0.0, 0.0, 1.0],
            "position_measured": False,
            "basis": "CAD Arducam B0066 envelope center in Robot Root frame",
        },
    }
    (model_dir / "geometry.json").write_text(json.dumps(geometry_doc, indent=2) + "\n")

    # Canonical model.json (frozen V1 map-1 joint order: R1, R2, L1, L2, R4, R3, L3, L4)
    joint_defs = [
        {"id": 0, "label": "R1", "name": "front_right_hip",  "cad_leg": "FR", "physical_leg": "front_right", "axis": "hip",  "pca_channel": 0, "adc_gpio": 20, "limits_deg": [-45.0, 45.0]},
        {"id": 1, "label": "R2", "name": "rear_right_hip",   "cad_leg": "RR", "physical_leg": "rear_right",  "axis": "hip",  "pca_channel": 1, "adc_gpio": 21, "limits_deg": [-45.0, 45.0]},
        {"id": 2, "label": "L1", "name": "front_left_hip",   "cad_leg": "FL", "physical_leg": "front_left",  "axis": "hip",  "pca_channel": 2, "adc_gpio": 22, "limits_deg": [-45.0, 45.0]},
        {"id": 3, "label": "L2", "name": "rear_left_hip",    "cad_leg": "RL", "physical_leg": "rear_left",   "axis": "hip",  "pca_channel": 3, "adc_gpio": 23, "limits_deg": [-45.0, 45.0]},
        {"id": 4, "label": "R4", "name": "rear_right_knee",  "cad_leg": "RR", "physical_leg": "rear_right",  "axis": "knee", "pca_channel": 4, "adc_gpio": 49, "limits_deg": [-15.0, 115.0]},
        {"id": 5, "label": "R3", "name": "front_right_knee", "cad_leg": "FR", "physical_leg": "front_right", "axis": "knee", "pca_channel": 5, "adc_gpio": 50, "limits_deg": [-15.0, 115.0]},
        {"id": 6, "label": "L3", "name": "front_left_knee",  "cad_leg": "FL", "physical_leg": "front_left",  "axis": "knee", "pca_channel": 6, "adc_gpio": 51, "limits_deg": [-15.0, 115.0]},
        {"id": 7, "label": "L4", "name": "rear_left_knee",   "cad_leg": "RL", "physical_leg": "rear_left",   "axis": "knee", "pca_channel": 7, "adc_gpio": 52, "limits_deg": [-15.0, 115.0]},
    ]
    model_doc = {
        "model": "v1-8servo",
        "board": "esp32p4-wifi6",
        "joint_map_version": 1,
        "geometry_id": geometry_doc["geometry_id"],
        "position_units": "signed centidegrees from standing neutral (0 = standing; +hip = forward +X; +knee = lift outward/up)",
        "hardware": {
            "controller": "Waveshare ESP32-P4-WIFI6",
            "servo_driver": {"type": "PCA9685", "i2c_port": 1, "sda_gpio": 2, "scl_gpio": 3, "oe_gpio": 4, "address": "0x40"},
            "imu": {"type": "GY-LSM6DS3", "i2c_port": 0, "sda_gpio": 7, "scl_gpio": 8, "address": "0x6A"},
            "display": {"type": "SSD1306_128x64", "scl_gpio": 26, "sda_gpio": 27, "address": "0x3C"},
            "camera": {"type": "Arducam B0066 (OV5647 MIPI-CSI)"},
            "feedback": {"type": "direct_adc_8ch", "multiplexer": False, "adc1_gpios": [20, 21, 22, 23], "adc2_gpios": [49, 50, 51, 52]},
        },
        "joints": joint_defs,
    }
    (model_dir / "model.json").write_text(json.dumps(model_doc, indent=2) + "\n")

    assembly_manifest = {
        "model": "v1-8servo",
        "geometry_id": geometry_doc["geometry_id"],
        "source_file": bpy.data.filepath,
        "scene": scene.name,
        "units": "mm",
        "coordinate_frame": "Robot Root body frame (+X forward, +Y left, +Z up)",
        "mass_kg": geometry_doc["mass_kg"],
        "mass_measured": False,
        "frames": frames,
        "objects": objects_meta,
        "excluded": excluded,
        "sensor_references": sensor_refs,
    }
    (sim_dir / "assembly.json").write_text(json.dumps(assembly_manifest, indent=2) + "\n")

    summary = {
        "model_dir": str(model_dir),
        "meshes": len(objects_meta),
        "triangles": sum(o["triangles"] for o in objects_meta),
        "standing_root_height_mm": stand_height_mm,
        "estimated_mass_kg": geometry_doc["mass_kg"],
        "bodies": sorted(set(o["body"] for o in objects_meta)),
    }
    print(json.dumps(summary, indent=2))
    return summary
