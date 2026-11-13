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


class _FastNumPyBody:
    """Zero-overhead float64 NumPy mirror of TensorBody for <1 ms 50 Hz CPU host ticks."""

    def __init__(self, body):
        self.O = body.O.detach().cpu().numpy()
        self.C = body.C.detach().cpu().numpy()
        self.A = float(body.A)
        self.r = float(body.r)
        self.L = float(body.L)
        self.b = float(body.b)
        self.a0 = float(body.a0)
        self.t0 = float(body.t0)
        self.b0 = float(body.b0)
        self.branch = float(body.branch)
        self.sign = body.sign.detach().cpu().numpy()
        self.translation = body.translation.detach().cpu().numpy()
        self.shoulder = body.shoulder.detach().cpu().numpy()
        self.mirror = body.mirror.detach().cpu().numpy()
        self.reference = body.reference.detach().cpu().numpy()
        self.home = body.home.detach().cpu().numpy()
        self.pulse_home = body.pulse_home.detach().cpu().numpy()
        self.pulse_scale = body.pulse_scale.detach().cpu().numpy()
        self.low = body.low.detach().cpu().numpy()
        self.high = body.high.detach().cpu().numpy()
        self.q0 = body.q0.detach().cpu().numpy()
        self.origin = body.origin.detach().cpu().numpy()
        self.scale = body.scale.detach().cpu().numpy()
        self.tick_us = float(body.tick_us)
        self.projection_fractions = body.projection_fractions.detach().cpu().numpy()
        self.cb0 = math.cos(self.b0)
        self.sb0 = math.sin(self.b0)
        self.length2 = self.reference[:, 0] ** 2 + self.reference[:, 2] ** 2
        self.length = np.sqrt(self.length2)
        self.dx0, self.dz0, self.bc0, self.bs0, *_ = self.seed(self.q0)
        oldt = self.t0 + self.q0[:, 2]
        self.crank_branch = (
            (self.dx0 + self.b * self.bc0 - self.C[0]) * np.sin(oldt)
            - (self.dz0 + self.b * self.bs0 - self.C[1]) * np.cos(oldt)
        )

    @staticmethod
    def _wrap(x: np.ndarray) -> np.ndarray:
        return np.arctan2(np.sin(x), np.cos(x))

    @staticmethod
    def _circle(d2: np.ndarray, radius: float | np.ndarray, other: float | np.ndarray):
        safe = np.maximum(d2, 1e-8)
        along = (radius * radius - other * other + d2) / (2.0 * safe)
        height = np.sqrt(np.maximum(radius * radius / safe - along * along, 0.0))
        valid = (d2 > 1e-8) & (d2 >= (radius - other) ** 2) & (d2 <= (radius + other) ** 2)
        return along, height, valid

    def seed(self, q: np.ndarray):
        a = q[..., 1] + self.a0
        t = q[..., 2] + self.t0
        dx = self.O[0] + self.A * np.cos(a)
        dz = self.O[1] + self.A * np.sin(a)
        x = self.C[0] + self.r * np.cos(t) - dx
        z = self.C[1] + self.r * np.sin(t) - dz
        along, height, valid = self._circle(x * x + z * z, self.b, self.L)
        height = height * self.branch
        bc = (along * x - height * z) / self.b
        bs = (along * z + height * x) / self.b
        lc = bc * self.cb0 + bs * self.sb0
        ls = bs * self.cb0 - bc * self.sb0
        return dx, dz, bc, bs, lc, ls, valid

    def forward(self, q: np.ndarray):
        dx, dz, _, _, lc, ls, valid = self.seed(q)
        h = q[..., 0]
        ch = np.cos(h)
        sh = np.sin(h)
        x = dx + lc * self.reference[:, 0] - ls * self.reference[:, 2]
        y = self.translation[:, 1] + self.reference[:, 1]
        z = self.translation[:, 2] + dz + ls * self.reference[:, 0] + lc * self.reference[:, 2]
        points = np.stack((self.translation[:, 0] + self.mirror * x, ch * y - sh * z, sh * y + ch * z), axis=-1)
        return self.shoulder + self.sign * points, valid

    def inverse(self, target: np.ndarray):
        v = (target - self.shoulder) * self.sign
        y = self.translation[:, 1] + self.reference[:, 1]
        zz = v[..., 1] ** 2 + v[..., 2] ** 2 - y * y
        z = -np.sqrt(np.maximum(zz, 0.0))
        norm = np.maximum(v[..., 1] ** 2 + v[..., 2] ** 2, 1e-8)
        hc = (y * v[..., 1] + z * v[..., 2]) / norm
        hs = (y * v[..., 2] - z * v[..., 1]) / norm
        x = (v[..., 0] - self.translation[:, 0]) * self.mirror - self.O[0]
        z = z - self.translation[:, 2] - self.O[1]
        along, height, valid = self._circle(x * x + z * z, self.A, self.length)
        ax = self.O[0] + along * x - height * z
        az = self.O[1] + along * z + height * x
        bx = self.O[0] + along * x + height * z
        bz = self.O[1] + along * z - height * x
        first = (ax - self.dx0) ** 2 + (az - self.dz0) ** 2 <= (bx - self.dx0) ** 2 + (bz - self.dz0) ** 2
        dx = np.where(first, ax, bx)
        dz = np.where(first, az, bz)
        lx = x + self.O[0] - dx
        lz = z + self.O[1] - dz
        lc = (lx * self.reference[:, 0] + lz * self.reference[:, 2]) / self.length2
        ls = (lz * self.reference[:, 0] - lx * self.reference[:, 2]) / self.length2
        bc = self.cb0 * lc - self.sb0 * ls
        bs = self.sb0 * lc + self.cb0 * ls
        ex = dx + self.b * bc
        ez = dz + self.b * bs
        cx = ex - self.C[0]
        cz = ez - self.C[1]
        ca, cht, crank_ok = self._circle(cx * cx + cz * cz, self.r, self.L)
        px0 = self.C[0] + ca * cx + cht * cz
        pz0 = self.C[1] + ca * cz - cht * cx
        ang0 = self._wrap(np.arctan2(pz0 - self.C[1], px0 - self.C[0]) - self.t0)
        ok0 = ((cx * (pz0 - self.C[1]) - cz * (px0 - self.C[0])) * self.crank_branch > 0.0) & (
            ((px0 - dx) * (ez - dz) - (pz0 - dz) * (ex - dx)) * self.branch >= 0.0
        )
        px1 = self.C[0] + ca * cx - cht * cz
        pz1 = self.C[1] + ca * cz + cht * cx
        ang1 = self._wrap(np.arctan2(pz1 - self.C[1], px1 - self.C[0]) - self.t0)
        ok1 = ((cx * (pz1 - self.C[1]) - cz * (px1 - self.C[0])) * self.crank_branch > 0.0) & (
            ((px1 - dx) * (ez - dz) - (pz1 - dz) * (ex - dx)) * self.branch >= 0.0
        )
        d0 = np.abs(self._wrap(ang0 - self.q0[:, 2]))
        d1 = np.abs(self._wrap(ang1 - self.q0[:, 2]))
        choose = ok0 & (~ok1 | (d0 <= d1))
        theta = np.where(choose, ang0, ang1)
        q = np.stack((np.arctan2(hs, hc), self._wrap(np.arctan2(dz - self.O[1], dx - self.O[0]) - self.a0), theta), axis=-1)
        return q, valid & crank_ok & (zz >= 0.0) & (ok0 | ok1)

    def bounded(self, q_in: np.ndarray):
        outside = np.any((q_in < self.low) | (q_in > self.high), axis=-1)
        if not np.any(outside):
            _, valid = self.forward(q_in)
            return q_in.copy(), valid
        target, _ = self.forward(q_in)
        q = np.clip(q_in, self.low, self.high)
        probe_step = math.pi / 18000.0
        shape = (8,) + (1,) * (q.ndim - 1) + (1,)
        fracs = self.projection_fractions.reshape(shape)
        active = outside.copy()
        for _ in range(8):
            position, valid = self.forward(q)
            error = target - position
            cost = np.sum(error * error, axis=-1)
            if not np.any(active & (cost >= 1e-8)):
                break
            jac = []
            derivative_ok = valid
            for j in (1, 2):
                step = np.where(q[..., j] + probe_step <= self.high[:, j], probe_step, -probe_step)
                probe = q.copy()
                probe[..., j] += step
                value, okay = self.forward(probe)
                jac.append((value - position) / step[..., None])
                derivative_ok = derivative_ok & okay & (q[..., j] + step >= self.low[:, j])
            ja, jb = jac
            a = np.sum(ja * ja, axis=-1)
            b_dot = np.sum(ja * jb, axis=-1)
            d = np.sum(jb * jb, axis=-1)
            e = np.sum(ja * error, axis=-1)
            f = np.sum(jb * error, axis=-1)
            det = a * d - b_dot * b_dot
            det_safe = np.maximum(det, 1e-12)
            a_safe = np.maximum(a, 1e-12)
            d_safe = np.maximum(d, 1e-12)
            sa = np.where(det > 1e-12, (d * e - b_dot * f) / det_safe, e / a_safe)
            sb = np.where(det > 1e-12, (a * f - b_dot * e) / det_safe, f / d_safe)
            ba = ((q[..., 1] <= self.low[:, 1]) & (sa < 0.0)) | ((q[..., 1] >= self.high[:, 1]) & (sa > 0.0))
            sa = np.where(ba, 0.0, sa)
            sb = np.where(ba, f / d_safe, sb)
            bb = ((q[..., 2] <= self.low[:, 2]) & (sb < 0.0)) | ((q[..., 2] >= self.high[:, 2]) & (sb > 0.0))
            sb = np.where(bb, 0.0, sb)
            sa = np.where(bb, e / a_safe, sa)
            delta = np.stack((np.zeros_like(sa), sa, sb), axis=-1)
            probes = np.clip(q[None, ...] + fracs * delta[None, ...], self.low, self.high)
            points, good = self.forward(probes)
            better = good & (np.sum((target[None, ...] - points) ** 2, axis=-1) < cost[None, ...])
            index = np.argmax(better, axis=0)
            selected = np.take_along_axis(probes, index[None, ..., None], axis=0)[0]
            update = active & derivative_ok & (cost >= 1e-8) & np.any(better, axis=0)
            if not np.any(update):
                break
            q = np.where(update[..., None], selected, q)
            active = update
        _, valid = self.forward(q)
        return q, valid

    def pwm(self, q: np.ndarray):
        q43 = q.reshape(-1, 4, 3)
        pulse = np.floor(self.pulse_home + (np.rad2deg(q43) - self.home) * self.pulse_scale + 0.5)
        width = np.floor(pulse / self.tick_us + 0.5) * self.tick_us
        physical = np.deg2rad(self.home + (width - self.pulse_home) / self.pulse_scale)
        return q43.reshape(-1, 12), physical.reshape(-1, 12)

    def _pulse_valid(self, q: np.ndarray) -> np.ndarray:
        pulse = np.floor(self.pulse_home + (np.rad2deg(q) - self.home) * self.pulse_scale + 0.5)
        return np.all((pulse[..., 1:] >= 300.0) & (pulse[..., 1:] <= 2950.0), axis=-1) & np.all(
            (pulse >= 1.0) & (pulse <= 65535.0), axis=-1
        )

    def continuous_decode_rad(self, actions_np: np.ndarray, grid_steps: int = 65, sub_steps: int = 17) -> np.ndarray:
        act = np.asarray(actions_np, dtype=np.float64).reshape(-1, 4, 3)
        bsz = act.shape[0]
        scale43 = self.scale.reshape(1, 1, 1, 3)
        s_lin = np.linspace(0.0, 1.0, grid_steps, dtype=np.float64)
        s_grid = np.broadcast_to(s_lin.reshape(1, grid_steps, 1), (bsz, grid_steps, 4))

        # 1. Closed-form geometric connectivity along ray (zero iterative Gauss-Newton calls on grid)
        target_grid = self.origin.reshape(1, 1, 4, 3) + act[:, None, :, :] * scale43 * s_grid[..., None]
        q_grid, geom_ok = self.inverse(target_grid)
        step_smooth = np.amax(np.abs(q_grid[:, 1:] - q_grid[:, :-1]), axis=-1) <= math.radians(18.0)
        geom_conn = geom_ok.copy()
        geom_conn[:, 0, :] = True
        geom_conn[:, 1:, :] &= step_smooth
        geom_conn = np.cumprod(geom_conn, axis=1).astype(bool)

        idx_lo = np.sum(geom_conn, axis=1, dtype=np.int64) - 1
        all_geom_ok = idx_lo == (grid_steps - 1)
        q_geom = np.take_along_axis(q_grid, idx_lo[:, None, :, None], axis=1)[:, 0, :, :]

        if not np.all(all_geom_ok):
            s_lo = s_lin[idx_lo]
            s_hi = s_lin[np.minimum(idx_lo + 1, grid_steps - 1)]
            u_sub = np.linspace(0.0, 1.0, sub_steps, dtype=np.float64)[1:-1]
            s_sub = s_lo[:, None, :] + u_sub.reshape(1, -1, 1) * (s_hi - s_lo)[:, None, :]
            target_sub = self.origin.reshape(1, 1, 4, 3) + act[:, None, :, :] * scale43 * s_sub[..., None]
            q_sub, ok_sub = self.inverse(target_sub)
            q_chain = np.concatenate([q_geom[:, None, :, :], q_sub], axis=1)
            sub_smooth = np.amax(np.abs(q_chain[:, 1:] - q_chain[:, :-1]), axis=-1) <= math.radians(12.0)
            sub_conn = np.cumprod((~all_geom_ok)[:, None, :] & ok_sub & sub_smooth, axis=1).astype(bool)
            sub_idx = np.sum(sub_conn, axis=1, dtype=np.int64)
            q_geom = np.take_along_axis(q_chain, sub_idx[:, None, :, None], axis=1)[:, 0, :, :]

        # 2. Single electrical-stop projection at the connected geometric endpoint (at most 1 bounded call)
        inb = np.all((q_geom >= self.low) & (q_geom <= self.high), axis=-1)
        if not np.all(inb):
            proj, pok = self.bounded(q_geom)
            q_cand = np.where(inb[..., None], q_geom, proj)
            cand_ok = np.where(inb, True, pok) & self._pulse_valid(q_cand)
        else:
            q_cand = q_geom
            cand_ok = self._pulse_valid(q_cand)

        if np.all(cand_ok):
            return q_cand.reshape(bsz, 12)

        # Fallback for any extreme leg where boundary projection violated pulse bounds: last strictly in-bounds ray point
        strict_ok = geom_conn & np.all((q_grid >= self.low) & (q_grid <= self.high), axis=-1) & self._pulse_valid(q_grid)
        strict_ok[:, 0, :] = True
        strict_conn = np.cumprod(strict_ok, axis=1).astype(bool)
        s_idx = np.sum(strict_conn, axis=1, dtype=np.int64) - 1
        q_strict = np.take_along_axis(q_grid, s_idx[:, None, :, None], axis=1)[:, 0, :, :]
        return np.where(cand_ok[..., None], q_cand, q_strict).reshape(bsz, 12)


