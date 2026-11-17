"""Shared 20 Hz simulation, host, and ESP32-P4 observation/action contract for System 3 (Living Presence)."""
from __future__ import annotations

from collections import deque
import math
from typing import Any, Mapping

PRESENCE_SCHEMA = "ainekio-presence-v1"
PRESENCE_FEATURES = 80
PRESENCE_SAMPLES = 4
PRESENCE_INTERVAL_S = 0.05
PRESENCE_OBS_SIZE = PRESENCE_FEATURES * PRESENCE_SAMPLES  # 320 floats
PRESENCE_HIDDEN_DIMS = (128, 96)
PRESENCE_FOOT_DIM = 12
PRESENCE_COMPLIANCE_DIM = 12
PRESENCE_EXPR_DIM = 6
PRESENCE_ACTION_DIM = PRESENCE_FOOT_DIM + PRESENCE_COMPLIANCE_DIM + PRESENCE_EXPR_DIM  # 30 outputs
PRESENCE_FOOT_SCALE_MM = (8.0, 8.0, 8.0)
PRESENCE_COMPLIANCE_STEP_MM = 1.8
PRESENCE_COMPLIANCE_MAX_XY_MM = 3.5
PRESENCE_COMPLIANCE_MAX_Z_MM = 2.0

LEGS = ("rear_left", "rear_right", "front_left", "front_right")
JOINTS = tuple(f"{leg}_{axis}" for leg in LEGS for axis in ("shoulder", "carrier", "crank"))

STAND_ANGLES_DEG = (0.0, 0.94, -21.25) * 4
# Canonical reviewed V2 crouch/rest posture (matches rise.crouch; 0.000 deg linkage error and >18 deg PWM margin).
REST_ANGLES_DEG = (0.0, -23.22, -22.03) * 4
CALM_PASSIVE_DEG = (0.0, 10.0, -44.0) * 4

EXPRESSION_MODES = (
    "idle",
    "listening",
    "talk_happy",
    "curious",
    "bored",
    "surprised",
)

PASSIVE_MODES = ("calm_then_release", "release", "calm_hold")

DEFAULTS: dict[str, Any] = {
    "enabled": True,
    "self_right_enabled": True,
    "chatter_relief_enabled": True,
    "social_gaze_enabled": True,
    "expressions_enabled": True,
    "servo_release_s": 180.0,
    "presence_defers_release": True,
    "passive_mode": "calm_then_release",
}


def presence_model_footprint(
    obs_size: int = PRESENCE_OBS_SIZE,
    hidden_dims: tuple[int, ...] = PRESENCE_HIDDEN_DIMS,
    out_dim: int = PRESENCE_ACTION_DIM,
) -> dict[str, Any]:
    """Compute exact parameter and RAM footprint to verify ESP32-P4 on-chip SRAM compatibility."""
    dims = (obs_size, *hidden_dims, out_dim)
    params = sum(dims[i] * dims[i + 1] + dims[i + 1] for i in range(len(dims) - 1))
    fp32_bytes = params * 4
    fp16_bytes = params * 2
    int8_bytes = params
    activation_floats = max(dims) * 2
    return {
        "schema": PRESENCE_SCHEMA,
        "hidden_dims": list(hidden_dims),
        "obs_size": obs_size,
        "action_dim": out_dim,
        "parameter_count": params,
        "fp32_bytes": fp32_bytes,
        "fp16_bytes": fp16_bytes,
        "int8_bytes": int8_bytes,
        "scratch_bytes": activation_floats * 4,
        # ESP32-P4 has 768 KB internal L2MEM SRAM + 32 MB PSRAM; <256 KB fits comfortably in internal SRAM.
        "p4_internal_sram_fit": (fp32_bytes + activation_floats * 4) <= 262144,
    }


def validate_presence_settings(raw: Mapping[str, Any] | None) -> dict[str, Any]:
    if raw is None:
        return dict(DEFAULTS)
    if not isinstance(raw, Mapping):
        raise ValueError("Presence settings must be an object")
    out = dict(DEFAULTS)
    for key in (
        "enabled",
        "self_right_enabled",
        "chatter_relief_enabled",
        "social_gaze_enabled",
        "expressions_enabled",
        "presence_defers_release",
    ):
        if key in raw:
            if type(raw[key]) is not bool:
                raise ValueError(f"{key} must be true or false")
            out[key] = raw[key]
    if "servo_release_s" in raw:
        val = raw["servo_release_s"]
        if isinstance(val, bool) or not isinstance(val, (int, float)) or not math.isfinite(val):
            raise ValueError("servo_release_s must be a finite number")
        fval = float(val)
        if fval < 0.0 or fval > 86400.0:
            raise ValueError("servo_release_s must be between 0 and 86400")
        out["servo_release_s"] = round(fval, 3)
    if "passive_mode" in raw:
        mode = raw["passive_mode"]
        if not isinstance(mode, str) or mode not in PASSIVE_MODES:
            raise ValueError(f"passive_mode must be one of {', '.join(PASSIVE_MODES)}")
        out["passive_mode"] = mode
    return out


