"""GPU MuJoCo (mjlab) PPO trainer, evaluator & ONNX exporter for V3 12-servo Neural Gait.

Full V2-aligned architecture ported onto V3 Option A-1 CAD + DS3225 PRO hardware:
  - Schema: "ainekio-v3-neural-gait-v2-proprio" (48 V2 proprio features + 2 speed-adaptive 1.30..2.00 Hz CPG phase x 12 frames = 600 obs)
  - Actor MLP: ObsNormalizer(600) -> 128 -> 64 -> 32 -> 12 (ELU hidden, Tanh output)
  - Action: 12 normalized [-1, 1] Cartesian foot offsets [dx, dy, dz] per leg,
    scaled by (78, 28, 36) mm and decoded via batched closed-form 4-bar IK
    (exact parity with Slave/software/models/v3-12servo/v3_kinematics.c) with
    8-step boundary bisection projection (1/256 precision; eliminates 50% step-jump cliffs).
  - Sensors: 500 Hz sampling, 50 Hz One-Euro filtered joint pos/vel, 208 Hz IMU + gravity.
  - Physics: exact closed-chain Option A-1 4-bar + double-parallelogram self-leveling ankles,
    full-speed DS3225 PRO 7.4V (3.43 Nm, 800 deg/s), CG solver (50 iters, njmax=512).
  - Training: V2 WalkingDifficulty flat-first curriculum, TerrainHeightSensorCfg foot height scan,
    V2 BoundedCost reward suite (with crab/turn-gated lateral stride + 2nd-diff chatter suppressor),
    multi-surface friction + actuator + mass/CoM DR, exact L<->R mirror symmetry, and V2
    critic-calibrated low-LR resume.

All evaluation metrics are MuJoCo simulation evidence (CAD-estimated 2.97 kg mass,
mass_measured=false), not physical hardware qualification.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

import mujoco
import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[3]
MASTER_DIR = str(ROOT / "Master")
if MASTER_DIR not in sys.path:
    sys.path.insert(0, MASTER_DIR)

from mjlab.entity import EntityArticulationInfoCfg, EntityCfg
from mjlab.envs import ManagerBasedRlEnv, mdp as env_mdp
from mjlab.managers import (
    CurriculumTermCfg,
    EventTermCfg,
    ObservationGroupCfg,
    ObservationTermCfg,
    RewardTermCfg,
    SceneEntityCfg,
    TerminationTermCfg,
)
from mjlab.managers.action_manager import ActionTerm, ActionTermCfg
from mjlab.managers.event_manager import requires_model_fields
from mjlab.rl import RslRlVecEnvWrapper
from mjlab.sensor import ContactMatch, ContactSensorCfg, ObjRef, RingPatternCfg, TerrainHeightSensorCfg
from mjlab.tasks.velocity import mdp as vel_mdp
import mjlab.terrains as terrain_gen
from mjlab.terrains.terrain_generator import TerrainGeneratorCfg
from collections import deque
from mjlab_microduck.tasks import mdp as upstream_mdp
from mjlab_microduck.tasks.microduck_velocity_env_cfg import (
    MicroduckRlCfg,
    make_microduck_velocity_env_cfg,
)

from gateway.neural_gait.artifacts import save_json
from gateway.neural_gait.microduck import (
    AinekioOnPolicyRunner,
    ElevatedRingPatternCfg,
    LearningObstaclesCfg,
    LearningSlopeCfg,
    LearningStairsCfg,
    LearningWaveCfg,
    MG90SActuatorCfg,
    mg90s_force_fields,
    motor_force_range,
)
from gateway.neural_gait import microduck_mdp as v2_mdp
from gateway.neural_gait.v3_environment import (
    V3_CARRIER_LIMITS_RAD,
    V3_CRANK_LIMITS_RAD,
    V3_JOINTS,
    V3_LEGS,
    V3_SERVO_EFFORT_NM,
    V3_SERVO_KP,
    V3_SERVO_KV,
    V3_SERVO_NO_LOAD_RAD_S,
    V3_SHOULDER_LIMITS_RAD,
    build_v3_xml,
    load_v3_geometry,
)

V3_SCHEMA = "ainekio-v3-neural-gait-v2-proprio"
V3_FEATURES = 50
V3_SAMPLES = 12
V3_OBS_SIZE = V3_FEATURES * V3_SAMPLES  # 600 (48 V2 proprio features + 2 CPG phase x 12 frames)
V3_GAIT_HZ = 1.65
V3_GAIT_HZ_MIN = 1.30
V3_GAIT_HZ_MAX = 2.00
V3_FOOT_ACTION_SCALE_MM = (78.0, 28.0, 36.0)
V3_ACTUATOR_DELAY_SUBSTEPS = 15  # 30 ms @ 500 Hz (50 Hz PCA9685 PWM frame + DS3225 PRO response lag; kills 25 Hz chatter)
V3_DEFAULT_HIDDEN_DIMS = (128, 64, 32)


def v3_gait_hz_torch(cmd: torch.Tensor) -> torch.Tensor:
    """Speed-adaptive trot cadence (1.30..2.00 Hz), exact match to v3_microduck.c."""
    lin = torch.hypot(cmd[:, 0], cmd[:, 1])
    eff = (lin / 0.38 + 0.45 * cmd[:, 2].abs() / 1.30).clamp(0.0, 1.0)
    return V3_GAIT_HZ_MIN + (V3_GAIT_HZ_MAX - V3_GAIT_HZ_MIN) * eff


def v3_gait_hz_np(cmd: np.ndarray) -> float:
    """NumPy scalar equivalent of v3_gait_hz_torch for standalone CPU evaluation."""
    lin = math.hypot(float(cmd[0]), float(cmd[1]))
    eff = min(1.0, max(0.0, lin / 0.38 + 0.45 * abs(float(cmd[2])) / 1.30))
    return V3_GAIT_HZ_MIN + (V3_GAIT_HZ_MAX - V3_GAIT_HZ_MIN) * eff


def _wrap_rad(a: torch.Tensor) -> torch.Tensor:
    return torch.atan2(torch.sin(a), torch.cos(a))


class V3TensorBody:
    """Batched GPU/CPU closed-form Option A-1 4-bar FK, IK & 13-step feasibility decoder.

    Exact parity with Slave/software/models/v3-12servo/v3_kinematics.c.
    """

    def __init__(self, geo: dict, *, device: str | torch.device = "cpu", scale_mm=V3_FOOT_ACTION_SCALE_MM):
        self.device = torch.device(device)
        dt = torch.float64

        def t(val):
            return torch.as_tensor(val, dtype=dt, device=self.device)

        lk = geo["linkage_mm"]
        self.L_car = float(lk["carrier"])
        self.L_crk = float(lk["crank"])
        self.L_pk = float(lk["pickup"])
        self.L_rod = float(lk["rod"])
        self.a0 = float(lk["alpha_zero_rad"])
        self.t0 = float(lk["theta_zero_rad"])
        self.b_off = float(lk["beta_offset_rad"])

        legs = [geo["legs"][name] for name in V3_LEGS]
        self.roll_sign = t([float(g["shoulder_roll_sign"]) for g in legs])          # (4,)
        self.sh_mm = t([g["shoulder_in_robot_mm"] for g in legs])                  # (4, 3)
        self.O_mm = t([g["carrier_in_shoulder_mm"] for g in legs])                 # (4, 3)
        self.C_mm = t([g["crank_in_shoulder_mm"] for g in legs])                   # (4, 3)
        self.sole_k_mm = t([g["sole_center_in_knee_mm"] for g in legs])            # (4, 3)
        self.y_const = self.O_mm[:, 1] + self.sole_k_mm[:, 1]                      # (4,)
        self.L_foot = torch.hypot(self.sole_k_mm[:, 0], self.sole_k_mm[:, 2])      # (4,)
        self.f2 = self.sole_k_mm[:, 0] ** 2 + self.sole_k_mm[:, 2] ** 2            # (4,)
        self.neutral_kx = self.O_mm[:, 0] + self.L_car * math.cos(self.a0)         # (4,)
        self.neutral_kz = self.O_mm[:, 2] + self.L_car * math.sin(self.a0)         # (4,)
        self.q0 = torch.zeros((4, 3), dtype=dt, device=self.device)
        neutral_pos, _, _ = self.forward(self.q0.unsqueeze(0))
        self.neutral_sole_mm = neutral_pos.squeeze(0)                              # (4, 3)

        self.scale_mm = t(scale_mm)                                                # (3,)
        self.scale_mm_f32 = torch.as_tensor(scale_mm, dtype=torch.float32, device=self.device)

        self.lo_rad = t([V3_SHOULDER_LIMITS_RAD[0], V3_CARRIER_LIMITS_RAD[0], V3_CRANK_LIMITS_RAD[0]])
        self.hi_rad = t([V3_SHOULDER_LIMITS_RAD[1], V3_CARRIER_LIMITS_RAD[1], V3_CRANK_LIMITS_RAD[1]])
        # Neutral foot positions in torso body frame (metres, shoulder-z origin)
        sh_z = 140.0
        origin_b_mm = self.neutral_sole_mm.clone()
        origin_b_mm[:, 2] -= sh_z
        self.foot_home_b_m = (origin_b_mm * 1e-3).to(torch.float32)                # (4, 3)

    def forward(self, q_rad: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """Forward kinematics: q_rad (..., 4, 3) -> (foot_robot_mm (..., 4, 3), valid, sin_mu)."""
        h_rad, alpha_rad, theta_rad = q_rad.unbind(-1)
        a = self.a0 + alpha_rad
        t = self.t0 + theta_rad

        dx = self.O_mm[:, 0] + self.L_car * torch.cos(a)
        dz = self.O_mm[:, 2] + self.L_car * torch.sin(a)
        px = self.C_mm[:, 0] + self.L_crk * torch.cos(t)
        pz = self.C_mm[:, 2] + self.L_crk * torch.sin(t)

        wx = px - dx
        wz = pz - dz
        d = torch.hypot(wx, wz)
        d_safe = d.clamp_min(1e-6)
        pk2 = self.L_pk * self.L_pk
        rd2 = self.L_rod * self.L_rod
        along = (pk2 - rd2 + d * d) / (2.0 * d_safe)
        h2 = pk2 - along * along
        valid = (d > 10.5) & (d < 101.5) & (h2 > 0.0)
        hh = torch.sqrt(h2.clamp_min(0.0))

        ex = dx + (along * wx - hh * wz) / d_safe
        ez = dz + (along * wz + hh * wx) / d_safe

        ux = (ex - dx) / self.L_pk
        uz = (ez - dz) / self.L_pk
        vx = (ex - px) / self.L_rod
        vz = (ez - pz) / self.L_rod
        sin_mu = (ux * vz - uz * vx).abs()

        beta = torch.atan2(ez - dz, ex - dx)
        diff = beta - self.b_off
        knee_rot_y = -torch.atan2(torch.sin(diff), torch.cos(diff))

        cy = torch.cos(knee_rot_y)
        sy = torch.sin(knee_rot_y)
        sx = self.sole_k_mm[:, 0]
        sy_lat = self.sole_k_mm[:, 1]
        sz = self.sole_k_mm[:, 2]

        fx_sh = dx + cy * sx + sy * sz
        fy_sh = self.O_mm[:, 1] + sy_lat
        fz_sh = dz - sy * sx + cy * sz

        rx = self.roll_sign * h_rad
        cr = torch.cos(rx)
        sr = torch.sin(rx)

        fx = self.sh_mm[:, 0] + fx_sh
        fy = self.sh_mm[:, 1] + cr * fy_sh - sr * fz_sh
        fz = self.sh_mm[:, 2] + sr * fy_sh + cr * fz_sh
        return torch.stack((fx, fy, fz), dim=-1), valid, sin_mu

    def forward_body_m(self, q_rad_flat: torch.Tensor) -> torch.Tensor:
        """FK foot positions in torso body frame (metres, shoulder-z origin), shape (N, 4, 3) float32."""
        q = q_rad_flat.to(torch.float64).reshape(-1, 4, 3)
        pos_rob_mm, _, _ = self.forward(q)
        pos_b = pos_rob_mm.clone()
        pos_b[..., 2] -= 140.0
        return (pos_b * 1e-3).to(torch.float32)

    def inverse_offset(self, offset_mm: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        """Closed-form IK from neutral sole offset (..., 4, 3) mm -> (q_rad (..., 4, 3), valid)."""
        target_rob = self.neutral_sole_mm + offset_mm
        tx = target_rob[..., 0] - self.sh_mm[:, 0]
        ty = target_rob[..., 1] - self.sh_mm[:, 1]
        tz = target_rob[..., 2] - self.sh_mm[:, 2]

        # 1. Closed-form shoulder roll h_rad
        yc = self.y_const
        r2 = ty * ty + tz * tz
        r2_safe = r2.clamp_min(1e-6)
        radicand = r2 - yc * yc
        valid = radicand > 1e-4
        z_sh = -torch.sqrt(radicand.clamp_min(1e-6))
        cr = (yc * ty + z_sh * tz) / r2_safe
        sr = (yc * tz - z_sh * ty) / r2_safe
        rx = torch.atan2(sr, cr)
        h_raw = rx / self.roll_sign
        h_rad = h_raw.clamp(self.lo_rad[0], self.hi_rad[0])

        # 2. Circle intersection for Knee (D) in sagittal plane
        ox = self.O_mm[:, 0]
        oz = self.O_mm[:, 2]
        sx = self.sole_k_mm[:, 0]
        sz = self.sole_k_mm[:, 2]

        vx = tx - ox
        vz = z_sh - oz
        dist = torch.hypot(vx, vz)
        dist_safe = dist.clamp_min(1e-6)
        valid = valid & (dist >= (self.L_car - self.L_foot).abs() + 1e-3) & (dist <= self.L_car + self.L_foot - 1e-3)

        c2 = self.L_car * self.L_car
        along = (c2 - self.f2 + dist * dist) / (2.0 * dist_safe)
        h2 = c2 - along * along
        valid = valid & (h2 >= 0.0)
        hh = torch.sqrt(h2.clamp_min(0.0))

        ax = ox + (along * vx - hh * vz) / dist_safe
        az = oz + (along * vz + hh * vx) / dist_safe
        bx = ox + (along * vx + hh * vz) / dist_safe
        bz = oz + (along * vz - hh * vx) / dist_safe
        da = (ax - self.neutral_kx) ** 2 + (az - self.neutral_kz) ** 2
        db = (bx - self.neutral_kx) ** 2 + (bz - self.neutral_kz) ** 2
        use_a = da <= db
        kx = torch.where(use_a, ax, bx)
        kz = torch.where(use_a, az, bz)

        alpha_raw = _wrap_rad(torch.atan2(kz - oz, kx - ox) - self.a0)
        alpha_rad = alpha_raw.clamp(self.lo_rad[1], self.hi_rad[1])

        # 3. Lower-leg orientation -> pickup point E
        lx = tx - kx
        lz = z_sh - kz
        cy = (lx * sx + lz * sz) / self.f2
        sy = (lx * sz - lz * sx) / self.f2
        knee_rot_y = torch.atan2(sy, cy)
        beta = self.b_off - knee_rot_y

        ex = kx + self.L_pk * torch.cos(beta)
        ez = kz + self.L_pk * torch.sin(beta)

        # 4. Crank circle (C, r=22) x Rod circle (E, R=56) -> P
        cx = self.C_mm[:, 0]
        cz = self.C_mm[:, 2]
        ex_c = ex - cx
        ez_c = ez - cz
        dc = torch.hypot(ex_c, ez_c)
        dc_safe = dc.clamp_min(1e-6)
        valid = valid & (dc >= abs(self.L_crk - self.L_rod) + 1e-3) & (dc <= self.L_crk + self.L_rod - 1e-3)

        ca = (self.L_crk * self.L_crk - self.L_rod * self.L_rod + dc * dc) / (2.0 * dc_safe)
        ch2 = self.L_crk * self.L_crk - ca * ca
        valid = valid & (ch2 >= 0.0)
        ch = torch.sqrt(ch2.clamp_min(0.0))

        margin = math.radians(1.0)
        best_theta = torch.zeros_like(alpha_rad)
        best_err = torch.full_like(alpha_rad, 1e9)
        found = torch.zeros_like(valid)

        for sign in (-1.0, 1.0):
            px = cx + (ca * ex_c - sign * ch * ez_c) / dc_safe
            pz = cz + (ca * ez_c + sign * ch * ex_c) / dc_safe
            td = _wrap_rad(torch.atan2(pz - cz, px - cx) - self.t0)
            in_lim = (td >= self.lo_rad[2] - margin) & (td <= self.hi_rad[2] + margin)
            tc = td.clamp(self.lo_rad[2], self.hi_rad[2])
            q_cand = torch.stack((h_rad, alpha_rad, tc), dim=-1)
            fk_pos, fk_ok, fk_sin = self.forward(q_cand)
            err = torch.hypot(fk_pos[..., 0] - target_rob[..., 0], fk_pos[..., 2] - target_rob[..., 2])
            score = err + 0.005 * torch.rad2deg(tc.abs())
            ok = valid & in_lim & fk_ok & (fk_sin >= 0.15) & (err <= 5.0)
            better = ok & (score < best_err)
            best_err = torch.where(better, score, best_err)
            best_theta = torch.where(better, tc, best_theta)
            found = found | ok

        q_out = torch.stack((h_rad, alpha_rad, best_theta), dim=-1)
        return q_out, found

    def decode(self, actions: torch.Tensor) -> torch.Tensor:
        """Decode (N, 12) normalized Cartesian foot offsets -> (N, 12) feasible joint targets (rad, float32).

        Exact parity with v3_microduck.c:
          - Full offset if valid;
          - Stage 1: preserve 100% of horizontal stride (dx, dy), 6-step bisect z from z_ref=clamp(dz, 0, 14) -> dz;
          - Stage 2: 7-step radial bisection from (0, 0, 0) -> (dx, dy, dz).
        """
        n = actions.shape[0]
        full_f32 = actions.to(torch.float32).reshape(n, 4, 3) * self.scale_mm_f32
        dx_f32 = full_f32[..., 0]
        dy_f32 = full_f32[..., 1]
        dz_f32 = full_f32[..., 2]
        q_full, ok_full = self.inverse_offset(full_f32.to(torch.float64))

        # Stage 1: vertical z-projection toward 14 mm sweet-spot preserving 100% of (dx, dy)
        z_ref = dz_f32.clamp(0.0, 14.0)
        ref_f32 = torch.stack((dx_f32, dy_f32, z_ref), dim=-1)
        q_z, ok_ref = self.inverse_offset(ref_f32.to(torch.float64))
        lo_z = torch.zeros((n, 4), dtype=torch.float32, device=actions.device)
        hi_z = torch.ones((n, 4), dtype=torch.float32, device=actions.device)
        for _ in range(6):
            mid_z = 0.5 * (lo_z + hi_z)
            zm = z_ref + (dz_f32 - z_ref) * mid_z
            cand_z = torch.stack((dx_f32, dy_f32, zm), dim=-1).to(torch.float64)
            qm, okm = self.inverse_offset(cand_z)
            lo_z = torch.where(okm, mid_z, lo_z)
            hi_z = torch.where(okm, hi_z, mid_z)
            q_z = torch.where(okm.unsqueeze(-1), qm, q_z)

        # Stage 2: radial bisection from (0, 0, 0) when horizontal (dx, dy) itself exceeds linkage reach
        lo_r = torch.zeros((n, 4), dtype=torch.float32, device=actions.device)
        hi_r = torch.ones((n, 4), dtype=torch.float32, device=actions.device)
        q_r = torch.zeros_like(q_full)
        for _ in range(7):
            mid_r = 0.5 * (lo_r + hi_r)
            cand_r = (full_f32 * mid_r.unsqueeze(-1)).to(torch.float64)
            qm, okm = self.inverse_offset(cand_r)
            lo_r = torch.where(okm, mid_r, lo_r)
            hi_r = torch.where(okm, hi_r, mid_r)
            q_r = torch.where(okm.unsqueeze(-1), qm, q_r)

        q_proj = torch.where(ok_ref.unsqueeze(-1), q_z, q_r)
        q_sel = torch.where(ok_full.unsqueeze(-1), q_full, q_proj)
        q_sel = q_sel.clamp(self.lo_rad, self.hi_rad)
        return q_sel.reshape(n, 12).to(torch.float32)


class V3TensorSensors:
    """500 Hz sensor sampling with V2's production 50 Hz One-Euro feedback filter & IMU noise."""

    def __init__(self, num_envs: int, device: str | torch.device, *, sensor_noise: bool = True, physics_hz: int = 500):
        self.num_envs = int(num_envs)
        self.device = torch.device(device)
        self.sensor_noise = bool(sensor_noise)
        self.physics_hz = int(physics_hz)
        self.q_raw = torch.zeros((num_envs, 12), dtype=torch.float32, device=self.device)
        self.q_filt = torch.zeros((num_envs, 12), dtype=torch.float32, device=self.device)
        self.deriv = torch.zeros((num_envs, 12), dtype=torch.float32, device=self.device)
        self.dq_filt = torch.zeros((num_envs, 12), dtype=torch.float32, device=self.device)
        self.gyro = torch.zeros((num_envs, 3), dtype=torch.float32, device=self.device)
        self.accel_g = torch.zeros((num_envs, 3), dtype=torch.float32, device=self.device)
        self.grav = torch.zeros((num_envs, 3), dtype=torch.float32, device=self.device)
        self.grav[:, 2] = -1.0
        self.prev_lin_vel_b = torch.zeros((num_envs, 3), dtype=torch.float32, device=self.device)
        self.feedback_init = torch.zeros(num_envs, dtype=torch.bool, device=self.device)
        self.substep_in_tick = 0

    def reset(self, ids, q0: torch.Tensor) -> None:
        self.q_raw[ids] = q0
        self.q_filt[ids] = q0
        self.deriv[ids] = 0.0
        self.dq_filt[ids] = 0.0
        self.gyro[ids] = 0.0
        self.accel_g[ids] = 0.0
        self.accel_g[ids, 2] = 1.0
        self.grav[ids] = 0.0
        self.grav[ids, 2] = -1.0
        self.prev_lin_vel_b[ids] = 0.0
        self.feedback_init[ids] = True

    def update_50hz(
        self,
        q_true: torch.Tensor,
        gyro_b: torch.Tensor,
        lin_vel_b: torch.Tensor,
        grav_b: torch.Tensor,
        dt: float = 0.02,
    ) -> None:
        """Exact V2 One-Euro filter law (5 Hz deriv LPF + adaptive 1.5 + 1.43*|dq| Hz pos LPF)."""
        q_meas = torch.nan_to_num(q_true, nan=0.0, posinf=2.0, neginf=-2.0)
        if self.sensor_noise:
            # Matches DS3225 PRO / 12-bit ADC 4th-wire noise (~0.5 deg std)
            q_meas = q_meas + torch.randn_like(q_meas) * math.radians(0.45)

        alpha = 1.0 / (1.0 + 1.0 / (2.0 * math.pi * 5.0 * dt))
        deriv_new = self.deriv + alpha * ((q_meas - self.q_raw) / dt - self.deriv)
        # Equivalent to V2's cutoff = 1.5 + 0.002 * |deriv_raw| (1 raw tick ~= 0.08 deg = 0.0014 rad)
        cutoff = 1.5 + 1.43 * deriv_new.abs()
        gain = 1.0 / (1.0 + 1.0 / (2.0 * math.pi * cutoff * dt))
        q_filt_new = self.q_filt + gain * (q_meas - self.q_filt)
        dq_filt_new = self.dq_filt + alpha * ((q_filt_new - self.q_filt) / dt - self.dq_filt)

        init = self.feedback_init.unsqueeze(-1)
        self.q_filt = torch.where(init, q_filt_new, q_meas)
        self.deriv = torch.where(init, deriv_new, torch.zeros_like(deriv_new))
        self.dq_filt = torch.where(init, dq_filt_new, torch.zeros_like(dq_filt_new))
        self.q_raw = q_meas
        self.feedback_init.fill_(True)

        accel_b = (lin_vel_b - self.prev_lin_vel_b) / dt - 9.81 * grav_b
        self.prev_lin_vel_b.copy_(lin_vel_b)
        accel_g = torch.clamp(accel_b / 9.81, -4.0, 4.0)
        gyro = torch.nan_to_num(gyro_b, nan=0.0, posinf=20.0, neginf=-20.0)
        grav = torch.nan_to_num(grav_b, nan=0.0, posinf=1.0, neginf=-1.0)
        if self.sensor_noise:
            gyro = gyro + torch.randn_like(gyro) * 0.03
            accel_g = accel_g + torch.randn_like(accel_g) * 0.03
            grav = grav + torch.randn_like(grav) * 0.015
        self.gyro.copy_(gyro)
        self.accel_g.copy_(accel_g)
        self.grav.copy_(grav)

    def features(self, command: torch.Tensor, prev_action: torch.Tensor, phase_rad: torch.Tensor) -> torch.Tensor:
        """50-feature proprioceptive + gated 1.65 Hz CPG frame (exact match to v3_microduck.c)."""
        moving = (torch.norm(command[:, :2], dim=-1) + 0.18 * command[:, 2].abs()) > 0.02
        ph_sin = torch.where(moving, torch.sin(phase_rad), torch.zeros_like(phase_rad))
        ph_cos = torch.where(moving, torch.cos(phase_rad), torch.zeros_like(phase_rad))
        phase_feat = torch.stack((ph_sin, ph_cos), dim=-1)
        return torch.nan_to_num(
            torch.cat(
                (self.q_filt, self.dq_filt, self.gyro, self.accel_g, self.grav, command, prev_action, phase_feat),
                dim=-1,
            ),
            nan=0.0,
            posinf=10.0,
            neginf=-10.0,
        )


