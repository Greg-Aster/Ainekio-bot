"""Shared simulation and physical 50 Hz observation/action contract for V1 8-DOF Neural Pose.

Frozen map-1 joint order (matching Slave/software/models/v1-8servo/include/ainekio/v1_model.h):
  0: R1 (front_right_hip)    [-45, +45] deg
  1: R2 (rear_right_hip)     [-45, +45] deg
  2: L1 (front_left_hip)     [-45, +45] deg
  3: L2 (rear_left_hip)      [-45, +45] deg
  4: R4 (rear_right_knee)    [-15, +115] deg
  5: R3 (front_right_knee)   [-15, +115] deg
  6: L3 (front_left_knee)    [-15, +115] deg
  7: L4 (rear_left_knee)     [-15, +115] deg

All 8 joints have +1 left-right mirror sign under FR<->FL and RR<->RL swap.
"""
from __future__ import annotations

from collections import deque
import math

V1_POSE_SCHEMA = "ainekio-v1-neural-pose-v1"
V1_POSE_FEATURES = 54
V1_POSE_SAMPLES = 15
V1_POSE_INTERVAL_S = 0.02
V1_POSE_OBS_SIZE = V1_POSE_FEATURES * V1_POSE_SAMPLES  # 810
V1_POSE_GOAL_SLICE = slice(33, 41)  # newest frame normalized goal targets in [-1, 1]

V1_POSE_LEGS = ("front_right", "rear_right", "front_left", "rear_left")
V1_POSE_JOINTS = (
    "front_right_hip",
    "rear_right_hip",
    "front_left_hip",
    "rear_left_hip",
    "rear_right_knee",
    "front_right_knee",
    "front_left_knee",
    "rear_left_knee",
)

# Exact affine mapping between mechanical limits and [-1, +1]:
#   hips  [-45, +45] deg  -> center=0,  half_span=45
#   knees [-15, +115] deg -> center=50, half_span=65
V1_JOINT_CENTER_DEG = (0.0, 0.0, 0.0, 0.0, 50.0, 50.0, 50.0, 50.0)
V1_JOINT_HALF_SPAN_DEG = (45.0, 45.0, 45.0, 45.0, 65.0, 65.0, 65.0, 65.0)
V1_JOINT_MIN_DEG = (-45.0, -45.0, -45.0, -45.0, -15.0, -15.0, -15.0, -15.0)
V1_JOINT_MAX_DEG = (45.0, 45.0, 45.0, 45.0, 115.0, 115.0, 115.0, 115.0)

