#!/usr/bin/env python3
"""
Export self-contained static-web assets for Ainekio V3 (12-Servo Komatsu Option A-1 DS3225 PRO)
into apps/simulator.ainek.io/public/:

  1. public/assets/robots/ainekio-v3.glb            — Rigged 4-bar Komatsu CAD from v3-2.blend (scene 'v3')
  2. public/sim/ainekio-v3-locomotion.xml           — Authoritative closed-chain 4-bar MuJoCo XML
  3. public/sim/v3-physics-config.json              — Exact V3 kinematics, joints, linkage & DS3225 PRO specs
  4. public/sim/policies/v3-neural-gait.{json,bin}  — Production v3-microduck-p4 ONNX policy (<1e-5 parity)
  5. public/sim/policies/v3-neural-pose.{json,bin}  — Production neural_pose_v3 ONNX policy (<1e-5 parity)
"""

from __future__ import annotations

import json
import math
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import mujoco
import numpy as np
import onnx
from onnx import numpy_helper
import onnxruntime as ort
import trimesh

AINEKIO_ROOT = Path("/home/greggles/Ainekio")
SIM_ROOT = Path("/home/greggles/Ainekio/apps/simulator")
BLENDER_BIN = Path("/home/greggles/blender-5.2.2-linux-x64/blender")
BLEND_FILE = AINEKIO_ROOT / "Slave/hardware/v2-12servo/v3-2.blend"

if str(AINEKIO_ROOT) not in sys.path:
    sys.path.insert(0, str(AINEKIO_ROOT))
if str(AINEKIO_ROOT / "Master") not in sys.path:
    sys.path.insert(0, str(AINEKIO_ROOT / "Master"))

from gateway.neural_gait.v3_environment import (
    V3_JOINTS,
    V3_LEGS,
    V3_SERVO_EFFORT_NM,
    V3_SERVO_NO_LOAD_RAD_S,
    build_v3_xml,
    load_v3_geometry,
)
from experiments.freestyle.neural_pose.v3_contract import (
    V3_CANONICAL_POSTURES_DEG,
    V3_CANONICAL_SUPPORT,
    V3_JOINT_HALF_DEG,
    V3_JOINT_HI_DEG,
    V3_JOINT_LO_DEG,
    V3_JOINT_MID_DEG,
    V3_POSE_FEATURES,
    V3_POSE_SAMPLES,
    V3_POSE_SCHEMA,
    SLICE_GOAL,
    v3_pose_mirror_tables,
)

V3_GAIT_DIR = AINEKIO_ROOT / "build/neural-gait/v3-microduck-p4"
V3_POSE_DIR = AINEKIO_ROOT / "experiments/freestyle/artifacts/neural_pose_v3"
SH_Z_ROBOT_MM = 140.0  # Torso origin in MuJoCo sits at shoulder axis height z=140 mm