def projected_gravity_from_wxyz(orientation_wxyz) -> list[float]:
    """Match TensorSensors (-gravity(q)) and microduck.c [30..32]: upright level -> [0, 0, -1]."""
    w, x, y, z = (float(v) for v in orientation_wxyz)
    return [
        -2.0 * (x * z - w * y),
        -2.0 * (y * z + w * x),
        1.0 - 2.0 * (w * w + z * z),
    ]


def tilt_roll_pitch_deg_from_wxyz(orientation_wxyz) -> tuple[float, float, float]:
    """Return (tilt_deg, roll_deg, pitch_deg) from body quaternion wxyz."""
    w, x, y, z = (float(v) for v in orientation_wxyz)
    up_x = 2.0 * (x * z - w * y)
    up_y = 2.0 * (y * z + w * x)
    up_z = max(-1.0, min(1.0, 1.0 - 2.0 * (x * x + y * y)))
    tilt_deg = math.degrees(math.acos(up_z))
    roll_deg = math.degrees(math.atan2(up_y, max(1e-6, abs(up_z))))
    pitch_deg = math.degrees(math.atan2(-up_x, max(1e-6, abs(up_z))))
    return tilt_deg, roll_deg, pitch_deg


def presence_foot_offsets(action_12, scale_mm=PRESENCE_FOOT_SCALE_MM) -> list[float]:
    if len(action_12) != PRESENCE_FOOT_DIM:
        raise ValueError(f"Expected {PRESENCE_FOOT_DIM} foot residual outputs")
    sx, sy, sz = (float(v) for v in scale_mm)
    scales = (sx, sy, sz) * 4
    out: list[float] = []
    for raw, scale in zip(action_12, scales):
        val = float(raw)
        if not math.isfinite(val):
            raise ValueError("Nonfinite presence foot residual")
        out.append(max(-1.0, min(1.0, val)) * scale)
    return out


def update_compliance_trim_mm(
    trim_mm: list[float] | tuple[float, ...],
    step_mm: list[float] | tuple[float, ...],
    *,
    enabled: bool = True,
    decay: float = 0.94,
) -> list[float]:
    """Update persistent stance compliance trim (mm) to relieve inter-leg shear without planar windup or sag."""
    if not enabled:
        return [0.0] * PRESENCE_FOOT_DIM
    raw_x = [float(trim_mm[leg * 3 + 0]) * decay + float(step_mm[leg * 3 + 0]) for leg in range(4)]
    raw_y = [float(trim_mm[leg * 3 + 1]) * decay + float(step_mm[leg * 3 + 1]) for leg in range(4)]
    raw_z = [float(trim_mm[leg * 3 + 2]) * 0.88 + float(step_mm[leg * 3 + 2]) for leg in range(4)]
    mean_x = 0.25 * sum(raw_x)
    mean_y = 0.25 * sum(raw_y)
    mean_z = 0.25 * sum(raw_z)
    out: list[float] = []
    for leg in range(4):
        tx = max(-PRESENCE_COMPLIANCE_MAX_XY_MM, min(PRESENCE_COMPLIANCE_MAX_XY_MM, raw_x[leg] - 0.5 * mean_x))
        ty = max(-PRESENCE_COMPLIANCE_MAX_XY_MM, min(PRESENCE_COMPLIANCE_MAX_XY_MM, raw_y[leg] - 0.5 * mean_y))
        tz = max(-PRESENCE_COMPLIANCE_MAX_Z_MM, min(PRESENCE_COMPLIANCE_MAX_Z_MM, raw_z[leg] - mean_z))
        out.extend((tx, ty, tz))
    return out