def v3_gait_mirror_tables() -> tuple[list[int], list[float], list[int], list[float], list[int], list[float]]:
    """Exact Left<->Right (Y -> -Y) reflection tables for V3 12-DOF Cartesian foot-offset gait.

    Leg order: RL(0), RR(1), FL(2), FR(3).
    - Joints [h, alpha, theta]: because RL/FL shoulder axes are -X and RR/FR are +X,
      +h pulls inward identically on both sides -> swap RL<->RR, FL<->FR with sign +1.
    - Actions [dx, dy, dz] per leg: swap RL<->RR, FL<->FR with signs [+1, -1, +1] (Y negates!).
    - Gated 1.65 Hz CPG phase [sin, cos]: mirroring shifts phase by pi -> negate [-1, -1].
    """
    j_perm = [3, 4, 5, 0, 1, 2, 9, 10, 11, 6, 7, 8]
    j_sign = [1.0] * 12
    act_perm = [3, 4, 5, 0, 1, 2, 9, 10, 11, 6, 7, 8]
    act_sign = [1.0, -1.0, 1.0] * 4

    # Single 50-feature frame: q(12), dq(12), gyro(3), accel_g(3), grav(3), cmd(3), prev_act(12), phase(2)
    f_perm: list[int] = []
    f_sign: list[float] = []
    f_perm.extend(j_perm)
    f_sign.extend(j_sign)
    f_perm.extend([12 + i for i in j_perm])
    f_sign.extend(j_sign)
    f_perm.extend([24, 25, 26])
    f_sign.extend([-1.0, 1.0, -1.0])   # gyro: (-wx, +wy, -wz)
    f_perm.extend([27, 28, 29])
    f_sign.extend([1.0, -1.0, 1.0])    # accel_g: (+ax, -ay, +az)
    f_perm.extend([30, 31, 32])
    f_sign.extend([1.0, -1.0, 1.0])    # grav: (+gx, -gy, +gz)
    f_perm.extend([33, 34, 35])
    f_sign.extend([1.0, -1.0, -1.0])   # cmd: (+vx, -vy, -wz)
    f_perm.extend([36 + i for i in act_perm])
    f_sign.extend(act_sign)
    # CPG phase [48, 49]: mirroring swaps Pair A(RR,FL) <-> Pair B(RL,FR) -> phase + pi -> negate [sin, cos]
    f_perm.extend([48, 49])
    f_sign.extend([-1.0, -1.0])
    assert len(f_perm) == V3_FEATURES and len(f_sign) == V3_FEATURES

    obs_perm: list[int] = []
    obs_sign: list[float] = []
    for k in range(V3_SAMPLES):
        off = k * V3_FEATURES
        obs_perm.extend([off + idx for idx in f_perm])
        obs_sign.extend(f_sign)

    # Critic privileged tail (8): lin_vel_b(3) [+vx, -vy, +vz], root_z(1) [+1], feet_contact(4) [RL<->RR, FL<->FR]
    crit_perm = list(obs_perm) + [
        V3_OBS_SIZE + 0,
        V3_OBS_SIZE + 1,
        V3_OBS_SIZE + 2,
        V3_OBS_SIZE + 3,
        V3_OBS_SIZE + 5,
        V3_OBS_SIZE + 4,
        V3_OBS_SIZE + 7,
        V3_OBS_SIZE + 6,
    ]
    crit_sign = list(obs_sign) + [1.0, -1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0]
    return obs_perm, obs_sign, crit_perm, crit_sign, act_perm, act_sign