BLENDER_DUMP_SCRIPT = r"""
import json, math, sys
from pathlib import Path
import bpy, bmesh, mathutils
import numpy as np

out_npz = Path(sys.argv[sys.argv.index("--") + 1])
out_meta = Path(sys.argv[sys.argv.index("--") + 2])

sc = bpy.data.scenes["v3"]
bpy.context.window.scene = sc
vl = sc.view_layers[0]
orig = sc.objects["V3 | Robot Origin"]

# Force all 4 legs to exact CAD neutral (h_deg=0, alpha_deg=0, theta_deg=0)
# while keeping active COPY_ROTATION constraints so all 4 legs' double-parallelogram
# ankle linkages align cleanly at CAD neutral.
for leg_key in ("RL", "RR", "FL", "FR"):
    for obj_name in (f"V3 | {leg_key} | Shoulder Origin", f"V3 | {leg_key} | Linkage Calculation"):
        obj = bpy.data.objects.get(obj_name)
        if obj is not None:
            for prop in ("h_deg", "alpha_deg", "theta_deg"):
                if prop in obj:
                    obj[prop] = 0.0
            obj.update_tag()
    for cname in (
        f"V3 | {leg_key} | Ankle Axis (F)",
        f"V3 | {leg_key} | AnkleLink - S1 Pivot",
        f"V3 | {leg_key} | AnkleLink - Knee Idler Axis (D)",
        f"V3 | {leg_key} | AnkleLink - K2 Pivot",
    ):
        co = bpy.data.objects.get(cname)
        if co is not None:
            for c in co.constraints:
                c.mute = False
            co.update_tag()

sc.frame_set(sc.frame_current)
vl.update()
deps = bpy.context.evaluated_depsgraph_get()
orig_eval = orig.evaluated_get(deps)
inv_orig = orig_eval.matrix_world.inverted()

# Record exact neutral robot-frame positions of optional ankle & double-parallelogram pivots
# plus any residual ankle rest-pitch offset so neutral crawler soles sit 100% flat on z=-40.93mm.
pivots = {}
ankle_level_rad = {}
for leg_key in ("RL", "RR", "FL", "FR"):
    leg_pivots = {}
    for pkey, pname in (
        ("ankle", f"V3 | {leg_key} | Ankle Axis (F)"),
        ("ankleS1", f"V3 | {leg_key} | AnkleLink - S1 Pivot"),
        ("ankleIdler", f"V3 | {leg_key} | AnkleLink - Knee Idler Axis (D)"),
        ("ankleK2", f"V3 | {leg_key} | AnkleLink - K2 Pivot"),
    ):
        po = bpy.data.objects.get(pname)
        if po is not None:
            m_rob = inv_orig @ po.evaluated_get(deps).matrix_world
            leg_pivots[pkey] = [float(v) for v in m_rob.translation]
    pivots[leg_key] = leg_pivots

    # Measure flat crawler sole normal at neutral; if COPY_ROTATION rest reference tilts the sole,
    # record the exact Y-pitch leveling correction around the ankle pivot.
    foot_obj = bpy.data.objects.get(f"V3 | {leg_key} | Komatsu - Sloped Split-Toe Crawler Foot")
    if foot_obj is not None and "ankle" in leg_pivots:
        fe = foot_obj.evaluated_get(deps)
        fm = fe.to_mesh()
        m_rob = inv_orig @ fe.matrix_world
        best_a = 0.0
        best_n = None
        for poly in fm.polygons:
            n = (m_rob.to_3x3() @ poly.normal).normalized()
            if n.z < -0.7 and poly.area > best_a:
                best_a = poly.area
                best_n = n
        fe.to_mesh_clear()
        if best_n is not None:
            pitch = math.atan2(float(best_n.x), float(-best_n.z))
            if abs(pitch) > math.radians(0.5):
                ankle_level_rad[f"V3_{leg_key}_Ankle"] = (pitch, leg_pivots["ankle"])

# Collect truly visible objects under 'V3 | DSSERVO Robot' collection (excludes archived/hidden backups)
def collect_col_objs(lc, under_v3=False):
    if lc.exclude or lc.hide_viewport or lc.collection.hide_viewport:
        return set()
    now_v3 = under_v3 or (lc.name == "V3 | DSSERVO Robot")
    res = set()
    if now_v3:
        for o in lc.collection.objects:
            if not o.hide_viewport and not o.hide_render:
                res.add(o)
    for ch in lc.children:
        res |= collect_col_objs(ch, now_v3)
    return res

vis_objs = collect_col_objs(vl.layer_collection, False)

SKIP_TOKENS = (
    "board -", "radxa", "pca9685", "esp32", "lsm6ds3", "cd74hc4067",
    "battery -", "power -", "mini560", "hiletgo", "flex route", "circuit island",
    "screw", "hex nut", "m2.6", "m3x", "m3 ", "m2.5", "25t spline", "shim",
    "bearing 683zz", "presep_", "preartpass_", "preclip_", "prelapjoint_",
    "premid", "preouter", "prepod", "prerear", "preisogrid", "wire grommet",
    "msp2807_pcb", "msp2807_rear", "6-pin header",
)

def should_skip(name: str) -> bool:
    low = name.lower()
    return any(tok in low for tok in SKIP_TOKENS)

def classify_node(obj) -> str:
    # Walk ancestor chain to find which articulated rig node owns this mesh
    chain = []
    cur = obj
    while cur is not None and cur != orig:
        chain.append(cur.name)
        cur = cur.parent
    for leg in ("RL", "RR", "FL", "FR"):
        if any(f"V3 | {leg} | Ankle Axis (F)" == n for n in chain):
            return f"V3_{leg}_Ankle"
        if obj.name == f"V3 | {leg} | Komatsu - Sloped Split-Toe Crawler Foot":
            return f"V3_{leg}_Ankle"
        if any(f"V3 | {leg} | AnkleLink - K2 Pivot" == n for n in chain):
            return f"V3_{leg}_AnkleK2"
        if any(f"V3 | {leg} | AnkleLink - Knee Idler Axis (D)" == n for n in chain):
            return f"V3_{leg}_AnkleIdler"
        if any(f"V3 | {leg} | AnkleLink - S1 Pivot" == n for n in chain):
            return f"V3_{leg}_AnkleS1"
        if any(f"V3 | {leg} | Knee Axis (D)" == n for n in chain):
            return f"V3_{leg}_Knee"
        if any(f"V3 | {leg} | Rod Input Axis (P)" == n for n in chain):
            return f"V3_{leg}_Rod"
        if any(f"V3 | {leg} | Carrier Axis (O)" == n for n in chain):
            return f"V3_{leg}_Carrier"
        if any(f"V3 | {leg} | Crank Axis (C)" == n for n in chain):
            return f"V3_{leg}_Crank"
        if any(f"V3 | {leg} | Shoulder Origin" == n for n in chain):
            return f"V3_{leg}_Shoulder"
    return "V3_RobotRoot"

def extract_mat_props_from_material(m):
    col = [0.085, 0.095, 0.108, 1.0]
    metal = 0.35
    rough = 0.48
    emissive = None
    if m is not None:
        col = [float(c) for c in m.diffuse_color[:4]]
        metal = float(m.metallic)
        rough = float(m.roughness)
        if m.use_nodes and m.node_tree:
            for n in m.node_tree.nodes:
                if n.type == "BSDF_PRINCIPLED":
                    bc = n.inputs["Base Color"].default_value
                    col = [float(bc[0]), float(bc[1]), float(bc[2]), 1.0]
                    metal = float(n.inputs["Metallic"].default_value)
                    rough = float(n.inputs["Roughness"].default_value)
                    if "Emission Color" in n.inputs and "Emission Strength" in n.inputs:
                        es = float(n.inputs["Emission Strength"].default_value)
                        if es > 0.01:
                            ec = n.inputs["Emission Color"].default_value
                            scale = min(1.0, es)
                            emissive = [
                                min(1.0, float(ec[0]) * scale),
                                min(1.0, float(ec[1]) * scale),
                                min(1.0, float(ec[2]) * scale),
                            ]
                    break
        # glTF 2.0 baseColorFactor and emissiveFactor are linear RGB, matching Blender Principled BSDF.
        # Apply gentle studio-readability tuning only where needed (e.g. glowing LED emitters / very dark metals).
        low_m = m.name.lower()
        if "ws2812" in low_m and "emitter" in low_m:
            emissive = [0.96, 0.88, 0.58]
        elif "amber beacon" in low_m:
            emissive = [1.0, 0.38, 0.02]
        elif "cast gunmetal" in low_m:
            # Lift dark gunmetal slightly so metallic bevels stay distinct from Dark Iron under WebGL studio lights
            col = [0.13, 0.145, 0.165, 1.0]
            metal, rough = 0.58, 0.42
        elif "dark iron" in low_m:
            col = [0.055, 0.060, 0.068, 1.0]
            metal, rough = 0.40, 0.52
        elif "hazard black" in low_m or "black housing" in low_m:
            col = [0.022, 0.024, 0.028, 1.0]
            metal, rough = 0.05, 0.58
    return col, metal, rough, emissive

arrays = {}
meta = []
idx = 0
for obj in sorted(vis_objs, key=lambda o: o.name):
    if obj.type != "MESH" or should_skip(obj.name):
        continue
    # Ensure it is part of V3 | Robot Origin hierarchy (or unparented V3 fender liner)
    cur = obj
    under_orig = False
    while cur is not None:
        if cur == orig:
            under_orig = True
            break
        cur = cur.parent
    if not under_orig and not (obj.parent is None and obj.name.startswith("V3 | ")):
        continue

    eval_obj = obj.evaluated_get(deps)
    mesh = eval_obj.to_mesh()
    if not mesh or len(mesh.polygons) == 0:
        eval_obj.to_mesh_clear()
        continue
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bmesh.ops.triangulate(bm, faces=bm.faces[:])
    # Transform vertices directly into V3 | Robot Origin coordinates (mm)
    m_rob = inv_orig @ eval_obj.matrix_world
    all_verts = np.array([(m_rob @ v.co)[:] for v in bm.verts], dtype=np.float32)

    node = classify_node(obj)
    if node in ankle_level_rad:
        pitch, piv = ankle_level_rad[node]
        cp, sp = math.cos(pitch), math.sin(pitch)
        px, py, pz = piv
        dx = all_verts[:, 0] - px
        dz = all_verts[:, 2] - pz
        all_verts[:, 0] = px + cp * dx + sp * dz
        all_verts[:, 2] = pz - sp * dx + cp * dz

    # Split faces by per-polygon material_index so multi-material CAD meshes retain EVERY color!
    faces_by_mat = {}
    for f in bm.faces:
        mi = int(f.material_index)
        faces_by_mat.setdefault(mi, []).append([v.index for v in f.verts])
    bm.free()
    eval_obj.to_mesh_clear()

    slots = obj.material_slots
    for mi, f_list in sorted(faces_by_mat.items()):
        if not f_list:
            continue
        mat = slots[mi].material if (0 <= mi < len(slots) and slots[mi].material is not None) else obj.active_material
        # Skip the static Blender placeholder screen texture faces (replaced by live animated V3_FaceDisplay)
        if mat is not None and "komatsu chest screen" in mat.name.lower():
            continue
        f_arr = np.array(f_list, dtype=np.int32)
        used_v, inv_v = np.unique(f_arr, return_inverse=True)
        sub_verts = all_verts[used_v]
        sub_faces = inv_v.reshape(-1, 3).astype(np.int32)
        rgba, metal, rough, emissive = extract_mat_props_from_material(mat)
        key = f"m{idx:04d}"
        arrays[f"{key}_v"] = sub_verts
        arrays[f"{key}_f"] = sub_faces
        meta.append({
            "key": key,
            "name": f"{obj.name}[slot{mi}:{mat.name if mat else 'none'}]",
            "node": node,
            "rgba": rgba,
            "metallic": metal,
            "roughness": rough,
            "emissive": emissive,
        })
        idx += 1

np.savez_compressed(str(out_npz), **arrays)
out_meta.write_text(json.dumps({"meshes": meta, "pivots": pivots}, indent=2), encoding="utf-8")
print(f"Blender dumped {len(meta)} visible V3 material sub-meshes -> {out_npz}")
"""