def assemble_presence_features(
    *,
    measured_deg,
    commanded_deg,
    velocity_deg_s,
    chatter_deg,
    usable_flags,
    orientation_wxyz,
    angular_rate_rad_s,
    acceleration_m_s2,
    imu_enabled: bool,
    chatter_relief_enabled: bool = True,
    person_yaw: float = 0.0,
    person_pitch: float = 0.0,
    person_conf: float = 0.0,
    known_face: float = 0.0,
    motion_mag: float = 0.0,
    listening_active: float = 0.0,
    mic_rms: float = 0.0,
    speaking_active: float = 0.0,
    speech_rms: float = 0.0,
    boredom_level: float = 0.0,
    phase_rad: float = 0.0,
    previous_foot_action=None,
) -> list[float]:
    """Assemble one 80-float 20 Hz presence observation frame.

    Layout (80 floats):
      [0..12]  joint_delta_from_stand_rad (12)
      [12..24] tracking_error_rad = (cmd - meas) * rad (12; 0 if chatter_relief_enabled=False)
      [24..36] chatter_rad (12; 0 if chatter_relief_enabled=False)
      [36..48] joint_vel_rad_s (12)
      [48..51] projected_gravity (3; [0, 0, -1] if imu_enabled=False)
      [51..54] angular_rate_rad_s (3; [0, 0, 0] if imu_enabled=False)
      [54..57] accel_delta_g (3; [0, 0, 0] if imu_enabled=False)
      [57..68] social/audio/idle context (11):
               [person_yaw, person_pitch, person_conf, known_face, motion_mag,
                listening_active, mic_rms, speaking_active, speech_rms,
                boredom_level, sin(phase_rad)]
      [68..80] previous_foot_action (12)
    """
    rad = math.pi / 180.0
    q_delta: list[float] = []
    q_err: list[float] = []
    q_chat: list[float] = []
    q_vel: list[float] = []

    for idx in range(12):
        ok = (
            bool(usable_flags[idx])
            and isinstance(measured_deg[idx], (int, float))
            and math.isfinite(measured_deg[idx])
        )
        cmd_ok = isinstance(commanded_deg[idx], (int, float)) and math.isfinite(commanded_deg[idx])
        cmd = float(commanded_deg[idx]) if cmd_ok else float(STAND_ANGLES_DEG[idx])
        meas = float(measured_deg[idx]) if ok else cmd
        vel = (
            float(velocity_deg_s[idx])
            if (ok and isinstance(velocity_deg_s[idx], (int, float)) and math.isfinite(velocity_deg_s[idx]))
            else 0.0
        )
        chat = (
            float(chatter_deg[idx])
            if (ok and isinstance(chatter_deg[idx], (int, float)) and math.isfinite(chatter_deg[idx]))
            else 0.0
        )
        q_delta.append(max(-2.5, min(2.5, (meas - STAND_ANGLES_DEG[idx]) * rad)))
        err_val = max(-0.6, min(0.6, (cmd - meas) * rad)) if (ok and chatter_relief_enabled) else 0.0
        chat_val = max(0.0, min(0.4, chat * rad)) if (ok and chatter_relief_enabled) else 0.0
        q_err.append(err_val)
        q_chat.append(chat_val)
        q_vel.append(max(-8.0, min(8.0, vel * rad)))

    if imu_enabled:
        proj_grav = [max(-1.0, min(1.0, v)) for v in projected_gravity_from_wxyz(orientation_wxyz)]
        gyro = [max(-6.0, min(6.0, float(v))) for v in angular_rate_rad_s]
        ax, ay, az = (float(v) for v in acceleration_m_s2)
        # Expected gravity vector in body frame is -proj_grav * 9.80665
        accel_delta_g = [
            max(-3.0, min(3.0, (ax + proj_grav[0] * 9.80665) / 9.80665)),
            max(-3.0, min(3.0, (ay + proj_grav[1] * 9.80665) / 9.80665)),
            max(-3.0, min(3.0, (az + proj_grav[2] * 9.80665) / 9.80665)),
        ]
    else:
        proj_grav = [0.0, 0.0, -1.0]
        gyro = [0.0, 0.0, 0.0]
        accel_delta_g = [0.0, 0.0, 0.0]

    context = [
        max(-1.0, min(1.0, float(person_yaw))),
        max(-1.0, min(1.0, float(person_pitch))),
        max(0.0, min(1.0, float(person_conf))),
        1.0 if float(known_face) >= 0.5 else 0.0,
        max(0.0, min(1.0, float(motion_mag))),
        1.0 if float(listening_active) >= 0.5 else 0.0,
        max(0.0, min(1.0, float(mic_rms))),
        1.0 if float(speaking_active) >= 0.5 else 0.0,
        max(0.0, min(1.0, float(speech_rms))),
        max(0.0, min(1.0, float(boredom_level))),
        math.sin(float(phase_rad)),
    ]

    prev = [0.0] * 12 if previous_foot_action is None else [
        max(-1.0, min(1.0, float(v))) for v in previous_foot_action
    ]
    row = q_delta + q_err + q_chat + q_vel + proj_grav + gyro + accel_delta_g + context + prev
    if len(row) != PRESENCE_FEATURES or not all(math.isfinite(v) for v in row):
        raise ValueError("Invalid 80-float presence feature row")
    return row


