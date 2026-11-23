#!/usr/bin/env python3
"""
Export self-contained static-web assets for Ainekio V1 (8-Servo ESP32-P4)
into apps/simulator.ainek.io/public/:

  1. public/assets/robots/ainekio-v1.glb       — Rigged CAD hierarchy from v3-2.blend assembly.npz
  2. public/sim/ainekio-v1-locomotion.xml      — Authoritative 8-DOF MuJoCo XML (v1_environment.py)
  3. public/sim/v1-physics-config.json         — Exact V1 kinematics, joints, sensors & actuator specs
  4. public/sim/policies/v1-neural-gait.{json,bin} — Production v1-microduck-p4 ONNX policy (<1e-5 parity)
  5. public/sim/policies/v1-neural-pose.{json,bin} — Production neural_pose_v1 ONNX policy (<1e-5 parity)
"""

from __future__ import annotations

import json
import math
import sys
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

if str(AINEKIO_ROOT) not in sys.path:
    sys.path.insert(0, str(AINEKIO_ROOT))
if str(AINEKIO_ROOT / "Master") not in sys.path:
    sys.path.insert(0, str(AINEKIO_ROOT / "Master"))

from gateway.neural_gait.v1_environment import (
    V1_JOINT_CODES,
    V1_JOINTS,
    V1_LEGS,
    build_v1_xml,
    load_v1_geometry,
)
from experiments.freestyle.neural_pose.v1_contract import (
    V1_CANONICAL_POSTURES_DEG,
    V1_CANONICAL_SUPPORT,
    V1_JOINT_CENTER_DEG,
    V1_JOINT_HALF_SPAN_DEG,
    V1_JOINT_MAX_DEG,
    V1_JOINT_MIN_DEG,
    V1_POSE_FEATURES,
    V1_POSE_SAMPLES,
    V1_POSE_SCHEMA,
)

V1_MODEL_DIR = AINEKIO_ROOT / "Slave/software/models/v1-8servo"
V1_GAIT_DIR = AINEKIO_ROOT / "build/neural-gait/v1-microduck-p4"
V1_POSE_DIR = AINEKIO_ROOT / "experiments/freestyle/artifacts/neural_pose_v1"


def _mj_mm_to_three_m(pts_mm: np.ndarray) -> np.ndarray:
    """Convert MuJoCo/CAD (+X fwd, +Y left, +Z up) in mm to Three.js (+Z fwd, +X left, +Y up) in m."""
    out = np.empty_like(pts_mm, dtype=np.float32)
    out[:, 0] = pts_mm[:, 1] * 1e-3
    out[:, 1] = pts_mm[:, 2] * 1e-3
    out[:, 2] = pts_mm[:, 0] * 1e-3
    return out


def _mj_vec_mm_to_three_m(v: list[float]) -> np.ndarray:
    return np.array([float(v[1]) * 1e-3, float(v[2]) * 1e-3, float(v[0]) * 1e-3], dtype=np.float64)


def _rot_y_mat4(deg: float) -> np.ndarray:
    rad = math.radians(deg)
    c, s = math.cos(rad), math.sin(rad)
    return np.array(
        [
            [c, 0.0, s, 0.0],
            [0.0, 1.0, 0.0, 0.0],
            [-s, 0.0, c, 0.0],
            [0.0, 0.0, 0.0, 1.0],
        ],
        dtype=np.float64,
    )


def _trans_mat4(t: np.ndarray) -> np.ndarray:
    m = np.eye(4, dtype=np.float64)
    m[:3, 3] = t
    return m


def _should_skip_mesh(name: str, body: str) -> bool:
    """Skip hidden internal PCBs, batteries, mounts & sub-mm screws to keep GLB lightweight (~4 MB)."""
    low = name.lower()
    if body == "torso":
        skip_tokens = (
            "board -",
            "battery -",
            "audio -",
            "imu -",
            "mount -",
            "pca9685",
            "mini560",
            "flex cable",
            "circuit",
            "screw head",
            "lead stubs",
            "upper gear cover",
        )
        return any(tok in low for tok in skip_tokens)
    # On legs, keep the shell, clockspring rotor/cup, bearing, horn & knee servo housing; skip tiny splines/screws
    skip_leg_tokens = (
        "output spline",
        "screw head",
        "horn center screw",
        "lead stubs",
        "upper gear cover",
    )
    return any(tok in low for tok in skip_leg_tokens)