def _mj_mm_to_three_m(pts_mm: np.ndarray) -> np.ndarray:
    """Convert MuJoCo/CAD (+X fwd, +Y left, +Z up) in mm to Three.js (+Z fwd, +X left, +Y up) in m."""
    out = np.empty_like(pts_mm, dtype=np.float32)
    out[:, 0] = pts_mm[:, 1] * 1e-3
    out[:, 1] = pts_mm[:, 2] * 1e-3
    out[:, 2] = pts_mm[:, 0] * 1e-3
    return out


def _mj_vec_mm_to_three_m(v: list[float]) -> np.ndarray:
    return np.array([float(v[1]) * 1e-3, float(v[2]) * 1e-3, float(v[0]) * 1e-3], dtype=np.float64)


def _trans_mat4(t: np.ndarray) -> np.ndarray:
    m = np.eye(4, dtype=np.float64)
    m[:3, 3] = t
    return m


def _simplify_cad_mesh(
    verts: np.ndarray,
    faces: np.ndarray,
    cell_m: float = 0.0012,
) -> tuple[np.ndarray, np.ndarray]:
    if len(faces) < 1000:
        return verts.astype(np.float32), faces.astype(np.int32)
    q = np.round(verts / cell_m).astype(np.int64)
    uniq, inv = np.unique(q, axis=0, return_inverse=True)
    new_v = np.zeros((len(uniq), 3), dtype=np.float32)
    counts = np.bincount(inv).astype(np.float32)
    np.add.at(new_v, inv, verts.astype(np.float32))
    new_v /= counts[:, None]
    nf = inv[faces]
    keep = (nf[:, 0] != nf[:, 1]) & (nf[:, 1] != nf[:, 2]) & (nf[:, 2] != nf[:, 0])
    nf = nf[keep]
    if len(nf) > 0:
        sf = np.sort(nf, axis=1)
        _, uidx = np.unique(sf, axis=0, return_index=True)
        nf = nf[np.sort(uidx)]
    return new_v, nf.astype(np.int32)