class PresenceObservationHistory:
    """Causal 4-frame (200 ms @ 20 Hz) ring buffer."""

    def __init__(self):
        self._samples: deque[tuple[float, list[float]]] = deque(maxlen=24)

    def reset(self) -> None:
        self._samples.clear()

    def push_and_project(self, timestamp_s: float, features: list[float]) -> list[float]:
        if len(features) != PRESENCE_FEATURES:
            raise ValueError(f"Expected {PRESENCE_FEATURES} features, got {len(features)}")
        t = float(timestamp_s)
        if self._samples and t < self._samples[-1][0]:
            self._samples.clear()
        if self._samples and t == self._samples[-1][0]:
            self._samples[-1] = (t, list(features))
        else:
            self._samples.append((t, list(features)))
        cutoff = t - PRESENCE_SAMPLES * PRESENCE_INTERVAL_S - 0.15
        while len(self._samples) > 1 and self._samples[0][0] < cutoff:
            self._samples.popleft()
        out: list[float] = []
        for idx in range(PRESENCE_SAMPLES):
            target_t = t - idx * PRESENCE_INTERVAL_S + 1e-9
            matched = None
            for sample_t, row in reversed(self._samples):
                if sample_t <= target_t:
                    matched = row
                    break
            if matched is None:
                matched = self._samples[0][1]
            out.extend(matched)
        return out


def kinematic_grounded_tilt_deg(feet_z_mm: list[float] | tuple[float, ...]) -> tuple[float, float]:
    """Expected body (roll_deg, pitch_deg) change if all 4 feet remain planted on flat ground.

    Matches `tilt_roll_pitch_deg_from_wxyz` sign convention:
    - `roll_deg > 0`: left side raised (`left_height > right_height`)
    - `pitch_deg > 0`: nose down (`rear_height > front_height`); `pitch_deg < 0`: nose up

    Leg order: (rear_left, rear_right, front_left, front_right).
    feet_z_mm[i] is foot vertical offset in body frame (negative = extending leg downward, raising that corner).
    Wheelbase ~ 124 mm, track ~ 94 mm.
    """
    rl_z, rr_z, fl_z, fr_z = (float(v) for v in feet_z_mm)
    front_height = -0.5 * (fl_z + fr_z)
    rear_height = -0.5 * (rl_z + rr_z)
    left_height = -0.5 * (fl_z + rl_z)
    right_height = -0.5 * (fr_z + rr_z)
    pitch_deg = math.degrees(math.atan2(rear_height - front_height, 124.0))
    roll_deg = math.degrees(math.atan2(left_height - right_height, 94.0))
    return roll_deg, pitch_deg