_SYMM_CACHE: dict[torch.device, tuple[torch.Tensor, ...]] = {}


def _get_symm_tensors(device: torch.device) -> tuple[torch.Tensor, ...]:
    cached = _SYMM_CACHE.get(device)
    if cached is None:
        op, os_, cp, cs, ap, as_ = v3_gait_mirror_tables()
        cached = (
            torch.tensor(op, dtype=torch.long, device=device),
            torch.tensor(os_, dtype=torch.float32, device=device),
            torch.tensor(cp, dtype=torch.long, device=device),
            torch.tensor(cs, dtype=torch.float32, device=device),
            torch.tensor(ap, dtype=torch.long, device=device),
            torch.tensor(as_, dtype=torch.float32, device=device),
        )
        _SYMM_CACHE[device] = cached
    return cached


def v3_symmetry_augmentation(env, obs=None, actions=None):
    """Exact L<->R mirror augmentation for rsl_rl symmetry_cfg."""
    obs_aug = None
    if obs is not None:
        if hasattr(obs, "keys"):
            dev = obs["actor"].device
            op, os_, cp, cs, _, _ = _get_symm_tensors(dev)
            mirrored = obs.clone()
            mirrored["actor"] = obs["actor"][..., op] * os_
            if "critic" in obs.keys():
                mirrored["critic"] = obs["critic"][..., cp] * cs
            obs_aug = torch.cat([obs, mirrored], dim=0)
        else:
            dev = obs.device
            op, os_, cp, cs, _, _ = _get_symm_tensors(dev)
            if obs.shape[-1] == V3_OBS_SIZE:
                m = obs[..., op] * os_
            else:
                m = obs[..., cp] * cs
            obs_aug = torch.cat([obs, m], dim=0)

    act_aug = None
    if actions is not None:
        dev = actions.device
        _, _, _, _, ap, as_ = _get_symm_tensors(dev)
        act_m = actions[..., ap] * as_
        act_aug = torch.cat([actions, act_m], dim=0)

    return obs_aug, act_aug


@dataclass(kw_only=True)
class V3FootActionCfg(ActionTermCfg):
    foot_scale_mm: tuple[float, float, float] = V3_FOOT_ACTION_SCALE_MM
    sensor_noise: bool = True

    def build(self, env):
        return V3FootAction(self, env)


class V3FootAction(ActionTerm):
    """V2-aligned GPU Cartesian foot-offset IK decoder + 15-frame One-Euro proprioceptive history."""

    def __init__(self, cfg: V3FootActionCfg, env):
        super().__init__(cfg, env)
        self.cfg = cfg
        self.geo = load_v3_geometry()
        dev = env.device
        self.body = V3TensorBody(self.geo, device=dev, scale_mm=cfg.foot_scale_mm)
        self.sensors = V3TensorSensors(env.num_envs, dev, sensor_noise=cfg.sensor_noise)
        self.joint_ids, _ = self._entity.find_joints(V3_JOINTS, preserve_order=True)
        self.foot_site_ids, _ = self._entity.find_sites(
            tuple(f"{leg}_foot" for leg in V3_LEGS), preserve_order=True
        )
        self._raw = torch.zeros((env.num_envs, 12), dtype=torch.float32, device=dev)
        self.prev_action = torch.zeros((env.num_envs, 12), dtype=torch.float32, device=dev)
        self.prev2_action = torch.zeros((env.num_envs, 12), dtype=torch.float32, device=dev)
        self.targets_rad = torch.zeros((env.num_envs, 12), dtype=torch.float32, device=dev)
        self.prev_targets_rad = torch.zeros((env.num_envs, 12), dtype=torch.float32, device=dev)
        self.prev2_targets_rad = torch.zeros((env.num_envs, 12), dtype=torch.float32, device=dev)
        self.history = torch.zeros((env.num_envs, V3_SAMPLES, V3_FEATURES), dtype=torch.float32, device=dev)
        self.phase_rad = torch.zeros(env.num_envs, dtype=torch.float32, device=dev)
        # V2-identical rolling EMA state for alternating_stride
        self.mean_dq = torch.zeros((env.num_envs, 12), dtype=torch.float32, device=dev)
        self.foot_home_pos_m = self.body.foot_home_b_m
        self.cur_foot_pos_m = self.foot_home_pos_m.unsqueeze(0).expand(env.num_envs, -1, -1).clone()
        self.mean_foot_pos_m = self.foot_home_pos_m.unsqueeze(0).expand(env.num_envs, -1, -1).clone()
        self.prev_foot_pos_m = self.foot_home_pos_m.unsqueeze(0).expand(env.num_envs, -1, -1).clone()
        self.foot_vel_b_m = torch.zeros((env.num_envs, 4, 3), dtype=torch.float32, device=dev)
        self.mean_amp_q = torch.zeros((env.num_envs, 4), dtype=torch.float32, device=dev)
        self.mean_amp_x_m = torch.zeros((env.num_envs, 4), dtype=torch.float32, device=dev)
        self.mean_amp_z_m = torch.zeros((env.num_envs, 4), dtype=torch.float32, device=dev)
        self.last_sync_step = -1
        self.last_obs_step = -1
        self.decode_fn = self.body.decode
        self.fk_fn = self.body.forward_body_m
        if torch.device(dev).type == "cuda" and env.num_envs >= 64:
            self.decode_fn = torch.compile(self.body.decode, fullgraph=True, dynamic=False)
            self.fk_fn = torch.compile(self.body.forward_body_m, fullgraph=True, dynamic=False)
        self.reset(None)

    @property
    def action_dim(self) -> int:
        return 12

    @property
    def raw_action(self) -> torch.Tensor:
        return self._raw

    def reset(self, env_ids=None) -> None:
        ids = slice(None) if env_ids is None else env_ids
        if env_ids is not None and len(env_ids) == 0:
            return
        self._raw[ids] = 0.0
        self.prev_action[ids] = 0.0
        self.prev2_action[ids] = 0.0
        self.targets_rad[ids] = 0.0
        self.prev_targets_rad[ids] = 0.0
        self.prev2_targets_rad[ids] = 0.0
        self.history[ids] = 0.0
        n_rst = self._env.num_envs if env_ids is None else len(env_ids)
        self.phase_rad[ids] = torch.rand(n_rst, device=self._env.device) * (2.0 * math.pi)
        self.mean_dq[ids] = 0.0
        self.mean_foot_pos_m[ids] = self.foot_home_pos_m
        self.mean_amp_q[ids] = 0.0
        self.mean_amp_x_m[ids] = 0.0
        self.mean_amp_z_m[ids] = 0.0
        q_now = self._entity.data.joint_pos[:, self.joint_ids]
        self.sensors.reset(ids, q_now[ids])
        fk_now = self.body.forward_body_m(q_now[ids])
        self.cur_foot_pos_m[ids] = fk_now
        self.prev_foot_pos_m[ids] = fk_now
        self.foot_vel_b_m[ids] = 0.0
        self.last_sync_step = -1
        self.last_obs_step = -1

    def process_actions(self, actions: torch.Tensor) -> None:
        self.prev2_action.copy_(self.prev_action)
        self.prev_action.copy_(self._raw)
        self.prev2_targets_rad.copy_(self.prev_targets_rad)
        self.prev_targets_rad.copy_(self.targets_rad)
        clipped = torch.clamp(torch.nan_to_num(actions, nan=0.0), -1.0, 1.0)
        self._raw.copy_(clipped)
        self.targets_rad.copy_(self.decode_fn(clipped))
        cmd = self._env.command_manager.get_command("twist")[:, :3]
        moving = (torch.norm(cmd[:, :2], dim=-1) + 0.18 * cmd[:, 2].abs()) > 0.02
        dph = torch.where(moving, 2.0 * math.pi * v3_gait_hz_torch(cmd) * float(self._env.step_dt), torch.zeros_like(self.phase_rad))
        self.phase_rad.add_(dph).remainder_(2.0 * math.pi)

    def apply_actions(self) -> None:
        self._entity.set_joint_position_target(self.targets_rad, joint_ids=self.joint_ids)

    def sync_step(self) -> None:
        step = int(self._env.common_step_counter)
        if step == self.last_sync_step:
            return
        self.last_sync_step = step
        robot = self._entity.data
        dt = float(self._env.step_dt)
        self.sensors.update_50hz(
            robot.joint_pos[:, self.joint_ids],
            robot.root_link_ang_vel_b,
            robot.root_link_lin_vel_b,
            robot.projected_gravity_b,
            dt=dt,
        )
        cur_foot_m = self.fk_fn(self.sensors.q_filt)
        self.foot_vel_b_m.copy_((cur_foot_m - self.prev_foot_pos_m) / max(dt, 1e-4))
        self.prev_foot_pos_m.copy_(cur_foot_m)
        self.cur_foot_pos_m.copy_(cur_foot_m)

    def observation(self) -> torch.Tensor:
        step = int(self._env.common_step_counter)
        if step == self.last_obs_step:
            return self.history.reshape(self._env.num_envs, V3_OBS_SIZE)
        self.last_obs_step = step
        self.sync_step()
        cmd = self._env.command_manager.get_command("twist")[:, :3]
        row = self.sensors.features(cmd, self._raw, self.phase_rad)
        self.history[:, 1:].copy_(self.history[:, :-1].clone())
        self.history[:, 0].copy_(row)
        return self.history.reshape(self._env.num_envs, V3_OBS_SIZE)


def _v3_obs_policy(env) -> torch.Tensor:
    return env.action_manager.get_term("feet").observation()


def _v3_obs_critic(env) -> torch.Tensor:
    term = env.action_manager.get_term("feet")
    obs = term.observation()
    robot = env.scene["robot"].data
    feet_c = (env.scene["feet_ground_contact"].data.found > 0).float()
    return torch.cat([obs, robot.root_link_lin_vel_b, robot.root_link_pos_w[:, 2:3], feet_c], dim=-1)


# ==============================================================================
# V2-Aligned Objective, Curriculum & Domain Randomization (scaled for V3 181 mm)
# ==============================================================================


def _v3_state(env):
    return env.curriculum_manager.get_term_cfg("walking_difficulty").func


def _v3_scores(env):
    robot = env.scene["robot"].data
    cmd = env.command_manager.get_command("twist")[:, :3]
    actual = torch.cat((robot.root_link_lin_vel_b[:, :2], robot.root_link_ang_vel_b[:, 2:3]), -1)
    quality, baseline = v2_mdp.tracking_scores(actual, cmd, _v3_state(env).widths)
    moving = (torch.norm(cmd[:, :2], dim=-1) + 0.18 * cmd[:, 2].abs()) > 0.02
    return quality, baseline, moving


