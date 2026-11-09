"""CPU-only Stanford Pupper V3 MJX/Brax neural gait actor for Ainekio V2."""

from dataclasses import dataclass, field
import json
import math
from pathlib import Path
import numpy as np

from .contract import JOINTS, PROPRIO_SCHEMA, observation_size


PUPPER_MJX_KIND = "pupper-mjx"
OBSERVATION_DIM = 36
HISTORY_STEPS = 15
HISTORY_DIM = OBSERVATION_DIM * HISTORY_STEPS


def quat_rotate_inv(q_wxyz, vector):
    """Rotate a 3D world-frame vector into the body frame by quat_inv(w, x, y, z)."""
    q = np.asarray(q_wxyz, dtype=np.float64).reshape(4)
    norm = float(np.linalg.norm(q))
    if not math.isfinite(norm) or norm <= 0.0:
        raise ValueError("Orientation quaternion must be non-zero")
    w, x, y, z = q / norm
    v = np.asarray(vector, dtype=np.float64).reshape(3)
    qvec = np.array([-x, -y, -z], dtype=np.float64)
    uv = np.cross(qvec, v)
    uuv = np.cross(qvec, uv)
    return v + 2.0 * (w * uv + uuv)


def projected_gravity_body(q_wxyz):
    """Project world down-vector [0, 0, -1] into the body frame."""
    return quat_rotate_inv(q_wxyz, np.array([0.0, 0.0, -1.0], dtype=np.float64)).astype(np.float32)


def rad_to_calibration_pulse(angles_rad, calibration):
    """Convert MuJoCo joint angles (rad) to servo PWM pulse widths (us)."""
    mapping = sorted(calibration, key=lambda item: item["id"])
    angles_deg = np.rad2deg(np.asarray(angles_rad, dtype=np.float64).reshape(12))
    home_deg = np.array([m["home_cd"] / 100.0 for m in mapping], dtype=np.float64)
    home_us = np.array([m["home_us"] for m in mapping], dtype=np.float64)
    scale = np.array([(-1.0 if m["invert"] else 1.0) * m["us_per_degree"] for m in mapping], dtype=np.float64)
    return np.floor(home_us + (angles_deg - home_deg) * scale + 0.5)


def calibration_pulse_to_rad(pulse_us, calibration):
    """Convert servo PWM pulse widths (us) to MuJoCo joint angles (rad)."""
    mapping = sorted(calibration, key=lambda item: item["id"])
    pulses = np.asarray(pulse_us, dtype=np.float64).reshape(12)
    home_deg = np.array([m["home_cd"] / 100.0 for m in mapping], dtype=np.float64)
    home_us = np.array([m["home_us"] for m in mapping], dtype=np.float64)
    scale = np.array([(-1.0 if m["invert"] else 1.0) * m["us_per_degree"] for m in mapping], dtype=np.float64)
    return np.deg2rad(home_deg + (pulses - home_us) / scale)


@dataclass
class _WalkHistoryState:
    obs_history: np.ndarray = field(default_factory=lambda: np.zeros(HISTORY_DIM, dtype=np.float32))
    last_action: np.ndarray = field(default_factory=lambda: np.zeros(12, dtype=np.float32))
    last_time_s: float = -math.inf
    steps: int = 0

    def reset(self):
        self.obs_history.fill(0.0)
        self.last_action.fill(0.0)
        self.last_time_s = -math.inf
        self.steps = 0