def _simplify_cad_mesh(
    verts: np.ndarray,
    faces: np.ndarray,
    cell_m: float = 0.0014,
) -> tuple[np.ndarray, np.ndarray]:
    """Spatial vertex-grid clustering (1.4 mm cells) to reduce dense STEP CAD fillets ~9x
    while preserving silhouette, mechanical proportions, and sub-2 mm accuracy."""
    if len(faces) < 1200:
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


def export_v1_glb(out_glb: Path) -> None:
    asm = json.loads((V1_MODEL_DIR / "simulation/assembly.json").read_text())
    geo = load_v1_geometry()
    npz = np.load(V1_MODEL_DIR / "simulation/assembly.npz")
    frames = {k: np.asarray(v, dtype=np.float64) for k, v in asm["frames"].items()}
    inv_frames = {k: np.linalg.inv(v) for k, v in frames.items()}

    scene = trimesh.Scene()
    root_name = "V1_RobotRoot"
    scene.graph.update(frame_from="world", frame_to=root_name, matrix=np.eye(4))

    # Build hierarchical hip & knee frames for each of the 4 legs
    for leg in V1_LEGS:
        lg = geo["legs"][leg]
        hip_node = f"{leg}_hip_node"
        knee_node = f"{leg}_knee_node"
        hip_t = _mj_vec_mm_to_three_m(lg["hip_in_body_mm"])
        knee_t = _mj_vec_mm_to_three_m(lg["knee_in_hip_mm"])
        yaw_deg = float(lg["neutral_yaw_deg"])

        # Hip node: translate to hip_in_body_mm then rotate Y by neutral_yaw_deg
        scene.graph.update(
            frame_from=root_name,
            frame_to=hip_node,
            matrix=_trans_mat4(hip_t) @ _rot_y_mat4(yaw_deg),
        )
        # Knee node: translate inside hip local frame to knee_in_hip_mm
        scene.graph.update(
            frame_from=hip_node,
            frame_to=knee_node,
            matrix=_trans_mat4(knee_t),
        )

    # Group meshes by (parent_node, rounded_rgba) to minimize draw calls while keeping crisp CAD colors!
    buckets: dict[tuple[str, tuple[int, int, int]], tuple[list[np.ndarray], list[np.ndarray], list[float]]] = {}
    kept_meshes = 0
    kept_tris = 0

    for obj in asm["objects"]:
        name = obj["name"]
        body = obj["body"]
        if _should_skip_mesh(name, body):
            continue
        key = obj["key"]
        verts_body = np.asarray(npz[f"{key}_vertices"], dtype=np.float64)
        faces = np.asarray(npz[f"{key}_faces"], dtype=np.int32)
        if len(faces) == 0:
            continue

        if body == "torso":
            parent_node = root_name
            local_mm = verts_body
        elif body.endswith("_upper_leg"):
            leg = body[: -len("_upper_leg")]
            parent_node = f"{leg}_hip_node"
            inv_m = inv_frames[f"{leg}_hip"]
            local_mm = (verts_body @ inv_m[:3, :3].T) + inv_m[:3, 3]
        elif body.endswith("_lower_leg"):
            leg = body[: -len("_lower_leg")]
            parent_node = f"{leg}_knee_node"
            inv_m = inv_frames[f"{leg}_knee"]
            local_mm = (verts_body @ inv_m[:3, :3].T) + inv_m[:3, 3]
        else:
            continue

        verts_three = _mj_mm_to_three_m(local_mm)
        rgba = [float(c) for c in obj.get("rgba", [0.4, 0.4, 0.4, 1.0])]
        # Enhance dark PLA charcoal shell slightly for crisp studio readability in WebGL
        if "lower leg" in name.lower():
            rgba = [0.88, 0.90, 0.94, 1.0]
        elif "upper leg" in name.lower() or "chassis" in name.lower() or "enclosure" in name.lower():
            rgba = [0.14, 0.16, 0.20, 1.0]
        elif "middle housing" in name.lower():
            rgba = [0.10, 0.42, 0.82, 1.0]  # iconic translucent-blue MG90S servo body!

        color_key = (int(round(rgba[0] * 255)), int(round(rgba[1] * 255)), int(round(rgba[2] * 255)))
        bkey = (parent_node, color_key)
        if bkey not in buckets:
            buckets[bkey] = ([], [], rgba)
        v_list, f_list, _ = buckets[bkey]
        v_offset = sum(len(v) for v in v_list)
        v_list.append(verts_three)
        f_list.append(faces + v_offset)
        kept_meshes += 1
        kept_tris += len(faces)

    final_tris = 0
    for idx, ((parent_node, rgb), (v_list, f_list, rgba)) in enumerate(sorted(buckets.items())):
        verts = np.vstack(v_list).astype(np.float32)
        faces = np.vstack(f_list).astype(np.int32)
        # Keep curved lower-leg blades extra fine (0.55 mm) while lightly clustering torso/hips (1.0 mm)
        cell_m = 0.00055 if parent_node.endswith("knee_node") else 0.0010
        verts, faces = _simplify_cad_mesh(verts, faces, cell_m=cell_m)
        if len(faces) == 0:
            continue
        final_tris += len(faces)
        is_metal = rgb[0] > 180 and rgb[1] > 180 and rgb[2] > 180
        mat = trimesh.visual.material.PBRMaterial(
            name=f"v1_mat_{idx}",
            baseColorFactor=[rgba[0], rgba[1], rgba[2], 1.0],
            metallicFactor=0.45 if is_metal else 0.14,
            roughnessFactor=0.35 if is_metal else 0.62,
        )
        mesh = trimesh.Trimesh(vertices=verts, faces=faces, process=False)
        mesh.visual = trimesh.visual.TextureVisuals(material=mat)
        gname = f"geom_{parent_node}_{idx}"
        scene.add_geometry(mesh, node_name=gname, geom_name=gname, parent_node_name=parent_node)

    # Add dedicated V1_FaceDisplay textured quad flush on the front tilted 0.96in SSD1306 OLED glass!
    # In oled_m local frame:
    #   +X_local = [+0.667, 0, +0.745] (outward surface normal pointing forward-up!)
    #   +Y_local = [0, +1, 0]          (robot-left, width +-13.65 mm)
    #   +Z_local = [-0.745, 0, +0.667] (up along tilted OLED screen)
    oled_m = np.asarray(asm["sensor_references"]["V1 | Display - 0.96in SSD1306 OLED"]["matrix_body"], dtype=np.float64)
    oled_verts_body = np.asarray(npz["mesh_009_vertices"], dtype=np.float64)
    oled_inv = np.linalg.inv(oled_m)
    oled_local = (oled_verts_body @ oled_inv[:3, :3].T) + oled_inv[:3, 3]
    local_x_front = float(oled_local[:, 0].max()) + 0.9  # +0.9 mm proud of glass along outward +X_local normal
    local_z_mid = 0.5 * (float(oled_local[:, 2].min()) + float(oled_local[:, 2].max()))
    hw_y = 11.2  # 22.4 mm active OLED width
    hh_z = 5.8   # 11.6 mm active OLED height (~2:1 128x64 OLED)
    # Viewer facing robot sees -Y_body on viewer-left (u=0) and +Y_body on viewer-right (u=1)
    # CanvasTexture has flipY=false so v=0 is top (+Z_local) and v=1 is bottom (-Z_local)
    corners_local = np.array(
        [
            [local_x_front, -hw_y, local_z_mid + hh_z],  # top-left (u=0, v=0)
            [local_x_front, +hw_y, local_z_mid + hh_z],  # top-right (u=1, v=0)
            [local_x_front, +hw_y, local_z_mid - hh_z],  # bot-right (u=1, v=1)
            [local_x_front, -hw_y, local_z_mid - hh_z],  # bot-left (u=0, v=1)
        ],
        dtype=np.float64,
    )
    face_tris = np.array([[0, 3, 2], [0, 2, 1]], dtype=np.int32)
    corners_body = (corners_local @ oled_m[:3, :3].T) + oled_m[:3, 3]
    corners_three = _mj_mm_to_three_m(corners_body)
    uvs = np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]], dtype=np.float32)
    face_mat = trimesh.visual.material.PBRMaterial(
        name="V1_FaceDisplay_Mat",
        baseColorFactor=[0.05, 0.08, 0.12, 1.0],
        metallicFactor=0.0,
        roughnessFactor=0.25,
    )
    face_mesh = trimesh.Trimesh(vertices=corners_three, faces=face_tris, process=False)
    face_mesh.visual = trimesh.visual.TextureVisuals(uv=uvs, material=face_mat)
    scene.add_geometry(
        face_mesh,
        node_name="V1_FaceDisplay",
        geom_name="V1_FaceDisplay",
        parent_node_name=root_name,
    )

    out_glb.parent.mkdir(parents=True, exist_ok=True)
    glb_bytes = scene.export(file_type="glb")
    out_glb.write_bytes(glb_bytes)
    print(
        f"Exported {out_glb} ({len(glb_bytes) / (1024 * 1024):.2f} MB, "
        f"{kept_meshes} CAD parts -> {len(buckets)} merged batches, {kept_tris:,} -> {final_tris:,} tris)"
    )


