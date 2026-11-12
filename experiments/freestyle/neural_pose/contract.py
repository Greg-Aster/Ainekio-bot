"""Shared simulation and physical 50 Hz observation/action contract for Neural Pose & Emote."""
from __future__ import annotations

from collections import deque
import math

POSE_SCHEMA = "ainekio-neural-pose-v1"
POSE_FEATURES = 86
POSE_SAMPLES = 15
POSE_INTERVAL_S = 0.02
POSE_OBS_SIZE = POSE_FEATURES * POSE_SAMPLES
POSE_FOOT_SCALE_MM = (95.0, 155.0, 180.0)

LEGS = ("rear_left", "rear_right", "front_left", "front_right")
JOINTS = tuple(
    f"{leg}_{axis}" for leg in LEGS for axis in ("shoulder", "carrier", "crank")
)


def projected_gravity_from_wxyz(orientation_wxyz):
    """Match TensorSensors (-gravity(q)) and microduck.c [30..32] exactly."""
    w, x, y, z = (float(v) for v in orientation_wxyz)
    return [
        -2.0 * (x * z - w * y),
        -2.0 * (y * z + w * x),
        1.0 - 2.0 * (w * w + z * z),
    ]


def pose_foot_offsets(action, scale_mm=POSE_FOOT_SCALE_MM) -> list[float]:
    """Scale 12 normalized [-1, 1] policy outputs to 12 flattened foot offsets (mm)."""
    if len(action) != 12:
        raise ValueError("Expected 12 normalized pose actions")
    sx, sy, sz = (float(v) for v in scale_mm)
    scales = (sx, sy, sz) * 4
    result = []
    for raw, scale in zip(action, scales):
        val = float(raw)
        if not math.isfinite(val):
            raise ValueError("Nonfinite neural pose action")
        val = max(-1.0, min(1.0, val))
        result.append(val * scale)
    return result


def assemble_pose_features(
    *,
    measured_deg,
    commanded_deg,
    velocity_deg_s,
    usable_flags,
    orientation_wxyz,
    angular_rate_rad_s,
    acceleration_m_s2,
    goal_joint_deg,
    goal_foot_norm,
    leg_support,
    speed_scale,
    previous_action,
):
    """Build one 86-float 50 Hz proprioceptive + goal frame."""
    rad = math.pi / 180.0
    joint_rad = []
    joint_vel = []
    usable_vec = []
    for idx in range(12):
        ok = bool(usable_flags[idx]) and isinstance(measured_deg[idx], (int, float)) and math.isfinite(measured_deg[idx])
        fallback = commanded_deg[idx] if isinstance(commanded_deg[idx], (int, float)) and math.isfinite(commanded_deg[idx]) else 0.0
        deg = float(measured_deg[idx]) if ok else float(fallback)
        vel = float(velocity_deg_s[idx]) if (ok and isinstance(velocity_deg_s[idx], (int, float)) and math.isfinite(velocity_deg_s[idx])) else 0.0
        joint_rad.append(deg * rad)
        joint_vel.append(vel * rad)
        usable_vec.append(1.0 if ok else 0.0)

    gyro = [float(v) for v in angular_rate_rad_s]
    accel_g = [float(v) / 9.81 for v in acceleration_m_s2]
    proj_grav = projected_gravity_from_wxyz(orientation_wxyz)
    goal_rad = [float(v) * rad for v in goal_joint_deg]
    foot_norm = [max(-1.0, min(1.0, float(v))) for v in goal_foot_norm]
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
        + goal_rad
        + foot_norm
        + support
        + [spd]
        + prev
    )
    if len(row) != POSE_FEATURES or not all(math.isfinite(v) for v in row):
        raise ValueError("Invalid 86-float neural pose feature row")
    return row


class PoseObservationHistory:
    """Causal 15-frame (300 ms @ 20 ms) ring buffer matching GPU history roll."""

    def __init__(self):
        self._samples: deque[tuple[float, list[float]]] = deque(maxlen=64)

    def reset(self):
        self._samples.clear()

    def push_and_project(self, timestamp_s: float, features: list[float]) -> list[float]:
        if len(features) != POSE_FEATURES:
            raise ValueError(f"Expected {POSE_FEATURES} features, got {len(features)}")
        t = float(timestamp_s)
        if self._samples and t < self._samples[-1][0]:
            self._samples.clear()
        if self._samples and t == self._samples[-1][0]:
            self._samples[-1] = (t, list(features))
        else:
            self._samples.append((t, list(features)))
        cutoff = t - POSE_SAMPLES * POSE_INTERVAL_S - 0.1
        while len(self._samples) > 1 and self._samples[0][0] < cutoff:
            self._samples.popleft()
        out: list[float] = []
        for idx in range(POSE_SAMPLES):
            target_t = t - idx * POSE_INTERVAL_S + 1e-9
            matched = None
            for sample_t, row in reversed(self._samples):
                if sample_t <= target_t:
                    matched = row
                    break
            if matched is None:
                # Before history fills on step 0, pad with earliest real acquired frame
                # (matches GPU reset priming with stationary first scan rather than raw zeros).
                matched = self._samples[0][1]
            out.extend(matched)
        return out