def _v3_torso_all_heights(env, target_z: float = 0.181):
    """V2's _torso_all_heights adapted to V3's 181 mm shoulder height and +-136 / +-95 mm footprint."""
    robot = env.scene["robot"].data
    up_b = (-robot.projected_gravity_b).clamp(-1.0, 1.0)
    rear_pitch_dz = -0.128 * up_b[:, 0]
    front_pitch_dz = 0.144 * up_b[:, 0]
    left_roll_dz = 0.095 * up_b[:, 1]
    right_roll_dz = -0.095 * up_b[:, 1]
    feet = env.action_manager.get_term("feet")
    feet.sync_step()
    foot_b_m = feet.cur_foot_pos_m
    foot_rel_m = foot_b_m - feet.foot_home_pos_m.unsqueeze(0)
    horiz_sq = foot_rel_m[..., :2].square().sum(-1)
    stride_arc_dz = 0.35 * (horiz_sq / target_z).clamp(0.0, 0.042)
    foot_vec = foot_rel_m.clone()
    foot_vec[..., 2] -= target_z
    leg_z = -(foot_vec * up_b.unsqueeze(1)).sum(-1) + stride_arc_dz
    rear_z = leg_z[:, :2].amax(-1) + 0.5 * rear_pitch_dz
    front_z = leg_z[:, 2:].amax(-1) + 0.5 * front_pitch_dz
    torso_z = 0.5 * (rear_z + front_z)
    left_z = torso_z + left_roll_dz
    right_z = torso_z + right_roll_dz
    return torso_z, rear_z, front_z, left_z, right_z


def _v3_body_collapsed(env, minimum_z: float = 0.115) -> torch.Tensor:
    torso_z, rear_z, front_z, left_z, right_z = _v3_torso_all_heights(env)
    side_min = minimum_z - 0.008
    grav = env.scene["robot"].data.projected_gravity_b
    flipped = grav[:, 2] > -0.35
    return flipped | (torso_z < minimum_z) | (rear_z < minimum_z) | (front_z < minimum_z) | (left_z < side_min) | (right_z < side_min)


def _v3_tracking_twist(env) -> torch.Tensor:
    """Exact V2 dense bounded tracking_twist with WalkingDifficulty accumulator."""
    robot = env.scene["robot"].data
    cmd = env.command_manager.get_command("twist")[:, :3]
    actual = torch.cat((robot.root_link_lin_vel_b[:, :2], robot.root_link_ang_vel_b[:, 2:3]), -1)
    quality, baseline, moving = _v3_scores(env)
    delta = quality - baseline
    headroom = (1.0 - baseline).clamp_min(1e-6)
    component_moving = baseline < 0.95
    negative = torch.where(component_moving, delta / (1.0 - baseline).clamp_min(0.5), 1.25 * delta)

    lin_cmd_sq = cmd[:, :2].square().sum(-1).clamp_min(1e-6)
    lin_dot = (actual[:, :2] * cmd[:, :2]).sum(-1)
    lin_ratio = lin_dot / lin_cmd_sq
    proj_vel = lin_ratio.unsqueeze(-1) * cmd[:, :2]
    orth_vel_sq = (actual[:, :2] - proj_vel).square().sum(-1)
    orth_gate = torch.exp(-orth_vel_sq / (0.055 ** 2))
    ang_ratio = (actual[:, 2] * cmd[:, 2]) / cmd[:, 2].square().clamp_min(1e-6)
    turn_xy_gate = torch.where(
        cmd[:, :2].square().sum(-1) < 4e-4,
        torch.exp(-actual[:, :2].square().sum(-1) / (0.07 ** 2)),
        torch.ones_like(ang_ratio),
    )
    lin_overspeed = torch.where(lin_ratio > 1.30, (lin_ratio - 1.30).clamp(0.0, 1.5), torch.zeros_like(lin_ratio))
    ang_overspeed = torch.where(ang_ratio > 1.35, (ang_ratio - 1.35).clamp(0.0, 1.5), torch.zeros_like(ang_ratio))
    lin_prog = (lin_ratio.clamp(0.0, 1.0) * orth_gate - 0.65 * lin_overspeed)
    ang_prog = (ang_ratio.clamp(0.0, 1.0) * turn_xy_gate - 0.50 * ang_overspeed)
    directed = torch.stack((lin_prog.clamp_min(0.0), ang_prog.clamp_min(0.0)), -1)
    positive = 0.60 * (delta / headroom).clamp_min(0.0) + 0.40 * directed - torch.stack((0.45 * lin_overspeed, 0.35 * ang_overspeed), -1)
    wrong_way = torch.stack(((lin_ratio < 0.0) | (lin_ratio > 1.40), (ang_ratio < 0.0) | (ang_ratio > 1.45)), -1)
    comp = torch.where(wrong_way & (delta < 0.0), negative, positive)

    rev_turn_bonus = (
        0.65 * torch.where(wrong_way[:, 0], 0.0, lin_prog) * (cmd[:, 0] < -0.02).to(lin_prog.dtype)
        + 0.65 * torch.where(wrong_way[:, 0], 0.0, lin_prog) * (cmd[:, 1].abs() > 0.03).to(lin_prog.dtype)
        + 0.40 * torch.where(wrong_way[:, 0], 0.0, lin_prog) * (cmd[:, 0] > 0.20).to(lin_prog.dtype)
        + 0.45 * torch.where(wrong_way[:, 1], 0.0, ang_prog) * (cmd[:, 2].abs() > 0.15).to(ang_prog.dtype)
    )
    lin_shortfall = 0.22 * (1.0 - lin_ratio.clamp(0.0, 1.0)).square() * (cmd[:, :2].square().sum(-1) > 4e-4).to(lin_prog.dtype)
    ang_gate = 0.35 + 0.65 * quality[:, 1].clamp(0.0, 1.0)
    lin_coupled = torch.where(comp[:, 0] > 0.0, comp[:, 0] * ang_gate, comp[:, 0])
    ang_authority = torch.where((cmd[:, 2].abs() > 0.15) & (comp[:, 1] > 0.0), 1.25, 1.0)
    improvement = lin_coupled + ang_authority * comp[:, 1] + rev_turn_bonus - lin_shortfall

    grav = robot.projected_gravity_b
    pitch_roll_gate = torch.exp(-8.0 * grav[:, 0].square() - 6.0 * grav[:, 1].square())
    upright = (-grav[:, 2]).clamp(0.0, 1.0) * pitch_roll_gate
    _, rear_z, front_z, left_z, right_z = _v3_torso_all_heights(env)
    support_z = torch.minimum(torch.minimum(rear_z, front_z), torch.minimum(left_z, right_z))
    foot_h = torch.nan_to_num(env.scene["foot_height_scan"].data.heights, nan=0.0, posinf=0.10, neginf=0.0).clamp(0.0, 0.10)
    rear_float = (torch.minimum(foot_h[:, 0], foot_h[:, 1]) - 0.006).clamp_min(0.0) / 0.012
    front_float = (torch.minimum(foot_h[:, 2], foot_h[:, 3]) - 0.006).clamp_min(0.0) / 0.012
    girdle_gate = torch.exp(-0.65 * (rear_float.square() + front_float.square()).clamp(0.0, 4.0))
    upright = upright * ((support_z - 0.138) / 0.032).clamp(0.20, 1.0) * girdle_gate

    result = torch.where(improvement > 0.0, improvement * upright, improvement)
    curriculum = _v3_state(env)
    active = baseline < 1.0
    progress = torch.maximum((delta / headroom).clamp(0.0, 1.0), (1.35 * torch.where(wrong_way, 0.0, directed)).clamp(0.0, 1.0))
    progress = torch.nan_to_num(progress, nan=0.0, posinf=0.0, neginf=0.0)
    curriculum.score_sum += (progress * active).sum(-1) / active.sum(-1).clamp_min(1.0)
    curriculum.elapsed += 1.0
    curriculum.score_count += moving.to(curriculum.score_count.dtype)
    env.extras["log"]["Tracking/linear_error_m_s"] = torch.norm(actual[:, :2] - cmd[:, :2], dim=-1).mean()
    env.extras["log"]["Tracking/yaw_error_rad_s"] = (actual[:, 2] - cmd[:, 2]).abs().mean()
    return torch.nan_to_num(result, nan=0.0, posinf=3.0, neginf=-3.0)


def _v3_upright_cost(env) -> torch.Tensor:
    """V2's upright_cost scaled to V3 181 mm height + straight-walk leg verticality."""
    _, _, moving = _v3_scores(env)
    robot = env.scene["robot"].data
    cmd = env.command_manager.get_command("twist")[:, :3]
    feet = env.action_manager.get_term("feet")
    grav = robot.projected_gravity_b
    tilt_cost = (1.0 - (-grav[:, 2]).clamp(-1.0, 1.0)) + 12.0 * grav[:, 0].square() + 7.5 * grav[:, 1].square()

    torso_z, rear_z, front_z, left_z, right_z = _v3_torso_all_heights(env)
    target_z = torch.where(moving, 0.179, 0.181)
    rear_sag = ((target_z - rear_z).clamp_min(0.0) / 0.022).square()
    side_z = torch.minimum(left_z, right_z)
    side_sag = ((target_z - side_z).clamp_min(0.0) / 0.022).square()
    height_err = (
        ((torso_z - target_z) / 0.028).square()
        + 0.85 * ((rear_z - target_z) / 0.028).square()
        + 0.85 * ((front_z - target_z) / 0.028).square()
        + 0.80 * rear_sag
        + 0.90 * side_sag
    ).clamp(0.0, 4.5)

    foot_h = torch.nan_to_num(env.scene["foot_height_scan"].data.heights, nan=0.0, posinf=0.10, neginf=0.0).clamp(0.0, 0.10)
    rear_float = (torch.minimum(foot_h[:, 0], foot_h[:, 1]) - 0.005).clamp_min(0.0) / 0.012
    front_float = (torch.minimum(foot_h[:, 2], foot_h[:, 3]) - 0.005).clamp_min(0.0) / 0.012
    girdle_float_cost = (rear_float.square() + front_float.square()).clamp(0.0, 4.0)

    # Keep shoulders vertical during straight walking & standing; free during crabbing/turning
    q_true = robot.joint_pos[:, feet.joint_ids]
    h_deg = torch.rad2deg(q_true[:, 0::3].abs())
    straight_w = 1.0 - (cmd[:, 1].abs() / 0.14 + 0.35 * cmd[:, 2].abs() / 1.20).clamp(0.0, 0.90)
    splay_cost = straight_w * ((h_deg / 6.0).square().mean(-1)).clamp(0.0, 3.0)

    env.extras["log"]["Posture/mean_height_mm"] = robot.root_link_pos_w[:, 2].mean() * 1000.0
    env.extras["log"]["Posture/mean_shoulder_splay_deg"] = h_deg.mean()
    return (tilt_cost + 0.45 * height_err + 0.40 * splay_cost + 0.55 * girdle_float_cost).clamp(0.0, 6.0)