def export_v3_glb(out_glb: Path, geo: dict[str, Any]) -> None:
    if not BLENDER_BIN.exists():
        raise FileNotFoundError(f"Missing Blender CLI: {BLENDER_BIN}")
    if not BLEND_FILE.exists():
        raise FileNotFoundError(f"Missing v3-2.blend: {BLEND_FILE}")

    with tempfile.TemporaryDirectory(prefix="v3-export-") as td:
        td_path = Path(td)
        dump_script = td_path / "dump_v3.py"
        dump_npz = td_path / "v3_meshes.npz"
        dump_meta = td_path / "v3_meta.json"
        dump_script.write_text(BLENDER_DUMP_SCRIPT, encoding="utf-8")

        cmd = [
            str(BLENDER_BIN),
            "--background",
            str(BLEND_FILE),
            "--python",
            str(dump_script),
            "--",
            str(dump_npz),
            str(dump_meta),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        for line in res.stdout.splitlines():
            if "Blender dumped" in line:
                print(f"  {line}")

        raw_dump = json.loads(dump_meta.read_text(encoding="utf-8"))
        meta = raw_dump["meshes"]
        pivots = raw_dump.get("pivots", {})
        npz = np.load(dump_npz)

        # Build exact Option A-1 4-bar + double-parallelogram ankle neutral node origins in V3_RobotRoot frame (mm, z shifted by -140 mm!)
        lk = geo["linkage_mm"]
        L_crk = float(lk["crank"])
        t0 = float(lk["theta_zero_rad"])

        node_origin_body_mm: dict[str, np.ndarray] = {
            "V3_RobotRoot": np.array([0.0, 0.0, 0.0], dtype=np.float64)
        }
        scene = trimesh.Scene()
        scene.graph.update(frame_from="world", frame_to="V3_RobotRoot", matrix=np.eye(4))

        for phys_name in V3_LEGS:
            lg = geo["legs"][phys_name]
            cad_leg = lg["cad_leg"]
            leg_pivots = pivots.get(cad_leg, {})
            sh_rob = np.array(lg["shoulder_in_robot_mm"], dtype=np.float64)
            sh_body = np.array([sh_rob[0], sh_rob[1], sh_rob[2] - SH_Z_ROBOT_MM], dtype=np.float64)
            car_sh = np.array(lg["carrier_in_shoulder_mm"], dtype=np.float64)
            crk_sh = np.array(lg["crank_in_shoulder_mm"], dtype=np.float64)
            knee_sh = np.array(lg["knee_neutral_in_shoulder_mm"], dtype=np.float64)
            rod_sh = np.array(
                [crk_sh[0] + L_crk * math.cos(t0), crk_sh[1], crk_sh[2] + L_crk * math.sin(t0)],
                dtype=np.float64,
            )

            # Ankle pivot in robot-oriented Knee frame (rotate ankle_pivot_in_knee_mm by knee_neutral_rot_y_deg)
            if "ankle" in leg_pivots:
                ank_body = np.array(leg_pivots["ankle"], dtype=np.float64)
                ank_body[2] -= SH_Z_ROBOT_MM
                ank_in_knee_body = ank_body - (sh_body + knee_sh)
            else:
                ank_k = np.array(lg["ankle_pivot_in_knee_mm"], dtype=np.float64)
                ky = math.radians(float(lg["knee_neutral_rot_y_deg"]))
                cy, sy = math.cos(ky), math.sin(ky)
                ank_in_knee_body = np.array(
                    [cy * ank_k[0] + sy * ank_k[2], ank_k[1], -sy * ank_k[0] + cy * ank_k[2]],
                    dtype=np.float64,
                )
                ank_body = sh_body + knee_sh + ank_in_knee_body

            sh_node = f"V3_{cad_leg}_Shoulder"
            car_node = f"V3_{cad_leg}_Carrier"
            crk_node = f"V3_{cad_leg}_Crank"
            knee_node = f"V3_{cad_leg}_Knee"
            rod_node = f"V3_{cad_leg}_Rod"
            ank_node = f"V3_{cad_leg}_Ankle"

            node_origin_body_mm[sh_node] = sh_body
            node_origin_body_mm[car_node] = sh_body + car_sh
            node_origin_body_mm[crk_node] = sh_body + crk_sh
            node_origin_body_mm[knee_node] = sh_body + knee_sh
            node_origin_body_mm[rod_node] = sh_body + rod_sh
            node_origin_body_mm[ank_node] = ank_body

            scene.graph.update(frame_from="V3_RobotRoot", frame_to=sh_node, matrix=_trans_mat4(_mj_vec_mm_to_three_m(sh_body.tolist())))
            scene.graph.update(frame_from=sh_node, frame_to=car_node, matrix=_trans_mat4(_mj_vec_mm_to_three_m(car_sh.tolist())))
            scene.graph.update(frame_from=sh_node, frame_to=crk_node, matrix=_trans_mat4(_mj_vec_mm_to_three_m(crk_sh.tolist())))
            scene.graph.update(frame_from=sh_node, frame_to=knee_node, matrix=_trans_mat4(_mj_vec_mm_to_three_m(knee_sh.tolist())))
            scene.graph.update(frame_from=sh_node, frame_to=rod_node, matrix=_trans_mat4(_mj_vec_mm_to_three_m(rod_sh.tolist())))
            scene.graph.update(frame_from=knee_node, frame_to=ank_node, matrix=_trans_mat4(_mj_vec_mm_to_three_m(ank_in_knee_body.tolist())))

            # Optional 2-stage double-parallelogram linkage nodes (present on FR prototype & future mirrored legs)
            if "ankleS1" in leg_pivots:
                s1_body = np.array(leg_pivots["ankleS1"], dtype=np.float64)
                s1_body[2] -= SH_Z_ROBOT_MM
                s1_node = f"V3_{cad_leg}_AnkleS1"
                node_origin_body_mm[s1_node] = s1_body
                scene.graph.update(frame_from=sh_node, frame_to=s1_node, matrix=_trans_mat4(_mj_vec_mm_to_three_m((s1_body - sh_body).tolist())))
            if "ankleIdler" in leg_pivots:
                id_body = np.array(leg_pivots["ankleIdler"], dtype=np.float64)
                id_body[2] -= SH_Z_ROBOT_MM
                id_node = f"V3_{cad_leg}_AnkleIdler"
                node_origin_body_mm[id_node] = id_body
                scene.graph.update(frame_from=knee_node, frame_to=id_node, matrix=_trans_mat4(_mj_vec_mm_to_three_m((id_body - (sh_body + knee_sh)).tolist())))
                if "ankleK2" in leg_pivots:
                    k2_body = np.array(leg_pivots["ankleK2"], dtype=np.float64)
                    k2_body[2] -= SH_Z_ROBOT_MM
                    k2_node = f"V3_{cad_leg}_AnkleK2"
                    node_origin_body_mm[k2_node] = k2_body
                    scene.graph.update(frame_from=id_node, frame_to=k2_node, matrix=_trans_mat4(_mj_vec_mm_to_three_m((k2_body - id_body).tolist())))

        # Bucket meshes by (parent_node, rounded color, metallic, roughness, emissive) for tiny draw-call count!
        buckets: dict[tuple[str, tuple[int, int, int, int, int, int, int, int]], tuple[list[np.ndarray], list[np.ndarray], list[float], float, float, list[float] | None]] = {}
        raw_tris = 0
        for item in meta:
            node = item["node"]
            origin_body = node_origin_body_mm.get(node, node_origin_body_mm["V3_RobotRoot"])
            verts_rob = np.asarray(npz[f"{item['key']}_v"], dtype=np.float64)
            faces = np.asarray(npz[f"{item['key']}_f"], dtype=np.int32)
            # Shift robot origin Z by -140 mm to torso shoulder-height origin, then into node local frame
            verts_body = verts_rob.copy()
            verts_body[:, 2] -= SH_Z_ROBOT_MM
            verts_local_mm = verts_body - origin_body[None, :]
            verts_three = _mj_mm_to_three_m(verts_local_mm)

            rgba = item["rgba"]
            metal = float(item["metallic"])
            rough = float(item["roughness"])
            emissive = item.get("emissive")
            er, eg, eb = emissive if emissive else (0.0, 0.0, 0.0)
            ckey = (
                int(round(rgba[0] * 255)),
                int(round(rgba[1] * 255)),
                int(round(rgba[2] * 255)),
                int(round(metal * 20)),
                int(round(rough * 20)),
                int(round(er * 255)),
                int(round(eg * 255)),
                int(round(eb * 255)),
            )
            bkey = (node, ckey)
            if bkey not in buckets:
                buckets[bkey] = ([], [], rgba, metal, rough, emissive)
            v_list, f_list, _, _, _, _ = buckets[bkey]
            v_off = sum(len(v) for v in v_list)
            v_list.append(verts_three)
            f_list.append(faces + v_off)
            raw_tris += len(faces)

        final_tris = 0
        for idx, ((parent_node, _ckey), (v_list, f_list, rgba, metal, rough, emissive)) in enumerate(sorted(buckets.items())):
            verts = np.vstack(v_list).astype(np.float32)
            faces = np.vstack(f_list).astype(np.int32)
            verts, faces = _simplify_cad_mesh(verts, faces, cell_m=0.0011)
            if len(faces) == 0:
                continue
            final_tris += len(faces)
            mat_kwargs: dict[str, Any] = {
                "name": f"v3_mat_{idx}",
                "baseColorFactor": [rgba[0], rgba[1], rgba[2], 1.0],
                "metallicFactor": metal,
                "roughnessFactor": rough,
            }
            if emissive:
                mat_kwargs["emissiveFactor"] = emissive
            mat = trimesh.visual.material.PBRMaterial(**mat_kwargs)
            mesh = trimesh.Trimesh(vertices=verts, faces=faces, process=False)
            mesh.visual = trimesh.visual.TextureVisuals(material=mat)
            gname = f"geom_{parent_node}_{idx}"
            scene.add_geometry(mesh, node_name=gname, geom_name=gname, parent_node_name=parent_node)

        # Add dedicated V3_FaceDisplay textured quad cleanly framed inside the Display Bezel aperture!
        # Display Bezel inner aperture: x=194.7..196.4 mm, y in [-26.3, +26.3] (52.6 mm), z in [119.5, 147.9] (28.4 mm).
        # Aspect ratio 52.0 x 27.8 mm (1.871) matches the 320x170 (1.882) live Ainekio face canvas with zero clipping!
        x_front = 195.0
        hw_y = 26.0
        z_mid = 133.7 - SH_Z_ROBOT_MM  # -6.3 mm (vertical center of bezel aperture 119.5..147.9)
        hh_z = 13.9
        # Viewer facing robot (+Z_three -> -Z_three): -Y_robot (-X_three) is viewer-left (u=0),
        # +Y_robot (+X_three) is viewer-right (u=1).
        # Note: trimesh flips v -> 1 - v on GLB export, so passing v=1 at top and v=0 at bottom
        # produces raw glTF TEXCOORD_0 v=0 at top and v=1 at bottom (right-side up with flipY=false)!
        corners_body = np.array(
            [
                [x_front, -hw_y, z_mid + hh_z],  # top-left (glTF u=0, v=0)
                [x_front, +hw_y, z_mid + hh_z],  # top-right (glTF u=1, v=0)
                [x_front, +hw_y, z_mid - hh_z],  # bot-right (glTF u=1, v=1)
                [x_front, -hw_y, z_mid - hh_z],  # bot-left (glTF u=0, v=1)
            ],
            dtype=np.float64,
        )
        corners_three = _mj_mm_to_three_m(corners_body)
        face_tris = np.array([[0, 3, 2], [0, 2, 1]], dtype=np.int32)
        uvs = np.array([[0.0, 1.0], [1.0, 1.0], [1.0, 0.0], [0.0, 0.0]], dtype=np.float32)
        face_mat = trimesh.visual.material.PBRMaterial(
            name="V3_FaceDisplay_Mat",
            baseColorFactor=[0.04, 0.06, 0.10, 1.0],
            metallicFactor=0.0,
            roughnessFactor=0.22,
        )
        face_mesh = trimesh.Trimesh(vertices=corners_three, faces=face_tris, process=False)
        face_mesh.visual = trimesh.visual.TextureVisuals(uv=uvs, material=face_mat)
        scene.add_geometry(
            face_mesh,
            node_name="V3_FaceDisplay",
            geom_name="V3_FaceDisplay",
            parent_node_name="V3_RobotRoot",
        )

        out_glb.parent.mkdir(parents=True, exist_ok=True)
        glb_bytes = scene.export(file_type="glb")
        out_glb.write_bytes(glb_bytes)
        print(
            f"Exported {out_glb} ({len(glb_bytes) / (1024 * 1024):.2f} MB, "
            f"{len(meta)} CAD parts -> {len(buckets)} merged batches, {raw_tris:,} -> {final_tris:,} tris)"
        )


def export_v3_mujoco_and_config(sim_dir: Path, geo: dict[str, Any]) -> None:
    xml = build_v3_xml(geo, floor=True)
    model = mujoco.MjModel.from_xml_string(xml)
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)

    # Verify V3 stands cleanly in MuJoCo for 200 steps!
    for _ in range(200):
        mujoco.mj_step(model, data)
    settled_z = float(data.qpos[2])
    stand_z = float(geo["standing_shoulder_height_mm"]) * 1e-3
    print(f"  [MuJoCo V3 Stand Check] settled torso z = {settled_z:.4f} m (stand_z={stand_z:.4f} m, ncon={data.ncon})")
    if not (0.14 < settled_z < 0.22):
        raise RuntimeError(f"V3 failed MuJoCo stand check: z={settled_z:.4f} m")

    mujoco.mj_resetData(model, data)
    mujoco.mj_forward(model, data)

    qadr = [int(model.jnt_qposadr[model.joint(name).id]) for name in V3_JOINTS]
    vadr = [int(model.jnt_dofadr[model.joint(name).id]) for name in V3_JOINTS]
    foot_geoms = [f"{leg}_foot" for leg in V3_LEGS]
    foot_geom_ids = [int(model.geom(name).id) for name in foot_geoms]

    xml_path = sim_dir / "ainekio-v3-locomotion.xml"
    xml_path.write_text(xml, encoding="utf-8")

    cfg = {
        "schemaVersion": 1,
        "model": "v3-12servo",
        "geometryId": geo["geometry_id"],
        "physicsHz": 500,
        "controlHz": 50,
        "standingRootHeightM": round(stand_z, 6),
        "torqueNm": V3_SERVO_EFFORT_NM,
        "motorNoLoadSpeedRadS": V3_SERVO_NO_LOAD_RAD_S,
        "jointNames": list(V3_JOINTS),
        "referenceJointDeg": [0.0] * 12,
        "jointLimitsMinDeg": list(V3_JOINT_LO_DEG),
        "jointLimitsMaxDeg": list(V3_JOINT_HI_DEG),
        "initQpos": [round(float(v), 6) for v in data.qpos],
        "qadr": qadr,
        "vadr": vadr,
        "torsoBodyId": int(model.body("torso").id),
        "floorGeomId": int(model.geom("floor").id),
        "footGeoms": foot_geoms,
        "footGeomIds": foot_geom_ids,
        "gyroSensorAdr": int(model.sensor_adr[model.sensor("imu_gyro").id]),
        "accelSensorAdr": int(model.sensor_adr[model.sensor("imu_accel").id]),
        "linkageMm": geo["linkage_mm"],
        "legMechanics": geo.get("leg_mechanics"),
        "legs": {
            leg: {
                "cadLeg": geo["legs"][leg]["cad_leg"],
                "jointIds": geo["legs"][leg]["joint_ids"],
                "shoulderRollSign": geo["legs"][leg]["shoulder_roll_sign"],
                "shoulderInRobotMm": geo["legs"][leg]["shoulder_in_robot_mm"],
                "carrierInShoulderMm": geo["legs"][leg]["carrier_in_shoulder_mm"],
                "crankInShoulderMm": geo["legs"][leg]["crank_in_shoulder_mm"],
                "kneeNeutralInShoulderMm": geo["legs"][leg]["knee_neutral_in_shoulder_mm"],
                "kneeNeutralRotYDeg": geo["legs"][leg]["knee_neutral_rot_y_deg"],
                "betaZeroRad": geo["legs"][leg]["beta_zero_rad"],
                "gammaZeroRad": geo["legs"][leg]["gamma_zero_rad"],
                "soleCenterInKneeMm": geo["legs"][leg]["sole_center_in_knee_mm"],
                "soleCenterInRobotMm": geo["legs"][leg]["sole_center_in_robot_mm"],
                "anklePivotInKneeMm": geo["legs"][leg].get("ankle_pivot_in_knee_mm"),
            }
            for leg in V3_LEGS
        },
    }
    cfg_path = sim_dir / "v3-physics-config.json"
    cfg_path.write_text(json.dumps(cfg, separators=(",", ":")), encoding="utf-8")
    print(f"Exported {xml_path} ({len(xml)} B) and {cfg_path} ({cfg_path.stat().st_size} B)")