def _fast_numpy_body(body) -> _FastNumPyBody:
    cached = getattr(body, "_np_fast", None)
    if cached is None:
        cached = _FastNumPyBody(body)
        setattr(body, "_np_fast", cached)
    return cached


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
        self._cal_cache: dict[tuple, object] = {
            self._calibration_key(self.env_config.robot["calibration"]): self.body
        }
        self.reference_joint_deg = list(self.env_config.reference_joint_deg)
        self.geometry_id = json.loads(
            (ROOT / "Slave/software/models/v2-12servo/motions/walk/manifest.json").read_text()
        )["geometry_id"]

    @staticmethod
    def _calibration_key(cal_joints: list[dict]) -> tuple:
        ordered = sorted(cal_joints, key=lambda j: int(j["id"]))
        return tuple(
            (
                int(j["id"]),
                int(round(float(j["home_cd"]))),
                int(round(float(j["home_us"]))),
                round(float(j["us_per_degree"]), 5),
                bool(j["invert"]),
            )
            for j in ordered
        )

    def body_for_calibration(self, cal_joints: list[dict] | None):
        """Return a cached TensorBody matching the robot's live electrical calibration."""
        if not cal_joints or len(cal_joints) != 12:
            return self.body
        key = self._calibration_key(cal_joints)
        cached = self._cal_cache.get(key)
        if cached is not None:
            return cached
        from gateway.neural_gait.tensor_body import TensorBody

        cfg_dict = dict(vars(self.env_config))
        cfg_dict["robot"] = {**dict(self.env_config.robot), "calibration": [dict(j) for j in cal_joints]}
        try:
            live_body = TensorBody(self.geometry, SimpleNamespace(**cfg_dict), device=self.device)
        except Exception:
            live_body = self.body
        self._cal_cache[key] = live_body
        return live_body

    def continuous_decode_rad(
        self,
        actions: torch.Tensor,
        *,
        body=None,
        grid_steps: int = 65,
        sub_steps: int = 17,
    ) -> torch.Tensor:
        """Continuously project `origin + s * act * scale` onto the connected feasible manifold from s=0.

        Eliminates P4 `2^-k` binary-halving discontinuities (1.0 -> 0.5 -> 0.25 = 25 deg jumps)
        and hip-cylinder (`zz < 0`) topological branch flips while preserving 100% reachable travel.
        """
        b = self.body if body is None else body
        if b.O.device.type == "cpu":
            fb = _fast_numpy_body(b)
            act_np = actions.detach().cpu().numpy() if isinstance(actions, torch.Tensor) else np.asarray(actions)
            out_np = fb.continuous_decode_rad(act_np, grid_steps=grid_steps, sub_steps=sub_steps)
            return torch.from_numpy(out_np).to(dtype=b.O.dtype, device=b.O.device)

        act = actions.to(dtype=b.O.dtype, device=b.device).reshape(-1, 4, 3)
        bsz = act.shape[0]
        scale43 = b.scale.reshape(1, 1, 1, 3)

        def eval_grid(s_grid: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
            target = b.origin.reshape(1, 1, 4, 3) + act.unsqueeze(1) * scale43 * s_grid.unsqueeze(-1)
            q, valid = b.inverse(target)
            inb = ((q >= b.low) & (q <= b.high)).all(-1)
            if bool((valid & (~inb)).any()):
                proj, pok = b.bounded(q)
                q = torch.where(inb.unsqueeze(-1), q, proj)
                valid = valid & torch.where(inb, True, pok)
            pulse = torch.floor(b.pulse_home + (torch.rad2deg(q) - b.home) * b.pulse_scale + 0.5)
            valid = valid & ((pulse[..., 1:] >= 300) & (pulse[..., 1:] <= 2950)).all(-1)
            valid = valid & ((pulse >= 1) & (pulse <= 65535)).all(-1)
            return q, valid

        s_lin = torch.linspace(0.0, 1.0, grid_steps, dtype=b.O.dtype, device=b.device)
        s_grid = s_lin.reshape(1, grid_steps, 1).expand(bsz, grid_steps, 4)
        q_grid, valid_grid = eval_grid(s_grid)
        step_smooth = (q_grid[:, 1:] - q_grid[:, :-1]).abs().amax(dim=-1) <= math.radians(24.0)
        valid_conn = valid_grid.clone()
        valid_conn[:, 0, :] = True
        valid_conn[:, 1:, :] = valid_conn[:, 1:, :] & step_smooth
        valid_conn = valid_conn.cumprod(dim=1).to(torch.bool)

        idx_lo = valid_conn.to(torch.int64).sum(dim=1) - 1
        all_ok = idx_lo == (grid_steps - 1)
        q_lo = torch.gather(q_grid, 1, idx_lo[:, None, :, None].expand(bsz, 1, 4, 3)).squeeze(1)
        if bool(all_ok.all()):
            return q_lo.reshape(bsz, 12)

        s_lo = s_lin[idx_lo]
        s_hi = s_lin[(idx_lo + 1).clamp(max=grid_steps - 1)]
        u_sub = torch.linspace(0.0, 1.0, sub_steps, dtype=b.O.dtype, device=b.device)[1:-1]
        s_sub = s_lo.unsqueeze(1) + u_sub.reshape(1, -1, 1) * (s_hi - s_lo).unsqueeze(1)
        q_sub, ok_sub = eval_grid(s_sub)
        q_chain = torch.cat([q_lo.unsqueeze(1), q_sub], dim=1)
        sub_smooth = (q_chain[:, 1:] - q_chain[:, :-1]).abs().amax(dim=-1) <= math.radians(16.0)
        sub_conn = ((~all_ok).unsqueeze(1) & ok_sub & sub_smooth).cumprod(dim=1).to(torch.bool)
        sub_idx = sub_conn.to(torch.int64).sum(dim=1)
        best_q = torch.gather(q_chain, 1, sub_idx[:, None, :, None].expand(bsz, 1, 4, 3)).squeeze(1)
        return best_q.reshape(bsz, 12)

    def step_host_command(
        self,
        actions,
        prev_q_rad: torch.Tensor,
        *,
        speed_scale: float = 1.0,
        body=None,
    ) -> tuple[torch.Tensor, list[float], list[float]]:
        """Decode policy actions smoothly on the closed four-bar manifold at physical motor speed.

        Returns `(next_q_rad [1,12], applied_action [12], feet_mm [12])` where `feet_mm` is
        guaranteed valid at `fraction = 1.0` on the P4's `ainekio_v2_nominal_foot_pose`.
        """
        b = self.body if body is None else body
        no_load_deg_s = float(getattr(self.env_config, "motor_no_load_speed_deg_s", 545.4545454545455))
        max_travel = math.radians(no_load_deg_s * max(0.25, min(1.0, float(speed_scale)))) / 50.0

        if b.O.device.type == "cpu":
            fb = _fast_numpy_body(b)
            act_np = actions.detach().cpu().numpy() if isinstance(actions, torch.Tensor) else np.asarray(actions, dtype=np.float64)
            goal = fb.continuous_decode_rad(act_np).reshape(1, 4, 3)
            prev = (
                prev_q_rad.detach().cpu().numpy() if isinstance(prev_q_rad, torch.Tensor) else np.asarray(prev_q_rad, dtype=np.float64)
            ).reshape(1, 4, 3)
            delta = goal - prev
            leg_max = np.maximum(np.amax(np.abs(delta), axis=-1, keepdims=True), 1e-12)
            u = np.minimum(max_travel / leg_max, 1.0)
            cand = prev + u * delta
            q_b, closed = fb.bounded(cand)
            pulse = np.floor(fb.pulse_home + (np.rad2deg(q_b) - fb.home) * fb.pulse_scale + 0.5)
            pulse_ok = np.all((pulse[..., 1:] >= 300.0) & (pulse[..., 1:] <= 2950.0), axis=-1) & np.all(
                (pulse >= 1.0) & (pulse <= 65535.0), axis=-1
            )
            ok = closed & pulse_ok
            q_sel = np.where(ok[..., None], q_b, prev)
            q_log, _ = fb.pwm(q_sel)
            pts, _ = fb.forward(q_log.reshape(1, 4, 3))
            feet_mm = (pts - fb.origin[None, ...]).reshape(12)
            applied_act = np.clip(feet_mm / np.tile(fb.scale, 4), -1.0, 1.0)
            return (
                torch.from_numpy(q_log.reshape(1, 12)).to(dtype=b.O.dtype, device=b.O.device),
                applied_act.tolist(),
                feet_mm.tolist(),
            )

        act_t = torch.as_tensor(actions, dtype=b.O.dtype, device=b.device).reshape(1, 12)
        goal = self.continuous_decode_rad(act_t, body=b).reshape(1, 4, 3)
        prev = prev_q_rad.to(dtype=b.O.dtype, device=b.device).reshape(1, 4, 3)
        delta = goal - prev
        leg_max = delta.abs().amax(dim=-1, keepdim=True).clamp_min(1e-12)
        u = (max_travel / leg_max).clamp(max=1.0)
        cand = prev + u * delta
        q_b, closed = b.bounded(cand)
        pulse = torch.floor(b.pulse_home + (torch.rad2deg(q_b) - b.home) * b.pulse_scale + 0.5)
        pulse_ok = ((pulse[..., 1:] >= 300) & (pulse[..., 1:] <= 2950)).all(-1) & (
            (pulse >= 1) & (pulse <= 65535)
        ).all(-1)
        ok = closed & pulse_ok
        q_sel = torch.where(ok.unsqueeze(-1), q_b, prev)
        q_log, _ = b.pwm(q_sel)
        pts, _ = b.forward(q_log.reshape(1, 4, 3))
        feet_mm = (pts - b.origin.unsqueeze(0)).reshape(12)
        applied_act = (feet_mm / b.scale.repeat(4)).clamp(-1.0, 1.0)
        return q_log.reshape(1, 12), applied_act.cpu().tolist(), feet_mm.cpu().tolist()

    def project_batch_rad(self, q_rad: torch.Tensor, *, body=None) -> tuple[torch.Tensor, torch.Tensor]:
        """Project (N, 12) rad onto closed four-bar + pulse bounds; return (q_bounded_rad, foot_norm)."""
        b = self.body if body is None else body
        orig_shape = q_rad.shape
        q43 = q_rad.to(dtype=torch.float64, device=b.device).reshape(-1, 4, 3)
        # First clamp to calibrated electrical limits, then run Gauss-Newton closure
        q_clamped = q43.clamp(b.low, b.high)
        # Shoulder limits from target_limits_deg
        lims = (
            torch.tensor(self.env_config.target_limits_deg, dtype=torch.float64, device=b.device)
            .reshape(4, 3, 2)
            * (math.pi / 180.0)
        )
        q_clamped = torch.maximum(torch.minimum(q_clamped, lims[..., 1]), lims[..., 0])
        q_b, valid = b.bounded(q_clamped)
        pts, fvalid = b.forward(q_b)
        ok = valid & fvalid
        if not bool(ok.all()):
            q_fallback = b.q0.unsqueeze(0).expand_as(q_b)
            q_b = torch.where(ok.unsqueeze(-1), q_b, q_fallback)
            pts, _ = b.forward(q_b)
        foot_norm = ((pts - b.origin) / b.scale).clamp(-1.0, 1.0)
        q_consistent = self.continuous_decode_rad(foot_norm.reshape(-1, 12), body=b).reshape(-1, 4, 3)
        pts_c, _ = b.forward(q_consistent)
        foot_norm_c = ((pts_c - b.origin) / b.scale).clamp(-1.0, 1.0)
        return (
            q_consistent.reshape(orig_shape).to(dtype=torch.float32),
            foot_norm_c.reshape(*orig_shape[:-1], 12).to(dtype=torch.float32),
        )

    def project_angles_deg(self, angles_deg, *, body=None) -> tuple[list[float], list[float]]:
        b = self.body if body is None else body
        q = torch.tensor(angles_deg, dtype=torch.float64, device=b.device).reshape(1, 12) * (math.pi / 180.0)
        q_rad, foot_norm = self.project_batch_rad(q, body=b)
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
        """Resolve `body` or `feet` relative to `current_deg`, preserving unmentioned legs on `feet`."""
        args = action["arguments"]
        op_name = action["name"]
        seed_proj_deg, _ = self.project_angles_deg(list(current_deg))
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

        pivot = np.asarray(
            self.geometry.get("continuous_walk", {}).get("body_rotation_pivot_mm", [0.0, 0.0, 65.0]),
            dtype=np.float64,
        )
        desired_feet = np.zeros((4, 3), dtype=np.float64)
        feet_np = feet_mm.cpu().numpy()
        for idx, leg in enumerate(CAD_LEG_ORDER):
            world_foot = feet_np[idx] + delta_map.get(leg, np.zeros(3, dtype=np.float64))
            if op_name == "body":
                # Body translates by `trans` and rotates by `rot` around `pivot` ([0, 0, 65] mm)
                # while stance feet stay planted (`reference.py:53-54`):
                # world_foot = trans + pivot + rot @ (p_body - pivot)
                desired_feet[idx] = pivot + rot.T @ (world_foot - trans - pivot)
            else:
                desired_feet[idx] = world_foot

        desired_t = torch.tensor(desired_feet, dtype=torch.float64, device=self.device)
        norm_act = ((desired_t - self.body.origin) / self.body.scale).clamp(-1.0, 1.0).reshape(1, 12)
        q_dec = self.continuous_decode_rad(norm_act).reshape(1, 12)
        decoded_deg = (q_dec[0] * (180.0 / math.pi)).cpu().tolist()
        if op_name == "feet":
            out_deg = list(seed_proj_deg)
            for idx, leg in enumerate(CAD_LEG_ORDER):
                if leg in delta_map:
                    out_deg[idx * 3 : idx * 3 + 3] = decoded_deg[idx * 3 : idx * 3 + 3]
            return out_deg
        return decoded_deg


def _is_nonstanding_posture(deg: list[float]) -> bool:
    """Return True when any leg is crouched/folded/lifted away from nominal standing."""
    for leg_idx in range(4):
        sh = deg[leg_idx * 3 + 0]
        ca = deg[leg_idx * 3 + 1]
        cr = deg[leg_idx * 3 + 2]
        if (
            abs(sh - STAND_ANGLES_DEG[leg_idx * 3 + 0]) > 20.0
            or abs(ca - STAND_ANGLES_DEG[leg_idx * 3 + 1]) > 18.0
            or abs(cr - STAND_ANGLES_DEG[leg_idx * 3 + 2]) > 18.0
        ):
            return True
    return False


def _pose_segment_duration_s(
    max_delta_deg: float,
    speed_scale: float,
    *,
    is_stand: bool = False,
    from_nonstanding: bool = False,
) -> float:
    """Compute realistic closed-loop servo + policy settling budget (independent of 2000 deg/s NVS ramp)."""
    servo_travel_deg_s = max(40.0, 115.0 * speed_scale)
    base = max_delta_deg / servo_travel_deg_s + (0.65 if (is_stand or from_nonstanding) else 0.55)
    floor = 1.75 if (max_delta_deg > 45.0 or from_nonstanding) else (1.05 if is_stand else 0.90)
    return max(floor, min(4.0, base))


def compile_goal_segments(program: list[dict], observation: dict, manifold: PoseManifold) -> list[dict]:
    """Convert a Freestyle/Library program into non-blocking 50 Hz goal segments."""
    joints_obs = observation.get("joints") or {}
    home_deg = [float((joints_obs.get(j) or {}).get("home_deg", STAND_ANGLES_DEG[i])) for i, j in enumerate(JOINTS)]
    raw_initial_deg = usable_joint_angles_deg(observation)
    cursor_deg, _ = manifold.project_angles_deg(raw_initial_deg)
    posture_initialized = False

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
            posture_initialized = True
            continue

        speed_pct = float(args.get("speed_pct", 70))
        speed_scale = max(0.15, min(1.0, speed_pct / 100.0))

        if name == "stand":
            physical_start_deg = list(raw_initial_deg) if not posture_initialized else list(cursor_deg)
            from_nonstanding = (not posture_initialized) and _is_nonstanding_posture(raw_initial_deg)
            goal_deg, goal_foot_norm = manifold.project_angles_deg(STAND_ANGLES_DEG)
            max_delta = max(abs(a - b) for a, b in zip(goal_deg, physical_start_deg))
            duration_s = _pose_segment_duration_s(
                max_delta, speed_scale, is_stand=True, from_nonstanding=from_nonstanding
            )
            segments.append(
                {
                    "kind": "pose_goal",
                    "index": index,
                    "action": action,
                    "start_deg": physical_start_deg,
                    "goal_deg": goal_deg,
                    "goal_foot_norm": goal_foot_norm,
                    "leg_support": [1.0, 1.0, 1.0, 1.0],
                    "speed_scale": speed_scale,
                    "duration_s": duration_s,
                }
            )
            cursor_deg = list(goal_deg)
            posture_initialized = True
            continue

        if name in ("move", "pose"):
            physical_start_deg = list(raw_initial_deg) if not posture_initialized else list(cursor_deg)
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
            max_delta = max(abs(a - b) for a, b in zip(goal_deg, physical_start_deg))
            duration_s = _pose_segment_duration_s(max_delta, speed_scale)
            segments.append(
                {
                    "kind": "pose_goal",
                    "index": index,
                    "action": action,
                    "start_deg": physical_start_deg,
                    "goal_deg": goal_deg,
                    "goal_foot_norm": goal_foot_norm,
                    "leg_support": support,
                    "speed_scale": speed_scale,
                    "duration_s": duration_s,
                }
            )
            cursor_deg = list(goal_deg)
            posture_initialized = True
            continue

        if name in ("feet", "body"):
            physical_start_deg = list(raw_initial_deg) if not posture_initialized else list(cursor_deg)
            from_nonstanding = False
            if not posture_initialized:
                if _is_nonstanding_posture(raw_initial_deg):
                    cursor_deg, _ = manifold.project_angles_deg(STAND_ANGLES_DEG)
                    from_nonstanding = True
                posture_initialized = True
            resolved = manifold.resolve_spatial_deg(action, cursor_deg)
            goal_deg, goal_foot_norm = manifold.project_angles_deg(resolved)
            support = manifold.infer_leg_support(goal_deg)
            max_delta = max(abs(a - b) for a, b in zip(goal_deg, physical_start_deg))
            duration_s = _pose_segment_duration_s(max_delta, speed_scale, from_nonstanding=from_nonstanding)
            segments.append(
                {
                    "kind": "pose_goal",
                    "index": index,
                    "action": action,
                    "start_deg": physical_start_deg,
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
            if "joint" in args:
                moving = [args["joint"]]
                j_indices = [JOINTS.index(args["joint"])]
                centers = [cursor_deg[j_indices[0]]]
                amps = [float(args["amplitude_deg"])]
            else:
                moving = list(args["joints"])
                j_indices = [JOINTS.index(j) for j in moving]
                ref = args.get("reference", "absolute")
                centers = []
                for j_idx, c_val in zip(j_indices, args.get("center_deg", [0.0] * len(j_indices))):
                    if ref == "current":
                        centers.append(cursor_deg[j_idx] + float(c_val))
                    elif ref == "home":
                        centers.append(home_deg[j_idx] + float(c_val))
                    else:
                        centers.append(float(c_val))
                raw_amp = args["amplitude_deg"]
                amps = [float(a) for a in raw_amp] if isinstance(raw_amp, (list, tuple)) else [float(raw_amp)] * len(j_indices)
            max_amp = max((abs(a) for a in amps), default=15.0)
            default_hz = max(0.45, min(2.2, (115.0 * speed_scale) / max(12.0, 4.0 * max_amp)))
            hz = max(0.2, min(4.0, float(args.get("hz", default_hz))))
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
            posture_initialized = True
            continue

        raise ValueError(f"Unsupported operation in neural pose sequencer: {name}")

    return segments
