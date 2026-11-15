"""GPU trainer, ONNX exporter, and 500 Hz MuJoCo physics qualifier for System 3 (Autonomic Presence).

Trains the ESP32-P4-sized (128, 96) MLP (`ainekio-presence-v1`, 55,250 parameters, ~216 KB FP32 / ~54 KB INT8)
on exact V2 closed-chain four-bar kinematics and qualifies the exported ONNX policy in 500 Hz MuJoCo physics.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
import time

import numpy as np
import onnx
import torch
import torch.nn as nn
import torch.nn.functional as F

ROOT = Path(__file__).resolve().parents[3]
MASTER_DIR = str(ROOT / "Master")
if MASTER_DIR not in sys.path:
    sys.path.insert(0, MASTER_DIR)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from experiments.freestyle.neural_pose.goals import PoseManifold, STAND_ANGLES_DEG, _ensure_native_library
from gateway.neural_gait.tensor_body import wrap


def full_four_bar_qpos20(body, q43_rad: torch.Tensor) -> torch.Tensor:
    """Compute all 20 joint angles [sh, ca, pickup, cr, rod]*4 with 0.0 loop-closure error."""
    q43 = q43_rad.to(dtype=torch.float64)
    q0 = torch.zeros((1, 4, 3), dtype=torch.float64, device=q43.device)
    dx0, dz0, bc0, bs0, *_ = body.seed(q0)
    px0 = body.C[0] + body.r * math.cos(body.t0)
    pz0 = body.C[1] + body.r * math.sin(body.t0)
    gamma0 = torch.atan2(dz0 + body.b * bs0 - pz0, dx0 + body.b * bc0 - px0)

    dx, dz, bc, bs, *_ = body.seed(q43)
    beta = torch.atan2(bs, bc)
    th = body.t0 + q43[..., 2]
    px = body.C[0] + body.r * torch.cos(th)
    pz = body.C[1] + body.r * torch.sin(th)
    gamma = torch.atan2(dz + body.b * bs - pz, dx + body.b * bc - px)
    pickup = wrap(beta - body.b0 - q43[..., 1])
    rod = wrap(gamma - gamma0 - q43[..., 2])
    q20 = torch.stack((q43[..., 0], q43[..., 1], pickup, q43[..., 2], rod), dim=-1)
    return q20.reshape(-1, 20).to(dtype=torch.float32)
from gateway.presence.actor import DEFAULT_ACTIVE_POLICY, PresenceActor
from gateway.presence.contract import (
    EXPRESSION_MODES,
    PRESENCE_ACTION_DIM,
    PRESENCE_COMPLIANCE_DIM,
    PRESENCE_COMPLIANCE_STEP_MM,
    PRESENCE_EXPR_DIM,
    PRESENCE_FEATURES,
    PRESENCE_FOOT_DIM,
    PRESENCE_FOOT_SCALE_MM,
    PRESENCE_HIDDEN_DIMS,
    PRESENCE_INTERVAL_S,
    PRESENCE_OBS_SIZE,
    PRESENCE_SAMPLES,
    PRESENCE_SCHEMA,
    PresenceObservationHistory,
    assemble_presence_features,
    presence_model_footprint,
    update_compliance_trim_mm,
)

_ensure_native_library()


class PresenceMLP(nn.Module):
    """Compact P4-friendly 2-hidden-layer ELU MLP: 320 -> 128 -> 96 -> 30."""

    def __init__(
        self,
        obs_size: int = PRESENCE_OBS_SIZE,
        hidden_dims: tuple[int, int] = PRESENCE_HIDDEN_DIMS,
        action_dim: int = PRESENCE_ACTION_DIM,
    ):
        super().__init__()
        h1, h2 = hidden_dims
        self.net = nn.Sequential(
            nn.Linear(obs_size, h1),
            nn.ELU(),
            nn.Linear(h1, h2),
            nn.ELU(),
            nn.Linear(h2, action_dim),
        )

    def forward(self, obs: torch.Tensor) -> torch.Tensor:
        out = self.net(obs)
        pose_comp = torch.tanh(out[:, : PRESENCE_FOOT_DIM + PRESENCE_COMPLIANCE_DIM])
        expr_logits = out[:, PRESENCE_FOOT_DIM + PRESENCE_COMPLIANCE_DIM :]
        # Gate `surprised` (index 5) on real IMU tilt/gyro energy in newest frame [48..54];
        # identically 0 when `imu_enabled=False` or standing calmly level.
        imu_energy = (
            obs[:, 48] * obs[:, 48]
            + obs[:, 49] * obs[:, 49]
            + obs[:, 51] * obs[:, 51]
            + obs[:, 52] * obs[:, 52]
            + obs[:, 53] * obs[:, 53]
        ).unsqueeze(-1)
        floor_logit = torch.min(expr_logits[:, :5], dim=-1, keepdim=True).values - 5.0
        surprised_logit = torch.where(imu_energy >= 0.015, expr_logits[:, 5:6], floor_logit)
        gated_logits = torch.cat([expr_logits[:, :5], surprised_logit], dim=-1)
        return torch.cat([pose_comp, gated_logits], dim=-1)


def _body_pose_foot_deltas_mm(
    manifold: PoseManifold,
    stand_feet_world: np.ndarray,
    *,
    tx_mm: np.ndarray,
    ty_mm: np.ndarray,
    tz_mm: np.ndarray,
    roll_deg: np.ndarray,
    pitch_deg: np.ndarray,
    yaw_deg: np.ndarray,
) -> np.ndarray:
    """Vectorized exact 6-DoF torso IK foot-offset residuals (in mm) relative to standing feet.

    Uses the V2 body rotation pivot [0, 0, 65] mm matching `experiments/freestyle/program.py`.
    When the body translates by +t and rotates by R around pivot P, planted world feet S
    move in the body frame to: p_body = P + R^T @ (S - P - t).
    """
    n = tx_mm.shape[0]
    pivot = np.array([0.0, 0.0, 65.0], dtype=np.float64).reshape(1, 1, 3)
    s_pts = stand_feet_world.reshape(1, 4, 3)  # [1, 4, 3] in body/world at stand

    rr = np.deg2rad(roll_deg)
    pp = np.deg2rad(pitch_deg)
    yy = np.deg2rad(yaw_deg)
    cr, sr = np.cos(rr), np.sin(rr)
    cp, sp = np.cos(pp), np.sin(pp)
    cy, sy = np.cos(yy), np.sin(yy)

    # R = Rz(yaw) @ Ry(pitch) @ Rx(roll) -> shape [N, 3, 3]
    r00 = cy * cp
    r01 = cy * sp * sr - sy * cr
    r02 = cy * sp * cr + sy * sr
    r10 = sy * cp
    r11 = sy * sp * sr + cy * cr
    r12 = sy * sp * cr - cy * sr
    r20 = -sp
    r21 = cp * sr
    r22 = cp * cr
    rot = np.stack(
        [
            np.stack([r00, r01, r02], axis=-1),
            np.stack([r10, r11, r12], axis=-1),
            np.stack([r20, r21, r22], axis=-1),
        ],
        axis=1,
    )  # [N, 3, 3]
    rot_t = np.swapaxes(rot, 1, 2)  # [N, 3, 3]

    trans = np.stack([tx_mm, ty_mm, tz_mm], axis=-1).reshape(n, 1, 3)
    rel = (s_pts - pivot) - trans  # [N, 4, 3]
    p_body = pivot + np.einsum("nij,nkj->nki", rot_t, rel)  # [N, 4, 3]
    deltas_mm = (p_body - s_pts).reshape(n, 12)
    return deltas_mm


def _quat_wxyz_from_rpy_deg(roll_deg: np.ndarray, pitch_deg: np.ndarray, yaw_deg: np.ndarray) -> np.ndarray:
    r = np.deg2rad(roll_deg) * 0.5
    p = np.deg2rad(pitch_deg) * 0.5
    y = np.deg2rad(yaw_deg) * 0.5
    cr, sr = np.cos(r), np.sin(r)
    cp, sp = np.cos(p), np.sin(p)
    cy, sy = np.cos(y), np.sin(y)
    w = cr * cp * cy + sr * sp * sy
    x = sr * cp * cy - cr * sp * sy
    yy = cr * sp * cy + sr * cp * sy
    z = cr * cp * sy - sr * sp * cy
    return np.stack([w, x, yy, z], axis=-1)


def build_presence_dataset(
    manifold: PoseManifold,
    num_sequences: int = 48000,
    seed: int = 42,
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
    """Synthesize physically grounded 4-frame (200 ms @ 20 Hz) multimodal sequences on V2 geometry."""
    rng = np.random.default_rng(seed)
    n = int(num_sequences)

    stand_q_rad = np.deg2rad(np.array(STAND_ANGLES_DEG, dtype=np.float64)).reshape(1, 4, 3)
    fb = manifold.body
    pts_t, _ = fb.forward(torch.from_numpy(stand_q_rad).to(device=fb.device, dtype=torch.float64))
    stand_pts_mm = pts_t[0].detach().cpu().numpy()  # [4, 3] foot positions in body frame (mm)

    # Numerical foot Jacobian d(foot_mm)/d(q_rad) at standing pose: [4, 3, 3]
    eps = 1e-4
    jac_mm_per_rad = np.zeros((4, 3, 3), dtype=np.float64)
    for axis in range(3):
        q_plus = stand_q_rad.copy()
        q_plus[:, :, axis] += eps
        p_plus, _ = fb.forward(torch.from_numpy(q_plus).to(device=fb.device, dtype=torch.float64))
        jac_mm_per_rad[:, :, axis] = (p_plus[0].detach().cpu().numpy() - stand_pts_mm) / eps

    # Regimes:
    # 0: calm_idle (14%), 1: chatter_relief (20%), 2: listening (16%),
    # 3: talking (20%), 4: curious_gaze (14%), 5: bored_restless (8%), 6: shove_reflex (8%)
    probs = [0.14, 0.20, 0.16, 0.20, 0.14, 0.08, 0.08]
    regimes = rng.choice(len(probs), size=n, p=probs)

    imu_enabled = rng.random(n) > 0.18  # 18% train with gyro switch OFF
    chatter_enabled = rng.random(n) > 0.10

    person_yaw = np.zeros(n, dtype=np.float64)
    person_pitch = np.zeros(n, dtype=np.float64)
    person_conf = np.zeros(n, dtype=np.float64)
    known_face = np.zeros(n, dtype=np.float64)
    motion_mag = np.zeros(n, dtype=np.float64)
    listening = np.zeros(n, dtype=np.float64)
    mic_rms = np.zeros(n, dtype=np.float64)
    speaking = np.zeros(n, dtype=np.float64)
    speech_rms = np.zeros(n, dtype=np.float64)
    boredom = np.zeros(n, dtype=np.float64)
    phase0 = rng.uniform(0.0, 2.0 * math.pi, size=n)

    # Populate multimodal context by regime (include voice-only listening/talking with person_conf == 0!)
    has_social = (regimes == 4) | (np.isin(regimes, [2, 3]) & (rng.random(n) < 0.55)) | (rng.random(n) < 0.22)
    person_yaw[has_social] = rng.uniform(-1.0, 1.0, size=int(np.sum(has_social)))
    person_pitch[has_social] = rng.uniform(-0.85, 0.85, size=int(np.sum(has_social)))
    person_conf[has_social] = rng.uniform(0.35, 1.0, size=int(np.sum(has_social)))
    known_face[has_social] = (rng.random(int(np.sum(has_social))) < 0.45).astype(np.float64)
    motion_mag[has_social] = rng.uniform(0.0, 0.8, size=int(np.sum(has_social)))

    m_listen = regimes == 2
    listening[m_listen] = 1.0
    mic_rms[m_listen] = rng.uniform(0.06, 0.85, size=int(np.sum(m_listen)))

    m_talk = regimes == 3
    speaking[m_talk] = 1.0
    speech_rms[m_talk] = rng.uniform(0.08, 0.95, size=int(np.sum(m_talk)))

    m_curious = regimes == 4
    person_conf[m_curious] = rng.uniform(0.55, 1.0, size=int(np.sum(m_curious)))
    motion_mag[m_curious] = rng.uniform(0.15, 1.0, size=int(np.sum(m_curious)))

    m_bored = regimes == 5
    person_conf[m_bored] = 0.0
    known_face[m_bored] = 0.0
    boredom[m_bored] = rng.uniform(0.20, 1.0, size=int(np.sum(m_bored)))

    # Simulated servo load/chatter error (cmd - meas in deg): normal standing gravity sag is ~0.8-1.4 deg
    cmd_minus_meas_deg = rng.normal(0.0, 0.75, size=(n, 12))
    chatter_deg = np.abs(rng.normal(0.10, 0.12, size=(n, 12)))
    m_chat = (regimes == 1) | (rng.random(n) < 0.34)
    n_chat = int(np.sum(m_chat))
    # Inject realistic carpet friction / snag fight (>2 deg) on 1..8 joints
    fight_mask = rng.random((n_chat, 12)) < 0.45
    fight_err = rng.choice([-1.0, 1.0], size=(n_chat, 12)) * rng.uniform(2.4, 11.5, size=(n_chat, 12)) * fight_mask
    cmd_minus_meas_deg[m_chat] += fight_err
    chatter_deg[m_chat] += np.abs(fight_err) * rng.uniform(0.25, 0.65, size=(n_chat, 12))

    # IMU state: nominal slight tilt + shove disturbance in regime 6
    body_roll_deg = rng.normal(0.0, 1.5, size=n)
    body_pitch_deg = rng.normal(0.0, 1.5, size=n)
    gyro_rad_s = rng.normal(0.0, 0.05, size=(n, 3))
    accel_jerk_m_s2 = rng.normal(0.0, 0.12, size=(n, 3))

    m_shove = regimes == 6
    n_shove = int(np.sum(m_shove))
    imu_enabled[m_shove] = True
    shove_onset_step = np.zeros(n, dtype=np.int64)
    shove_onset_step[m_shove] = rng.choice([0, 1, 2], size=n_shove, p=[0.35, 0.30, 0.35])
    body_roll_deg[m_shove] = rng.choice([-1.0, 1.0], size=n_shove) * rng.uniform(7.0, 22.0, size=n_shove)
    body_pitch_deg[m_shove] = rng.uniform(-16.0, 16.0, size=n_shove)
    gyro_rad_s[m_shove] = rng.uniform(-2.6, 2.6, size=(n_shove, 3))
    accel_jerk_m_s2[m_shove] = rng.uniform(-4.5, 4.5, size=(n_shove, 3))

    # Compute target 6-DoF torso pose for each sequence step t in 0..3 (chronological -> causal buffer)
    scale_vec = np.array(PRESENCE_FOOT_SCALE_MM * 4, dtype=np.float64).reshape(1, 12)
    obs_windows = np.zeros((n, PRESENCE_OBS_SIZE), dtype=np.float32)

    # Pre-compute per-tick compliance step in mm using exact Jacobian J * (-err_rad)
    # Yields 45% of unmet servo fight (>2.0 deg deadband or active chatter) per 50 ms tick without gravity drift.
    eff_err_rad = np.deg2rad(cmd_minus_meas_deg) * chatter_enabled[:, None]
    deadband = (np.abs(cmd_minus_meas_deg) > 2.0) | (chatter_deg > 0.90)
    yield_q_rad = -0.48 * eff_err_rad * deadband
    comp_step_mm = np.einsum("lij,nlj->nli", jac_mm_per_rad, yield_q_rad.reshape(n, 4, 3))  # [N, 4, 3]
    comp_step_mm[:, :, 2] -= np.mean(comp_step_mm[:, :, 2], axis=1, keepdims=True)
    comp_step_mm[:, :, 0] -= 0.45 * np.mean(comp_step_mm[:, :, 0], axis=1, keepdims=True)
    comp_step_mm[:, :, 1] -= 0.45 * np.mean(comp_step_mm[:, :, 1], axis=1, keepdims=True)
    target_comp_norm = np.clip(
        comp_step_mm.reshape(n, 12) / PRESENCE_COMPLIANCE_STEP_MM, -1.0, 1.0
    ).astype(np.float32)

    # Sample broad initial `prev_action` and broad posture offsets (`q_delta` across full stand/off-stand/sit workspace)
    # so closed-loop rollouts contract cleanly to `target_foot_norm` without positive-feedback extrapolation.
    init_bucket = rng.random(n)
    prev_action = np.where(
        (init_bucket < 0.45)[:, None],
        np.clip(rng.normal(0.0, 0.15, size=(n, 12)), -1.0, 1.0),
        np.where(
            (init_bucket < 0.80)[:, None],
            rng.uniform(-0.85, 0.85, size=(n, 12)),
            rng.uniform(-1.0, 1.0, size=(n, 12)),
        ),
    )
    posture_bucket = rng.random(n)
    posture_offset_deg = np.where(
        (posture_bucket < 0.45)[:, None],
        rng.normal(0.0, 4.5, size=(n, 12)),
        np.where(
            (posture_bucket < 0.78)[:, None],
            rng.uniform(-22.0, 22.0, size=(n, 12)),
            rng.uniform(-50.0, 42.0, size=(n, 12)),
        ),
    )
    stand_deg_arr = np.array(STAND_ANGLES_DEG, dtype=np.float64)[None, :]
    chronological_frames: list[np.ndarray] = []
    target_foot_norm = np.zeros((n, 12), dtype=np.float32)

    for step_idx in range(PRESENCE_SAMPLES):
        dt = (step_idx - (PRESENCE_SAMPLES - 1)) * PRESENCE_INTERVAL_S
        ph = phase0 + 2.2 * dt
        s_ph = np.sin(ph)
        c_ph = np.cos(ph)

        # Modulate speech envelope realistically over the 4 frames
        step_speech_rms = np.clip(speech_rms * (0.75 + 0.35 * np.sin(ph * 2.3)), 0.0, 1.0) * speaking
        step_mic_rms = np.clip(mic_rms * (0.80 + 0.25 * np.cos(ph * 1.9)), 0.0, 1.0) * listening

        # 1. Calm living breathing & gentle posture sway centered symmetrically on standing anchor
        tz = 0.8 * s_ph
        tx = 0.6 * c_ph
        ty = 0.6 * s_ph
        roll = 0.7 * c_ph
        pitch = -0.8 * s_ph
        yaw = 0.8 * s_ph

        # 2. Social YOLOE gaze & curious idle glance tracking (bounded inside V2 linear four-bar workspace)
        gaze_w = person_conf
        yaw += gaze_w * person_yaw * 3.6
        pitch += gaze_w * (-person_pitch * 3.0)
        roll += gaze_w * person_yaw * 1.3
        tx += gaze_w * (-0.8 + known_face * 0.8)

        # 3. Active listening posture (attentive perk-up + gentle weight shift)
        listen_w = listening * (0.72 + 0.28 * step_mic_rms)
        pitch -= listen_w * (2.6 + 0.7 * s_ph)
        roll += listen_w * np.where(person_yaw >= 0.0, 1.8, -1.8)
        yaw += listen_w * np.where(np.abs(person_yaw) > 0.08, person_yaw * 2.4, 1.3 * c_ph)
        tx -= listen_w * 1.1
        tz += listen_w * 0.6

        # 4. Expressive talking body language synced to live TTS syllable envelope
        talk_env = speaking * (0.42 + 0.58 * step_speech_rms)
        pitch -= talk_env * (1.8 + 1.6 * np.maximum(0.0, s_ph))
        roll += talk_env * 2.0 * s_ph
        yaw += talk_env * 2.5 * c_ph
        tx += talk_env * (-0.9 + 0.8 * c_ph)
        tz += talk_env * (0.4 + 0.8 * np.abs(s_ph))

        # 5. Restless boredom (curious scanning & weight shifts well inside symmetric comfort bounds)
        b_w = boredom
        yaw += b_w * 3.8 * s_ph
        pitch += b_w * 2.4 * c_ph
        roll += b_w * 1.6 * s_ph * c_ph
        ty += b_w * 2.2 * c_ph
        tx -= b_w * 0.6
        tz += b_w * (1.0 * s_ph - 0.3)

        # 6. Causal IMU shove state & reflex (counter-lean damping when imu_enabled=True)
        shove_live = (~m_shove) | (step_idx >= shove_onset_step)
        step_roll_deg = np.where(shove_live, body_roll_deg, rng.normal(0.0, 1.2, size=n))
        step_pitch_deg = np.where(shove_live, body_pitch_deg, rng.normal(0.0, 1.2, size=n))
        step_gyro = np.where(shove_live[:, None], gyro_rad_s, rng.normal(0.0, 0.04, size=(n, 3)))
        step_jerk = np.where(shove_live[:, None], accel_jerk_m_s2, rng.normal(0.0, 0.10, size=(n, 3)))

        eff_imu = imu_enabled.astype(np.float64)
        shove_active = ((np.hypot(step_roll_deg, step_pitch_deg) > 4.5) | (np.linalg.norm(step_gyro, axis=-1) > 0.9)) * eff_imu
        roll -= shove_active * np.clip(0.32 * step_roll_deg + 1.5 * step_gyro[:, 0], -3.5, 3.5)
        pitch -= shove_active * np.clip(0.32 * step_pitch_deg + 1.5 * step_gyro[:, 1], -3.5, 3.5)
        tz -= shove_active * 1.4

        # Couple nose-up pitch (< 0) with slight hindquarters shift so rear carriers stay centered
        tx += np.minimum(0.0, pitch) * 0.25

        pose_mm = _body_pose_foot_deltas_mm(
            manifold,
            stand_pts_mm,
            tx_mm=np.clip(tx, -3.5, 2.5),
            ty_mm=np.clip(ty, -3.5, 3.5),
            tz_mm=np.clip(tz, -3.0, 2.5),
            roll_deg=np.clip(roll, -3.5, 3.5),
            pitch_deg=np.clip(pitch, -4.2, 3.5),
            yaw_deg=np.clip(yaw, -4.2, 4.2),
        )
        foot_norm_step = np.clip(pose_mm / scale_vec, -1.0, 1.0)

        # Construct realistic closed-loop sensor frame from actual `prev_action` IK + broad anchor/posture offsets
        cur_pts_mm = stand_pts_mm[None, :, :] + (prev_action * scale_vec).reshape(n, 4, 3)
        q_ik_t, valid_ik_t = fb.inverse(torch.from_numpy(cur_pts_mm).to(device=fb.device, dtype=torch.float64))
        q_ik_deg = np.rad2deg(q_ik_t.reshape(n, 12).detach().cpu().numpy())
        valid_ik = valid_ik_t.reshape(n, -1).all(axis=1)[:, None]
        cmd_deg = np.where(valid_ik, q_ik_deg, stand_deg_arr) + posture_offset_deg + rng.normal(0.0, 1.5, size=(n, 12))
        meas_deg = cmd_deg - cmd_minus_meas_deg
        vel_deg_s = rng.normal(0.0, 8.0, size=(n, 12)) + chatter_deg * 6.0 * np.sin(ph[:, None] * 6.0)

        quats = _quat_wxyz_from_rpy_deg(step_roll_deg, step_pitch_deg, np.zeros(n))
        # Gravity in body frame for accelerometer
        w, x, y, z = quats[:, 0], quats[:, 1], quats[:, 2], quats[:, 3]
        pg_x = -2.0 * (x * z - w * y)
        pg_y = -2.0 * (y * z + w * x)
        pg_z = 1.0 - 2.0 * (w * w + z * z)
        accel = np.stack([-pg_x, -pg_y, -pg_z], axis=-1) * 9.80665 + step_jerk

        rad = math.pi / 180.0
        q_delta = np.clip((meas_deg - np.array(STAND_ANGLES_DEG)[None, :]) * rad, -2.5, 2.5)
        q_err = np.where(chatter_enabled[:, None], np.clip((cmd_deg - meas_deg) * rad, -0.6, 0.6), 0.0)
        q_chat = np.where(chatter_enabled[:, None], np.clip(chatter_deg * rad, 0.0, 0.4), 0.0)
        q_vel = np.clip(vel_deg_s * rad, -8.0, 8.0)

        pg_feat = np.where(
            imu_enabled[:, None],
            np.clip(np.stack([pg_x, pg_y, pg_z], axis=-1), -1.0, 1.0),
            np.array([[0.0, 0.0, -1.0]]),
        )
        gyro_feat = np.where(imu_enabled[:, None], np.clip(step_gyro, -6.0, 6.0), 0.0)
        aj_feat = np.where(imu_enabled[:, None], np.clip(step_jerk / 9.80665, -3.0, 3.0), 0.0)

        ctx = np.stack(
            [
                person_yaw,
                person_pitch,
                person_conf,
                known_face,
                motion_mag,
                listening,
                step_mic_rms,
                speaking,
                step_speech_rms,
                boredom,
                s_ph,
            ],
            axis=-1,
        )
        frame = np.concatenate(
            [q_delta, q_err, q_chat, q_vel, pg_feat, gyro_feat, aj_feat, ctx, prev_action],
            axis=-1,
        ).astype(np.float32)
        chronological_frames.append(frame)

        # Advance prev_action smoothly toward target
        prev_action = 0.35 * prev_action + 0.65 * foot_norm_step
        if step_idx == PRESENCE_SAMPLES - 1:
            target_foot_norm = foot_norm_step.astype(np.float32)

    # Causal history order matches `PresenceObservationHistory.push_and_project`: newest frame [0] first!
    obs_windows = np.concatenate(list(reversed(chronological_frames)), axis=-1)

    # Expression labels:
    # 0: idle, 1: listening, 2: talk_happy, 3: curious, 4: bored, 5: surprised
    shove_mag = np.hypot(body_roll_deg, body_pitch_deg) + np.linalg.norm(gyro_rad_s, axis=-1) * 12.0
    expr_labels = np.zeros(n, dtype=np.int64)
    expr_labels = np.where(boredom >= 0.25, 4, expr_labels)
    expr_labels = np.where((person_conf >= 0.45) | (motion_mag >= 0.40), 3, expr_labels)
    expr_labels = np.where(speaking >= 0.5, 2, expr_labels)
    expr_labels = np.where(listening >= 0.5, 1, expr_labels)
    expr_labels = np.where(imu_enabled & (shove_mag >= 11.5), 5, expr_labels)

    return (
        torch.from_numpy(obs_windows),
        torch.from_numpy(target_foot_norm),
        torch.from_numpy(target_comp_norm),
        torch.from_numpy(expr_labels),
    )


def export_presence_onnx(model: PresenceMLP, out_path: Path) -> dict:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cpu_model = PresenceMLP().eval()
    cpu_model.load_state_dict(model.cpu().state_dict())
    dummy = torch.zeros((1, PRESENCE_OBS_SIZE), dtype=torch.float32)

    torch.onnx.export(
        cpu_model,
        dummy,
        str(out_path),
        input_names=["obs"],
        output_names=["actions"],
        opset_version=17,
        do_constant_folding=True,
        dynamo=False,
    )
    proto = onnx.load(str(out_path))
    meta = {
        "ainekio_schema": PRESENCE_SCHEMA,
        "ainekio_foot_scale_mm": ",".join(f"{v:g}" for v in PRESENCE_FOOT_SCALE_MM),
        "ainekio_compliance_step_mm": f"{PRESENCE_COMPLIANCE_STEP_MM:g}",
        "ainekio_hidden_dims": ",".join(str(v) for v in PRESENCE_HIDDEN_DIMS),
        "ainekio_expressions": ",".join(EXPRESSION_MODES),
    }
    existing = {p.key: p for p in proto.metadata_props}
    for k, v in meta.items():
        if k in existing:
            existing[k].value = v
        else:
            prop = proto.metadata_props.add()
            prop.key = k
            prop.value = v
    onnx.save(proto, str(out_path))
    return presence_model_footprint()


def qualify_in_mujoco(policy_path: Path, manifold: PoseManifold) -> dict:
    """Run real 500 Hz MuJoCo physics closed-loop qualification across System 3 capabilities."""
    import mujoco
    from gateway.neural_gait.environment import EnvironmentConfig, build_xml

    actor = PresenceActor(policy_path)
    env_cfg = EnvironmentConfig()
    xml = build_xml(env_cfg)
    mj_model = mujoco.MjModel.from_xml_string(xml)
    mj_data = mujoco.MjData(mj_model)

    stand_deg = list(STAND_ANGLES_DEG)
    stand_rad = torch.tensor(stand_deg, dtype=torch.float64, device=manifold.body.device).reshape(1, 4, 3) * (
        math.pi / 180.0
    )
    _, stand_pose_norm = manifold.project_angles_deg(stand_deg)
    stand_pts_t, _ = manifold.body.forward(stand_rad)
    stand_feet_mm = (stand_pts_t - manifold.body.origin.unsqueeze(0)).reshape(12).detach().cpu().numpy()
    pose_scale = np.array((95.0, 155.0, 180.0) * 4, dtype=np.float64)

    q_dof_idx = [mj_model.jnt_qposadr[mj_model. actuator_trnid[i, 0]] for i in range(12)]
    v_dof_idx = [mj_model.jnt_dofadr[mj_model.actuator_trnid[i, 0]] for i in range(12)]

    def _reset_robot(shear_deg: float = 0.0):
        mujoco.mj_resetData(mj_model, mj_data)
        init_deg = list(stand_deg)
        if shear_deg != 0.0:
            # Opposing left/right shoulder + front/rear crank shear on high-friction ground
            for leg_i in range(4):
                init_deg[leg_i * 3 + 0] += shear_deg if leg_i in (0, 2) else -shear_deg
                init_deg[leg_i * 3 + 2] += 0.6 * shear_deg if leg_i < 2 else -0.6 * shear_deg
        q43 = torch.tensor(init_deg, dtype=torch.float64, device=manifold.body.device).reshape(1, 4, 3) * (
            math.pi / 180.0
        )
        q20 = full_four_bar_qpos20(manifold.body, q43)[0].detach().cpu().numpy()
        mj_data.qpos[0:3] = [0.0, 0.0, 0.145]
        mj_data.qpos[3:7] = [1.0, 0.0, 0.0, 0.0]
        mj_data.qpos[7:27] = q20
        mj_data.ctrl[:12] = np.deg2rad(stand_deg)
        mujoco.mj_forward(mj_model, mj_data)
        for _ in range(150):  # 0.3s settle onto floor
            mujoco.mj_step(mj_model, mj_data)

    def _run_episode(
        *,
        seconds: float,
        enable_presence: bool,
        shear_deg: float = 0.0,
        imu_enabled: bool = True,
        chatter_relief: bool = True,
        person_yaw: float = 0.0,
        person_pitch: float = 0.0,
        person_conf: float = 0.0,
        listening: float = 0.0,
        speaking: float = 0.0,
        boredom: float = 0.0,
        shove_at_s: float | None = None,
    ) -> dict:
        _reset_robot(shear_deg=shear_deg)
        if shear_deg != 0.0:
            # Statue mode holds mismatched sheared target fighting ground friction
            sheared_cmd = list(stand_deg)
            for leg_i in range(4):
                sheared_cmd[leg_i * 3 + 0] -= shear_deg if leg_i in (0, 2) else -shear_deg
            base_cmd_rad = np.deg2rad(sheared_cmd)
        else:
            base_cmd_rad = np.deg2rad(stand_deg)

        mj_data.ctrl[:12] = base_cmd_rad.copy()
        for _ in range(100):
            mujoco.mj_step(mj_model, mj_data)
        standing_z = float(mj_data.qpos[2])

        hist = PresenceObservationHistory()
        prev_foot_norm = [0.0] * 12
        compliance_trim_mm = [0.0] * 12
        cmd_q_rad = torch.from_numpy(base_cmd_rad.reshape(1, 12)).to(
            dtype=torch.float64, device=manifold.body.device
        )
        base_pose_feet_mm, _ = manifold.body.forward(cmd_q_rad.reshape(1, 4, 3))
        anchor_feet_mm = (base_pose_feet_mm - manifold.body.origin.unsqueeze(0)).reshape(12).detach().cpu().numpy()

        steps_20hz = int(round(seconds / PRESENCE_INTERVAL_S))
        substeps = max(1, int(round(PRESENCE_INTERVAL_S / mj_model.opt.timestep)))

        torques = []
        track_errs = []
        pitches = []
        yaws = []
        tilts = []
        expressions = []
        shove_expressions = []
        fell = False
        shoved = False

        for tick in range(steps_20hz):
            t_s = tick * PRESENCE_INTERVAL_S
            if shove_at_s is not None and not shoved and t_s >= shove_at_s:
                mj_data.qvel[1] += 0.34  # lateral shove
                mj_data.qvel[3] += 2.35  # sharp roll angular impulse
                shoved = True

            meas_rad = np.array([mj_data.qpos[idx] for idx in q_dof_idx], dtype=np.float64)
            vel_rad_s = np.array([mj_data.qvel[idx] for idx in v_dof_idx], dtype=np.float64)
            cmd_deg = np.rad2deg(mj_data.ctrl[:12]).tolist()
            meas_deg = np.rad2deg(meas_rad).tolist()
            vel_deg_s = np.rad2deg(vel_rad_s).tolist()
            err_deg = [abs(c - m) for c, m in zip(cmd_deg, meas_deg)]
            chat_deg = [e * 0.45 for e in err_deg]

            quat = mj_data.qpos[3:7].tolist()
            gyro = mj_data.qvel[3:6].tolist()
            w, x, y, z = quat
            up_z = max(-1.0, min(1.0, 1.0 - 2.0 * (x * x + y * y)))
            tilt_deg = math.degrees(math.acos(up_z))
            tilts.append(tilt_deg)
            if tilt_deg > 52.0 or mj_data.qpos[2] < max(0.036, standing_z - 0.025):
                fell = True

            sp_rms = (0.55 + 0.40 * math.sin(t_s * 9.5)) if speaking > 0.5 else 0.0
            mc_rms = (0.35 + 0.20 * math.cos(t_s * 6.0)) if listening > 0.5 else 0.0

            if enable_presence:
                feat = assemble_presence_features(
                    measured_deg=meas_deg,
                    commanded_deg=cmd_deg,
                    velocity_deg_s=vel_deg_s,
                    chatter_deg=chat_deg,
                    usable_flags=[True] * 12,
                    orientation_wxyz=quat,
                    angular_rate_rad_s=gyro,
                    acceleration_m_s2=[0.0, 0.0, 9.80665],
                    imu_enabled=imu_enabled,
                    chatter_relief_enabled=chatter_relief,
                    person_yaw=person_yaw,
                    person_pitch=person_pitch,
                    person_conf=person_conf,
                    known_face=1.0 if person_conf > 0.7 else 0.0,
                    motion_mag=0.4 if person_conf > 0.0 else 0.0,
                    listening_active=listening,
                    mic_rms=mc_rms,
                    speaking_active=speaking,
                    speech_rms=sp_rms,
                    boredom_level=boredom,
                    phase_rad=t_s * 2.2,
                    previous_foot_action=prev_foot_norm,
                )
                obs_vec = hist.push_and_project(t_s, feat)
                foot_norm, foot_delta_mm, comp_step_mm, expr, _ = actor.infer(obs_vec)
                prev_foot_norm = foot_norm
                compliance_trim_mm = update_compliance_trim_mm(
                    compliance_trim_mm,
                    comp_step_mm,
                    enabled=chatter_relief,
                )
                expressions.append(expr)
                if shove_at_s is not None and shove_at_s <= t_s <= shove_at_s + 0.35:
                    shove_expressions.append(expr)
                desired_feet_mm = (
                    anchor_feet_mm
                    + np.asarray(foot_delta_mm, dtype=np.float64)
                    + np.asarray(compliance_trim_mm, dtype=np.float64)
                )
                pose_act = np.clip(desired_feet_mm / pose_scale, -1.0, 1.0).tolist()
                cmd_q_rad, _, _ = manifold.step_host_command(pose_act, cmd_q_rad, speed_scale=1.0)
                mj_data.ctrl[:12] = cmd_q_rad[0].detach().cpu().numpy()

            for _ in range(substeps):
                mujoco.mj_step(mj_model, mj_data)

            torques.append(float(np.linalg.norm(mj_data.actuator_force[:12])))
            meas_after = np.rad2deg([mj_data.qpos[idx] for idx in q_dof_idx])
            cmd_after = np.rad2deg(mj_data.ctrl[:12])
            track_errs.append(float(np.mean(np.abs(cmd_after - meas_after))))

            qw, qx, qy, qz = mj_data.qpos[3:7]
            pitch_deg = math.degrees(math.asin(max(-1.0, min(1.0, 2.0 * (qw * qy - qz * qx)))))
            yaw_deg = math.degrees(math.atan2(2.0 * (qw * qz + qx * qy), 1.0 - 2.0 * (qy * qy + qz * qz)))
            pitches.append(pitch_deg)
            yaws.append(yaw_deg)

        result = {
            "fell": fell,
            "mean_torque_nm": round(float(np.mean(torques[10:])), 4),
            "mean_tracking_error_deg": round(float(np.mean(track_errs[10:])), 3),
            "peak_tilt_deg": round(float(np.max(tilts)), 2),
            "mean_yaw_deg": round(float(np.mean(yaws[-15:])), 2),
            "mean_pitch_deg": round(float(np.mean(pitches[-15:])), 2),
            "pitch_span_deg": round(float(np.max(pitches[5:]) - np.min(pitches[5:])), 2),
            "yaw_span_deg": round(float(np.max(yaws[5:]) - np.min(yaws[5:])), 2),
            "dominant_expression": max(set(expressions), key=expressions.count) if expressions else "none",
        }
        if shove_expressions:
            result["shove_window_expressions"] = sorted(set(shove_expressions))
        return result

    orig_friction = mj_model.geom_friction.copy()
    orig_pair = mj_model.pair_friction.copy() if mj_model.npair > 0 else None
    mj_model.geom_friction[:, 0] = 2.6  # High-grip carpet pile where statue servos snag, buzz & drain battery
    if orig_pair is not None:
        mj_model.pair_friction[:, 0] = 2.6
        mj_model.pair_friction[:, 1] = 2.6
    statue_shear = _run_episode(seconds=2.5, enable_presence=False, shear_deg=9.0)
    compliant_shear = _run_episode(seconds=2.5, enable_presence=True, shear_deg=9.0, chatter_relief=True)
    mj_model.geom_friction[:] = orig_friction
    if orig_pair is not None:
        mj_model.pair_friction[:] = orig_pair

    gaze_left = _run_episode(seconds=2.0, enable_presence=True, person_yaw=0.85, person_pitch=0.4, person_conf=0.9)
    gaze_right = _run_episode(seconds=2.0, enable_presence=True, person_yaw=-0.85, person_pitch=-0.3, person_conf=0.9)
    listen_ep = _run_episode(seconds=2.0, enable_presence=True, listening=1.0, person_yaw=0.4, person_conf=0.8)
    talk_ep = _run_episode(seconds=2.5, enable_presence=True, speaking=1.0, person_conf=0.7)
    bored_ep = _run_episode(seconds=3.0, enable_presence=True, boredom=0.9)
    shove_ep = _run_episode(seconds=2.5, enable_presence=True, imu_enabled=True, shove_at_s=0.4)
    shove_masked_ep = _run_episode(seconds=2.5, enable_presence=True, imu_enabled=False, shove_at_s=0.4)
    listen_imu_off_ep = _run_episode(
        seconds=4.0,
        enable_presence=True,
        imu_enabled=False,
        listening=1.0,
        person_yaw=-0.75,
        person_pitch=0.35,
        person_conf=0.95,
    )

    # Closed-loop stability audit starting from the exact asymmetric post-stand posture (`seq=455`)
    # with `imu_enabled=False`, `listening=1.0`, `person_conf=0.95`, and perturbed `prev_foot_norm`.
    offstand_init_deg = [11.2, -3.8, -27.7, -5.9, 0.8, -19.5, -8.0, -2.2, -29.6, -1.2, 5.0, -13.9]
    cl_hist = PresenceObservationHistory()
    cl_prev_norm = [0.75, -0.75, 0.75] * 4
    cl_trim_mm = [0.0] * 12
    cl_cmd_q = torch.deg2rad(torch.tensor(offstand_init_deg, dtype=torch.float64, device=manifold.body.device)).reshape(1, 12)
    cl_meas_deg = list(offstand_init_deg)
    cl_exprs: list[str] = []
    cl_max_dev_deg = 0.0
    for step_i in range(120):
        t_cl = step_i * PRESENCE_INTERVAL_S
        cl_cmd_deg = np.rad2deg(cl_cmd_q[0].detach().cpu().numpy()).tolist()
        feat_cl = assemble_presence_features(
            measured_deg=cl_meas_deg,
            commanded_deg=cl_cmd_deg,
            velocity_deg_s=[0.0] * 12,
            chatter_deg=[0.2] * 12,
            usable_flags=[True] * 12,
            orientation_wxyz=[1.0, 0.0, 0.0, 0.0],
            angular_rate_rad_s=[0.0, 0.0, 0.0],
            acceleration_m_s2=[0.0, 0.0, 9.80665],
            imu_enabled=False,
            chatter_relief_enabled=True,
            person_yaw=-0.80,
            person_pitch=0.35,
            person_conf=0.95,
            known_face=1.0,
            motion_mag=0.5,
            listening_active=1.0,
            mic_rms=0.55,
            speaking_active=0.0,
            speech_rms=0.0,
            boredom_level=0.0,
            phase_rad=t_cl * 2.2,
            previous_foot_action=cl_prev_norm,
        )
        obs_cl = cl_hist.push_and_project(t_cl, feat_cl)
        cl_prev_norm, cl_foot_mm, cl_comp_mm, expr_cl, _ = actor.infer(obs_cl)
        cl_exprs.append(expr_cl)
        cl_trim_mm = update_compliance_trim_mm(cl_trim_mm, cl_comp_mm, enabled=True)
        des_mm = stand_feet_mm + np.asarray(cl_foot_mm) + np.asarray(cl_trim_mm)
        p_act = np.clip(des_mm / pose_scale, -1.0, 1.0).tolist()
        cl_cmd_q, _, _ = manifold.step_host_command(p_act, cl_cmd_q, speed_scale=1.0)
        next_cmd_deg = np.rad2deg(cl_cmd_q[0].detach().cpu().numpy()).tolist()
        cl_meas_deg = [0.25 * m + 0.75 * c for m, c in zip(cl_meas_deg, next_cmd_deg)]
        if step_i >= 20:
            cl_max_dev_deg = max(
                cl_max_dev_deg,
                max(abs(c - s) for c, s in zip(next_cmd_deg, stand_deg)),
            )

    return {
        "statue_shear": statue_shear,
        "compliant_shear": compliant_shear,
        "shear_tracking_error_reduction_pct": round(
            100.0 * (1.0 - compliant_shear["mean_tracking_error_deg"] / max(1e-6, statue_shear["mean_tracking_error_deg"])),
            1,
        ),
        "shear_torque_reduction_pct": round(
            100.0 * (1.0 - compliant_shear["mean_torque_nm"] / max(1e-6, statue_shear["mean_torque_nm"])),
            1,
        ),
        "gaze_left": gaze_left,
        "gaze_right": gaze_right,
        "listening": listen_ep,
        "listening_imu_off": listen_imu_off_ep,
        "talking": talk_ep,
        "boredom": bored_ep,
        "shove_imu_on": shove_ep,
        "shove_imu_off": shove_masked_ep,
        "closed_loop_offstand_max_dev_deg": round(cl_max_dev_deg, 2),
        "closed_loop_imu_off_surprised_count": cl_exprs.count("surprised"),
        "all_upright": not any(
            ep["fell"]
            for ep in (compliant_shear, gaze_left, gaze_right, listen_ep, listen_imu_off_ep, talk_ep, bored_ep, shove_ep)
        ),
    }


def train_and_export(
    output_dir: Path = DEFAULT_ACTIVE_POLICY.parent,
    *,
    num_sequences: int = 72000,
    epochs: int = 32,
    batch_size: int = 512,
    lr: float = 2.5e-3,
    seed: int = 42,
) -> dict:
    t0 = time.monotonic()
    torch.manual_seed(seed)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    manifold = PoseManifold()

    obs_all, foot_all, comp_all, expr_all = build_presence_dataset(manifold, num_sequences=num_sequences, seed=seed)
    n_val = max(2048, int(0.08 * len(obs_all)))
    n_train = len(obs_all) - n_val

    train_obs, val_obs = obs_all[:n_train].to(device), obs_all[n_train:].to(device)
    train_foot, val_foot = foot_all[:n_train].to(device), foot_all[n_train:].to(device)
    train_comp, val_comp = comp_all[:n_train].to(device), comp_all[n_train:].to(device)
    train_expr, val_expr = expr_all[:n_train].to(device), expr_all[n_train:].to(device)

    model = PresenceMLP().to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=epochs, eta_min=1e-4)

    comp_end = PRESENCE_FOOT_DIM + PRESENCE_COMPLIANCE_DIM

    for _epoch in range(epochs):
        model.train()
        perm = torch.randperm(n_train, device=device)
        for i in range(0, n_train, batch_size):
            idx = perm[i : i + batch_size]
            pred = model(train_obs[idx])
            pred_foot = pred[:, :PRESENCE_FOOT_DIM]
            pred_comp = pred[:, PRESENCE_FOOT_DIM:comp_end]
            pred_expr = pred[:, comp_end:]
            loss_foot = F.mse_loss(pred_foot, train_foot[idx])
            loss_comp = F.mse_loss(pred_comp, train_comp[idx])
            loss_expr = 0.15 * F.cross_entropy(pred_expr, train_expr[idx])
            loss = loss_foot + loss_comp + loss_expr
            opt.zero_grad(set_to_none=True)
            loss.backward()
            opt.step()
        sched.step()

    model.eval()
    with torch.no_grad():
        vpred = model(val_obs)
        val_foot_rmse = float(torch.sqrt(F.mse_loss(vpred[:, :PRESENCE_FOOT_DIM], val_foot)).item())
        val_comp_rmse = float(torch.sqrt(F.mse_loss(vpred[:, PRESENCE_FOOT_DIM:comp_end], val_comp)).item())
        val_expr_acc = float((vpred[:, comp_end:].argmax(dim=-1) == val_expr).float().mean().item())

    policy_path = output_dir / "policy.onnx"
    footprint = export_presence_onnx(model, policy_path)
    qualification = qualify_in_mujoco(policy_path, PoseManifold(device="cpu"))
    summary = {
        "schema": PRESENCE_SCHEMA,
        "device": str(device),
        "num_sequences": num_sequences,
        "epochs": epochs,
        "val_foot_rmse_norm": round(val_foot_rmse, 5),
        "val_compliance_rmse_norm": round(val_comp_rmse, 5),
        "val_expression_accuracy": round(val_expr_acc, 4),
        "footprint": footprint,
        "mujoco_500hz_qualification": qualification,
        "duration_s": round(time.monotonic() - t0, 2),
        "policy_path": str(policy_path),
    }
    (output_dir / "training-summary.json").write_text(json.dumps(summary, indent=2))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Train and qualify System 3 Autonomic Presence ONNX policy")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_ACTIVE_POLICY.parent)
    parser.add_argument("--sequences", type=int, default=72000)
    parser.add_argument("--epochs", type=int, default=32)
    args = parser.parse_args()
    summary = train_and_export(args.output_dir, num_sequences=args.sequences, epochs=args.epochs)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