def export_v1_mujoco_and_config(sim_dir: Path) -> None:
    geo = load_v1_geometry()
    xml = build_v1_xml(geo, include_floor=True)
    model = mujoco.MjModel.from_xml_string(xml)
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)

    # Verify V1 stands cleanly in MuJoCo for 200 steps!
    for _ in range(200):
        mujoco.mj_step(model, data)
    settled_z = float(data.qpos[2])
    print(f"  [MuJoCo V1 Stand Check] settled torso z = {settled_z:.4f} m (stand_z={geo['standing_root_height_mm']*1e-3:.4f} m)")
    if not (0.04 < settled_z < 0.08):
        raise RuntimeError(f"V1 failed MuJoCo stand check: z={settled_z:.4f} m")

    # Reset to clean initial pose for config extraction
    mujoco.mj_resetData(model, data)
    mujoco.mj_forward(model, data)

    qadr = [int(model.jnt_qposadr[model.joint(name).id]) for name in V1_JOINTS]
    vadr = [int(model.jnt_dofadr[model.joint(name).id]) for name in V1_JOINTS]
    foot_geoms = [f"{leg}_foot_geom" for leg in V1_LEGS]
    foot_geom_ids = [int(model.geom(name).id) for name in foot_geoms]

    xml_path = sim_dir / "ainekio-v1-locomotion.xml"
    xml_path.write_text(xml, encoding="utf-8")

    cfg = {
        "schemaVersion": 1,
        "model": "v1-8servo",
        "geometryId": geo["geometry_id"],
        "physicsHz": 500,
        "controlHz": 50,
        "standingRootHeightM": round(float(geo["standing_root_height_mm"]) * 1e-3, 6),
        "jointNames": list(V1_JOINTS),
        "jointCodes": list(V1_JOINT_CODES),
        "referenceJointDeg": [0.0] * 8,
        "jointLimitsMinDeg": list(V1_JOINT_MIN_DEG),
        "jointLimitsMaxDeg": list(V1_JOINT_MAX_DEG),
        "initQpos": [float(v) for v in data.qpos],
        "qadr": qadr,
        "vadr": vadr,
        "torsoBodyId": int(model.body("torso").id),
        "floorGeomId": int(model.geom("floor").id),
        "footGeoms": foot_geoms,
        "footGeomIds": foot_geom_ids,
        "gyroSensorAdr": int(model.sensor_adr[model.sensor("imu_gyro").id]),
        "accelSensorAdr": int(model.sensor_adr[model.sensor("imu_accel").id]),
        "quatSensorAdr": int(model.sensor_adr[model.sensor("imu_quat").id]),
        "cameraSiteBodyMm": list(geo["camera_site"]["position_body_mm"]),
        "legs": {
            leg: {
                "hipJointId": int(geo["legs"][leg]["hip_joint_id"]),
                "kneeJointId": int(geo["legs"][leg]["knee_joint_id"]),
                "neutralYawDeg": float(geo["legs"][leg]["neutral_yaw_deg"]),
                "hipSign": float(geo["legs"][leg]["hip_sign"]),
                "kneeSign": float(geo["legs"][leg]["knee_sign"]),
            }
            for leg in V1_LEGS
        },
    }
    cfg_path = sim_dir / "v1-physics-config.json"
    cfg_path.write_text(json.dumps(cfg, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"Exported {xml_path} ({xml_path.stat().st_size} B) and {cfg_path} ({cfg_path.stat().st_size} B)")


def _elu(x: np.ndarray) -> np.ndarray:
    return np.where(x > 0.0, x, np.expm1(x))


def _eval_mlp(obs: np.ndarray, mean: np.ndarray, std: np.ndarray, layers: list[tuple[np.ndarray, np.ndarray, str]]) -> np.ndarray:
    h = (obs.astype(np.float32) - mean) / std
    for w, b, act in layers:
        h = h @ w.T + b
        if act == "elu":
            h = _elu(h)
        elif act == "tanh":
            h = np.tanh(h)
    return h


def _pack_tensors(tensors: list[tuple[str, np.ndarray]]) -> tuple[bytes, dict[str, dict[str, Any]]]:
    chunks: list[bytes] = []
    layout: dict[str, dict[str, Any]] = {}
    off = 0
    for name, arr in tensors:
        f32 = np.ascontiguousarray(arr, dtype="<f4")
        layout[name] = {"offset": off, "length": int(f32.size), "shape": [int(d) for d in f32.shape]}
        chunks.append(f32.tobytes())
        off += int(f32.size)
    return b"".join(chunks), layout


def _find_div_std(inits: dict[str, np.ndarray], width: int) -> np.ndarray:
    for name, arr in inits.items():
        if name != "obs_normalizer._mean" and arr.size == width and arr.dtype == np.float32:
            if "Div" in name or "std" in name.lower():
                return arr.reshape(-1).astype(np.float32)
    raise RuntimeError(f"Could not locate normalizer std tensor of width {width}")


def export_v1_neural_policies(policies_dir: Path) -> None:
    policies_dir.mkdir(parents=True, exist_ok=True)

    # 1. V1 Neural Gait (v1-microduck-p4)
    gait_onnx = V1_GAIT_DIR / "policy.onnx"
    gait_meta_file = json.loads((V1_GAIT_DIR / "manifest.json").read_text())
    m_g = onnx.load(str(gait_onnx))
    inits_g = {i.name: numpy_helper.to_array(i) for i in m_g.graph.initializer}
    meta_g = {p.key: p.value for p in m_g.metadata_props}

    mean_g = inits_g["obs_normalizer._mean"].reshape(-1).astype(np.float32)
    std_g = _find_div_std(inits_g, mean_g.size)
    layer_specs = [
        ("mlp.0.weight", "mlp.0.bias", "elu"),
        ("mlp.2.weight", "mlp.2.bias", "elu"),
        ("mlp.4.weight", "mlp.4.bias", "elu"),
        ("mlp.6.weight", "mlp.6.bias", "tanh"),
    ]
    layers_g = [(inits_g[w].astype(np.float32), inits_g[b].astype(np.float32), act) for w, b, act in layer_specs]

    sess_g = ort.InferenceSession(str(gait_onnx), providers=["CPUExecutionProvider"])
    in_g, out_g = sess_g.get_inputs()[0].name, sess_g.get_outputs()[0].name
    rng = np.random.default_rng(20261121)
    golden_g = []
    max_err_g = 0.0
    for idx in range(3):
        x = np.zeros(mean_g.size, dtype=np.float32) if idx == 0 else rng.normal(0.0, 0.35, size=mean_g.size).astype(np.float32)
        ref = np.clip(sess_g.run([out_g], {in_g: x[None, :]})[0][0], -1.0, 1.0)
        got = np.clip(_eval_mlp(x, mean_g, std_g, layers_g), -1.0, 1.0)
        max_err_g = max(max_err_g, float(np.max(np.abs(ref - got))))
        golden_g.append({"seed": idx, "obs": [round(float(v), 6) for v in x], "action": [round(float(v), 7) for v in ref]})
    if max_err_g > 1e-5:
        raise RuntimeError(f"V1 Neural Gait parity failed: {max_err_g}")

    packed_g = [("mean", mean_g), ("std", std_g)]
    lmeta_g = []
    for i, (w, b, act) in enumerate(layers_g):
        packed_g.extend([(f"w{i}", w), (f"b{i}", b)])
        lmeta_g.append({"weight": f"w{i}", "bias": f"b{i}", "inDim": int(w.shape[1]), "outDim": int(w.shape[0]), "activation": act})
    blob_g, layout_g = _pack_tensors(packed_g)
    (policies_dir / "v1-neural-gait.bin").write_bytes(blob_g)
    gait_manifest = {
        "schemaVersion": 1,
        "kind": "v1-microduck-mjlab",
        "modelId": V1_GAIT_DIR.name,
        "observationSchema": meta_g.get("ainekio_schema", gait_meta_file["schema"]),
        "checkpointSha256": meta_g.get("checkpoint_sha256", ""),
        "geometryId": gait_meta_file["geometry_id"],
        "controlHz": 50,
        "gaitHz": 3.0,
        "obsDim": int(mean_g.size),
        "featureDim": 38,
        "historySamples": 8,
        "actionScaleDeg": [float(v) for v in gait_meta_file["action_scale_deg"]],
        "jointMinDeg": list(V1_JOINT_MIN_DEG),
        "jointMaxDeg": list(V1_JOINT_MAX_DEG),
        "defaultProfile": {"forwardMS": 0.16, "lateralMS": 0.09, "yawRadS": 1.2},
        "weightsFile": "/sim/policies/v1-neural-gait.bin",
        "layers": lmeta_g,
        "tensors": layout_g,
        "onnxMaxAbsError": max_err_g,
        "goldenTests": golden_g,
    }
    (policies_dir / "v1-neural-gait.json").write_text(json.dumps(gait_manifest, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"Exported V1 Neural Gait ({len(blob_g)/1024:.1f} KB, ONNX max_err={max_err_g:.2e})")

    # 2. V1 Neural Pose (neural_pose_v1 — reflection-equivariant residual MLP)
    pose_onnx = V1_POSE_DIR / "policy.onnx"
    pose_meta_file = json.loads((V1_POSE_DIR / "manifest.json").read_text())
    m_p = onnx.load(str(pose_onnx))
    inits_p = {i.name: numpy_helper.to_array(i) for i in m_p.graph.initializer}
    meta_p = {p.key: p.value for p in m_p.metadata_props}

    mean_p = inits_p["obs_normalizer._mean"].reshape(-1).astype(np.float32)
    std_p = _find_div_std(inits_p, mean_p.size)
    obs_perm = inits_p["obs_mirror_perm"].astype(np.int64)
    obs_sign = inits_p["obs_mirror_sign"].astype(np.float32)
    act_perm = inits_p["act_mirror_perm"].astype(np.int64)
    act_sign = inits_p["act_mirror_sign"].astype(np.float32)
    residual_scale = float(pose_meta_file.get("residual_scale", 0.35))
    layers_p = [(inits_p[w].astype(np.float32), inits_p[b].astype(np.float32), act) for w, b, act in layer_specs]

    def eval_equivariant_pose(obs: np.ndarray) -> np.ndarray:
        goal_norm = obs[33:41].astype(np.float32)
        obs_m = obs[obs_perm] * obs_sign
        r1 = _eval_mlp(obs, mean_p, std_p, layers_p)
        r2 = _eval_mlp(obs_m, mean_p, std_p, layers_p)[act_perm] * act_sign
        residual = 0.5 * (r1 + r2)
        return np.clip(goal_norm + residual_scale * residual, -1.0, 1.0)

    sess_p = ort.InferenceSession(str(pose_onnx), providers=["CPUExecutionProvider"])
    in_p, out_p = sess_p.get_inputs()[0].name, sess_p.get_outputs()[0].name
    golden_p = []
    max_err_p = 0.0
    for idx in range(3):
        x = np.zeros(mean_p.size, dtype=np.float32) if idx == 0 else rng.normal(0.0, 0.35, size=mean_p.size).astype(np.float32)
        ref = sess_p.run([out_p], {in_p: x[None, :]})[0][0]
        got = eval_equivariant_pose(x)
        max_err_p = max(max_err_p, float(np.max(np.abs(ref - got))))
        golden_p.append({"seed": idx, "obs": [round(float(v), 6) for v in x], "action": [round(float(v), 7) for v in ref]})
    if max_err_p > 1e-5:
        raise RuntimeError(f"V1 Neural Pose parity failed: {max_err_p}")

    packed_p = [("mean", mean_p), ("std", std_p), ("obsMirrorSign", obs_sign), ("actMirrorSign", act_sign)]
    lmeta_p = []
    for i, (w, b, act) in enumerate(layers_p):
        packed_p.extend([(f"w{i}", w), (f"b{i}", b)])
        lmeta_p.append({"weight": f"w{i}", "bias": f"b{i}", "inDim": int(w.shape[1]), "outDim": int(w.shape[0]), "activation": act})
    blob_p, layout_p = _pack_tensors(packed_p)
    (policies_dir / "v1-neural-pose.bin").write_bytes(blob_p)

    v1_motions = [
        {"id": "stand", "label": "Stand", "face": "default", "goalDeg": list(V1_CANONICAL_POSTURES_DEG["stand"]), "support": list(V1_CANONICAL_SUPPORT["stand"])},
        {"id": "sit", "label": "Sit", "face": "happy", "goalDeg": list(V1_CANONICAL_POSTURES_DEG["sit"]), "support": list(V1_CANONICAL_SUPPORT["sit"])},
        {"id": "lay_down", "label": "Lay Down", "face": "sleep", "goalDeg": list(V1_CANONICAL_POSTURES_DEG["lay_down"]), "support": list(V1_CANONICAL_SUPPORT["lay_down"])},
        {"id": "crouch", "label": "Crouch", "face": "curious", "goalDeg": list(V1_CANONICAL_POSTURES_DEG["crouch"]), "support": list(V1_CANONICAL_SUPPORT["crouch"])},
        {"id": "bow", "label": "Bow", "face": "happy", "goalDeg": list(V1_CANONICAL_POSTURES_DEG["bow"]), "support": list(V1_CANONICAL_SUPPORT["bow"])},
        {"id": "stretch", "label": "Stretch", "face": "excited", "goalDeg": list(V1_CANONICAL_POSTURES_DEG["stretch"]), "support": list(V1_CANONICAL_SUPPORT["stretch"])},
        {"id": "wave_fr", "label": "Wave Right", "face": "wave", "goalDeg": list(V1_CANONICAL_POSTURES_DEG["wave_fr"]), "support": list(V1_CANONICAL_SUPPORT["wave_fr"])},
        {"id": "wave_fl", "label": "Wave Left", "face": "wave", "goalDeg": list(V1_CANONICAL_POSTURES_DEG["wave_fl"]), "support": list(V1_CANONICAL_SUPPORT["wave_fl"])},
    ]
    pose_manifest = {
        "schemaVersion": 1,
        "kind": "v1-neural-pose-mjlab",
        "modelId": V1_POSE_DIR.name,
        "observationSchema": meta_p.get("ainekio_schema", V1_POSE_SCHEMA),
        "checkpointSha256": meta_p.get("checkpoint_sha256", ""),
        "geometryId": pose_meta_file["geometry_id"],
        "controlHz": 50,
        "obsDim": int(mean_p.size),
        "featureDim": V1_POSE_FEATURES,
        "historySamples": V1_POSE_SAMPLES,
        "goalSliceStart": 33,
        "goalSliceEnd": 41,
        "residualScale": residual_scale,
        "jointCenterDeg": list(V1_JOINT_CENTER_DEG),
        "jointHalfSpanDeg": list(V1_JOINT_HALF_SPAN_DEG),
        "jointMinDeg": list(V1_JOINT_MIN_DEG),
        "jointMaxDeg": list(V1_JOINT_MAX_DEG),
        "obsMirrorPerm": [int(v) for v in obs_perm],
        "actMirrorPerm": [int(v) for v in act_perm],
        "weightsFile": "/sim/policies/v1-neural-pose.bin",
        "layers": lmeta_p,
        "tensors": layout_p,
        "motions": v1_motions,
        "onnxMaxAbsError": max_err_p,
        "goldenTests": golden_p,
    }
    (policies_dir / "v1-neural-pose.json").write_text(json.dumps(pose_manifest, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"Exported V1 Neural Pose ({len(blob_p)/1024:.1f} KB, ONNX max_err={max_err_p:.2e}, {len(v1_motions)} motions)")


def main() -> int:
    export_v1_glb(SIM_ROOT / "public/assets/robots/ainekio-v1.glb")
    export_v1_mujoco_and_config(SIM_ROOT / "public/sim")
    export_v1_neural_policies(SIM_ROOT / "public/sim/policies")
    print("All Ainekio V1 static-web simulator assets exported & verified!")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