def _pack_tensors(tensors: dict[str, np.ndarray]) -> tuple[bytes, dict[str, Any]]:
    chunks: list[np.ndarray] = []
    layout: dict[str, Any] = {}
    offset = 0
    for name, arr in tensors.items():
        flat = np.ascontiguousarray(arr, dtype=np.float32).reshape(-1)
        layout[name] = {
            "offset": offset,
            "length": int(flat.size),
            "shape": [int(d) for d in arr.shape],
        }
        chunks.append(flat)
        offset += int(flat.size)
    packed = np.concatenate(chunks).astype("<f4").tobytes()
    return packed, layout


def _elu(x: np.ndarray) -> np.ndarray:
    return np.where(x > 0.0, x, np.expm1(x))


def export_v3_gait_policy(policies_dir: Path) -> None:
    onnx_path = V3_GAIT_DIR / "policy.onnx"
    manifest_src = json.loads((V3_GAIT_DIR / "manifest.json").read_text())
    model = onnx.load(str(onnx_path))
    inits = {t.name: numpy_helper.to_array(t) for t in model.graph.initializer}

    mean = inits["obs_normalizer._mean"].reshape(-1).astype(np.float32)
    div_key = next(k for k in inits if "Div" in k or "_std" in k)
    std = inits[div_key].reshape(-1).astype(np.float32)
    w0 = inits["mlp.0.weight"].astype(np.float32)
    b0 = inits["mlp.0.bias"].astype(np.float32)
    w1 = inits["mlp.2.weight"].astype(np.float32)
    b1 = inits["mlp.2.bias"].astype(np.float32)
    w2 = inits["mlp.4.weight"].astype(np.float32)
    b2 = inits["mlp.4.bias"].astype(np.float32)
    w3 = inits["mlp.6.weight"].astype(np.float32)
    b3 = inits["mlp.6.bias"].astype(np.float32)

    packed, layout = _pack_tensors(
        {
            "mean": mean,
            "std": std,
            "w0": w0,
            "b0": b0,
            "w1": w1,
            "b1": b1,
            "w2": w2,
            "b2": b2,
            "w3": w3,
            "b3": b3,
        }
    )

    sess = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
    in_name = sess.get_inputs()[0].name
    golden = []
    max_err = 0.0
    for seed in range(3):
        rng = np.random.default_rng(300 + seed)
        obs = np.zeros((1, 400), dtype=np.float32) if seed == 0 else rng.normal(0.0, 0.35, size=(1, 400)).astype(np.float32)
        ort_out = sess.run(None, {in_name: obs})[0][0]
        x = (obs[0] - mean) / std
        x = _elu(w0 @ x + b0)
        x = _elu(w1 @ x + b1)
        x = _elu(w2 @ x + b2)
        y = np.tanh(w3 @ x + b3)
        err = float(np.max(np.abs(y - ort_out)))
        max_err = max(max_err, err)
        golden.append(
            {
                "seed": seed,
                "obs": [round(float(v), 6) for v in obs[0]],
                "action": [round(float(v), 7) for v in ort_out],
            }
        )
    if max_err > 1e-5:
        raise RuntimeError(f"V3 Neural Gait ONNX parity error too large: {max_err}")

    out_bin = policies_dir / "v3-neural-gait.bin"
    out_json = policies_dir / "v3-neural-gait.json"
    out_bin.write_bytes(packed)
    manifest = {
        "schemaVersion": 1,
        "kind": "v3-microduck-mjlab",
        "modelId": "v3-microduck-p4",
        "observationSchema": manifest_src["schema"],
        "geometryId": manifest_src["geometry_id"],
        "controlHz": 50,
        "gaitHz": float(manifest_src.get("gait_hz", 2.2)),
        "obsDim": 400,
        "featureDim": 50,
        "historySamples": 8,
        "actionScaleDeg": list(manifest_src.get("action_scale_deg", [25.0, 45.0, 45.0])),
        "jointMinDeg": list(V3_JOINT_LO_DEG),
        "jointMaxDeg": list(V3_JOINT_HI_DEG),
        "defaultProfile": {
            "forwardMS": 0.35,
            "lateralMS": 0.20,
            "yawRadS": 1.50,
        },
        "weightsFile": "/sim/policies/v3-neural-gait.bin",
        "layers": [
            {"weight": "w0", "bias": "b0", "inDim": int(w0.shape[1]), "outDim": int(w0.shape[0]), "activation": "elu"},
            {"weight": "w1", "bias": "b1", "inDim": int(w1.shape[1]), "outDim": int(w1.shape[0]), "activation": "elu"},
            {"weight": "w2", "bias": "b2", "inDim": int(w2.shape[1]), "outDim": int(w2.shape[0]), "activation": "elu"},
            {"weight": "w3", "bias": "b3", "inDim": int(w3.shape[1]), "outDim": int(w3.shape[0]), "activation": "tanh"},
        ],
        "tensors": layout,
        "onnxMaxAbsError": max_err,
        "goldenTests": golden,
    }
    out_json.write_text(json.dumps(manifest, separators=(",", ":")), encoding="utf-8")
    print(f"Exported V3 Neural Gait ({len(packed) / 1024:.1f} KB, ONNX max_err={max_err:.2e})")