class PupperMjxActor:
    """Pure NumPy CPU actor for exported Stanford Pupper V3 MJX RTNeural JSON policies."""

    def __init__(self, policy_path, environment=None):
        self.path = Path(policy_path)
        payload = json.loads(self.path.read_text())
        in_shape = payload.get("in_shape")
        if in_shape != [None, HISTORY_DIM]:
            raise ValueError(f"Expected Pupper MJX input shape [None, {HISTORY_DIM}], got {in_shape}")
        raw_layers = payload.get("layers", [])
        if len(raw_layers) != 5:
            raise ValueError(f"Expected 5 dense MLP layers, got {len(raw_layers)}")
        self.layers = []
        expected_in = HISTORY_DIM
        for index, layer in enumerate(raw_layers):
            weights = layer.get("weights", [])
            if len(weights) != 2:
                raise ValueError(f"Layer {index} must contain [kernel, bias]")
            kernel = np.asarray(weights[0], dtype=np.float32)
            bias = np.asarray(weights[1], dtype=np.float32)
            if kernel.ndim != 2 or bias.ndim != 1 or kernel.shape[0] != expected_in or kernel.shape[1] != bias.shape[0]:
                raise ValueError(f"Layer {index} has invalid weight shapes {kernel.shape}, {bias.shape}")
            activation = layer.get("activation")
            if activation not in ("elu", "tanh", "linear"):
                raise ValueError(f"Unsupported layer activation {activation!r}")
            self.layers.append((kernel, bias, activation))
            expected_in = int(kernel.shape[1])
        if expected_in != len(JOINTS):
            raise ValueError(f"Expected 12 action outputs, got {expected_in}")

        self.observation_history = int(payload.get("observation_history", HISTORY_STEPS))
        self.use_imu = bool(payload.get("use_imu", True))
        self.default_joint_pos = np.asarray(
            payload.get("default_joint_pos", [0.0, 0.06038839370012283, -0.37751471996307373] * 4),
            dtype=np.float64,
        ).reshape(12)
        self.action_scale = np.asarray(
            payload.get("action_scale", [0.78, 1.05, 1.05] * 4),
            dtype=np.float64,
        ).reshape(12)
        self.joint_lower_limits = np.asarray(payload["joint_lower_limits"], dtype=np.float64).reshape(12)
        self.joint_upper_limits = np.asarray(payload["joint_upper_limits"], dtype=np.float64).reshape(12)
        self.desired_world_z = np.asarray(
            payload.get("desired_world_z_in_body_frame", [0.0, 0.0, 1.0]),
            dtype=np.float32,
        ).reshape(3)
        self.kp = float(payload.get("kp", 3.1))
        self.kd = float(payload.get("kd", 0.09))

        self.environment = dict(environment or {})
        self.reference_joint_deg = np.asarray(
            self.environment.get("reference_joint_deg", np.rad2deg(self.default_joint_pos).tolist()),
            dtype=np.float64,
        ).reshape(12)
        self.foot_action_scale_mm = np.asarray(
            self.environment.get("foot_action_scale_mm", [100.0, 100.0, 100.0]),
            dtype=np.float64,
        ).reshape(3)
        self.joint_speed_deg_s = float(self.environment.get("joint_speed_deg_s", 60.0 / 0.11))
        self.control_hz = float(self.environment.get("control_hz", 50.0))
        self._body_model = None
        self._walk_states = {}
        self._default_state = _WalkHistoryState()

    def _body(self):
        if self._body_model is None:
            from .native import BodyModel
            robot = self.environment.get("robot")
            if not robot:
                from .environment import EnvironmentConfig
                robot = EnvironmentConfig().robot
            self._body_model = BodyModel(robot)
        return self._body_model

    def close(self):
        if self._body_model is not None:
            self._body_model.close()
            self._body_model = None

    def reset(self, walk_context=None):
        if walk_context is None:
            self._default_state.reset()
            self._walk_states.clear()
            return
        key = self._context_key(walk_context)
        if key in self._walk_states:
            self._walk_states[key].reset()

    @staticmethod
    def _context_key(walk_context):
        if not isinstance(walk_context, dict):
            return None
        return (
            walk_context.get("gateway_instance"),
            walk_context.get("robot_id"),
            walk_context.get("epoch"),
            walk_context.get("walk"),
        )

    def _state_for(self, walk_context=None, observation_time_s=None, is_initial=False):
        key = self._context_key(walk_context)
        if key is None or all(part is None for part in key):
            state = self._default_state
        else:
            if key not in self._walk_states:
                if len(self._walk_states) >= 16:
                    oldest = next(iter(self._walk_states))
                    del self._walk_states[oldest]
                self._walk_states[key] = _WalkHistoryState()
            state = self._walk_states[key]
        if is_initial or (
            observation_time_s is not None
            and math.isfinite(observation_time_s)
            and observation_time_s < state.last_time_s - 1e-6
        ):
            state.reset()
        if observation_time_s is not None and math.isfinite(observation_time_s):
            state.last_time_s = float(observation_time_s)
        return state

    def single_step_observation(self, observation, *, last_action=None):
        """Construct the 36-float single-step Pupper MJX observation vector."""
        ang_vel = np.asarray(observation["angular_rate_rad_s"], dtype=np.float32).reshape(3)
        gravity = projected_gravity_body(observation["orientation_wxyz"])
        command = np.asarray(observation["command"], dtype=np.float32).reshape(3)
        joint_rad = np.deg2rad(np.asarray(observation["joint_deg"], dtype=np.float64).reshape(12))
        motor_angles_rel = (joint_rad - self.default_joint_pos).astype(np.float32)
        prev_act = (
            np.zeros(12, dtype=np.float32)
            if last_action is None
            else np.asarray(last_action, dtype=np.float32).reshape(12)
        )
        obs_36 = np.concatenate((ang_vel, gravity, command, self.desired_world_z, motor_angles_rel, prev_act))
        return np.clip(obs_36, -100.0, 100.0).astype(np.float32)

    def forward(self, obs_history):
        """Run the 5-layer MLP forward pass in pure NumPy (< 0.1 ms on CPU)."""
        x = np.asarray(obs_history, dtype=np.float32)
        single = x.ndim == 1
        if single:
            x = x.reshape(1, -1)
        if x.shape[-1] != HISTORY_DIM:
            raise ValueError(f"Expected {HISTORY_DIM}-dim observation history, got shape {x.shape}")
        for kernel, bias, activation in self.layers:
            x = x @ kernel + bias
            if activation == "elu":
                x = np.where(x > 0.0, x, np.expm1(np.minimum(x, 0.0)))
            elif activation == "tanh":
                x = np.tanh(x)
        return x[0] if single else x

    def action_to_joint_targets_rad(self, raw_action):
        """Convert raw network output in [-1, 1] to clipped MuJoCo joint targets (rad)."""
        act = np.clip(np.asarray(raw_action, dtype=np.float64).reshape(12), -1.0, 1.0)
        return np.clip(self.default_joint_pos + act * self.action_scale, self.joint_lower_limits, self.joint_upper_limits)

    def angles_to_foot_offsets_mm(self, target_deg, reference_deg=None, current_target_deg=None):
        """Convert 12 joint target angles (deg) to 4x3 foot offsets (mm) via authoritative C BodyModel."""
        body = self._body()
        ref = self.reference_joint_deg if reference_deg is None else np.asarray(reference_deg, dtype=np.float64).reshape(12)
        cur = ref if current_target_deg is None else np.asarray(current_target_deg, dtype=np.float64).reshape(12)
        tgt = np.asarray(target_deg, dtype=np.float64).reshape(12)
        dt = 1.0 / self.control_hz
        try:
            offsets = body.foot_offsets_for_angles(tgt, ref)
            resolved = body.foot_target(offsets, ref, cur, self.joint_speed_deg_s, dt)
            if resolved is not None and np.all(resolved["leg_fit"] == 1.0) and np.max(np.abs(resolved["nominal_goal_angles"] - tgt)) < 0.5:
                return offsets.reshape(12), resolved
        except ValueError:
            pass

        fitted = ref.copy()
        for leg in range(4):
            sl = slice(3 * leg, 3 * leg + 3)
            ref_leg = ref[sl]
            tgt_leg = tgt[sl]

            def _leg_ok(cand_leg):
                probe = ref.copy()
                probe[sl] = cand_leg
                try:
                    off = body.foot_offsets_for_angles(probe, ref)
                    res = body.foot_target(off, ref, ref, self.joint_speed_deg_s, dt)
                    return (
                        res is not None
                        and res["leg_fit"][leg] == 1.0
                        and float(np.max(np.abs(res["nominal_goal_angles"][sl] - cand_leg))) < 0.5
                    )
                except ValueError:
                    return False

            if _leg_ok(tgt_leg):
                fitted[sl] = tgt_leg
            else:
                lo, hi = 0.0, 1.0
                for _ in range(10):
                    mid = 0.5 * (lo + hi)
                    cand = ref_leg + mid * (tgt_leg - ref_leg)
                    if _leg_ok(cand):
                        lo = mid
                    else:
                        hi = mid
                fitted[sl] = ref_leg + lo * (tgt_leg - ref_leg)

        offsets = body.foot_offsets_for_angles(fitted, ref)
        resolved = body.foot_target(offsets, ref, cur, self.joint_speed_deg_s, dt)
        return offsets.reshape(12), resolved

    def infer_observation(self, observation, *, walk_context=None):
        """Step the 15-step observation history ring buffer and compute joint & foot targets."""
        prev_from_obs = observation.get("previous_action")
        is_initial = (
            prev_from_obs is not None
            and np.all(np.asarray(prev_from_obs, dtype=np.float64) == 0.0)
            and "proprio_history" in observation
            and all(all(v == 0.0 for v in row) for row in observation["proprio_history"][1:])
        )
        state = self._state_for(
            walk_context,
            observation_time_s=observation.get("observation_time_s"),
            is_initial=is_initial,
        )
        obs_36 = self.single_step_observation(observation, last_action=state.last_action)
        state.obs_history = np.roll(state.obs_history, OBSERVATION_DIM)
        state.obs_history[:OBSERVATION_DIM] = obs_36
        raw_action = self.forward(state.obs_history)
        state.last_action = raw_action.copy()
        state.steps += 1

        motor_targets_rad = self.action_to_joint_targets_rad(raw_action)
        motor_targets_deg = np.rad2deg(motor_targets_rad)
        offsets_mm, resolved = self.angles_to_foot_offsets_mm(
            motor_targets_deg,
            reference_deg=self.reference_joint_deg,
            current_target_deg=observation.get("target_deg", self.reference_joint_deg),
        )
        normalized_action = np.clip(
            (offsets_mm.reshape(4, 3) / self.foot_action_scale_mm).reshape(12),
            -1.0,
            1.0,
        ).astype(np.float32)
        return dict(
            action=normalized_action,
            raw_action=raw_action,
            motor_targets_rad=motor_targets_rad,
            motor_targets_deg=motor_targets_deg,
            requested_foot_offset_mm=offsets_mm,
            resolved=resolved,
        )

    def predict(self, values, deterministic=True):
        """Compatible predictor for both 540-dim Pupper MJX vectors and 720-dim PROPRIO_SCHEMA vectors."""
        del deterministic
        arr = np.asarray(values, dtype=np.float32)
        if arr.ndim == 1 and arr.shape[0] == HISTORY_DIM:
            raw_action = self.forward(arr)
            return raw_action, None
        if arr.ndim == 2 and arr.shape[1] == HISTORY_DIM:
            return self.forward(arr), None

        proprio_size = observation_size(PROPRIO_SCHEMA)
        single = arr.ndim == 1
        if single:
            arr = arr.reshape(1, -1)
        if arr.shape[1] < proprio_size:
            raise ValueError(f"Unsupported observation vector shape {arr.shape}")

        outputs = []
        for row in arr:
            newest = row[:48]
            older = row[48:proprio_size]
            if np.all(older == 0.0) and np.all(newest[36:48] == 0.0):
                self._default_state.reset()
            joint_rad = newest[0:12].astype(np.float64)
            ang_vel = newest[24:27].astype(np.float32)
            gravity = newest[30:33].astype(np.float32)
            command = newest[33:36].astype(np.float32)
            motor_angles_rel = (joint_rad - self.default_joint_pos).astype(np.float32)
            obs_36 = np.clip(
                np.concatenate((ang_vel, gravity, command, self.desired_world_z, motor_angles_rel, self._default_state.last_action)),
                -100.0,
                100.0,
            ).astype(np.float32)
            self._default_state.obs_history = np.roll(self._default_state.obs_history, OBSERVATION_DIM)
            self._default_state.obs_history[:OBSERVATION_DIM] = obs_36
            raw_action = self.forward(self._default_state.obs_history)
            self._default_state.last_action = raw_action.copy()
            self._default_state.steps += 1
            motor_targets_rad = self.action_to_joint_targets_rad(raw_action)
            offsets_mm, _ = self.angles_to_foot_offsets_mm(np.rad2deg(motor_targets_rad))
            norm_act = np.clip(
                (offsets_mm.reshape(4, 3) / self.foot_action_scale_mm).reshape(12),
                -1.0,
                1.0,
            ).astype(np.float32)
            outputs.append(norm_act)
        result = np.stack(outputs, axis=0)
        return (result[0] if single else result), None
