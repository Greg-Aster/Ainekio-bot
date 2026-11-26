"""Freestyle Neural Pose observation, normalization, mirror & posture contract for V3 (v3-12servo).

Schema: "ainekio-v3-neural-pose-v1"
  - 12 joints in canonical map-2 order: [RL(h,a,t), RR(h,a,t), FL(h,a,t), FR(h,a,t)]
  - Exact Option A-1 4-bar limits: shoulder [-30,+30] deg, carrier [-40,+50] deg, crank [-50,+50] deg
  - Every joint has +1 sign under Left<->Right mirror (positive h adducts inward on both sides).
"""
from __future__ import annotations

import math
from typing import Sequence

V3_POSE_SCHEMA = "ainekio-v3-neural-pose-v1"
V3_POSE_JOINTS = 12
V3_POSE_FEATURES = 86  # 12*6 (meas,cmd,vel,usable,goal,prev_act) + 9 (imu) + 4 (support) + 1 (speed)
V3_POSE_SAMPLES = 15
V3_POSE_OBS_SIZE = V3_POSE_FEATURES * V3_POSE_SAMPLES  # 1290

# Feature slice offsets inside a single 86-float frame
SLICE_MEAS = slice(0, 12)
SLICE_CMD = slice(12, 24)
SLICE_VEL = slice(24, 36)
SLICE_USABLE = slice(36, 48)
SLICE_GYRO = slice(48, 51)
SLICE_ACCEL = slice(51, 54)
SLICE_GRAV = slice(54, 57)
SLICE_GOAL = slice(57, 69)
SLICE_SUPPORT = slice(69, 73)
IDX_SPEED = 73
SLICE_PREV_ACT = slice(74, 86)

V3_JOINT_LO_DEG = (-30.0, -40.0, -50.0) * 4
V3_JOINT_HI_DEG = (30.0, 50.0, 50.0) * 4
V3_JOINT_MID_DEG = tuple(0.5 * (lo + hi) for lo, hi in zip(V3_JOINT_LO_DEG, V3_JOINT_HI_DEG))
V3_JOINT_HALF_DEG = tuple(0.5 * (hi - lo) for lo, hi in zip(V3_JOINT_LO_DEG, V3_JOINT_HI_DEG))

# Canonical postures matching Slave/software/models/v3-12servo/v3_motion.c
V3_CANONICAL_POSTURES_DEG: dict[str, tuple[float, ...]] = {
    "stand":    (  0.0,   0.0,   0.0,   0.0,   0.0,   0.0,   0.0,   0.0,   0.0,   0.0,   0.0,   0.0),
    "crouch":   ( -4.0, -22.0,  28.0,  -4.0, -22.0,  28.0,  -4.0, -22.0,  28.0,  -4.0, -22.0,  28.0),
    "lay_down": ( -8.0, -38.0,  46.0,  -8.0, -38.0,  46.0,  -8.0, -38.0,  46.0,  -8.0, -38.0,  46.0),
    "sit":      ( -4.0, -34.0,  42.0,  -4.0, -34.0,  42.0,   0.0,  14.0, -12.0,   0.0,  14.0, -12.0),
    "bow":      (  0.0,  12.0, -10.0,   0.0,  12.0, -10.0,  -4.0, -34.0,  42.0,  -4.0, -34.0,  42.0),
    "stretch":  (  0.0, -18.0, -24.0,   0.0, -18.0, -24.0,   0.0,  24.0,  28.0,   0.0,  24.0,  28.0),
    "wave_fr":  ( -6.0,  -8.0,   8.0,   4.0, -14.0,  16.0,   6.0, -12.0,  14.0, -12.0,  36.0,  42.0),
    "wave_fl":  (  4.0, -14.0,  16.0,  -6.0,  -8.0,   8.0, -12.0,  36.0,  42.0,   6.0, -12.0,  14.0),
}

# Support mask [RL, RR, FL, FR]: 1.0 = supporting leg, 0.0 = lifted/free leg
V3_CANONICAL_SUPPORT: dict[str, tuple[float, float, float, float]] = {
    "stand":    (1.0, 1.0, 1.0, 1.0),
    "crouch":   (1.0, 1.0, 1.0, 1.0),
    "lay_down": (1.0, 1.0, 1.0, 1.0),
    "sit":      (1.0, 1.0, 1.0, 1.0),
    "bow":      (1.0, 1.0, 1.0, 1.0),
    "stretch":  (1.0, 1.0, 1.0, 1.0),
    "wave_fr":  (1.0, 1.0, 1.0, 0.0),
    "wave_fl":  (1.0, 1.0, 0.0, 1.0),
}


def deg_to_norm(angles_deg: Sequence[float]) -> list[float]:
    if len(angles_deg) != V3_POSE_JOINTS:
        raise ValueError(f"Expected {V3_POSE_JOINTS} angles, got {len(angles_deg)}")
    return [
        max(-1.0, min(1.0, (float(a) - m) / h))
        for a, m, h in zip(angles_deg, V3_JOINT_MID_DEG, V3_JOINT_HALF_DEG)
    ]