class SympatheticMotionMonitor:
    """Detects ungrounded (picked-up/supported) leg movement and unrecoverable tips.

    Physics principle:
    1. When feet push against a supporting surface, measured 4th-wire leg extension differentials
       produce a sympathetic change in IMU body roll/pitch. When supported in the air (or dangling),
       4th-wire sensors confirm the legs moved, yet the IMU does not show the sympathetic grounded
       reaction (or shows uncorrelated hand-carried motion).
    2. When tipped over and attempting self-righting, grounded recovery reduces `tilt_deg` toward 0.
       If joints stall or move for the recovery window without sympathetic upright progress, the
       robot is wedged/inverted and should enter a calm passive state rather than thrashing.
    """

    def __init__(self, window_s: float = 0.75):
        self.window_s = float(window_s)
        self._samples: deque[tuple[float, list[float], tuple[float, float], float, float, float]] = deque(maxlen=48)
        self._righting_started_at: float | None = None
        self._righting_initial_tilt_deg: float = 0.0
        self._unsym_streak: int = 0
        self.last_score: float = 1.0

    def reset(self) -> None:
        self._samples.clear()
        self._righting_started_at = None
        self._righting_initial_tilt_deg = 0.0
        self._unsym_streak = 0
        self.last_score = 1.0

    def start_righting(self, now: float, initial_tilt_deg: float) -> None:
        self._righting_started_at = float(now)
        self._righting_initial_tilt_deg = float(initial_tilt_deg)

    def clear_righting(self) -> None:
        self._righting_started_at = None
        self._righting_initial_tilt_deg = 0.0

    def evaluate_righting(
        self,
        *,
        now: float,
        tilt_deg: float,
        tip_clear_degrees: float,
        stalled: bool = False,
        timeout_s: float = 2.8,
        min_progress_deg: float = 12.0,
    ) -> tuple[str, str | None]:
        """Return ('recovered' | 'in_progress' | 'passive', reason)."""
        if tilt_deg < tip_clear_degrees:
            self.clear_righting()
            return "recovered", None
        if stalled:
            self.clear_righting()
            return "passive", "righting_servo_stall"
        if self._righting_started_at is None:
            self.start_righting(now, tilt_deg)
            return "in_progress", None
        elapsed = now - self._righting_started_at
        progress = self._righting_initial_tilt_deg - tilt_deg
        if elapsed >= timeout_s and progress < min_progress_deg:
            self.clear_righting()
            return "passive", "righting_no_sympathetic_progress"
        return "in_progress", None

    def observe_stance_motion(
        self,
        *,
        now: float,
        measured_deg: list[float],
        measured_feet_z_mm: list[float],
        orientation_wxyz,
        angular_rate_rad_s,
        acceleration_m_s2,
    ) -> tuple[bool, float, str | None]:
        """Record a 20 Hz sample and check whether substantial leg movement produced sympathetic IMU response.

        Returns (unsympathetic_detected, sympathy_score, reason).
        """
        t = float(now)
        if self._samples and t < self._samples[-1][0]:
            self._samples.clear()
            self._unsym_streak = 0
        _, imu_roll, imu_pitch = tilt_roll_pitch_deg_from_wxyz(orientation_wxyz)
        kin_roll, kin_pitch = kinematic_grounded_tilt_deg(measured_feet_z_mm)
        gyro_dps = math.degrees(math.hypot(*(float(v) for v in angular_rate_rad_s)))
        dt = (t - self._samples[-1][0]) if self._samples else 0.05
        self._samples.append((t, list(measured_deg), (kin_roll, kin_pitch), imu_roll, imu_pitch, gyro_dps))

        cutoff = t - self.window_s
        while len(self._samples) > 2 and self._samples[0][0] < cutoff:
            self._samples.popleft()

        if len(self._samples) < 4:
            return False, self.last_score, None

        t0 = self._samples[0][0]
        if t - t0 < 0.40:
            return False, self.last_score, None

        n = len(self._samples)
        max_joint_step = max(
            max(s[1][i] for s in self._samples) - min(s[1][i] for s in self._samples)
            for i in range(12)
        )
        kr_vals = [s[2][0] for s in self._samples]
        kp_vals = [s[2][1] for s in self._samples]
        ir_vals = [s[3] for s in self._samples]
        ip_vals = [s[4] for s in self._samples]
        kin_span = math.hypot(max(kr_vals) - min(kr_vals), max(kp_vals) - min(kp_vals))
        imu_span = math.hypot(max(ir_vals) - min(ir_vals), max(ip_vals) - min(ip_vals))
        mean_gyro_dps = sum(s[5] for s in self._samples) / n

        # Only judge sympathetic ground reaction when the legs executed an unmistakable tilting differential
        if max_joint_step < 6.0 or kin_span < 5.2:
            self._unsym_streak = 0
            return False, self.last_score, None

        m_kr = sum(kr_vals) / n
        m_kp = sum(kp_vals) / n
        m_ir = sum(ir_vals) / n
        m_ip = sum(ip_vals) / n
        var_k = sum((kr_vals[k] - m_kr) ** 2 + (kp_vals[k] - m_kp) ** 2 for k in range(n))
        cov_ki = sum(
            (kr_vals[k] - m_kr) * (ir_vals[k] - m_ir) + (kp_vals[k] - m_kp) * (ip_vals[k] - m_ip)
            for k in range(n)
        )
        score = cov_ki / max(0.5, var_k)
        self.last_score = round(max(-1.0, min(2.0, score)), 3)

        # Legs moved decisively in a pitch/roll differential, yet body neither tilted sympathetically
        # nor showed proportional grounded IMU excursion (resting on a support stand or held in air).
        no_ground_response = (
            score < 0.10
            and gyro_dps < 180.0
            and (score < -0.15 or (imu_span + 0.15 * mean_gyro_dps) < 0.28 * kin_span)
        )
        if no_ground_response:
            step_weight = 3 if dt >= 0.12 else 1
            self._unsym_streak += step_weight
            if self._unsym_streak >= 3:
                return True, self.last_score, "legs_moved_without_ground_reaction"
        else:
            self._unsym_streak = 0
        return False, self.last_score, None
