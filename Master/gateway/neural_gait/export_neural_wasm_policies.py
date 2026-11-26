#!/usr/bin/env python3
"""Export Ainekio's active Neural Gait & Neural Pose ONNX checkpoints,
four-bar PoseManifold constants, and compiled Motion Library programs
for 100% client-side static-web execution in simulator.ainek.io.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sqlite3
import sys

import numpy as np
import onnx
from onnx import numpy_helper
import onnxruntime as ort

AINEKIO_ROOT = Path(__file__).resolve().parents[3]
if str(AINEKIO_ROOT / "Master") not in sys.path:
    sys.path.insert(0, str(AINEKIO_ROOT / "Master"))
if str(AINEKIO_ROOT / "Slave/software") not in sys.path:
    sys.path.insert(0, str(AINEKIO_ROOT / "Slave/software"))
if str(AINEKIO_ROOT) not in sys.path:
    sys.path.insert(0, str(AINEKIO_ROOT))

from experiments.freestyle.compact_wire import ProgramEncoding
from experiments.freestyle.neural_pose.contract import (
    JOINTS,
    POSE_FEATURES,
    POSE_FOOT_SCALE_MM,
    POSE_OBS_SIZE,
    POSE_SAMPLES,
    POSE_SCHEMA,
)
from experiments.freestyle.neural_pose.goals import (
    STAND_ANGLES_DEG,
    PoseManifold,
    _fast_numpy_body,
    compile_goal_segments,
)

DEFAULT_GAIT_DIR = AINEKIO_ROOT / "build/neural-gait/microduck-v20-studya-p4"
DEFAULT_POSE_DIR = AINEKIO_ROOT / "experiments/freestyle/artifacts/neural-pose-active"
DEFAULT_MOTION_DB = AINEKIO_ROOT / "build/gateway/physical/motion-library.sqlite"
DEFAULT_OUT_DIR = Path("/home/greggles/Ainekio/apps/simulator/public/sim/policies")

# Curated production motions from Ainekio's Motion Library (id, label, preferred family)
CURATED_MOTIONS: tuple[tuple[str, str, str], ...] = (
    ("stand", "Stand", "natural_legacy_stand"),
    ("sit", "Sit", "natural_legacy_sit"),
    ("lay", "Lay Down", "natural_legacy_lay_down"),
    ("wave", "Wave", "freestyle_wave_right_hand"),
    ("bow", "Bow", "natural_legacy_bow"),
    ("stretch", "Stretch", "freestyle_leg_stretch_and_shake"),
    ("shake", "Shake", "natural_legacy_shake"),
    ("dance", "Dance", "freestyle_salsa_dance"),
    ("cute", "Cute", "natural_legacy_cute"),
    ("nod", "Nod", "natural_legacy_nod"),
    ("point", "Point", "natural_legacy_point"),
    ("celebrate", "Celebrate", "natural_legacy_celebrate"),
    ("pushup", "Push-Up", "natural_legacy_pushup"),
    ("crouch", "Crouch", "natural_legacy_crouch"),
)


def _elu(x: np.ndarray) -> np.ndarray:
    return np.where(x > 0.0, x, np.expm1(x))


def _load_initializers(model: onnx.ModelProto) -> dict[str, np.ndarray]:
    return {init.name: numpy_helper.to_array(init) for init in model.graph.initializer}


def _find_div_std_name(inits: dict[str, np.ndarray], width: int) -> str:
    for name, arr in inits.items():
        if name != "obs_normalizer._mean" and arr.size == width and arr.dtype == np.float32:
            if "Div" in name or "std" in name.lower():
                return name
    raise RuntimeError(f"Could not find normalizer std tensor of width {width} in {list(inits.keys())}")


def _pack_float32_tensors(tensors: list[tuple[str, np.ndarray]]) -> tuple[bytes, dict[str, dict]]:
    chunks: list[bytes] = []
    layout: dict[str, dict] = {}
    offset_floats = 0
    for name, arr in tensors:
        f32 = np.ascontiguousarray(arr, dtype="<f4")
        layout[name] = {
            "offset": offset_floats,
            "length": int(f32.size),
            "shape": [int(d) for d in f32.shape],
        }
        chunks.append(f32.tobytes())
        offset_floats += int(f32.size)
    return b"".join(chunks), layout


def _eval_mlp(
    obs: np.ndarray,
    mean: np.ndarray,
    std: np.ndarray,
    layers: list[tuple[np.ndarray, np.ndarray, str]],
) -> np.ndarray:
    h = (obs.astype(np.float32) - mean) / std
    for w, b, act in layers:
        h = h @ w.T + b
        if act == "elu":
            h = _elu(h)
        elif act == "tanh":
            h = np.tanh(h)
    return h


def export_neural_gait(gait_dir: Path, out_dir: Path) -> dict:
    onnx_path = gait_dir / "policy.onnx"
    env_path = gait_dir / "environment.json"
    walk_manifest = json.loads(
        (AINEKIO_ROOT / "Slave/software/models/v2-12servo/motions/walk/manifest.json").read_text()
    )
    env_cfg = json.loads(env_path.read_text())
    model = onnx.load(str(onnx_path))
    meta = {prop.key: prop.value for prop in model.metadata_props}
    inits = _load_initializers(model)

    mean = inits["obs_normalizer._mean"].reshape(-1).astype(np.float32)
    std_name = _find_div_std_name(inits, mean.size)
    std = inits[std_name].reshape(-1).astype(np.float32)

    layer_specs = [
        ("mlp.0.weight", "mlp.0.bias", "elu"),
        ("mlp.2.weight", "mlp.2.bias", "elu"),
        ("mlp.4.weight", "mlp.4.bias", "elu"),
        ("mlp.6.weight", "mlp.6.bias", "tanh"),
    ]
    layers = [(inits[w].astype(np.float32), inits[b].astype(np.float32), act) for w, b, act in layer_specs]

    # Verify numerical parity against ONNXRuntime
    sess = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
    in_name = sess.get_inputs()[0].name
    out_name = sess.get_outputs()[0].name
    rng = np.random.default_rng(20261121)
    golden: list[dict] = []
    max_err = 0.0
    for idx in range(3):
        x = (
            np.zeros(mean.size, dtype=np.float32)
            if idx == 0
            else rng.normal(0.0, 0.35, size=mean.size).astype(np.float32)
        )
        ref = np.clip(sess.run([out_name], {in_name: x[None, :]})[0][0], -1.0, 1.0)
        got = np.clip(_eval_mlp(x, mean, std, layers), -1.0, 1.0)
        err = float(np.max(np.abs(ref - got)))
        max_err = max(max_err, err)
        golden.append(
            {
                "seed": idx,
                "obs": [round(float(v), 6) for v in x],
                "action": [round(float(v), 7) for v in ref],
            }
        )
    if max_err > 1e-5:
        raise RuntimeError(f"Neural Gait ONNX parity check failed: max_err={max_err}")

    packed_tensors: list[tuple[str, np.ndarray]] = [("mean", mean), ("std", std)]
    layer_meta = []
    for i, (w, b, act) in enumerate(layers):
        packed_tensors.append((f"w{i}", w))
        packed_tensors.append((f"b{i}", b))
        layer_meta.append(
            {
                "weight": f"w{i}",
                "bias": f"b{i}",
                "inDim": int(w.shape[1]),
                "outDim": int(w.shape[0]),
                "activation": act,
            }
        )

    blob, layout = _pack_float32_tensors(packed_tensors)
    bin_path = out_dir / "neural-gait.bin"
    bin_path.write_bytes(blob)

    manifest = {
        "schemaVersion": 1,
        "kind": "microduck-mjlab",
        "modelId": gait_dir.resolve().name,
        "observationSchema": meta.get("ainekio_schema", env_cfg.get("observation_schema")),
        "actionContract": meta.get("ainekio_action", "normalized-foot-offsets-v1"),
        "checkpointSha256": meta.get("checkpoint_sha256", ""),
        "geometryId": walk_manifest["geometry_id"],
        "controlHz": int(env_cfg.get("control_hz", 50)),
        "obsDim": int(mean.size),
        "featureDim": 48,
        "historySamples": 15,
        "footActionScaleMm": [float(v) for v in env_cfg["foot_action_scale_mm"]],
        "referenceJointDeg": [float(v) for v in env_cfg["reference_joint_deg"]],
        "defaultProfile": {
            "forwardMS": 0.15,
            "lateralMS": 0.08,
            "yawRadS": 1.0,
        },
        "weightsFile": "neural-gait.bin",
        "layers": layer_meta,
        "tensors": layout,
        "onnxMaxAbsError": max_err,
        "goldenTests": golden,
    }
    json_path = out_dir / "neural-gait.json"
    json_path.write_text(json.dumps(manifest, separators=(",", ":")) + "\n", encoding="utf-8")
    print(
        f"Exported Neural Gait ({manifest['modelId']}): {bin_path.name} ({len(blob)/1024:.1f} KB), "
        f"ONNX max_err={max_err:.2e}"
    )
    return manifest


def export_neural_pose(pose_dir: Path, out_dir: Path) -> dict:
    resolved_dir = pose_dir.resolve()
    onnx_path = resolved_dir / "policy.onnx"
    walk_manifest = json.loads(
        (AINEKIO_ROOT / "Slave/software/models/v2-12servo/motions/walk/manifest.json").read_text()
    )
    model = onnx.load(str(onnx_path))
    meta = {prop.key: prop.value for prop in model.metadata_props}
    inits = _load_initializers(model)

    mean = inits["obs_normalizer._mean"].reshape(-1).astype(np.float32)
    std_name = _find_div_std_name(inits, mean.size)
    std = inits[std_name].reshape(-1).astype(np.float32)
    obs_mirror_perm = inits["obs_mirror_perm"].reshape(-1).astype(np.int64)
    obs_mirror_sign = inits["obs_mirror_sign"].reshape(-1).astype(np.float32)
    act_mirror_perm = inits["act_mirror_perm"].reshape(-1).astype(np.int64)
    act_mirror_sign = inits["act_mirror_sign"].reshape(-1).astype(np.float32)

    residual_scale = float(meta.get("ainekio_residual_scale", "0.43"))
    foot_scale_mm = [
        float(v) for v in (meta.get("ainekio_foot_scale_mm") or "95.0,155.0,180.0").split(",")
    ]
    goal_slice_start = 57
    goal_slice_end = 69

    layer_specs = [
        ("mlp.0.weight", "mlp.0.bias", "elu"),
        ("mlp.2.weight", "mlp.2.bias", "elu"),
        ("mlp.4.weight", "mlp.4.bias", "elu"),
        ("mlp.6.weight", "mlp.6.bias", "tanh"),
    ]
    layers = [(inits[w].astype(np.float32), inits[b].astype(np.float32), act) for w, b, act in layer_specs]

    # Verify exact equivariant residual parity against ONNXRuntime
    sess = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
    in_name = sess.get_inputs()[0].name
    out_name = sess.get_outputs()[0].name
    rng = np.random.default_rng(20261122)
    golden: list[dict] = []
    max_err = 0.0
    for idx in range(3):
        x = (
            np.zeros(POSE_OBS_SIZE, dtype=np.float32)
            if idx == 0
            else rng.normal(0.0, 0.3, size=POSE_OBS_SIZE).astype(np.float32)
        )
        if idx > 0:
            x[goal_slice_start:goal_slice_end] = np.clip(x[goal_slice_start:goal_slice_end], -0.8, 0.8)
        ref = np.clip(sess.run([out_name], {in_name: x[None, :]})[0][0], -1.0, 1.0)
        y1 = _eval_mlp(x, mean, std, layers)
        xm = x[obs_mirror_perm] * obs_mirror_sign
        y2 = _eval_mlp(xm, mean, std, layers)[act_mirror_perm] * act_mirror_sign
        got = np.clip(x[goal_slice_start:goal_slice_end] + 0.5 * (y1 + y2) * residual_scale, -1.0, 1.0)
        err = float(np.max(np.abs(ref - got)))
        max_err = max(max_err, err)
        golden.append(
            {
                "seed": idx,
                "obs": [round(float(v), 6) for v in x],
                "action": [round(float(v), 7) for v in ref],
            }
        )
    if max_err > 1e-5:
        raise RuntimeError(f"Neural Pose ONNX parity check failed: max_err={max_err}")

    packed_tensors: list[tuple[str, np.ndarray]] = [
        ("mean", mean),
        ("std", std),
        ("obsMirrorSign", obs_mirror_sign),
        ("actMirrorSign", act_mirror_sign),
    ]
    layer_meta = []
    for i, (w, b, act) in enumerate(layers):
        packed_tensors.append((f"w{i}", w))
        packed_tensors.append((f"b{i}", b))
        layer_meta.append(
            {
                "weight": f"w{i}",
                "bias": f"b{i}",
                "inDim": int(w.shape[1]),
                "outDim": int(w.shape[0]),
                "activation": act,
            }
        )

    blob, layout = _pack_float32_tensors(packed_tensors)
    bin_path = out_dir / "neural-pose.bin"
    bin_path.write_bytes(blob)

    manifest = {
        "schemaVersion": 1,
        "kind": "neural-pose-equivariant-v1",
        "modelId": resolved_dir.name,
        "observationSchema": meta.get("ainekio_schema", POSE_SCHEMA),
        "actionContract": meta.get("ainekio_action", "normalized-pose-foot-offsets-v1"),
        "checkpointSha256": meta.get("checkpoint_sha256", ""),
        "geometryId": walk_manifest["geometry_id"],
        "controlHz": 50,
        "obsDim": POSE_OBS_SIZE,
        "featureDim": POSE_FEATURES,
        "historySamples": POSE_SAMPLES,
        "goalFootSliceStart": goal_slice_start,
        "goalFootSliceEnd": goal_slice_end,
        "residualScale": residual_scale,
        "footScaleMm": foot_scale_mm,
        "obsMirrorPerm": [int(v) for v in obs_mirror_perm],
        "actMirrorPerm": [int(v) for v in act_mirror_perm],
        "weightsFile": "neural-pose.bin",
        "layers": layer_meta,
        "tensors": layout,
        "onnxMaxAbsError": max_err,
        "goldenTests": golden,
    }
    json_path = out_dir / "neural-pose.json"
    json_path.write_text(json.dumps(manifest, separators=(",", ":")) + "\n", encoding="utf-8")
    print(
        f"Exported Neural Pose ({manifest['modelId']}): {bin_path.name} ({len(blob)/1024:.1f} KB), "
        f"ONNX max_err={max_err:.2e}"
    )
    return manifest


def export_pose_manifold_and_library(
    pose_dir: Path,
    motion_db: Path,
    out_dir: Path,
    gait_dir: Path = DEFAULT_GAIT_DIR,
) -> None:
    resolved_dir = pose_dir.resolve()
    gait_env = gait_dir.resolve() / "environment.json"
    env_json = gait_env if gait_env.exists() else (resolved_dir / "environment.json")
    manifold = PoseManifold(env_json) if env_json.exists() else PoseManifold()
    fb = _fast_numpy_body(manifold.body)

    # Golden vectors to verify TypeScript PoseManifold port bit-for-bit
    test_angles_list = [
        list(STAND_ANGLES_DEG),
        [0.0, 20.0, -5.0, 0.0, 20.0, -5.0, -10.0, -15.0, -25.0, 12.0, 35.0, 15.0],
        [-12.0, -18.0, -22.0, 12.0, -18.0, -22.0, 0.0, 15.0, -30.0, 0.0, 15.0, -30.0],
    ]
    manifold_golden = []
    prev_q = np.deg2rad(np.asarray(STAND_ANGLES_DEG, dtype=np.float64)).reshape(1, 12)
    for deg in test_angles_list:
        proj_deg, foot_norm = manifold.project_angles_deg(deg)
        next_q, applied_act, feet_mm = manifold.step_host_command(foot_norm, prev_q, speed_scale=0.75)
        manifold_golden.append(
            {
                "inputDeg": [round(float(v), 5) for v in deg],
                "projectedDeg": [round(float(v), 5) for v in proj_deg],
                "footNorm": [round(float(v), 6) for v in foot_norm],
                "prevQDeg": [round(float(v), 5) for v in np.rad2deg(prev_q[0]).tolist()],
                "speedScale": 0.75,
                "nextQDeg": [round(float(v), 5) for v in np.rad2deg(next_q[0].cpu().numpy()).tolist()],
                "appliedAct": [round(float(v), 6) for v in applied_act],
                "feetMm": [round(float(v), 5) for v in feet_mm],
            }
        )
        prev_q = next_q.cpu().numpy()

    manifold_payload = {
        "schemaVersion": 1,
        "geometryId": manifold.geometry_id,
        "referenceJointDeg": [float(v) for v in manifold.reference_joint_deg],
        "standAnglesDeg": [float(v) for v in STAND_ANGLES_DEG],
        "targetLimitsDeg": [[float(lo), float(hi)] for lo, hi in manifold.env_config.target_limits_deg],
        "motorNoLoadSpeedDegS": float(getattr(manifold.env_config, "motor_no_load_speed_deg_s", 545.4545454545455)),
        "O": [float(v) for v in fb.O.tolist()],
        "C": [float(v) for v in fb.C.tolist()],
        "A": float(fb.A),
        "r": float(fb.r),
        "L": float(fb.L),
        "b": float(fb.b),
        "a0": float(fb.a0),
        "t0": float(fb.t0),
        "b0": float(fb.b0),
        "branch": float(fb.branch),
        "sign": [[float(x) for x in row] for row in fb.sign.tolist()],
        "translation": [[float(x) for x in row] for row in fb.translation.tolist()],
        "shoulder": [[float(x) for x in row] for row in fb.shoulder.tolist()],
        "mirror": [float(v) for v in fb.mirror.tolist()],
        "reference": [[float(x) for x in row] for row in fb.reference.tolist()],
        "home": [[float(x) for x in row] for row in fb.home.tolist()],
        "pulseHome": [[float(x) for x in row] for row in fb.pulse_home.tolist()],
        "pulseScale": [[float(x) for x in row] for row in fb.pulse_scale.tolist()],
        "low": [[float(-1e6 if not math.isfinite(x) and x < 0 else (1e6 if not math.isfinite(x) else x)) for x in row] for row in fb.low.tolist()],
        "high": [[float(1e6 if not math.isfinite(x) and x > 0 else (-1e6 if not math.isfinite(x) else x)) for x in row] for row in fb.high.tolist()],
        "q0": [[float(x) for x in row] for row in fb.q0.tolist()],
        "origin": [[float(x) for x in row] for row in fb.origin.tolist()],
        "scale": [float(v) for v in fb.scale.tolist()],
        "tickUs": float(fb.tick_us),
        "projectionFractions": [float(v) for v in fb.projection_fractions.tolist()],
        "goldenTests": manifold_golden,
    }
    manifold_path = out_dir / "pose-manifold.json"
    manifold_path.write_text(json.dumps(manifold_payload, separators=(",", ":"), allow_nan=False) + "\n", encoding="utf-8")
    print(f"Exported PoseManifold: {manifold_path.name} ({manifold_path.stat().st_size/1024:.1f} KB)")

    # Compile curated production Motion Library programs via compile_goal_segments
    con = sqlite3.connect(str(motion_db))
    tools = json.loads(con.execute("SELECT value FROM metadata WHERE key = 'tools'").fetchone()[0])
    encoding = ProgramEncoding(tools)
    stand_obs = {
        "joints": {
            j: {
                "feedback_usable": True,
                "filtered_model_deg": float(STAND_ANGLES_DEG[i]),
                "commanded_model_deg": float(STAND_ANGLES_DEG[i]),
                "home_deg": float(STAND_ANGLES_DEG[i]),
            }
            for i, j in enumerate(JOINTS)
        }
    }

    compiled_motions: list[dict] = []
    for clip_id, label, family in CURATED_MOTIONS:
        row = con.execute(
            "SELECT id, title, payload FROM examples WHERE family = ? ORDER BY updated_ns DESC LIMIT 1",
            (family,),
        ).fetchone()
        if not row:
            raise RuntimeError(f"Curated motion family not found in {motion_db}: {family}")
        payload = json.loads(row[2])
        answers = payload["answers"]
        program = encoding.decode(answers)
        segments = compile_goal_segments(program, stand_obs, manifold)

        # Strip non-runtime metadata for compact static web bundle
        compact_segments: list[dict] = []
        for seg in segments:
            kind = seg["kind"]
            if kind == "face":
                compact_segments.append({"kind": "face", "expr": str(seg["expr"])})
            elif kind == "hold":
                compact_segments.append({"kind": "hold", "seconds": round(float(seg["seconds"]), 4)})
            elif kind == "pose_goal":
                compact_segments.append(
                    {
                        "kind": "pose_goal",
                        "goalDeg": [round(float(v), 4) for v in seg["goal_deg"]],
                        "goalFootNorm": [round(float(v), 5) for v in seg["goal_foot_norm"]],
                        "legSupport": [float(v) for v in seg["leg_support"]],
                        "speedScale": round(float(seg["speed_scale"]), 4),
                        "durationS": round(float(seg["duration_s"]), 4),
                        "isStand": bool(seg.get("is_stand", False)),
                        "fromNonstanding": bool(seg.get("from_nonstanding", False)),
                    }
                )
            elif kind == "oscillate_goal":
                compact_segments.append(
                    {
                        "kind": "oscillate_goal",
                        "baseDeg": [round(float(v), 4) for v in seg["base_deg"]],
                        "jointIndices": [int(v) for v in seg["joint_indices"]],
                        "centersDeg": [round(float(v), 4) for v in seg["centers_deg"]],
                        "amplitudesDeg": [round(float(v), 4) for v in seg["amplitudes_deg"]],
                        "hz": round(float(seg["hz"]), 4),
                        "cycles": round(float(seg["cycles"]), 4),
                        "legSupport": [float(v) for v in seg["leg_support"]],
                        "speedScale": round(float(seg["speed_scale"]), 4),
                        "durationS": round(float(seg["duration_s"]), 4),
                        "endDeg": [round(float(v), 4) for v in seg["end_deg"]],
                    }
                )
        compiled_motions.append(
            {
                "id": clip_id,
                "label": label,
                "sourceFamily": family,
                "sourceTitle": str(row[1]),
                "sourceId": str(row[0]),
                "segments": compact_segments,
            }
        )
    con.close()

    lib_payload = {
        "schemaVersion": 1,
        "poseModelId": resolved_dir.name,
        "standAnglesDeg": [float(v) for v in STAND_ANGLES_DEG],
        "motions": compiled_motions,
    }
    lib_path = out_dir / "neural-pose-library.json"
    lib_path.write_text(json.dumps(lib_payload, separators=(",", ":")) + "\n", encoding="utf-8")
    print(
        f"Exported Neural Pose Motion Library: {lib_path.name} ({lib_path.stat().st_size/1024:.1f} KB, "
        f"{len(compiled_motions)} curated motions)"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Export Ainekio Neural Gait & Neural Pose for static web WASM.")
    parser.add_argument("--gait-dir", type=Path, default=DEFAULT_GAIT_DIR)
    parser.add_argument("--pose-dir", type=Path, default=DEFAULT_POSE_DIR)
    parser.add_argument("--motion-db", type=Path, default=DEFAULT_MOTION_DB)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    export_neural_gait(args.gait_dir, args.out_dir)
    export_neural_pose(args.pose_dir, args.out_dir)
    export_pose_manifold_and_library(args.pose_dir, args.motion_db, args.out_dir, args.gait_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