def export_v3_pose_policy(policies_dir: Path) -> None:
    onnx_path = V3_POSE_DIR / "policy.onnx"
    manifest_src = json.loads((V3_POSE_DIR / "manifest.json").read_text())
    model = onnx.load(str(onnx_path))
    inits = {t.name: numpy_helper.to_array(t) for t in model.graph.initializer}

    mean = inits["obs_normalizer._mean"].reshape(-1).astype(np.float32)
    div_key = next(k for k in inits if "Div" in k or "_std" in k)
    std = inits[div_key].reshape(-1).astype(np.float32)
    obs_mirror_perm = inits["obs_mirror_perm"].reshape(-1).astype(np.int32)
    obs_mirror_sign = inits["obs_mirror_sign"].reshape(-1).astype(np.float32)
    act_mirror_perm = inits["act_mirror_perm"].reshape(-1).astype(np.int32)
    act_mirror_sign = inits["act_mirror_sign"].reshape(-1).astype(np.float32)
    w0 = inits["mlp.0.weight"].astype(np.float32)
    b0 = inits["mlp.0.bias"].astype(np.float32)
    w1 = inits["mlp.2.weight"].astype(np.float32)
    b1 = inits["mlp.2.bias"].astype(np.float32)
    w2 = inits["mlp.4.weight"].astype(np.float32)
    b2 = inits["mlp.4.bias"].astype(np.float32)
    w3 = inits["mlp.6.weight"].astype(np.float32)
    b3 = inits["mlp.6.bias"].astype(np.float32)

    residual_scale = float(manifest_src.get("residual_scale", 0.35))
    goal_start = int(SLICE_GOAL.start)
    goal_end = int(SLICE_GOAL.stop)

    packed, layout = _pack_tensors(
        {
            "mean": mean,
            "std": std,
            "obsMirrorSign": obs_mirror_sign,
            "actMirrorSign": act_mirror_sign,
            "w0": w0,
            "b0": b0,
            "w1": w1,
            "b1": b1,
            "w2": w2,
            "b2": b2,
            "w3": w3,
            "b3": b3,
        }
    )

    def run_mlp(obs_vec: np.ndarray) -> np.ndarray:
        x = (obs_vec - mean) / std
        x = _elu(w0 @ x + b0)
        x = _elu(w1 @ x + b1)
        x = _elu(w2 @ x + b2)
        return np.tanh(w3 @ x + b3)

    sess = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
    in_name = sess.get_inputs()[0].name
    golden = []
    max_err = 0.0
    for seed in range(3):
        rng = np.random.default_rng(400 + seed)
        obs = np.zeros((1, 1290), dtype=np.float32) if seed == 0 else rng.normal(0.0, 0.35, size=(1, 1290)).astype(np.float32)
        ort_out = sess.run(None, {in_name: obs})[0][0]
        y1 = run_mlp(obs[0])
        m_obs = obs[0][obs_mirror_perm] * obs_mirror_sign
        y2 = run_mlp(m_obs)[act_mirror_perm] * act_mirror_sign
        sym = 0.5 * (y1 + y2) * residual_scale
        pred = np.clip(obs[0][goal_start:goal_end] + sym, -1.0, 1.0)
        err = float(np.max(np.abs(pred - ort_out)))
        max_err = max(max_err, err)
        golden.append(
            {
                "seed": seed,
                "obs": [round(float(v), 6) for v in obs[0]],
                "action": [round(float(v), 7) for v in ort_out],
            }
        )
    if max_err > 1e-5:
        raise RuntimeError(f"V3 Neural Pose ONNX parity error too large: {max_err}")

    motions = [
        {
            "id": mid,
            "label": label,
            "face": face,
            "goalDeg": [float(v) for v in V3_CANONICAL_POSTURES_DEG[mid]],
            "support": [float(v) for v in V3_CANONICAL_SUPPORT[mid]],
        }
        for mid, label, face in [
            ("stand", "Stand", "default"),
            ("sit", "Sit", "happy"),
            ("lay_down", "Lay Down", "sleep"),
            ("crouch", "Crouch", "curious"),
            ("bow", "Bow", "happy"),
            ("stretch", "Stretch", "excited"),
            ("wave_fr", "Wave Right", "wave"),
            ("wave_fl", "Wave Left", "wave"),
        ]
    ]

    out_bin = policies_dir / "v3-neural-pose.bin"
    out_json = policies_dir / "v3-neural-pose.json"
    out_bin.write_bytes(packed)
    manifest = {
        "schemaVersion": 1,
        "kind": "v3-neural-pose-mjlab",
        "modelId": "neural_pose_v3",
        "observationSchema": V3_POSE_SCHEMA,
        "geometryId": manifest_src["geometry_id"],
        "controlHz": 50,
        "obsDim": V3_POSE_FEATURES * V3_POSE_SAMPLES,
        "featureDim": V3_POSE_FEATURES,
        "historySamples": V3_POSE_SAMPLES,
        "goalSliceStart": goal_start,
        "goalSliceEnd": goal_end,
        "residualScale": residual_scale,
        "jointCenterDeg": [float(v) for v in V3_JOINT_MID_DEG],
        "jointHalfSpanDeg": [float(v) for v in V3_JOINT_HALF_DEG],
        "jointMinDeg": [float(v) for v in V3_JOINT_LO_DEG],
        "jointMaxDeg": [float(v) for v in V3_JOINT_HI_DEG],
        "obsMirrorPerm": [int(v) for v in obs_mirror_perm],
        "actMirrorPerm": [int(v) for v in act_mirror_perm],
        "weightsFile": "/sim/policies/v3-neural-pose.bin",
        "layers": [
            {"weight": "w0", "bias": "b0", "inDim": int(w0.shape[1]), "outDim": int(w0.shape[0]), "activation": "elu"},
            {"weight": "w1", "bias": "b1", "inDim": int(w1.shape[1]), "outDim": int(w1.shape[0]), "activation": "elu"},
            {"weight": "w2", "bias": "b2", "inDim": int(w2.shape[1]), "outDim": int(w2.shape[0]), "activation": "elu"},
            {"weight": "w3", "bias": "b3", "inDim": int(w3.shape[1]), "outDim": int(w3.shape[0]), "activation": "tanh"},
        ],
        "tensors": layout,
        "motions": motions,
        "onnxMaxAbsError": max_err,
        "goldenTests": golden,
    }
    out_json.write_text(json.dumps(manifest, separators=(",", ":")), encoding="utf-8")
    print(f"Exported V3 Neural Pose ({len(packed) / 1024:.1f} KB, ONNX max_err={max_err:.2e}, {len(motions)} motions)")


def main() -> None:
    geo = load_v3_geometry()
    export_v3_glb(SIM_ROOT / "public/assets/robots/ainekio-v3.glb", geo)
    export_v3_mujoco_and_config(SIM_ROOT / "public/sim", geo)
    policies_dir = SIM_ROOT / "public/sim/policies"
    policies_dir.mkdir(parents=True, exist_ok=True)
    export_v3_gait_policy(policies_dir)
    export_v3_pose_policy(policies_dir)
    print("All Ainekio V3 static-web simulator assets exported & verified!")


if __name__ == "__main__":
    main()