def _v3_alternating_stride(env) -> torch.Tensor:
    """Exact V2 alternating_stride with crab/turn-gated lateral s_y (no straight-walk splay bribe!)."""
    quality, _, moving = _v3_scores(env)
    robot = env.scene["robot"].data
    cmd = env.command_manager.get_command("twist")[:, :3]
    feet = env.action_manager.get_term("feet")

    lin_cmd_sq = cmd[:, :2].square().sum(-1)
    lin_dot = (robot.root_link_lin_vel_b[:, :2] * cmd[:, :2]).sum(-1)
    ang_gate = 0.35 + 0.65 * quality[:, 1].clamp(0.0, 1.0)
    dir_gate = torch.where((lin_cmd_sq > 1e-4) & (lin_dot < -0.015), 0.2, 1.0) * ang_gate
    grav = robot.projected_gravity_b
    upright = (-grav[:, 2]).clamp(0.0, 1.0) * torch.exp(-3.0 * grav[:, :2].square().sum(-1))

    c = (env.scene["feet_ground_contact"].data.found > 0).to(upright.dtype)
    diag_a = c[:, 0] * c[:, 3] * (1.0 - c[:, 1]) * (1.0 - c[:, 2])  # Pair B (RL+FR) stance, Pair A (RR+FL) swing
    diag_b = c[:, 1] * c[:, 2] * (1.0 - c[:, 0]) * (1.0 - c[:, 3])  # Pair A (RR+FL) stance, Pair B (RL+FR) swing
    same_girdle_hop = (1.0 - c[:, 0]) * (1.0 - c[:, 1]) + (1.0 - c[:, 2]) * (1.0 - c[:, 3])
    all_air = (c.sum(-1) < 0.5).to(upright.dtype)

    # Smooth sinusoidal CPG swing arc + Newtonian horizontal foot-velocity alignment
    feet.sync_step()
    s = torch.sin(feet.phase_rad)
    leg_phase = torch.stack((-s, s, s, -s), dim=-1)  # >0 = swing bell, <0 = stance
    swing_arc = leg_phase.clamp(0.0, 1.0)
    stance_arc = (-leg_phase).clamp(0.0, 1.0)
    foot_h = torch.nan_to_num(env.scene["foot_height_scan"].data.heights, nan=0.0, posinf=0.10, neginf=0.0).clamp(0.0, 0.10)
    firm_stance = c * ((0.006 - foot_h) / 0.006).clamp(0.0, 1.0)
    stance_ok = (stance_arc * (0.65 * c + 0.35 * firm_stance)).sum(-1) / 1.27
    swing_ok = (swing_arc * (1.0 - c)).sum(-1) / 1.27
    # Require actual swing liftoff so frozen 4-foot standing at cmd != 0 earns zero gait reward
    phase_contact = stance_ok.clamp(0.0, 1.1) * (0.12 + 0.88 * swing_ok.clamp(0.0, 1.1))
    # Smooth sinusoidal target swing trajectory peaking at 18 mm (stays inside the 141 mm 4-bar sweet spot!)
    target_swing_h = 0.018 * swing_arc
    arc_match = (1.0 - ((foot_h - target_swing_h).abs() / 0.015).clamp(0.0, 1.0)) * (foot_h > 0.004).to(upright.dtype)
    phase_lift = (swing_arc * arc_match).sum(-1) / 1.15
    cpg_diag = torch.where(s > 0.12, diag_a, torch.where(s < -0.12, diag_b, 0.5 * (diag_a + diag_b)))

    # Exact rigid-body swing/stance horizontal velocity direction per foot for any (vx, vy, wz)
    home_xy = feet.foot_home_pos_m[:, :2].unsqueeze(0)  # (1, 4, 2)
    v_des_x = cmd[:, 0:1] - cmd[:, 2:3] * home_xy[..., 1]
    v_des_y = cmd[:, 1:2] + cmd[:, 2:3] * home_xy[..., 0]
    v_des = torch.stack((v_des_x, v_des_y), dim=-1)  # (N, 4, 2)
    v_norm = torch.norm(v_des, dim=-1)
    u_des = v_des / v_norm.unsqueeze(-1).clamp_min(1e-4)
    v_par = ((feet.foot_vel_b_m[..., :2] * u_des).sum(-1) / v_norm.clamp(0.06, 0.48)).clamp(-1.6, 1.6)
    phase_vel = (leg_phase * v_par).clamp(-0.65, 1.25).mean(-1)

    rew = (
        (0.85 * cpg_diag + 0.95 * phase_contact + 0.65 * phase_lift + 1.35 * phase_vel) * dir_gate
        - 0.60 * same_girdle_hop
        - 1.00 * all_air
    )

    q = feet.sensors.q_filt
    vq = feet.sensors.dq_filt / 10.0
    feet.mean_dq.lerp_(q, 0.05)
    ac_dq = q - feet.mean_dq
    leg_q = 0.5 * (ac_dq[:, 1::3] / 0.35 + ac_dq[:, 2::3] / 0.45)
    leg_vq = 0.5 * (vq[:, 1::3] + vq[:, 2::3])

    lin_mag = (lin_cmd_sq.sqrt() / 0.18).clamp_min(0.0)
    ang_mag = (cmd[:, 2].abs() / 0.60).clamp_min(0.0)
    turn_frac = (ang_mag / (lin_mag + ang_mag + 1e-5)).clamp(0.0, 1.0)
    lin_frac = 1.0 - turn_frac
    crab_frac = (cmd[:, 1].abs() / (cmd[:, 0].abs() + cmd[:, 1].abs() + 0.05)).clamp(0.0, 1.0)

    side_sign = leg_q.new_tensor([1.0, -1.0, 1.0, -1.0])
    rot_q = leg_q * side_sign
    rot_vq = leg_vq * side_sign

    rear_anti_lin = (-(leg_q[:, 0] * leg_q[:, 1] + 0.35 * leg_vq[:, 0] * leg_vq[:, 1])).clamp(-0.2, 1.5)
    front_anti_lin = (-(leg_q[:, 2] * leg_q[:, 3] + 0.35 * leg_vq[:, 2] * leg_vq[:, 3])).clamp(-0.2, 1.5)
    diag_sync_lin = 0.5 * (
        (leg_q[:, 0] * leg_q[:, 3] + 0.35 * leg_vq[:, 0] * leg_vq[:, 3])
        + (leg_q[:, 1] * leg_q[:, 2] + 0.35 * leg_vq[:, 1] * leg_vq[:, 2])
    ).clamp(-0.2, 1.6)
    rear_anti_rot = (-(rot_q[:, 0] * rot_q[:, 1] + 0.35 * rot_vq[:, 0] * rot_vq[:, 1])).clamp(-0.2, 1.5)
    front_anti_rot = (-(rot_q[:, 2] * rot_q[:, 3] + 0.35 * rot_vq[:, 2] * rot_vq[:, 3])).clamp(-0.2, 1.5)
    diag_sync_rot = 0.5 * (
        (rot_q[:, 0] * rot_q[:, 3] + 0.35 * rot_vq[:, 0] * rot_vq[:, 3])
        + (rot_q[:, 1] * rot_q[:, 2] + 0.35 * rot_vq[:, 1] * rot_vq[:, 2])
    ).clamp(-0.2, 1.6)
    stride_q = lin_frac * (rear_anti_lin + front_anti_lin + diag_sync_lin) + turn_frac * (
        rear_anti_rot + front_anti_rot + diag_sync_rot
    )
    anchor_xy_gate = torch.where((cmd[:, 0] < -0.02) | (cmd[:, 2].abs() > 0.15), 0.25, 1.0)
    rew = rew + 0.42 * stride_q * dir_gate - 0.14 * anchor_xy_gate * feet.mean_dq.square().sum(-1)

    # Zero-mean AC foot-XY stride excursion in body frame (Option A-1 full reach: ~64mm half-amplitude = 128mm span!)
    # Lateral s_y gated strictly by crab_frac / turn_frac so straight walking NEVER bribes hip splay!
    foot_pos_m = feet.cur_foot_pos_m
    feet.mean_foot_pos_m.lerp_(foot_pos_m, 0.05)
    ac_pos_m = foot_pos_m - feet.mean_foot_pos_m
    s_xy = torch.stack((ac_pos_m[..., 0] / 0.064, (ac_pos_m[..., 1] / 0.028) * crab_frac.unsqueeze(-1)), dim=-1)
    s_xy_rot = torch.stack((ac_pos_m[..., 0] / 0.064, (ac_pos_m[..., 1] / 0.028) * turn_frac.unsqueeze(-1)), dim=-1)
    rot_xy_sign = s_xy.new_tensor([[1.0, -1.0], [-1.0, -1.0], [1.0, 1.0], [-1.0, 1.0]])
    r_xy = s_xy_rot * rot_xy_sign

    rear_f_lin = (-(s_xy[:, 0] * s_xy[:, 1]).sum(-1)).clamp(-0.2, 1.6)
    front_f_lin = (-(s_xy[:, 2] * s_xy[:, 3]).sum(-1)).clamp(-0.2, 1.6)
    diag_f_lin = 0.5 * ((s_xy[:, 0] * s_xy[:, 3]).sum(-1) + (s_xy[:, 1] * s_xy[:, 2]).sum(-1)).clamp(-0.2, 1.7)
    rear_f_rot = (-(r_xy[:, 0] * r_xy[:, 1]).sum(-1)).clamp(-0.2, 1.6)
    front_f_rot = (-(r_xy[:, 2] * r_xy[:, 3]).sum(-1)).clamp(-0.2, 1.6)
    diag_f_rot = 0.5 * ((r_xy[:, 0] * r_xy[:, 3]).sum(-1) + (r_xy[:, 1] * r_xy[:, 2]).sum(-1)).clamp(-0.2, 1.7)
    stride_xy = lin_frac * (rear_f_lin + front_f_lin + diag_f_lin) + turn_frac * (
        rear_f_rot + front_f_rot + diag_f_rot
    )
    rew = rew + 0.50 * stride_xy * dir_gate

    # Center mean foot stance around home +-95.4mm & enforce even 4-leg stride + lift symmetry
    mean_offset_m = feet.mean_foot_pos_m - feet.foot_home_pos_m.unsqueeze(0)
    feet.mean_amp_q.lerp_(leg_q.abs(), 0.05)
    feet.mean_amp_x_m.lerp_(ac_pos_m[..., 0].abs(), 0.05)
    feet.mean_amp_z_m.lerp_(ac_pos_m[..., 2].abs(), 0.05)

    xy_offset_cost = (mean_offset_m[..., :2] / 0.045).square().sum((-1, -2))
    z_offset_cost = (mean_offset_m[..., 2] / 0.026).square().sum(-1)
    rew = rew - 0.11 * (anchor_xy_gate * xy_offset_cost + z_offset_cost)

    straight_cmd = ((cmd[:, 2].abs() < 0.15) & (cmd[:, 1].abs() < 0.03)).to(rew.dtype)
    q_sym_err = (feet.mean_amp_q[:, 0] - feet.mean_amp_q[:, 1]).square() + (feet.mean_amp_q[:, 2] - feet.mean_amp_q[:, 3]).square()
    z_sym_err = ((feet.mean_amp_z_m[:, 0] - feet.mean_amp_z_m[:, 1]) / 0.010).square() + (
        (feet.mean_amp_z_m[:, 2] - feet.mean_amp_z_m[:, 3]) / 0.010
    ).square()
    rear_sym_lift = (torch.minimum(feet.mean_amp_z_m[:, 0], feet.mean_amp_z_m[:, 1]) / 0.0065).clamp(0.0, 1.0)
    front_sym_lift = (torch.minimum(feet.mean_amp_z_m[:, 2], feet.mean_amp_z_m[:, 3]) / 0.0065).clamp(0.0, 1.0)
    fwd_gate = (cmd[:, 0].abs() > 0.06).to(rew.dtype) * dir_gate
    rear_sym_stride = (torch.minimum(feet.mean_amp_x_m[:, 0], feet.mean_amp_x_m[:, 1]) / 0.048).clamp(0.0, 1.0)
    front_sym_stride = (torch.minimum(feet.mean_amp_x_m[:, 2], feet.mean_amp_x_m[:, 3]) / 0.048).clamp(0.0, 1.0)
    roll_lean = (robot.projected_gravity_b[:, 1] / 0.08).square().clamp(0.0, 2.0)

    rew = (
        rew
        + dir_gate * (0.28 * rear_sym_lift + 0.24 * front_sym_lift)
        + fwd_gate * (0.25 * rear_sym_stride + 0.25 * front_sym_stride)
        - 0.20 * straight_cmd * dir_gate * roll_lean
        - 0.25 * straight_cmd * (q_sym_err.clamp(0.0, 2.5) + z_sym_err.clamp(0.0, 2.5))
    )

    env.extras["log"]["Gait/diag_trot_frac"] = (diag_a + diag_b).mean()
    env.extras["log"]["Gait/same_girdle_hop_frac"] = (same_girdle_hop > 0.5).float().mean()
    env.extras["log"]["Gait/min_leg_amp_x_mm"] = feet.mean_amp_x_m.amin(-1).mean() * 1000.0
    return torch.nan_to_num(rew * moving.to(rew.dtype) * upright, nan=0.0, posinf=5.0, neginf=-5.0)


def _v3_tracked_air_time(env) -> torch.Tensor:
    """Exact V2 tracked_air_time (0.10..0.38s band) gated against same-girdle bunny-hops."""
    quality, baseline, moving = _v3_scores(env)
    progress = ((quality - baseline) / (1.0 - baseline).clamp_min(1e-6)).clamp(0.0, 1.0)
    progress = torch.nan_to_num(progress, nan=0.0, posinf=0.0, neginf=0.0)
    airtime = vel_mdp.feet_air_time(
        env,
        sensor_name="feet_ground_contact",
        threshold_min=0.10,
        threshold_max=0.38,
        command_name="twist",
        command_threshold=0.0,
    )
    c = (env.scene["feet_ground_contact"].data.found > 0).float()
    no_girdle_hop = (((c[:, 0] + c[:, 1]) > 0.5) & ((c[:, 2] + c[:, 3]) > 0.5)).to(airtime.dtype)
    hop_gate = 0.25 + 0.75 * no_girdle_hop
    grav = env.scene["robot"].data.projected_gravity_b
    upright = (-grav[:, 2]).clamp(0.0, 1.0) * torch.exp(-3.0 * grav[:, :2].square().sum(-1))
    return airtime / 4.0 * (0.3 + 0.7 * progress.mean(-1)) * moving.to(upright.dtype) * hop_gate * upright


def _v3_standing_pose(env) -> torch.Tensor:
    """Exact V2 standing_pose: calm zero-velocity neutral stand + moving stance-stall/air-hang cost."""
    _, _, moving = _v3_scores(env)
    feet = env.action_manager.get_term("feet")
    data = feet._entity.data
    q_true = data.joint_pos[:, feet.joint_ids]
    dq_true = data.joint_vel[:, feet.joint_ids]
    pose_err = q_true.square().mean(-1) + 0.08 * dq_true.square().mean(-1)
    c = (env.scene["feet_ground_contact"].data.found > 0).float()
    unplanted = (4.0 - c.sum(-1)).clamp_min(0.0) * 0.35
    contact = env.scene["feet_ground_contact"].data
    air_hang = (contact.current_air_time - 0.44).clamp(0.0, 1.0).mean(-1)
    drag_over = (contact.current_contact_time - 0.72).clamp(0.0, 1.6)
    peer_stepping = (contact.current_contact_time.amin(-1) < 0.42).to(drag_over.dtype)
    stance_stall = 0.5 * (contact.current_contact_time - 0.62).clamp(0.0, 1.0).mean(-1) + 1.15 * drag_over.amax(-1) * peer_stepping
    still = (~moving).to(pose_err.dtype)
    mov = moving.to(pose_err.dtype)
    return (pose_err + unplanted) * still + (air_hang + stance_stall) * mov


def _v3_action_change(env) -> torch.Tensor:
    """2nd-order action + decoded-joint jerk smoothness (crushes 25 Hz turn/reverse chatter without damping wide strides)."""
    feet = env.action_manager.get_term("feet")
    d1 = (feet._raw - feet.prev_action).square().mean(-1)
    d2 = (feet._raw - 2.0 * feet.prev_action + feet.prev2_action).square().mean(-1)
    qd2 = ((feet.targets_rad - 2.0 * feet.prev_targets_rad + feet.prev2_targets_rad) / 0.25).square().mean(-1)
    return 0.04 * d1 + 0.70 * d2 + 0.26 * qd2