# Canonical V1 postures (exact match to Slave/software/models/v1-8servo/v1_motion.c)
V1_CANONICAL_POSTURES_DEG: dict[str, tuple[float, ...]] = {
    "stand":    (0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
    "crouch":   (0.0, 0.0, 0.0, 0.0, 42.0, 42.0, 42.0, 42.0),
    "lay_down": (0.0, 0.0, 0.0, 0.0, 90.0, 90.0, 90.0, 90.0),
    "sit":      (10.0, -15.0, 10.0, -15.0, 65.0, -5.0, -5.0, 65.0),
    "bow":      (15.0, -5.0, 15.0, -5.0, 5.0, 58.0, 58.0, 5.0),
    "stretch":  (28.0, -28.0, 28.0, -28.0, 22.0, 22.0, 22.0, 22.0),
    "wave_fr":  (35.0, -10.0, -8.0, -10.0, 15.0, 92.0, 8.0, 15.0),
    "wave_fl":  (-8.0, -10.0, 35.0, -10.0, 15.0, 8.0, 92.0, 15.0),
}
V1_CANONICAL_SUPPORT: dict[str, tuple[float, float, float, float]] = {
    "stand":    (1.0, 1.0, 1.0, 1.0),
    "crouch":   (1.0, 1.0, 1.0, 1.0),
    "lay_down": (1.0, 1.0, 1.0, 1.0),
    "sit":      (1.0, 1.0, 1.0, 1.0),
    "bow":      (1.0, 1.0, 1.0, 1.0),
    "stretch":  (1.0, 1.0, 1.0, 1.0),
    "wave_fr":  (0.0, 1.0, 1.0, 1.0),
    "wave_fl":  (1.0, 1.0, 0.0, 1.0),
}


def deg_to_norm(angles_deg) -> list[float]:
    if len(angles_deg) != 8:
        raise ValueError(f"Expected 8 V1 joint angles, got {len(angles_deg)}")
    return [
        max(-1.0, min(1.0, (float(a) - c) / s))
        for a, c, s in zip(angles_deg, V1_JOINT_CENTER_DEG, V1_JOINT_HALF_SPAN_DEG)
    ]


def norm_to_deg(action_norm) -> list[float]:
    if len(action_norm) != 8:
        raise ValueError(f"Expected 8 normalized V1 actions, got {len(action_norm)}")
    out = []
    for raw, c, s, lo, hi in zip(
        action_norm, V1_JOINT_CENTER_DEG, V1_JOINT_HALF_SPAN_DEG, V1_JOINT_MIN_DEG, V1_JOINT_MAX_DEG
    ):
        val = float(raw)
        if not math.isfinite(val):
            raise ValueError("Nonfinite V1 neural pose action")
        val = max(-1.0, min(1.0, val))
        deg = max(lo, min(hi, c + val * s))
        out.append(deg)
    return out


def projected_gravity_from_wxyz(orientation_wxyz) -> list[float]:
    w, x, y, z = (float(v) for v in orientation_wxyz)
    return [
        -2.0 * (x * z - w * y),
        -2.0 * (y * z + w * x),
        1.0 - 2.0 * (w * w + z * z),
    ]


def assemble_v1_pose_features(
    *,
    measured_deg,
    commanded_deg,
    velocity_deg_s,
    usable_flags,
    orientation_wxyz,
    angular_rate_rad_s,
    acceleration_m_s2,
    goal_joint_deg,
    leg_support,
    speed_scale,
    previous_action,
) -> list[float]:
    """Build one 54-float 50 Hz proprioceptive + goal frame for V1 Neural Pose."""
    rad = math.pi / 180.0
    joint_rad = []
    joint_vel = []
    usable_vec = []
    for idx in range(8):
        ok = (
            bool(usable_flags[idx])
            and isinstance(measured_deg[idx], (int, float))
            and math.isfinite(measured_deg[idx])
        )
        fallback = (
            commanded_deg[idx]
            if isinstance(commanded_deg[idx], (int, float)) and math.isfinite(commanded_deg[idx])
            else 0.0
        )
        deg = float(measured_deg[idx]) if ok else float(fallback)
        vel = (
            float(velocity_deg_s[idx])
            if (ok and isinstance(velocity_deg_s[idx], (int, float)) and math.isfinite(velocity_deg_s[idx]))
            else 0.0
        )
        joint_rad.append(deg * rad)
        joint_vel.append(vel * rad)
        usable_vec.append(1.0 if ok else 0.0)

    gyro = [float(v) for v in angular_rate_rad_s]
    accel_g = [float(v) / 9.81 for v in acceleration_m_s2]
    proj_grav = projected_gravity_from_wxyz(orientation_wxyz)
    goal_norm = deg_to_norm(goal_joint_deg)
    support = [1.0 if float(v) >= 0.5 else 0.0 for v in leg_support]
    spd = max(0.1, min(1.0, float(speed_scale)))
    prev = [max(-1.0, min(1.0, float(v))) for v in previous_action]

    row = (
        joint_rad
        + joint_vel
        + usable_vec
        + gyro
        + accel_g
        + proj_grav
        + goal_norm
        + support
        + [spd]
        + prev
    )
    if len(row) != V1_POSE_FEATURES or not all(math.isfinite(v) for v in row):
        raise ValueError("Invalid 54-float V1 neural pose feature row")
    return row


def v1_pose_mirror_tables() -> tuple[list[int], list[float], list[int], list[float]]:
    """Exact sagittal left-right reflection tables `(obs_perm_810, obs_sign_810, act_perm_8, act_sign_8)`.

    Swaps FR(0,5) <-> FL(2,6) and RR(1,4) <-> RL(3,7).
    All 8 V1 model joints have +1 mirror sign; gyro negates (x, z); accel & proj_grav negate y.
    """
    j_perm = [2, 3, 0, 1, 7, 6, 5, 4]
    j_sign = [1.0] * 8
    leg_perm = [2, 3, 0, 1]  # FR<->FL, RR<->RL

    perm_54 = (
        j_perm
        + [8 + i for i in j_perm]
        + [16 + i for i in j_perm]
        + [24, 25, 26]
        + [27, 28, 29]
        + [30, 31, 32]
        + [33 + i for i in j_perm]
        + [41 + i for i in leg_perm]
        + [45]
        + [46 + i for i in j_perm]
    )
    sign_54 = (
        j_sign
        + j_sign
        + [1.0] * 8
        + [-1.0, 1.0, -1.0]
        + [1.0, -1.0, 1.0]
        + [1.0, -1.0, 1.0]
        + j_sign
        + [1.0] * 4
        + [1.0]
        + j_sign
    )
    obs_perm = [f * V1_POSE_FEATURES + idx for f in range(V1_POSE_SAMPLES) for idx in perm_54]
    obs_sign = sign_54 * V1_POSE_SAMPLES
    return obs_perm, obs_sign, j_perm, j_sign


class V1PoseObservationHistory:
    """Causal 15-frame (300 ms @ 20 ms) ring buffer matching GPU history roll."""

    def __init__(self) -> None:
        self._samples: deque[tuple[float, list[float]]] = deque(maxlen=64)

    def reset(self) -> None:
        self._samples.clear()

    def push_and_project(self, timestamp_s: float, features: list[float]) -> list[float]:
        if len(features) != V1_POSE_FEATURES:
            raise ValueError(f"Expected {V1_POSE_FEATURES} features, got {len(features)}")
        t = float(timestamp_s)
        if self._samples and t < self._samples[-1][0]:
            self._samples.clear()
        if self._samples and t == self._samples[-1][0]:
            self._samples[-1] = (t, list(features))
        else:
            self._samples.append((t, list(features)))
        cutoff = t - V1_POSE_SAMPLES * V1_POSE_INTERVAL_S - 0.1
        while len(self._samples) > 1 and self._samples[0][0] < cutoff:
            self._samples.popleft()
        out: list[float] = []
        for idx in range(V1_POSE_SAMPLES):
            target_t = t - idx * V1_POSE_INTERVAL_S + 1e-9
            matched = None
            for sample_t, row in reversed(self._samples):
                if sample_t <= target_t:
                    matched = row
                    break
            if matched is None:
                matched = self._samples[0][1]
            out.extend(matched)
        return out