def norm_to_deg(norm: Sequence[float]) -> list[float]:
    if len(norm) != V3_POSE_JOINTS:
        raise ValueError(f"Expected {V3_POSE_JOINTS} normalized values, got {len(norm)}")
    return [
        max(lo, min(hi, float(v) * h + m))
        for v, lo, hi, m, h in zip(norm, V3_JOINT_LO_DEG, V3_JOINT_HI_DEG, V3_JOINT_MID_DEG, V3_JOINT_HALF_DEG)
    ]


def v3_pose_mirror_tables() -> tuple[list[int], list[float], list[int], list[float]]:
    """Return exact Left<->Right mirror permutation & sign tables for (obs, action)."""
    # RL(0,1,2) <-> RR(3,4,5); FL(6,7,8) <-> FR(9,10,11)
    act_perm = [3, 4, 5, 0, 1, 2, 9, 10, 11, 6, 7, 8]
    act_sign = [1.0] * 12

    frame_perm: list[int] = []
    frame_sign: list[float] = []
    # meas(12), cmd(12), vel(12), usable(12)
    for base in (0, 12, 24, 36):
        frame_perm.extend(base + p for p in act_perm)
        frame_sign.extend(act_sign)
    # gyro(3): [-1, +1, -1]
    frame_perm.extend([48, 49, 50])
    frame_sign.extend([-1.0, 1.0, -1.0])
    # accel_g(3): [+1, -1, +1]
    frame_perm.extend([51, 52, 53])
    frame_sign.extend([1.0, -1.0, 1.0])
    # grav(3): [+1, -1, +1]
    frame_perm.extend([54, 55, 56])
    frame_sign.extend([1.0, -1.0, 1.0])
    # goal(12)
    frame_perm.extend(57 + p for p in act_perm)
    frame_sign.extend(act_sign)
    # support(4): [RL, RR, FL, FR] -> [RR, RL, FR, FL]
    frame_perm.extend([70, 69, 72, 71])
    frame_sign.extend([1.0, 1.0, 1.0, 1.0])
    # speed(1)
    frame_perm.append(73)
    frame_sign.append(1.0)
    # prev_act(12)
    frame_perm.extend(74 + p for p in act_perm)
    frame_sign.extend(act_sign)

    assert len(frame_perm) == V3_POSE_FEATURES
    obs_perm: list[int] = []
    obs_sign: list[float] = []
    for k in range(V3_POSE_SAMPLES):
        off = k * V3_POSE_FEATURES
        obs_perm.extend(off + p for p in frame_perm)
        obs_sign.extend(frame_sign)
    return obs_perm, obs_sign, act_perm, act_sign


def assemble_v3_pose_features(
    *,
    measured_deg: Sequence[float],
    commanded_deg: Sequence[float],
    velocity_deg_s: Sequence[float],
    usable_flags: Sequence[bool],
    orientation_wxyz: Sequence[float],
    angular_rate_rad_s: Sequence[float],
    acceleration_m_s2: Sequence[float],
    goal_joint_deg: Sequence[float],
    leg_support: Sequence[float],
    speed_scale: float,
    previous_action: Sequence[float],
) -> list[float]:
    d2r = math.pi / 180.0
    w, x, y, z = (float(v) for v in orientation_wxyz)
    grav = [-2.0 * (x * z - w * y), -2.0 * (y * z + w * x), 1.0 - 2.0 * (w * w + z * z)]
    accel_g = [max(-4.0, min(4.0, float(a) / 9.81)) for a in acceleration_m_s2]
    row: list[float] = []
    row.extend(float(a) * d2r for a in measured_deg)
    row.extend(float(a) * d2r for a in commanded_deg)
    row.extend(float(v) * d2r for v in velocity_deg_s)
    row.extend(1.0 if u else 0.0 for u in usable_flags)
    row.extend(float(g) for g in angular_rate_rad_s)
    row.extend(accel_g)
    row.extend(grav)
    row.extend(deg_to_norm(goal_joint_deg))
    row.extend(float(s) for s in leg_support)
    row.append(max(0.05, min(1.0, float(speed_scale))))
    row.extend(max(-1.0, min(1.0, float(a))) for a in previous_action)
    assert len(row) == V3_POSE_FEATURES
    return row


class V3PoseObservationHistory:
    """50 Hz causal ring buffer projecting the latest 15 frames (newest at [0..85])."""

    def __init__(self, samples: int = V3_POSE_SAMPLES, period_s: float = 0.02):
        self.samples = samples
        self.period_s = period_s
        self._ring: list[tuple[float, list[float]]] = []

    def reset(self) -> None:
        self._ring.clear()

    def push_and_project(self, timestamp_s: float, row: Sequence[float]) -> list[float]:
        if len(row) != V3_POSE_FEATURES:
            raise ValueError(f"Expected {V3_POSE_FEATURES} features, got {len(row)}")
        if self._ring and timestamp_s < self._ring[-1][0]:
            self._ring.clear()
        self._ring.append((float(timestamp_s), [float(x) for x in row]))
        cutoff = timestamp_s - (self.samples + 2) * self.period_s
        while len(self._ring) > 1 and self._ring[1][0] < cutoff:
            self._ring.pop(0)
        out: list[float] = []
        for idx in range(self.samples):
            target_t = timestamp_s - idx * self.period_s + 1e-9
            matched = None
            for t, feat in reversed(self._ring):
                if t <= target_t:
                    matched = feat
                    break
            out.extend(matched if matched is not None else [0.0] * V3_POSE_FEATURES)
        return out