def _v3_action_size(env) -> torch.Tensor:
    """V2 action_size at stand (drives Cartesian foot offsets cleanly to 0,0,0 when command is zero)."""
    _, _, moving = _v3_scores(env)
    feet = env.action_manager.get_term("feet")
    return feet._raw.square().mean(-1) * (~moving).to(feet._raw.dtype)


def _v3_stand_still(env) -> torch.Tensor:
    """Positive additive stand funnel so dead-calm 4-foot neutral stand matches walking's reward scale."""
    _, _, moving = _v3_scores(env)
    still = (~moving).to(torch.float32)
    robot = env.scene["robot"].data
    feet = env.action_manager.get_term("feet")
    q = robot.joint_pos[:, feet.joint_ids]
    dq = robot.joint_vel[:, feet.joint_ids]
    z = robot.root_link_pos_w[:, 2]
    c = (env.scene["feet_ground_contact"].data.found > 0).float()
    grav = robot.projected_gravity_b
    upright = (-grav[:, 2]).clamp(0.0, 1.0) * torch.exp(-3.5 * grav[:, :2].square().sum(-1))

    r_plant = 0.35 * (c.sum(-1) / 4.0) + 0.65 * (c.sum(-1) >= 3.5).float()
    dq_rms = torch.sqrt(dq.square().mean(-1) + 1e-6)
    act_rms = torch.sqrt(feet._raw.square().mean(-1) + 1e-6)
    dact_rms = torch.sqrt((feet._raw - feet.prev_action).square().mean(-1) + 1e-6)
    vel_sq = robot.root_link_lin_vel_b[:, :2].square().sum(-1) + 0.25 * robot.root_link_ang_vel_b[:, 2].square()

    r_dq = 0.45 * (1.0 - dq_rms / 8.0).clamp(0.0, 1.0) + 0.55 * torch.exp(-(dq_rms / 0.35).square())
    r_act = 0.45 * (1.0 - act_rms / 0.6).clamp(0.0, 1.0) + 0.55 * torch.exp(-(act_rms / 0.10).square())
    r_dact = 0.40 * (1.0 - dact_rms / 0.4).clamp(0.0, 1.0) + 0.60 * torch.exp(-(dact_rms / 0.015).square())
    r_vel = torch.exp(-vel_sq / 0.015)
    r_z = torch.exp(-((z - 0.181) / 0.018).square())
    r_q = torch.exp(-(q.square().mean(-1) / 0.04))
    return (0.20 * r_plant + 0.22 * r_dq + 0.20 * r_act + 0.20 * r_dact + 0.08 * r_vel + 0.05 * r_z + 0.05 * r_q) * upright * still


@requires_model_fields("actuator_forcerange", "actuator_gainprm", "actuator_biasprm")
def _v3_randomize_actuators(env, env_ids=None, kp_range=(0.78, 1.15), kd_range=(0.80, 1.40), effort_range=(0.85, 1.08)):
    """V2-style per-joint DS3225 PRO kp/kd/effort randomization."""
    ids = torch.arange(env.num_envs, device=env.device) if env_ids is None else env_ids
    n = len(ids)
    if n == 0:
        return
    mj_m = env.sim.mj_model
    base_kp = torch.as_tensor(mj_m.actuator_gainprm[:12, 0], dtype=torch.float32, device=env.device).unsqueeze(0)
    base_kd = torch.as_tensor(-mj_m.actuator_biasprm[:12, 2], dtype=torch.float32, device=env.device).unsqueeze(0)
    kp_mult = kp_range[0] + (kp_range[1] - kp_range[0]) * torch.rand((n, 12), device=env.device)
    kd_mult = kd_range[0] + (kd_range[1] - kd_range[0]) * torch.rand((n, 12), device=env.device)
    eff_mult = effort_range[0] + (effort_range[1] - effort_range[0]) * torch.rand((n, 12), device=env.device)
    ctrl_ids = torch.arange(12, dtype=torch.long, device=env.device)
    kp = base_kp * kp_mult
    kd = base_kd * kd_mult
    env.sim.model.actuator_gainprm[ids.unsqueeze(1), ctrl_ids.unsqueeze(0), 0] = kp
    env.sim.model.actuator_biasprm[ids.unsqueeze(1), ctrl_ids.unsqueeze(0), 1] = -kp
    env.sim.model.actuator_biasprm[ids.unsqueeze(1), ctrl_ids.unsqueeze(0), 2] = -kd
    robot_entity = env.scene["robot"]
    for act in getattr(robot_entity, "actuators", ()):
        scale = getattr(act, "effort_scale", None)
        if scale is None or scale.shape != (env.num_envs, 12) or scale.device != eff_mult.device:
            scale = torch.ones((env.num_envs, 12), dtype=torch.float32, device=eff_mult.device)
            act.effort_scale = scale
        scale[ids] = eff_mult


def _v3_robot_spec_fn(geo: dict):
    """Strip standalone floor/actuators/option and apply V2 geom groups (group=1) & foot priority=1."""
    raw_xml = build_v3_xml(geo, floor=False)
    root = ET.fromstring(raw_xml)
    for tag in ("actuator", "option"):
        el = root.find(tag)
        if el is not None:
            root.remove(el)
    wb = root.find("worldbody")
    if wb is not None:
        for child in list(wb):
            if child.tag != "body":
                wb.remove(child)
    # Match V2 (microduck.py L345-351): all robot geoms in group 1 so foot_height_scan only hits terrain group 0
    for geom in root.iter("geom"):
        geom.set("group", "1")
        if geom.get("name", "").endswith("_foot"):
            geom.set("priority", "1")
    spec_xml = ET.tostring(root, encoding="unicode")
    return lambda: mujoco.MjSpec.from_string(spec_xml)


def make_v3_env_cfg(num_envs: int = 2048, *, play: bool = False, rough: bool = True, polish: bool = False):
    """Build V2-aligned mjlab environment config for V3 Option A-1 12-servo quadruped."""
    geo = load_v3_geometry()
    z_stand = float(geo["standing_shoulder_height_mm"]) / 1000.0  # 0.1809 m

    cfg = make_microduck_velocity_env_cfg(play=play, rough=False)
    cfg.scene.num_envs = int(num_envs)
    if rough and not play:
        cfg.scene.terrain.terrain_type = "generator"
        cfg.scene.terrain.max_init_terrain_level = 0
        cfg.scene.terrain.terrain_generator = TerrainGeneratorCfg(
            size=(8.0, 8.0),
            border_width=20.0,
            num_rows=5,
            num_cols=5,
            add_lights=False,
            curriculum=True,
            sub_terrains={
                "flat": terrain_gen.BoxFlatTerrainCfg(proportion=0.25),
                "slope_up": LearningSlopeCfg(
                    proportion=0.20,
                    slope_range=(0.0, math.tan(math.radians(8.0))),
                    platform_width=0.6,
                    vertical_scale=0.001,
                ),
                "cable_ledges": LearningStairsCfg(
                    proportion=0.20,
                    step_height_range=(0.006, 0.022),
                    step_width=0.22,
                    platform_width=1.2,
                    border_width=0.5,
                ),
                "obstacles": LearningObstaclesCfg(
                    proportion=0.20,
                    obstacle_width_range=(0.12, 0.30),
                    obstacle_height_range=(0.006, 0.022),
                    num_obstacles=10,
                    platform_width=0.55,
                    horizontal_scale=0.10,
                    vertical_scale=0.001,
                ),
                "waves": LearningWaveCfg(
                    proportion=0.15,
                    amplitude_range=(0.006, 0.018),
                    num_waves=3,
                    horizontal_scale=0.12,
                    vertical_scale=0.001,
                ),
            },
        )
    else:
        cfg.scene.terrain.terrain_type = "plane"
        cfg.scene.terrain.terrain_generator = None

    cfg.viewer.body_name = "torso"
    init_state = EntityCfg.InitialStateCfg(
        pos=(0.0, 0.0, z_stand + 0.002),
        joint_pos={".*": 0.0},
        joint_vel={".*": 0.0},
    )
    actuators = (
        MG90SActuatorCfg(
            target_names_expr=tuple(V3_JOINTS),
            stiffness=V3_SERVO_KP,
            damping=V3_SERVO_KV,
            effort_limit=V3_SERVO_EFFORT_NM,
            speed_rad_s=V3_SERVO_NO_LOAD_RAD_S,
            delay_min_lag=V3_ACTUATOR_DELAY_SUBSTEPS,
            delay_max_lag=V3_ACTUATOR_DELAY_SUBSTEPS,
        ),
    )
    cfg.scene.entities = {
        "robot": EntityCfg(
            spec_fn=_v3_robot_spec_fn(geo),
            init_state=init_state,
            articulation=EntityArticulationInfoCfg(actuators=actuators),
        )
    }

    foot_geoms = tuple(f"{leg}_foot" for leg in V3_LEGS)
    foot_sites = tuple(f"{leg}_foot" for leg in V3_LEGS)
    cfg.scene.sensors = (
        ContactSensorCfg(
            name="feet_ground_contact",
            primary=ContactMatch(mode="geom", pattern=foot_geoms, entity="robot"),
            secondary=ContactMatch(mode="body", pattern="terrain"),
            fields=("found", "force"),
            reduce="netforce",
            num_slots=1,
            track_air_time=True,
        ),
        TerrainHeightSensorCfg(
            name="foot_height_scan",
            frame=tuple(ObjRef(type="site", name=n, entity="robot") for n in foot_sites),
            pattern=ElevatedRingPatternCfg(rings=(RingPatternCfg.Ring(0.022, 2),), include_center=True, z_offset=0.12),
            ray_alignment="yaw",
            max_distance=1.0,
            exclude_parent_body=True,
            include_geom_groups=(0,),
        ),
    )

    cfg.actions = {"feet": V3FootActionCfg(entity_name="robot", sensor_noise=not play)}

    twist = cfg.commands["twist"]
    cfg.commands = {"twist": twist}
    twist.heading_command = False
    twist.ranges.heading = None
    twist.rel_heading_envs = 0.0
    twist.rel_standing_envs = 0.20
    twist.ranges.lin_vel_x = (-0.35, 0.45)
    twist.ranges.lin_vel_y = (-0.22, 0.22)
    twist.ranges.ang_vel_z = (-1.50, 1.50)
    twist.resampling_time_range = (4.0, 7.0)

    cfg.observations = {
        "actor": ObservationGroupCfg(
            terms={"proprio": ObservationTermCfg(func=_v3_obs_policy)},
            enable_corruption=False,
        ),
        "critic": ObservationGroupCfg(
            terms={"privileged": ObservationTermCfg(func=_v3_obs_critic)},
            enable_corruption=False,
        ),
    }

    # Exact V2 event & DR suite
    mass_rand = deepcopy(cfg.events["randomize_mass_inertia"])
    com_rand = deepcopy(cfg.events["randomize_com"])
    cfg.events = {
        "mg90s_force_fields": EventTermCfg(func=mg90s_force_fields, mode="startup"),
        "reset_base": EventTermCfg(func=v2_mdp.reset_base, mode="reset"),
        "reset_joints": EventTermCfg(
            func=env_mdp.reset_joints_by_offset,
            mode="reset",
            params={
                "position_range": (-0.05, 0.05),
                "velocity_range": (0.0, 0.0),
                "asset_cfg": SceneEntityCfg("robot", joint_names=list(V3_JOINTS)),
            },
        ),
        "foot_friction": EventTermCfg(
            func=v2_mdp.randomize_multisurface_friction,
            mode="reset",
            params={"asset_cfg": SceneEntityCfg("robot", geom_names=foot_geoms), "ranges": (0.22, 1.35)},
        ),
    }
    if not play:
        mass_rand.params["asset_cfg"].body_names = (".*",)
        mass_rand.params["alpha_range"] = (math.log(0.88) / 2.0, math.log(1.12) / 2.0)
        cfg.events["randomize_mass_inertia"] = mass_rand
        com_rand.params["asset_cfg"].body_names = ("torso",)
        com_rand.params["ranges"] = {0: (-0.018, 0.018), 1: (-0.012, 0.012), 2: (-0.008, 0.008)}
        cfg.events["randomize_com"] = com_rand
        cfg.events["randomize_actuators"] = EventTermCfg(func=_v3_randomize_actuators, mode="reset")
        cfg.events["push_robot"] = EventTermCfg(
            func=v2_mdp.push_robot, mode="interval", interval_range_s=(2.5, 5.5)
        )

    # Exact V2 BoundedCost reward architecture
    keep = ("body_ang_vel", "foot_clearance", "foot_swing_height", "foot_slip")
    cfg.rewards = {name: cfg.rewards[name] for name in keep}
    for term in cfg.rewards.values():
        asset = term.params.get("asset_cfg")
        if asset is not None:
            if asset.body_names:
                asset.body_names = ("torso",)
            if asset.site_names:
                asset.site_names = foot_sites

    cfg.rewards["foot_clearance"] = RewardTermCfg(
        func=v2_mdp.foot_clearance,
        weight=-0.20,
        params=dict(
            cfg.rewards["foot_clearance"].params,
            sensor_name="feet_ground_contact",
            target_height=0.016,
            max_free_height=0.036,
        ),
    )
    cfg.rewards["foot_swing_height"] = RewardTermCfg(
        func=v2_mdp.foot_swing_height,
        weight=-0.08,
        params=dict(
            cfg.rewards["foot_swing_height"].params,
            target_height=0.017,
            max_free_height=0.036,
        ),
    )
    cfg.rewards["foot_slip"] = RewardTermCfg(
        func=v2_mdp.foot_slip,
        weight=-0.32,
        params=cfg.rewards["foot_slip"].params,
    )
    cfg.rewards["body_ang_vel"].weight = -0.05
    cfg.rewards.update(
        {
            "tracking_twist": RewardTermCfg(func=_v3_tracking_twist, weight=6.5),
            "upright_cost": RewardTermCfg(func=_v3_upright_cost, weight=-1.5),
            "tracked_air_time": RewardTermCfg(func=_v3_tracked_air_time, weight=2.2),
            "alternating_stride": RewardTermCfg(func=_v3_alternating_stride, weight=2.4),
            "action_change": RewardTermCfg(func=_v3_action_change, weight=-0.12),
            "action_size": RewardTermCfg(func=_v3_action_size, weight=-1.20),
            "standing_pose": RewardTermCfg(func=_v3_standing_pose, weight=-2.20),
            "stand_still": RewardTermCfg(func=_v3_stand_still, weight=5.6 if polish else 5.0),
        }
    )
    for name, limit in {
        "body_ang_vel": 12.0,
        "foot_slip": 1.5,
        "foot_clearance": 1.5,
        "foot_swing_height": 1.0,
        "standing_pose": 8.0,
        "action_change": 3.0,
        "action_size": 1.0,
    }.items():
        term = cfg.rewards[name]
        cfg.rewards[name] = RewardTermCfg(
            func=v2_mdp.BoundedCost,
            weight=term.weight,
            params={"function": term.func, "parameters": term.params, "limit": limit},
        )

    rate_stages = (
        [
            {"step": 0, "weight": -0.45},
            {"step": 80 * 24, "weight": -0.50},
            {"step": 150 * 24, "weight": -0.54},
        ]
        if polish
        else [
            {"step": 0, "weight": -0.10},
            {"step": 80 * 24, "weight": -0.20},
            {"step": 170 * 24, "weight": -0.32},
            {"step": 260 * 24, "weight": -0.45},
        ]
    )
    stand_stages = (
        [{"step": 0, "rel_standing_envs": 0.25}]
        if polish
        else [
            {"step": 0, "rel_standing_envs": 0.05},
            {"step": 110 * 24, "rel_standing_envs": 0.12},
            {"step": 230 * 24, "rel_standing_envs": 0.20},
            {"step": 340 * 24, "rel_standing_envs": 0.25},
        ]
    )
    cfg.curriculum = {
        "walking_difficulty": CurriculumTermCfg(
            func=v2_mdp.WalkingDifficulty,
            params={"widths": [0.12, 0.08, 0.35]},
        ),
        "action_rate_weight": CurriculumTermCfg(
            func=upstream_mdp.reward_weight,
            params={"reward_name": "action_change", "weight_stages": rate_stages},
        ),
        "standing_envs": CurriculumTermCfg(
            func=upstream_mdp.standing_envs_curriculum,
            params={"command_name": "twist", "standing_stages": stand_stages},
        ),
    }
    cfg.terminations = {
        "time_out": TerminationTermCfg(func=env_mdp.time_out, time_out=True),
        "nan_state": TerminationTermCfg(func=v2_mdp.invalid_physics),
        "body_collapsed": TerminationTermCfg(func=_v3_body_collapsed),
    }

    # Exact V2 closed-chain GPU solver settings (avoiding mujoco_warp#1415 Newton float32 issues)
    cfg.sim.mujoco.timestep = 0.002  # 500 Hz physics
    cfg.sim.mujoco.integrator = "implicitfast"
    cfg.sim.mujoco.solver = "cg"
    cfg.sim.mujoco.iterations = 50
    cfg.sim.nconmax = 128
    cfg.sim.njmax = 512
    cfg.decimation = 10  # 50 Hz control
    cfg.episode_length_s = 20.0
    return cfg


