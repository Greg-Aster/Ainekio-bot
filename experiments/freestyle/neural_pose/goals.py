"""Non-blocking goal manifold projector and Freestyle program sequencer.

Converts any Freestyle or Motion Library program (`pose`, `move`, `oscillate`,
`feet`, `body`, `stand`, `hold`, `face`, `gait`, `stop`, `release`) into smooth
closed-chain 50 Hz goal segments without brittle Cartesian IK exceptions.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import torch

from .contract import JOINTS, LEGS, POSE_FOOT_SCALE_MM

ROOT = Path(__file__).resolve().parents[3]
GEOMETRY_PATH = ROOT / "Slave/software/models/v2-12servo/geometry.json"
DEFAULT_ENV_JSON = ROOT / "build/neural-gait/microduck-v17-p4/environment.json"
STAND_ANGLES_DEG = (0.0, 0.94, -21.25) * 4

CAD_LEG_ORDER = ("rear_left", "rear_right", "front_left", "front_right")


def usable_joint_angles_deg(observation: dict) -> list[float]:
    """Read current 12-joint angles, falling back to commanded/home when 4th-wire is faulted."""
    joints = observation.get("joints") or {}
    out: list[float] = []
    for idx, name in enumerate(JOINTS):
        info = joints.get(name) or {}
        usable = bool(info.get("feedback_usable", False))
        measured = info.get("filtered_model_deg", info.get("model_deg"))
        commanded = info.get("commanded_model_deg")
        home = info.get("home_deg", STAND_ANGLES_DEG[idx])
        if usable and isinstance(measured, (int, float)) and math.isfinite(measured):
            out.append(float(measured))
        elif isinstance(commanded, (int, float)) and math.isfinite(commanded):
            out.append(float(commanded))
        elif isinstance(measured, (int, float)) and math.isfinite(measured):
            # Detached servo with uncalibrated/clipped reading: clamp toward safe home
            out.append(float(home))
        else:
            out.append(float(home))
    return out


def _ensure_native_library() -> None:
    """Use isolated cached libgait_native.so if a concurrent workspace CMake edit is in progress."""
    import ctypes
    import sys

    master_dir = str(ROOT / "Master")
    if master_dir not in sys.path:
        sys.path.insert(0, master_dir)
    import gateway.neural_gait.native as ng_native

    if getattr(ng_native, "_neural_pose_patched", False):
        return
    orig_lib = ng_native.library
    cached_so = ROOT / "experiments/freestyle/artifacts/libgait_native_cached.so"

    def _safe_library():
        try:
            return orig_lib()
        except Exception:
            if not cached_so.exists():
                raise
            lib = ctypes.CDLL(str(cached_so))
            arr = ng_native.ARRAY
            sbytes = np.ctypeslib.ndpointer(dtype=np.uint8, flags="C_CONTIGUOUS")
            lib.simulation_new.argtypes = [arr, arr, arr]
            lib.simulation_new.restype = ctypes.c_void_p
            lib.simulation_free.argtypes = [ctypes.c_void_p]
            lib.simulation_foot_geometry.argtypes = [arr]
            lib.simulation_sensor_size.restype = ctypes.c_size_t
            lib.simulation_sensor_export.argtypes = [ctypes.c_void_p, sbytes]
            lib.simulation_sensor_import.argtypes = [ctypes.c_void_p, sbytes]
            lib.simulation_imu_calibration.argtypes = [ctypes.c_void_p, arr, arr]
            lib.simulation_imu_calibration.restype = ctypes.c_int
            lib.simulation_target.argtypes = [ctypes.c_void_p, arr, arr, ctypes.c_double, ctypes.c_double, arr]
            lib.simulation_feedback.argtypes = [ctypes.c_void_p, arr, arr, arr, arr]
            lib.simulation_feedback.restype = ctypes.c_uint
            lib.simulation_arrival.argtypes = [ctypes.c_void_p, arr, ctypes.c_double, arr]
            lib.simulation_arrival.restype = ctypes.c_int
            lib.simulation_imu.argtypes = [ctypes.c_void_p, ctypes.c_double, arr, arr, arr]
            lib.simulation_foot_target.argtypes = [
                ctypes.c_void_p, arr, arr, arr, ctypes.c_double, ctypes.c_double, ctypes.c_double, arr
            ]
            lib.simulation_foot_action_scale.argtypes = [ctypes.c_void_p, arr, arr, arr]
            lib.simulation_foot_action_scale.restype = ctypes.c_int
            lib.simulation_foot_offsets_for_angles.argtypes = [ctypes.c_void_p, arr, arr, arr]
            lib.simulation_foot_offsets_for_angles.restype = ctypes.c_int
            lib.simulation_balance_configure.argtypes = [ctypes.c_void_p, arr]
            lib.simulation_balance_configure.restype = None
            lib.simulation_pwm.argtypes = [ctypes.c_void_p, arr, ctypes.c_double, ctypes.c_double, arr]
            lib.simulation_imu_status.argtypes = [ctypes.c_void_p, ctypes.c_double, arr]
            lib.simulation_walk_configure.argtypes = [ctypes.c_void_p, arr, arr, ctypes.c_int]
            lib.simulation_walk_accept.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_double]
            lib.simulation_walk_tick.argtypes = [ctypes.c_void_p, ctypes.c_double, arr, arr, ctypes.c_int, arr]
            return lib

    ng_native.library = _safe_library
    ng_native._neural_pose_patched = True


class PoseManifold:
    """Exact V2 four-bar closed-chain manifold and foot-offset encoder."""

    def __init__(self, env_config_path: str | Path = DEFAULT_ENV_JSON, *, device: str = "cpu"):
        _ensure_native_library()
        from gateway.neural_gait.tensor_body import TensorBody

        raw_cfg = json.loads(Path(env_config_path).read_text())
        self.env_config = SimpleNamespace(
            **{
                **raw_cfg,
                "foot_action_scale_mm": list(POSE_FOOT_SCALE_MM),
                "control_hz": 50,
                "physics_hz": 500,
            }
        )
        self.geometry = json.loads(GEOMETRY_PATH.read_text())
        self.device = device
        self.body = TensorBody(self.geometry, self.env_config, device=device)
        self.reference_joint_deg = list(self.env_config.reference_joint_deg)
        self.geometry_id = json.loads(
            (ROOT / "Slave/software/models/v2-12servo/motions/walk/manifest.json").read_text()
        )["geometry_id"]

    def project_batch_rad(self, q_rad: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        """Project (N, 12) rad onto closed four-bar + pulse bounds; return (q_bounded_rad, foot_norm)."""
        orig_shape = q_rad.shape
        q43 = q_rad.to(dtype=torch.float64, device=self.device).reshape(-1, 4, 3)
        # First clamp to calibrated electrical limits, then run Gauss-Newton closure
        q_clamped = q43.clamp(self.body.low, self.body.high)
        # Shoulder limits from target_limits_deg
        lims = (
            torch.tensor(self.env_config.target_limits_deg, dtype=torch.float64, device=self.device)
            .reshape(4, 3, 2)
            * (math.pi / 180.0)
        )
        q_clamped = torch.maximum(torch.minimum(q_clamped, lims[..., 1]), lims[..., 0])
        q_b, valid = self.body.bounded(q_clamped)
        # Any leg whose random carrier/crank combination violates triangle closure falls back
        # via foot-space 13-step projection so valid == True everywhere.
        pts, fvalid = self.body.forward(q_b)
        ok = valid & fvalid
        if not bool(ok.all()):
            q_fallback = self.body.q0.unsqueeze(0).expand_as(q_b)
            q_b = torch.where(ok.unsqueeze(-1), q_b, q_fallback)
            pts, _ = self.body.forward(q_b)
        foot_norm = ((pts - self.body.origin) / self.body.scale).clamp(-1.0, 1.0)
        # Roundtrip through decode so goal angles and goal foot_norm are 100% consistent with P4
        q_consistent = self.body.decode(foot_norm.reshape(-1, 12)).reshape(-1, 4, 3)
        pts_c, _ = self.body.forward(q_consistent)
        foot_norm_c = ((pts_c - self.body.origin) / self.body.scale).clamp(-1.0, 1.0)
        return (
            q_consistent.reshape(orig_shape).to(dtype=torch.float32),
            foot_norm_c.reshape(*orig_shape[:-1], 12).to(dtype=torch.float32),
        )

    def project_angles_deg(self, angles_deg) -> tuple[list[float], list[float]]:
        q = torch.tensor(angles_deg, dtype=torch.float64, device=self.device).reshape(1, 12) * (math.pi / 180.0)
        q_rad, foot_norm = self.project_batch_rad(q)
        deg = (q_rad[0] * (180.0 / math.pi)).cpu().tolist()
        return deg, foot_norm[0].cpu().tolist()

    def infer_leg_support(self, bounded_deg) -> list[float]:
        """Determine [rl, rr, fl, fr] support hints (1.0=stance, 0.0=free/lifted leg)."""
        q = (
            torch.tensor(bounded_deg, dtype=torch.float64, device=self.device).reshape(1, 4, 3)
            * (math.pi / 180.0)
        )
        pts, _ = self.body.forward(q)
        z_mm = pts[0, :, 2].cpu().tolist()  # body-frame z (higher = lifted toward/above torso)
        min_z = min(z_mm)
        max_z = max(z_mm)
        if max_z - min_z <= 8.0:
            return [1.0, 1.0, 1.0, 1.0]
        support = [0.0 if (z - min_z) > 10.0 else 1.0 for z in z_mm]
        # Never mark all 4 legs unsupported; keep lowest leg(s) as stance reference
        if sum(support) == 0.0:
            return [1.0, 1.0, 1.0, 1.0]
        return support

    def resolve_spatial_deg(self, action: dict, current_deg: list[float]) -> list[float]:
        """Resolve `body` or `feet` without throwing on folded/unloaded postures."""
        args = action["arguments"]
        op_name = action["name"]
        # Check if current posture is folded / out of nominal standing envelope
        folded = False
        for leg_idx in range(4):
            ca = current_deg[leg_idx * 3 + 1]
            cr = current_deg[leg_idx * 3 + 2]
            if ca < -26.0 or cr < -72.0 or cr > 45.0:
                folded = True
                break
        seed_deg = list(STAND_ANGLES_DEG) if folded else list(current_deg)
        seed_proj_deg, _ = self.project_angles_deg(seed_deg)
        q_seed = (
            torch.tensor(seed_proj_deg, dtype=torch.float64, device=self.device).reshape(4, 3)
            * (math.pi / 180.0)
        )
        feet_mm, _ = self.body.forward(q_seed)  # (4, 3) in body frame (mm)

        legs = args.get("legs") or []
        offsets = args.get("offsets_mm") if op_name == "feet" else (args.get("foot_offsets_mm") or [])
        delta_map = {leg: np.asarray(off, dtype=np.float64) for leg, off in zip(legs, offsets)}

        trans = np.asarray(args.get("translation_mm", [0.0, 0.0, 0.0]), dtype=np.float64)
        rx, ry, rz = np.deg2rad(args.get("rotation_deg", [0.0, 0.0, 0.0]))
        cx, sx = math.cos(rx), math.sin(rx)
        cy, sy = math.cos(ry), math.sin(ry)
        cz, sz = math.cos(rz), math.sin(rz)
        rot = np.array(
            [
                [cz * cy, cz * sy * sx - sz * cx, cz * sy * cx + sz * sx],
                [sz * cy, sz * sy * sx + cz * cx, sz * sy * cx - cz * sx],
                [-sy, cy * sx, cy * cx],
            ],
            dtype=np.float64,
        )

        desired_feet = np.zeros((4, 3), dtype=np.float64)
        feet_np = feet_mm.cpu().numpy()
        for idx, leg in enumerate(CAD_LEG_ORDER):
            world_foot = feet_np[idx] + delta_map.get(leg, np.zeros(3, dtype=np.float64))
            if op_name == "body":
                # Body translates by `trans` and rotates by `rot` while stance feet stay planted:
                # p_body = R^T @ (p_world - trans)
                desired_feet[idx] = rot.T @ (world_foot - trans)
            else:
                desired_feet[idx] = world_foot

        desired_t = torch.tensor(desired_feet, dtype=torch.float64, device=self.device)
        norm_act = ((desired_t - self.body.origin) / self.body.scale).clamp(-1.0, 1.0).reshape(1, 12)
        q_dec = self.body.decode(norm_act).reshape(1, 12)
        return (q_dec[0] * (180.0 / math.pi)).cpu().tolist()


def compile_goal_segments(program: list[dict], observation: dict, manifold: PoseManifold) -> list[dict]:
    """Convert a Freestyle/Library program into non-blocking 50 Hz goal segments."""
    joints_obs = observation.get("joints") or {}
    home_deg = [float((joints_obs.get(j) or {}).get("home_deg", STAND_ANGLES_DEG[i])) for i, j in enumerate(JOINTS)]
    cursor_deg, _ = manifold.project_angles_deg(usable_joint_angles_deg(observation))
    max_speed_deg_s = max(120.0, float(observation.get("joint_speed_limit_deg_s") or 545.45))

    segments: list[dict] = []
    for index, action in enumerate(program):
        name = action["name"]
        args = action.get("arguments") or {}
        if name == "face":
            segments.append({"kind": "face", "index": index, "action": action, "expr": args["expr"]})
            continue
        if name == "hold":
            segments.append({"kind": "hold", "index": index, "action": action, "seconds": float(args["seconds"])})
            continue
        if name in ("stop", "release", "gait"):
            segments.append({"kind": name, "index": index, "action": action, "arguments": dict(args)})
            if name in ("stop", "release"):
                break
            cursor_deg = list(STAND_ANGLES_DEG)
            continue

        speed_pct = float(args.get("speed_pct", 70))
        speed_scale = max(0.15, min(1.0, speed_pct / 100.0))

        if name == "stand":
            goal_deg, goal_foot_norm = manifold.project_angles_deg(STAND_ANGLES_DEG)
            max_delta = max(abs(a - b) for a, b in zip(goal_deg, cursor_deg))
            eff_speed = max(90.0, min(360.0, max_speed_deg_s * 0.45 * speed_scale))
            duration_s = max(0.45, min(2.2, max_delta / eff_speed + 0.25))
            segments.append(
                {
                    "kind": "pose_goal",
                    "index": index,
                    "action": action,
                    "start_deg": list(cursor_deg),
                    "goal_deg": goal_deg,
                    "goal_foot_norm": goal_foot_norm,
                    "leg_support": [1.0, 1.0, 1.0, 1.0],
                    "speed_scale": speed_scale,
                    "duration_s": duration_s,
                }
            )
            cursor_deg = list(goal_deg)
            continue

        if name in ("move", "pose"):
            moving = [args["joint"]] if name == "move" else list(args["joints"])
            raw_targets = [args["angle_deg"]] if name == "move" else list(args["angles_deg"])
            ref = args.get("reference", "absolute")
            candidate = list(cursor_deg)
            for j_name, val in zip(moving, raw_targets):
                j_idx = JOINTS.index(j_name)
                if ref == "current":
                    candidate[j_idx] = cursor_deg[j_idx] + float(val)
                elif ref == "home":
                    candidate[j_idx] = home_deg[j_idx] + float(val)
                else:
                    candidate[j_idx] = float(val)
            goal_deg, goal_foot_norm = manifold.project_angles_deg(candidate)
            support = manifold.infer_leg_support(goal_deg)
            max_delta = max(abs(a - b) for a, b in zip(goal_deg, cursor_deg))
            eff_speed = max(80.0, min(380.0, max_speed_deg_s * 0.45 * speed_scale))
            duration_s = max(0.32, min(2.5, max_delta / eff_speed + 0.18))
            segments.append(
                {
                    "kind": "pose_goal",
                    "index": index,
                    "action": action,
                    "start_deg": list(cursor_deg),
                    "goal_deg": goal_deg,
                    "goal_foot_norm": goal_foot_norm,
                    "leg_support": support,
                    "speed_scale": speed_scale,
                    "duration_s": duration_s,
                }
            )
            cursor_deg = list(goal_deg)
            continue

        if name in ("feet", "body"):
            resolved = manifold.resolve_spatial_deg(action, cursor_deg)
            goal_deg, goal_foot_norm = manifold.project_angles_deg(resolved)
            support = manifold.infer_leg_support(goal_deg)
            max_delta = max(abs(a - b) for a, b in zip(goal_deg, cursor_deg))
            eff_speed = max(80.0, min(360.0, max_speed_deg_s * 0.45 * speed_scale))
            duration_s = max(0.35, min(2.5, max_delta / eff_speed + 0.20))
            segments.append(
                {
                    "kind": "pose_goal",
                    "index": index,
                    "action": action,
                    "start_deg": list(cursor_deg),
                    "goal_deg": goal_deg,
                    "goal_foot_norm": goal_foot_norm,
                    "leg_support": support,
                    "speed_scale": speed_scale,
                    "duration_s": duration_s,
                }
            )
            cursor_deg = list(goal_deg)
            continue

        if name == "oscillate":
            moving = list(args["joints"])
            j_indices = [JOINTS.index(j) for j in moving]
            ref = args.get("reference", "absolute")
            centers = []
            for j_idx, c_val in zip(j_indices, args["center_deg"]):
                if ref == "current":
                    centers.append(cursor_deg[j_idx] + float(c_val))
                elif ref == "home":
                    centers.append(home_deg[j_idx] + float(c_val))
                else:
                    centers.append(float(c_val))
            amps = [float(a) for a in args["amplitude_deg"]]
            hz = max(0.2, min(4.0, float(args["hz"])))
            cycles = max(0.5, float(args["cycles"]))
            osc_duration = cycles / hz
            center_pose = list(cursor_deg)
            for j_idx, c_deg in zip(j_indices, centers):
                center_pose[j_idx] = c_deg
            end_deg, _ = manifold.project_angles_deg(center_pose)
            support = manifold.infer_leg_support(end_deg)
            segments.append(
                {
                    "kind": "oscillate_goal",
                    "index": index,
                    "action": action,
                    "base_deg": list(center_pose),
                    "joint_indices": j_indices,
                    "centers_deg": centers,
                    "amplitudes_deg": amps,
                    "hz": hz,
                    "cycles": cycles,
                    "leg_support": support,
                    "speed_scale": max(0.5, speed_scale),
                    "duration_s": osc_duration + 0.12,
                    "end_deg": end_deg,
                }
            )
            cursor_deg = list(end_deg)
            continue

        raise ValueError(f"Unsupported operation in neural pose sequencer: {name}")

    return segments