def train_v3_gait(
    directory: Path,
    *,
    iterations: int = 550,
    num_envs: int = 2048,
    device: str = "cuda:0",
    seed: int = 42,
    hidden_dims: tuple[int, int, int] = V3_DEFAULT_HIDDEN_DIMS,
    rough: bool = True,
    resume: Path | None = None,
    polish: bool = False,
) -> Path:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    save_json(directory / "progress.json", {"state": "starting", "iterations": iterations, "steps": 0})
    env = None
    try:
        cfg = make_v3_env_cfg(num_envs=num_envs, play=False, rough=rough, polish=polish)
        cfg.seed = seed
        if cfg.scene.terrain.terrain_generator is not None:
            cfg.scene.terrain.terrain_generator.seed = seed

        agent = deepcopy(MicroduckRlCfg)
        agent.logger = "tensorboard"
        agent.seed = seed
        agent.max_iterations = iterations
        agent.num_steps_per_env = 24
        agent.save_interval = max(50, iterations // 4)
        agent.actor.hidden_dims = tuple(hidden_dims)
        agent.critic.hidden_dims = (256, 128, 64)
        agent.actor.obs_normalization = True
        agent.critic.obs_normalization = True
        agent.actor.distribution_cfg = {
            "class_name": "gateway.neural_gait.microduck_policy:FootGaussianDistribution",
            "init_std": 0.65,
            "std_type": "log",
        }
        agent.algorithm.entropy_coef = 0.001 if polish else 0.003
        agent.algorithm.learning_rate = 1.5e-4 if polish else 1.0e-3
        agent.algorithm.desired_kl = 0.006 if polish else 0.01
        agent.algorithm.symmetry_cfg = {
            "use_data_augmentation": True,
            "use_mirror_loss": True,
            "mirror_loss_coeff": 2.5,
            "data_augmentation_func": "gateway.neural_gait.v3_microduck:v3_symmetry_augmentation",
        }

        geo = load_v3_geometry()
        save_json(
            directory / "manifest.json",
            {
                "model": "v3-12servo",
                "geometry_id": geo["geometry_id"],
                "schema": V3_SCHEMA,
                "obs_size": V3_OBS_SIZE,
                "features": V3_FEATURES,
                "samples": V3_SAMPLES,
                "actions": 12,
                "action_space": "normalized-foot-offsets-v3-ik",
                "foot_action_scale_mm": list(V3_FOOT_ACTION_SCALE_MM),
                "hidden_dims": list(hidden_dims),
                "solver": cfg.sim.mujoco.solver,
                "mass_kg": geo["mass_kg"],
                "mass_measured": geo["mass_measured"],
                "servo_specs": geo["servo_specs"],
                "iterations": iterations,
                "num_envs": num_envs,
                "seed": seed,
                "physical_qualified": False,
            },
        )

        env = ManagerBasedRlEnv(cfg, device=device)
        wrapped = RslRlVecEnvWrapper(env, clip_actions=1.0)
        runner = AinekioOnPolicyRunner(wrapped, asdict(agent), str(directory / "learner"), device)

        def _symmetrize_normalizers():
            op, os_, cp, cs, _, _ = _get_symm_tensors(torch.device(device))
            for norm, perm, sign in (
                (getattr(runner.alg.actor, "obs_normalizer", None), op, os_),
                (getattr(runner.alg.critic, "obs_normalizer", None), cp, cs),
            ):
                if norm is not None and hasattr(norm, "_mean") and hasattr(norm, "_std"):
                    with torch.no_grad():
                        m = norm._mean.data
                        norm._mean.data.copy_(0.5 * (m + m[..., perm] * sign))
                        if hasattr(norm, "_var"):
                            v = norm._var.data
                            norm._var.data.copy_(0.5 * (v + v[..., perm]))
                            norm._std.data.copy_(torch.sqrt(norm._var.data.clamp_min(1e-8)))
                        else:
                            s = norm._std.data
                            norm._std.data.copy_(0.5 * (s + s[..., perm]))

        # Exact V2 critic-calibrated low-LR resume + physical action-scale invariance
        if resume is not None:
            ckpt_path = Path(resume) / "learner.pt" if Path(resume).is_dir() else Path(resume)
            runner.load(
                str(ckpt_path),
                load_cfg={"actor": True, "critic": True, "optimizer": False, "iteration": False, "rnd": False},
                map_location=device,
            )
            prev_manifest = ckpt_path.parent / "manifest.json"
            if prev_manifest.exists():
                try:
                    prev_meta = json.loads(prev_manifest.read_text())
                    old_sc = prev_meta.get("foot_action_scale_mm")
                    if old_sc and len(old_sc) == 3 and tuple(float(x) for x in old_sc) != tuple(V3_FOOT_ACTION_SCALE_MM):
                        ratio_3 = [float(old_sc[i]) / float(V3_FOOT_ACTION_SCALE_MM[i]) for i in range(3)]
                        ratio_12 = torch.tensor(ratio_3 * 4, dtype=torch.float32, device=device)
                        with torch.no_grad():
                            last_lin = runner.alg.actor.mlp[-1]
                            last_lin.weight.data.mul_(ratio_12.unsqueeze(1))
                            last_lin.bias.data.mul_(ratio_12)
                            for norm in (runner.alg.actor.obs_normalizer, runner.alg.critic.obs_normalizer):
                                if norm is not None and hasattr(norm, "_mean"):
                                    for k in range(V3_SAMPLES):
                                        sl = slice(k * V3_FEATURES + 36, k * V3_FEATURES + 48)
                                        norm._mean.data[..., sl] *= ratio_12
                                        if hasattr(norm, "_var"):
                                            norm._var.data[..., sl] *= ratio_12.square()
                                            norm._std.data[..., sl] = torch.sqrt(norm._var.data[..., sl].clamp_min(1e-8))
                                        else:
                                            norm._std.data[..., sl] *= ratio_12
                except Exception as exc:
                    print(f"[resume] action-scale remap skipped: {exc}")
            _symmetrize_normalizers()
            if hasattr(runner.alg.actor, "distribution") and hasattr(runner.alg.actor.distribution, "log_std_param"):
                if polish:
                    runner.alg.actor.distribution.log_std_param.data.clamp_(max=-1.75)
                else:
                    runner.alg.actor.distribution.log_std_param.data.clamp_(min=-1.55, max=-0.95)

            actor = runner.alg.actor
            critic = runner.alg.critic
            actor.obs_normalizer.eval()
            critic.obs_normalizer.eval()
            c_opt = torch.optim.AdamW(critic.mlp.parameters(), lr=1.2e-3, weight_decay=1e-5)
            gamma = float(getattr(runner.alg, "gamma", 0.99))
            wrapped.reset()
            c_obs_l, nc_obs_l, rew_l, done_l, to_l = [], [], [], [], []
            try:
                with torch.no_grad():
                    for _ in range(140):
                        otd = wrapped.get_observations()
                        an = actor.obs_normalizer(otd["actor"])
                        cn = critic.obs_normalizer(otd["critic"])
                        act = actor.mlp(an).clamp(-8.0, 8.0).tanh()
                        notd, rw, dn, ext = wrapped.step(act)
                        ncn = critic.obs_normalizer(notd["critic"])
                        tos = ext.get("time_outs", torch.zeros_like(dn, dtype=torch.bool))
                        c_obs_l.append(cn.detach())
                        nc_obs_l.append(ncn.detach())
                        rew_l.append(rw.to(torch.float32).detach())
                        done_l.append((dn > 0).to(torch.float32).detach())
                        to_l.append(tos.to(torch.float32).detach())
                c_all = torch.cat(c_obs_l, dim=0)
                n_c = c_all.shape[0]
                for sw in range(4):
                    with torch.no_grad():
                        r_ret = critic.mlp(nc_obs_l[-1]).squeeze(-1) if sw > 0 else torch.zeros_like(rew_l[-1])
                        rets = [None] * len(rew_l)
                        for t_idx in range(len(rew_l) - 1, -1, -1):
                            vb = critic.mlp(nc_obs_l[t_idx]).squeeze(-1) if sw > 0 else torch.zeros_like(r_ret)
                            cont = torch.where(done_l[t_idx] > 0.5, to_l[t_idx] * vb, r_ret)
                            r_ret = rew_l[t_idx] + gamma * cont
                            rets[t_idx] = r_ret
                    ret_all = torch.cat(rets, dim=0).unsqueeze(-1)
                    for _ in range(4):
                        perm = torch.randperm(n_c, device=device)
                        for st in range(0, n_c, 4096):
                            idx = perm[st : st + 4096]
                            loss = (critic.mlp(c_all[idx]) - ret_all[idx]).square().mean()
                            c_opt.zero_grad()
                            loss.backward()
                            torch.nn.utils.clip_grad_norm_(critic.mlp.parameters(), 2.0)
                            c_opt.step()
            finally:
                actor.obs_normalizer.train(True)
                critic.obs_normalizer.train(True)
            wrapped.reset()
            runner.alg.optimizer.state.clear()
            if hasattr(runner.alg, "learning_rate"):
                runner.alg.learning_rate = 1.5e-4 if polish else 4.5e-4
                for group in runner.alg.optimizer.param_groups:
                    group["lr"] = runner.alg.learning_rate

        original_log = runner.logger.log

        def _progress(**values):
            _symmetrize_normalizers()
            original_log(**values)
            completed = values["it"] - values["start_it"] + 1
            save_json(
                directory / "progress.json",
                {
                    "state": "training",
                    "iterations": completed,
                    "total_iterations": iterations,
                    "steps": completed * num_envs * agent.num_steps_per_env,
                },
            )

        runner.logger.log = _progress
        runner.learn(iterations, init_at_random_ep_len=True)
        _symmetrize_normalizers()
        runner.save(str(directory / "learner.pt"))

        onnx_path = directory / "policy.onnx"
        runner.export_policy_to_onnx(str(directory), "policy.onnx")
        from mjlab.rl.exporter_utils import attach_metadata_to_onnx

        attach_metadata_to_onnx(
            str(onnx_path),
            {
                "ainekio_model": "v3-12servo",
                "ainekio_geometry_id": geo["geometry_id"],
                "ainekio_schema": V3_SCHEMA,
                "ainekio_action": "normalized-foot-offsets-v3-ik",
                "ainekio_foot_action_scale_mm": json.dumps(list(V3_FOOT_ACTION_SCALE_MM)),
                "checkpoint_sha256": hashlib.sha256((directory / "learner.pt").read_bytes()).hexdigest(),
            },
        )
        steps = iterations * num_envs * agent.num_steps_per_env
        save_json(
            directory / "progress.json",
            {"state": "complete", "iterations": iterations, "steps": steps, "physical_qualified": False},
        )
        return onnx_path
    finally:
        if env is not None:
            env.close()


def evaluate_v3_policy(onnx_path: Path, output_json: Path | None = None) -> dict:
    """Evaluate a trained V3 V2-aligned ONNX policy in standalone CPU MuJoCo."""
    import onnxruntime as ort

    geo = load_v3_geometry()
    xml = build_v3_xml(geo, floor=True)
    model = mujoco.MjModel.from_xml_string(xml)
    data = mujoco.MjData(model)
    body = V3TensorBody(geo, device="cpu", scale_mm=V3_FOOT_ACTION_SCALE_MM)
    sensors = V3TensorSensors(1, "cpu", sensor_noise=False)

    sess = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
    in_name = sess.get_inputs()[0].name

    j_ids = [mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, name) for name in V3_JOINTS]
    q_ids = [int(model.jnt_qposadr[j]) for j in j_ids]
    v_ids = [int(model.jnt_dofadr[j]) for j in j_ids]
    act_ids = [mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_ACTUATOR, name) for name in V3_JOINTS]
    foot_geom_ids = [mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, f"{leg}_foot") for leg in V3_LEGS]
    foot_site_ids = [mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_SITE, f"{leg}_foot") for leg in V3_LEGS]
    floor_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, "floor")

    scenarios = {
        "stand": (0.0, 0.0, 0.0),
        "walk_fwd": (0.32, 0.0, 0.0),
        "walk_fast": (0.45, 0.0, 0.0),
        "walk_back": (-0.30, 0.0, 0.0),
        "turn_left": (0.0, 0.0, 1.30),
        "turn_right": (0.0, 0.0, -1.30),
        "crab_left": (0.0, 0.20, 0.0),
        "crab_right": (0.0, -0.20, 0.0),
    }

    z_init = float(geo["standing_shoulder_height_mm"]) / 1000.0 + 0.002
    dt_ctrl = 0.02
    substeps = 10
    results = {}

    for sc_name, cmd_tuple in scenarios.items():
        mujoco.mj_resetData(model, data)
        data.qpos[2] = z_init
        mujoco.mj_forward(model, data)

        sensors.reset(slice(None), torch.zeros((1, 12), dtype=torch.float32))
        history = np.zeros((V3_SAMPLES, V3_FEATURES), dtype=np.float32)
        prev_action = np.zeros(12, dtype=np.float32)
        cmd = np.asarray(cmd_tuple, dtype=np.float32)
        phase_rad = 0.0
        delay_q = deque([np.zeros(12, dtype=np.float32) for _ in range(V3_ACTUATOR_DELAY_SUBSTEPS + 1)],
                        maxlen=V3_ACTUATOR_DELAY_SUBSTEPS + 1)

        survived = True
        vx_l, vy_l, wz_l, z_l, splay_l, foot_y_l = [], [], [], [], [], []
        body_w_l, raw_l = [], []
        peak_qd = 0.0
        diag_steps = hop_steps = all_air_steps = eval_steps = 0
        foot_x_hist, foot_z_hist = [], []
        max_ank_err = 0.0

        for step in range(250):  # 5.0 s at 50 Hz
            R = data.xmat[1].reshape(3, 3)
            q_true = torch.tensor(data.qpos[q_ids], dtype=torch.float32).unsqueeze(0)
            lin_b = torch.tensor(R.T @ data.qvel[:3], dtype=torch.float32).unsqueeze(0)
            gyro_b = torch.tensor(data.qvel[3:6], dtype=torch.float32).unsqueeze(0)  # MuJoCo freejoint qvel[3:6] is already body-frame!
            grav_b = torch.tensor(R.T @ np.array([0.0, 0.0, -1.0]), dtype=torch.float32).unsqueeze(0)
            sensors.update_50hz(q_true, gyro_b, lin_b, grav_b, dt=dt_ctrl)
            row = sensors.features(
                torch.tensor(cmd, dtype=torch.float32).unsqueeze(0),
                torch.tensor(prev_action, dtype=torch.float32).unsqueeze(0),
                torch.tensor([phase_rad], dtype=torch.float32),
            )[0].numpy()

            history[1:] = history[:-1]
            history[0] = row

            raw = np.clip(sess.run(None, {in_name: history.reshape(1, -1)})[0][0], -1.0, 1.0).astype(np.float32)
            prev_action = raw
            targets = body.decode(torch.tensor(raw, dtype=torch.float32).unsqueeze(0))[0].numpy()
            cmd_mag = math.hypot(float(cmd[0]), float(cmd[1])) + 0.18 * abs(float(cmd[2]))
            if cmd_mag > 0.02:
                phase_rad = (phase_rad + 2.0 * math.pi * v3_gait_hz_np(cmd) * dt_ctrl) % (2.0 * math.pi)

            for _ in range(substeps):
                delay_q.append(targets.copy())
                delayed_targets = delay_q[0]
                qd = data.qvel[v_ids]
                lo_f, hi_f = motor_force_range(qd, V3_SERVO_EFFORT_NM, V3_SERVO_NO_LOAD_RAD_S)
                for k, aid in enumerate(act_ids):
                    model.actuator_forcerange[aid, 0] = lo_f[k]
                    model.actuator_forcerange[aid, 1] = hi_f[k]
                    data.ctrl[aid] = delayed_targets[k]
                mujoco.mj_step(model, data)

            R_post = data.xmat[1].reshape(3, 3)
            if (R_post.T @ np.array([0.0, 0.0, -1.0]))[2] > -0.35 or data.qpos[2] < 0.095:
                survived = False
                break

            if step >= 75:  # steady-state 1.5..5.0 s
                v_body = R_post.T @ data.qvel[:3]
                w_body = data.qvel[3:6]
                vx_l.append(float(v_body[0]))
                vy_l.append(float(v_body[1]))
                wz_l.append(float(w_body[2]))
                z_l.append(float(data.qpos[2]) * 1000.0)
                splay_l.append(float(np.rad2deg(np.abs(data.qpos[q_ids][0::3])).mean()))
                body_w_l.append(np.rad2deg(np.abs(w_body[:2])).tolist())
                raw_l.append(raw.copy())
                peak_qd = max(peak_qd, float(np.rad2deg(np.max(np.abs(data.qvel[v_ids])))))
                eval_steps += 1

                c = [0, 0, 0, 0]
                for ci in range(data.ncon):
                    con = data.contact[ci]
                    for li, gid in enumerate(foot_geom_ids):
                        if (con.geom1 == gid and con.geom2 == floor_id) or (con.geom2 == gid and con.geom1 == floor_id):
                            c[li] = 1
                if (c[0] == 1 and c[3] == 1 and c[1] == 0 and c[2] == 0) or (
                    c[1] == 1 and c[2] == 1 and c[0] == 0 and c[3] == 0
                ):
                    diag_steps += 1
                if (c[0] == 0 and c[1] == 0) or (c[2] == 0 and c[3] == 0):
                    hop_steps += 1
                if sum(c) == 0:
                    all_air_steps += 1

                fx_b, fy_b, fz_w = [], [], []
                for sid in foot_site_ids:
                    rel = R_post.T @ (data.site_xpos[sid] - data.qpos[:3])
                    fx_b.append(float(rel[0]) * 1000.0)
                    fy_b.append(abs(float(rel[1])) * 1000.0)
                    fz_w.append(float(data.site_xpos[sid][2]) * 1000.0)
                foot_x_hist.append(fx_b)
                foot_y_l.append(float(np.mean(fy_b)))
                foot_z_hist.append(fz_w)
                for gid in foot_geom_ids:
                    up_g = data.geom_xmat[gid].reshape(3, 3)[:, 2]
                    cos_t = float(np.clip(np.dot(up_g, R_post[:, 2]), -1.0, 1.0))
                    max_ank_err = max(max_ank_err, math.degrees(math.acos(cos_t)))

        fx_arr = np.asarray(foot_x_hist) if foot_x_hist else np.zeros((2, 4))
        fz_arr = np.asarray(foot_z_hist) if foot_z_hist else np.zeros((2, 4))
        raw_arr = np.asarray(raw_l) if len(raw_l) > 2 else np.zeros((3, 12))
        dr = np.diff(raw_arr, axis=0)
        chatter_pct = float(((dr[1:] * dr[:-1]) < 0).mean() * 100.0) if len(dr) > 1 else 0.0
        mean_dact = float(np.abs(dr).mean()) if len(dr) > 0 else 0.0
        body_rp_deg_s = float(np.mean(body_w_l)) if body_w_l else 0.0

        def _corr(a, b):
            if len(a) < 5 or np.std(a) < 1e-4 or np.std(b) < 1e-4:
                return 0.0
            return round(float(np.corrcoef(a, b)[0, 1]), 2)

        per_leg_stride = np.ptp(fx_arr, axis=0)
        results[sc_name] = {
            "command": list(cmd_tuple),
            "survived": survived,
            "mean_vx_m_s": round(float(np.mean(vx_l)) if vx_l else 0.0, 4),
            "mean_vy_m_s": round(float(np.mean(vy_l)) if vy_l else 0.0, 4),
            "mean_wz_rad_s": round(float(np.mean(wz_l)) if wz_l else 0.0, 4),
            "mean_height_mm": round(float(np.mean(z_l)) if z_l else 0.0, 2),
            "mean_shoulder_splay_deg": round(float(np.mean(splay_l)) if splay_l else 0.0, 1),
            "mean_foot_y_abs_mm": round(float(np.mean(foot_y_l)) if foot_y_l else 0.0, 1),
            "peak_joint_speed_deg_s": round(peak_qd, 1),
            "action_chatter_pct": round(chatter_pct, 1),
            "mean_delta_action": round(mean_dact, 3),
            "mean_body_rp_deg_s": round(body_rp_deg_s, 1),
            "diag_trot_pct": round(100.0 * diag_steps / max(1, eval_steps), 1),
            "same_girdle_hop_pct": round(100.0 * hop_steps / max(1, eval_steps), 1),
            "all_air_pct": round(100.0 * all_air_steps / max(1, eval_steps), 1),
            "stride_x_mm": round(float(np.mean(per_leg_stride)), 1),
            "min_leg_stride_x_mm": round(float(np.min(per_leg_stride)), 1),
            "lift_z_mm": round(float(np.mean(np.ptp(fz_arr, axis=0))), 1),
            "corr_rear_x": _corr(fx_arr[:, 0], fx_arr[:, 1]),
            "corr_front_x": _corr(fx_arr[:, 2], fx_arr[:, 3]),
            "corr_diag_x": round(0.5 * (_corr(fx_arr[:, 0], fx_arr[:, 3]) + _corr(fx_arr[:, 1], fx_arr[:, 2])), 2),
            "max_ankle_level_err_deg": round(max_ank_err, 2),
        }

    report = {
        "model": "v3-12servo",
        "geometry_id": geo["geometry_id"],
        "schema": V3_SCHEMA,
        "mass_kg": geo["mass_kg"],
        "mass_measured": geo["mass_measured"],
        "basis": "MuJoCo CPU closed-chain 4-bar simulation (DS3225 PRO 7.4V, V2-aligned IK); not physical hardware qualification",
        "scenarios": results,
    }
    if output_json is not None:
        save_json(output_json, report)
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description="Train & evaluate V3 12-servo Option A-1 neural gait (V2-aligned)")
    ap.add_argument("--directory", type=Path, default=ROOT / "build/neural-gait/v3-microduck-p4")
    ap.add_argument("--iterations", type=int, default=550)
    ap.add_argument("--num-envs", type=int, default=2048)
    ap.add_argument("--device", default="cuda:0")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--flat", action="store_true")
    ap.add_argument("--evaluate-only", action="store_true")
    ap.add_argument("--resume", type=Path, default=None)
    ap.add_argument("--polish", action="store_true")
    args = ap.parse_args()

    onnx_path = args.directory / "policy.onnx"
    if not args.evaluate_only:
        onnx_path = train_v3_gait(
            args.directory,
            iterations=args.iterations,
            num_envs=args.num_envs,
            device=args.device,
            seed=args.seed,
            rough=not args.flat,
            resume=args.resume,
            polish=args.polish,
        )
    report = evaluate_v3_policy(onnx_path, args.directory / "evaluation.json")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
