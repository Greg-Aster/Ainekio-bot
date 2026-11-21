"""GPU MuJoCo (mjlab) PPO trainer & ONNX exporter for the 50 Hz Neural Pose & Emote Controller."""
from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import asdict, dataclass, replace
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
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mjlab.entity import EntityArticulationInfoCfg, EntityCfg
from mjlab.envs import ManagerBasedRlEnv, mdp as env_mdp
from mjlab.managers import (
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
from mjlab.sensor import ContactMatch, ContactSensorCfg
import mjlab.terrains as terrain_gen
from mjlab.terrains.terrain_generator import TerrainGeneratorCfg
from mjlab_microduck.tasks.microduck_velocity_env_cfg import (
    MicroduckRlCfg,
    make_microduck_velocity_env_cfg,
)
from rsl_rl.models.mlp_model import MLPModel, _OnnxMLPModel, _TorchMLPModel

from gateway.neural_gait.artifacts import save_json
from gateway.neural_gait.environment import (
    ENVIRONMENT_VERSION,
    GEOMETRY,
    EnvironmentConfig,
    GaitEnvironment,
    build_xml,
    representation_identity,
)
from gateway.neural_gait.microduck import (
    AinekioOnPolicyRunner,
    LearningSlopeCfg,
    LearningWaveCfg,
    MG90SActuatorCfg,
    mg90s_force_fields,
)
import gateway.neural_gait.microduck_mdp as gait_mdp
from gateway.neural_gait.tensor_body import TensorBody
from gateway.neural_gait.tensor_sensors import TensorSensors, gravity

from .actor import NeuralPoseActor
from .contract import (
    JOINTS,
    LEGS,
    POSE_FEATURES,
    POSE_FOOT_SCALE_MM,
    POSE_OBS_SIZE,
    POSE_SAMPLES,
    POSE_SCHEMA,
    pose_mirror_tables,
)
from .goals import DEFAULT_ENV_JSON, STAND_ANGLES_DEG, PoseManifold, _ensure_native_library
from . import mdp as pose_mdp

_ensure_native_library()

RECIPE = "ainekio-neural-pose-mjlab-v6-relock"
DEFAULT_HIDDEN_DIMS = (512, 256, 128)
POSE_RESIDUAL_SCALE = 0.43
POSE_GOAL_FOOT_SLICE = slice(57, 69)
MAX_CMD_DELAY_TICKS = 4
MAX_OBS_DELAY_TICKS = 6
DEFAULT_JAM_EPISODE_PROB = 0.16
DEFAULT_STANCE_JAM_PROB = 0.62


@requires_model_fields("jnt_range")
def pose_joint_range_fields(env, env_ids):
    """Allocate per-world joint ranges for physical unilateral limb-obstruction injection."""


def _register_mirror_buffers(module: torch.nn.Module, *, persistent: bool) -> None:
    obs_p, obs_s, act_p, act_s = pose_mirror_tables()
    module.register_buffer("obs_mirror_perm", torch.tensor(obs_p, dtype=torch.long), persistent=persistent)
    module.register_buffer("obs_mirror_sign", torch.tensor(obs_s, dtype=torch.float32), persistent=persistent)
    module.register_buffer("act_mirror_perm", torch.tensor(act_p, dtype=torch.long), persistent=persistent)
    module.register_buffer("act_mirror_sign", torch.tensor(act_s, dtype=torch.float32), persistent=persistent)


class _ResidualTorchMLPModel(_TorchMLPModel):
    def __init__(self, model: MLPModel, residual_scale: float = POSE_RESIDUAL_SCALE) -> None:
        super().__init__(model)
        self.residual_scale = float(residual_scale)
        _register_mirror_buffers(self, persistent=True)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        goal_foot = x[:, POSE_GOAL_FOOT_SLICE]
        x_mir = x[:, self.obs_mirror_perm] * self.obs_mirror_sign
        u_fwd = super().forward(x)
        u_mir = super().forward(x_mir)[:, self.act_mirror_perm] * self.act_mirror_sign
        u = 0.5 * (u_fwd + u_mir)
        return torch.clamp(goal_foot + self.residual_scale * u, -1.0, 1.0)


class _ResidualOnnxMLPModel(_OnnxMLPModel):
    def __init__(self, model: MLPModel, verbose: bool, residual_scale: float = POSE_RESIDUAL_SCALE) -> None:
        super().__init__(model, verbose)
        self.residual_scale = float(residual_scale)
        _register_mirror_buffers(self, persistent=True)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        goal_foot = x[:, POSE_GOAL_FOOT_SLICE]
        x_mir = x[:, self.obs_mirror_perm] * self.obs_mirror_sign
        u_fwd = super().forward(x)
        u_mir = super().forward(x_mir)[:, self.act_mirror_perm] * self.act_mirror_sign
        u = 0.5 * (u_fwd + u_mir)
        return torch.clamp(goal_foot + self.residual_scale * u, -1.0, 1.0)


class ResidualPoseMLPModel(MLPModel):
    """Left-right reflection-equivariant goal-anchored residual MLP:
    preserves 100% of asymmetric single-limb poses/jams while guaranteeing exact zero
    lateral bias whenever the state and goal are left-right symmetric."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        _register_mirror_buffers(self, persistent=False)

    @torch.no_grad()
    def symmetrize_normalizer(self) -> None:
        if hasattr(self.obs_normalizer, "_mean") and hasattr(self.obs_normalizer, "_var"):
            m = self.obs_normalizer._mean.detach().clone()
            v = self.obs_normalizer._var.detach().clone()
            m_sym = (0.5 * (m + m[:, self.obs_mirror_perm] * self.obs_mirror_sign)).clone()
            v_sym = (0.5 * (v + v[:, self.obs_mirror_perm])).clone()
            self.obs_normalizer._buffers["_mean"] = m_sym
            self.obs_normalizer._buffers["_var"] = v_sym
            self.obs_normalizer._buffers["_std"] = torch.sqrt(v_sym).clone()

    def update_normalization(self, obs) -> None:
        if self.obs_normalization:
            mlp_obs = torch.cat([obs[g] for g in self.obs_groups], dim=-1)
            mir_obs = mlp_obs[:, self.obs_mirror_perm] * self.obs_mirror_sign
            self.obs_normalizer.update(torch.cat((mlp_obs, mir_obs), dim=0))  # type: ignore[attr-defined]
            self.symmetrize_normalizer()

    def forward(self, obs, masks=None, hidden_state=None, stochastic_output: bool = False) -> torch.Tensor:
        from rsl_rl.utils import unpad_trajectories

        obs = unpad_trajectories(obs, masks) if masks is not None and not self.is_recurrent else obs
        raw_obs = torch.cat([obs[g] for g in self.obs_groups], dim=-1)
        mir_obs = raw_obs[:, self.obs_mirror_perm] * self.obs_mirror_sign
        mlp_fwd = self.mlp(self.obs_normalizer(raw_obs))
        mlp_mir = self.mlp(self.obs_normalizer(mir_obs))[:, self.act_mirror_perm] * self.act_mirror_sign
        mlp_output = 0.5 * (mlp_fwd + mlp_mir)
        if self.distribution is not None:
            if stochastic_output:
                self.distribution.update(mlp_output)
                return self.distribution.sample()
            return self.distribution.deterministic_output(mlp_output)
        return mlp_output

    def as_jit(self) -> torch.nn.Module:
        self.symmetrize_normalizer()
        return _ResidualTorchMLPModel(self, residual_scale=POSE_RESIDUAL_SCALE)

    def as_onnx(self, verbose: bool) -> torch.nn.Module:
        self.symmetrize_normalizer()
        return _ResidualOnnxMLPModel(self, verbose, residual_scale=POSE_RESIDUAL_SCALE)


@requires_model_fields("actuator_gainprm", "actuator_biasprm")
def randomize_pose_actuators(env, env_ids):
    """Randomize servo Kp/Kd (including stiff physical MG90S hold), torque envelope, and 4th-wire ADC."""
    ids = torch.arange(env.num_envs, device=env.device) if env_ids is None else env_ids
    n = len(ids)
    if n == 0:
        return
    pose_term = env.action_manager.get_term("pose")
    base_kp = float(pose_term.config.servo_kp)
    base_kd = float(pose_term.config.servo_kd)

    # Physical Miuzei MG90S internal PID + gearbox load: span Kp 0.85x..1.85x and independent Kd up to 2.25x
    # so 40% of worlds exhibit slower loaded swing rates (135..210 deg/s), forcing closed-loop airborne hold
    # until 4th-wire measured_deg actually arrives at goal rather than open-loop hop timing.
    kp_mult = 0.85 + 1.00 * torch.rand((n, 12), device=env.device)
    kd_mult = 0.85 + 1.40 * torch.rand((n, 12), device=env.device)
    effort_mult = 0.78 + 0.34 * torch.rand((n, 12), device=env.device)

    kp = base_kp * kp_mult
    kd = base_kd * kd_mult
    ctrl_ids = torch.arange(12, dtype=torch.long, device=env.device)
    env.sim.model.actuator_gainprm[ids.unsqueeze(1), ctrl_ids.unsqueeze(0), 0] = kp
    env.sim.model.actuator_biasprm[ids.unsqueeze(1), ctrl_ids.unsqueeze(0), 1] = -kp
    env.sim.model.actuator_biasprm[ids.unsqueeze(1), ctrl_ids.unsqueeze(0), 2] = -kd

    robot_entity = env.scene["robot"]
    for act in getattr(robot_entity, "actuators", ()):
        scale = getattr(act, "effort_scale", None)
        if scale is None or scale.shape != (env.num_envs, 12) or scale.device != effort_mult.device:
            scale = torch.ones((env.num_envs, 12), dtype=torch.float32, device=effort_mult.device)
            act.effort_scale = scale
        scale[ids] = effort_mult

    adc_active = torch.rand((n, 1), device=env.device) < 0.50
    scale_jitter = 0.975 + 0.050 * torch.rand((n, 1), device=env.device)
    offset_jitter = -20.0 + 40.0 * torch.rand((n, 12), device=env.device)
    pose_term.sensors.raw_scale[ids] = torch.where(adc_active, scale_jitter, 1.0)
    pose_term.sensors.raw_offset[ids] = torch.where(adc_active, offset_jitter, 0.0)
    pose_term.sensors.feedback_initialized[ids] = False
    pose_term.sensors.feedback(pose_term.sensors.trace[0, ids], 0.02, ids=ids)


def push_grounded_robot(env, env_ids):
    """Apply external linear & angular velocity disturbances to grounded worlds for instant balance recovery."""
    ids = torch.arange(env.num_envs, device=env.device) if env_ids is None else env_ids
    if len(ids) == 0:
        return
    pose_term = env.action_manager.get_term("pose")
    grounded_ids = ids[~pose_term.is_suspended[ids]]
    if len(grounded_ids) == 0:
        return
    asset = env.scene["robot"]
    limits = torch.tensor([0.18, 0.16, 0.04, 0.46, 0.46, 0.22], device=env.device)
    delta = (torch.rand((len(grounded_ids), 6), device=env.device) * 2 - 1) * limits
    asset.write_root_link_velocity_to_sim(
        asset.data.root_link_vel_w[grounded_ids] + delta, env_ids=grounded_ids
    )


@dataclass(kw_only=True)
class PoseActionCfg(ActionTermCfg):
    environment: dict
    total_mass_kg: float
    goal_bank_size: int = 2048

    def build(self, env):
        return PoseAction(self, env)


class PoseAction(ActionTerm):
    """50 Hz Foot-Offset Pose Action, 4th-wire fault simulator, goal scheduler & air-support wrench."""

    def __init__(self, cfg: PoseActionCfg, env):
        super().__init__(cfg, env)
        import experiments.freestyle.freestyle_curriculum as fc

        self.config = EnvironmentConfig(**cfg.environment)
        self.total_mass_kg = float(cfg.total_mass_kg)
        self.manifold = PoseManifold(device=str(env.device))
        self.manifold.env_config = self.config
        self.manifold.body = TensorBody(json.loads(GEOMETRY.read_text()), self.config, device=env.device)
        PoseManifold._apply_calibrated_carrier_floor(self.manifold.body)
        self.body = self.manifold.body
        self.sensors = TensorSensors(self.config, env.num_envs, env.device)

        self.joint_ids, _ = self._entity.find_joints(JOINTS, preserve_order=True)
        self.foot_site_ids, _ = self._entity.find_sites(
            tuple(f"{leg}_reference" for leg in LEGS), preserve_order=True
        )
        self.pickup_body_ids, _ = self._entity.find_bodies(
            tuple(f"{leg}_pickup_body" for leg in LEGS), preserve_order=True
        )

        # 70% grounded worlds, 30% supported/suspended-in-air (legs unloaded) worlds
        n_grounded = int(round(env.num_envs * 0.70))
        self.is_suspended = torch.arange(env.num_envs, device=env.device) >= n_grounded
        self.suspended_ids = torch.nonzero(self.is_suspended, as_tuple=False).squeeze(-1)
        self.grounded_ids = torch.nonzero(~self.is_suspended, as_tuple=False).squeeze(-1)

        # Build diverse GPU goal bank (60+ curriculum families + 3-leg waves + 2-paw mimes + stances)
        (
            self.goal_bank_rad,
            self.goal_bank_foot,
            self.goal_bank_support,
            self.grounded_goal_count,
        ) = pose_mdp.build_pose_goal_bank(self.manifold, count=cfg.goal_bank_size, seed=7)
        self.stand_q_rad = self.goal_bank_rad[0].clone()
        self.stand_foot_norm = self.goal_bank_foot[0].clone()

        # Folded, resting, sitting, and hanging-unloaded initial postures (including exact user diagnostic angles)
        folded_deg = torch.tensor(
            [
                [-2.2, -44.6, -58.6, 2.1, -41.1, -55.2, -2.9, 16.8, -70.5, -0.7, 19.4, -96.7],
                list(fc.REST_ANGLES),
                list(fc.SIT_ANGLES),
                list(fc.CROUCH_ANGLES),
                list(fc.DEEP_SQUAT_ANGLES),
                [0.0, -38.0, -68.0, 0.0, -38.0, -68.0, 0.0, -32.0, -72.0, 0.0, -32.0, -72.0],
                [12.0, -30.0, -55.0, -12.0, -30.0, -55.0, -10.0, 22.0, -65.0, 10.0, 22.0, -65.0],
            ],
            dtype=torch.float32,
            device=env.device,
        )
        folded_jitter = folded_deg.repeat(8, 1)
        folded_jitter[len(folded_deg) :] += (
            torch.rand((len(folded_deg) * 7, 12), device=env.device) * 2 - 1
        ) * 3.5
        self.folded_presets_rad, _ = self.manifold.project_batch_rad(folded_jitter * (math.pi / 180.0))

        # Asymmetric splayed/twisted grounded initial postures (including exact live -40.9 deg & -26.3 deg splays + mirrors)
        splay_gen = torch.Generator(device="cpu")
        splay_gen.manual_seed(19)
        splay_base = torch.tensor(STAND_ANGLES_DEG, dtype=torch.float32).reshape(1, 4, 3).repeat(256, 1, 1)
        splay_base[:160] += (torch.rand((160, 4, 3), generator=splay_gen) * 2 - 1) * torch.tensor([8.0, 7.0, 5.0])
        splay_base[160:] += (torch.rand((96, 4, 3), generator=splay_gen) * 2 - 1) * torch.tensor([8.0, 12.0, 14.0])
        for row_i in range(256):
            n_bad = 1 if (row_i % 4 < 2) else (2 if row_i % 4 == 2 else (3 if row_i % 8 == 3 else 4))
            legs_picked = torch.randperm(4, generator=splay_gen)[:n_bad]
            for leg_i in legs_picked.tolist():
                sh_sign = -1.0 if torch.rand((), generator=splay_gen).item() < 0.65 else 1.0
                if row_i < 96:
                    # Dedicated 4.5..18 deg small/medium splays so policy steps crisply all the way into <2.5 deg
                    splay_base[row_i, leg_i, 0] = sh_sign * (4.5 + 13.5 * torch.rand((), generator=splay_gen).item())
                else:
                    max_mag = 52.0 if sh_sign < 0.0 else 38.0
                    splay_base[row_i, leg_i, 0] = sh_sign * (12.0 + (max_mag - 12.0) * torch.rand((), generator=splay_gen).item())
                if row_i < 176:
                    # Keep splayed stance foot planted on the floor (models carpet/floor friction splays)
                    splay_base[row_i, leg_i, 1] = -6.0 + 15.0 * torch.rand((), generator=splay_gen).item()
                    splay_base[row_i, leg_i, 2] = -25.0 + 10.0 * torch.rand((), generator=splay_gen).item()
                else:
                    splay_base[row_i, leg_i, 1] += -28.0 + 50.0 * torch.rand((), generator=splay_gen).item()
                    splay_base[row_i, leg_i, 2] += -20.0 + 62.0 * torch.rand((), generator=splay_gen).item()
        live_splays = torch.tensor(
            [
                [-40.77, 18.37, 13.27, 2.97, -25.05, -18.65, -3.55, 20.07, -12.97, -16.36, 0.14, -31.21],
                [2.97, -25.05, -18.65, -40.77, 18.37, 13.27, -16.36, 0.14, -31.21, -3.55, 20.07, -12.97],
                [-26.28, -0.14, 4.90, -3.85, -11.41, -20.46, -6.57, 17.23, -21.42, -12.20, 8.39, -36.86],
                [-3.85, -11.41, -20.46, -26.28, -0.14, 4.90, -12.20, 8.39, -36.86, -6.57, 17.23, -21.42],
                [-40.91, 7.01, -19.84, -12.44, 7.71, -21.42, -12.37, -0.78, -20.25, -17.82, 5.15, -21.68],
                [-12.44, 7.71, -21.42, -40.91, 7.01, -19.84, -17.82, 5.15, -21.68, -12.37, -0.78, -20.25],
                [-12.37, -0.78, -20.25, -17.82, 5.15, -21.68, -40.91, 7.01, -19.84, -12.44, 7.71, -21.42],
                [-17.82, 5.15, -21.68, -12.37, -0.78, -20.25, -12.44, 7.71, -21.42, -40.91, 7.01, -19.84],
                [-31.25, 1.09, -3.96, -9.87, -0.03, -19.67, -4.67, 2.46, -11.17, -8.62, -1.46, -23.74],
                [-9.87, -0.03, -19.67, -31.25, 1.09, -3.96, -8.62, -1.46, -23.74, -4.67, 2.46, -11.17],
                [-50.30, 35.00, 32.38, -33.18, 37.97, 22.25, -37.98, 32.21, 19.19, -33.42, 27.44, 20.05],
                [-33.18, 37.97, 22.25, -50.30, 35.00, 32.38, -33.42, 27.44, 20.05, -37.98, 32.21, 19.19],
                [-27.13, 1.13, 58.44, -13.64, -34.49, -14.37, -20.00, -21.86, 1.84, -30.14, -36.36, -27.89],
                [-13.64, -34.49, -14.37, -27.13, 1.13, 58.44, -30.14, -36.36, -27.89, -20.00, -21.86, 1.84],
                [-53.44, -27.26, -2.23, -21.91, -41.15, -34.95, -46.66, -13.00, -8.87, -47.66, -28.55, -34.11],
                [-21.91, -41.15, -34.95, -53.44, -27.26, -2.23, -47.66, -28.55, -34.11, -46.66, -13.00, -8.87],
                [-15.20, -12.80, -18.10, -6.60, -14.50, -30.50, -14.40, 26.40, -25.30, -19.30, 25.90, -35.80],
                [-6.60, -14.50, -30.50, -15.20, -12.80, -18.10, -19.30, 25.90, -35.80, -14.40, 26.40, -25.30],
                # Exact 15:56:55.98 overhead stretch return (rear crouched at -34 deg, front at +88/+47 deg) + mirror
                [-5.80, -27.50, -21.40, 0.70, -27.50, -24.00, 13.30, 88.30, 58.60, 9.00, 47.40, 44.50],
                [0.70, -27.50, -24.00, -5.80, -27.50, -21.40, 9.00, 47.40, 44.50, 13.30, 88.30, 58.60],
                [-13.80, -22.00, -12.00, 2.70, -22.00, -16.00, -8.40, 0.94, -21.25, -1.60, 0.94, -21.25],
                [2.70, -22.00, -16.00, -13.80, -22.00, -12.00, -1.60, 0.94, -21.25, -8.40, 0.94, -21.25],
            ],
            dtype=torch.float32,
        )
        splay_all = torch.cat((live_splays, splay_base.reshape(256, 12)), dim=0).to(device=env.device)
        self.splayed_presets_rad, _ = self.manifold.project_batch_rad(splay_all * (math.pi / 180.0))
        if torch.device(env.device).type == "cuda":
            torch.cuda.empty_cache()

        self._raw = torch.zeros((env.num_envs, 12), dtype=torch.float32, device=env.device)
        self.prev_raw_action = torch.zeros_like(self._raw)
        self.prev_action_delta = torch.zeros_like(self._raw)
        self.applied_action = torch.zeros_like(self._raw)
        self.prev_applied_action = torch.zeros_like(self._raw)
        self.prev_applied_delta = torch.zeros_like(self._raw)

        self.logical = self.body.q0.reshape(1, 12).expand(env.num_envs, -1).clone()
        self.logical, self.targets = self.body.pwm(self.logical)
        self.targets = self.targets.to(torch.float32)
        self.delayed_targets = self.targets.clone()

        # Host<->Wi-Fi<->P4 transport delay ring buffers (50 Hz control ticks)
        self.env_arange = torch.arange(env.num_envs, dtype=torch.long, device=env.device)
        self.cmd_delay_ticks = torch.zeros(env.num_envs, dtype=torch.long, device=env.device)
        self.obs_delay_ticks = torch.zeros(env.num_envs, dtype=torch.long, device=env.device)
        self.pkt_hold_prob = torch.zeros(env.num_envs, dtype=torch.float32, device=env.device)
        self.cmd_delay_buf = self.targets.unsqueeze(0).expand(MAX_CMD_DELAY_TICKS + 1, -1, -1).clone()
        # P4 telemetry packet: [joint_rad(12), joint_vel(12), cmd_rad(12), gyro(3), accel_g(3), proj_grav(3)] = 45 floats
        self.obs_delay_buf = torch.zeros(
            (MAX_OBS_DELAY_TICKS + 1, env.num_envs, 45), dtype=torch.float32, device=env.device
        )
        self.held_p4_frame = torch.zeros((env.num_envs, 45), dtype=torch.float32, device=env.device)

        # Goal & oscillation buffers
        self.base_goal_rad = self.stand_q_rad.unsqueeze(0).expand(env.num_envs, -1).clone()
        self.base_goal_foot = self.stand_foot_norm.unsqueeze(0).expand(env.num_envs, -1).clone()
        self.current_goal_rad = self.base_goal_rad.clone()
        self.current_goal_foot = self.base_goal_foot.clone()
        self.leg_support = torch.ones((env.num_envs, 4), dtype=torch.float32, device=env.device)
        self.speed_scale = torch.full((env.num_envs, 1), 0.75, dtype=torch.float32, device=env.device)

        self.goal_timer = torch.zeros(env.num_envs, dtype=torch.long, device=env.device)
        self.osc_active = torch.zeros(env.num_envs, dtype=torch.bool, device=env.device)
        self.osc_amp_rad = torch.zeros((env.num_envs, 12), dtype=torch.float32, device=env.device)
        self.osc_hz = torch.ones((env.num_envs, 1), dtype=torch.float32, device=env.device)
        self.osc_step = torch.zeros(env.num_envs, dtype=torch.long, device=env.device)

        # 4th-wire ADC usability mask (simulates clipped/faulted feedback wires like joints 1 & 4)
        self.usable_mask = torch.ones((env.num_envs, 12), dtype=torch.bool, device=env.device)

        # Mechanical jam / physical limb-obstruction curriculum buffers
        mj_m = env.sim.mj_model
        self.mj_joint_ids = torch.tensor(
            [int(mj_m.joint(f"robot/{name}").id) for name in JOINTS], dtype=torch.long, device=env.device
        )
        self.default_jnt_range = torch.as_tensor(
            mj_m.jnt_range[self.mj_joint_ids.detach().cpu().numpy()], dtype=torch.float32, device=env.device
        )
        self.jam_episode = torch.zeros(env.num_envs, dtype=torch.bool, device=env.device)
        self.jam_leg_mask = torch.zeros((env.num_envs, 4), dtype=torch.bool, device=env.device)
        self.jam_joint_mask = torch.zeros((env.num_envs, 12), dtype=torch.bool, device=env.device)
        self.jam_stop_rad = torch.zeros((env.num_envs, 12), dtype=torch.float32, device=env.device)
        self.jam_mid_rad = torch.zeros((env.num_envs, 12), dtype=torch.float32, device=env.device)
        self.jam_dir = torch.zeros((env.num_envs, 12), dtype=torch.float32, device=env.device)
        self.jam_contacted = torch.zeros((env.num_envs, 4), dtype=torch.bool, device=env.device)
        self.jam_contact_age = torch.zeros((env.num_envs, 4), dtype=torch.long, device=env.device)

        # Ground-contact unilateral shoulder friction-lock buffers (unlocks the instant foot lifts Z)
        self.stance_jam_episode = torch.zeros(env.num_envs, dtype=torch.bool, device=env.device)
        self.stance_jam_leg_mask = torch.zeros((env.num_envs, 4), dtype=torch.bool, device=env.device)
        self.stance_jam_unlocked = torch.zeros((env.num_envs, 4), dtype=torch.bool, device=env.device)
        self.stance_jam_airborne = torch.zeros((env.num_envs, 4), dtype=torch.bool, device=env.device)
        self.stance_step_leg = torch.zeros((env.num_envs, 4), dtype=torch.bool, device=env.device)
        self.stance_jam_age = torch.zeros((env.num_envs, 4), dtype=torch.long, device=env.device)
        self.stance_jam_lock_rad = torch.zeros((env.num_envs, 4), dtype=torch.float32, device=env.device)
        self.stance_jam_dir = torch.zeros((env.num_envs, 4), dtype=torch.float32, device=env.device)
        self.stance_jam_floor_z = torch.full((env.num_envs, 4), 1e6, dtype=torch.float32, device=env.device)

        self.history = torch.zeros(
            (env.num_envs, POSE_SAMPLES, POSE_FEATURES), dtype=torch.float32, device=env.device
        )
        self.history_step = None
        self.pending_reset = None

        self.target_lims_rad = (
            torch.tensor(self.config.target_limits_deg, dtype=torch.float64, device=env.device).reshape(4, 3, 2)
            * (math.pi / 180.0)
        )
        self.suspended_target_pos = self._env.scene.env_origins[self.suspended_ids].clone()
        self.suspended_target_pos[:, 2] += 0.28
        self.forward_fn = self.body.forward

        body = self.body
        # Match goals.py:step_host_command physical MG90S no-load slew rate (545.45 deg/s @ 50 Hz = 10.91 deg/tick)
        motor_max_travel = math.radians(float(self.config.motor_no_load_speed_deg_s)) / float(self.config.control_hz)

        def _step_pose_cmd(actions_t: torch.Tensor, previous_t: torch.Tensor, spd_t: torch.Tensor):
            goal = body.decode(actions_t).reshape(-1, 4, 3)
            prev = previous_t.to(body.O.dtype).reshape(-1, 4, 3)
            lim = (motor_max_travel * spd_t.to(body.O.dtype).clamp(0.25, 1.0)).unsqueeze(-1)
            delta = goal - prev
            leg_max = delta.abs().amax(dim=-1, keepdim=True).clamp_min(1e-12)
            u = (lim / leg_max).clamp(max=1.0)
            cand = prev + u * delta
            q_b, closed = body.bounded(cand)
            pulse = torch.floor(body.pulse_home + (torch.rad2deg(q_b) - body.home) * body.pulse_scale + 0.5)
            pulse_ok = ((pulse[..., 1:] >= 300) & (pulse[..., 1:] <= 2950)).all(-1) & (
                (pulse >= 1) & (pulse <= 65535)
            ).all(-1)
            ok = closed & pulse_ok
            q_sel = torch.where(ok.unsqueeze(-1), q_b, prev)
            q_log, q_phys = body.pwm(q_sel)
            pts, _ = body.forward(q_log.reshape(-1, 4, 3))
            applied = ((pts - body.origin) / body.scale).clamp(-1.0, 1.0).reshape(-1, 12).to(torch.float32)
            return q_log, q_phys.to(torch.float32), applied

        self.step_pose_cmd = _step_pose_cmd
        self.reset(None)
        if torch.device(env.device).type == "cuda" and env.num_envs >= 64:
            self.step_pose_cmd = torch.compile(_step_pose_cmd, fullgraph=True, dynamic=False)
            self.forward_fn = torch.compile(self.body.forward, fullgraph=True, dynamic=False)

    @property
    def action_dim(self):
        return 12

    @property
    def raw_action(self):
        return self._raw

    def _inject_goal_obstructions(self, ids: torch.Tensor, q_start: torch.Tensor):
        n = len(ids)
        if n == 0:
            return
        dev = self._env.device
        jnt_ranges = self._env.sim.model.jnt_range
        jnt_ranges[ids.unsqueeze(1), self.mj_joint_ids.unsqueeze(0), :] = self.default_jnt_range.unsqueeze(0)

        self.jam_leg_mask[ids] = False
        self.jam_joint_mask[ids] = False
        self.jam_dir[ids] = 0.0
        self.jam_contacted[ids] = False
        self.jam_contact_age[ids] = 0
        self.jam_mid_rad[ids] = self.current_goal_rad[ids]
        self.jam_stop_rad[ids] = self.current_goal_rad[ids]

        self.stance_jam_leg_mask[ids] = False
        self.stance_jam_unlocked[ids] = False
        self.stance_jam_airborne[ids] = False
        self.stance_step_leg[ids] = False
        self.stance_jam_age[ids] = 0
        self.stance_jam_lock_rad[ids] = 0.0
        self.stance_jam_dir[ids] = 0.0
        self.stance_jam_floor_z[ids] = 1e6

        # 1. Ground-contact unilateral shoulder friction jam (1..4 locked shoulders; re-locks on early touchdown!)
        seg_sjam = self.stance_jam_episode[ids] & (~self.jam_episode[ids]) & (torch.rand(n, device=dev) < 0.88)
        if bool(seg_sjam.any()):
            sj_local = torch.nonzero(seg_sjam, as_tuple=False).squeeze(-1)
            sj_ids = ids[sj_local]
            ms = len(sj_ids)
            qs_s = q_start[sj_local].reshape(ms, 4, 3)
            qg_s = self.current_goal_rad[sj_ids].reshape(ms, 4, 3)
            d_sh = qg_s[..., 0] - qs_s[..., 0]
            usable_sh = self.usable_mask[sj_ids].reshape(ms, 4, 3)[..., 0]
            sup_s = self.leg_support[sj_ids] > 0.5
            four_leg_stance = self.leg_support[sj_ids].sum(dim=-1, keepdim=True) > 3.5
            valid_sj = four_leg_stance & sup_s & usable_sh & (d_sh.abs() > 0.058)
            if bool(valid_sj.any()):
                sj_ok = valid_sj.any(dim=-1)
                sj_scores = torch.where(valid_sj, d_sh.abs() + 0.05 * torch.rand_like(d_sh), torch.full_like(d_sh, -1.0))
                sj_sel = sj_scores.argmax(dim=-1)
                sj_oh = torch.nn.functional.one_hot(sj_sel, num_classes=4).to(torch.bool) & sj_ok.unsqueeze(-1)
                multi_lock = torch.rand((ms, 1), device=dev) < 0.55
                sj_mask = torch.where(multi_lock, valid_sj, sj_oh) & sj_ok.unsqueeze(-1)
                active_sj_ids = sj_ids[sj_ok]
                self.osc_active[active_sj_ids] = False
                self.osc_amp_rad[active_sj_ids] = 0.0
                multi_cnt = sj_mask.sum(dim=-1)
                self.goal_timer[sj_ids] = torch.where(
                    multi_cnt >= 2, torch.clamp(self.goal_timer[sj_ids], min=155), self.goal_timer[sj_ids]
                )
                # 55% snag immediately (0..20% travel -> large 10..42 deg splay),
                # 25% snag mid-way (42..72% travel -> medium 7..18 deg splay),
                # 20% settle near goal (2.6..6.2 deg residual inside the 6.5 deg non-stepping deadband!)
                u_snag = torch.rand((ms, 1), device=dev)
                alpha_sj = torch.where(
                    u_snag < 0.55,
                    0.20 * torch.rand((ms, 1), device=dev),
                    torch.where(
                        u_snag < 0.80,
                        0.42 + 0.30 * torch.rand((ms, 1), device=dev),
                        1.0 - (0.046 + 0.062 * torch.rand((ms, 1), device=dev)) / d_sh.abs().clamp_min(0.12),
                    ),
                ).clamp(0.0, 0.94)
                lock_sh = qs_s[..., 0] + alpha_sj * d_sh
                rem_after_lock = (qg_s[..., 0] - lock_sh).abs()
                sj_mask = sj_mask & (rem_after_lock > 0.045)
                sj_ok = sj_mask.any(dim=-1)
                sj_dir = torch.where(sj_mask, torch.sign(d_sh), torch.zeros_like(d_sh))
                sh_jids = self.mj_joint_ids[0::3]
                def_sh_lo = self.default_jnt_range[0::3, 0].unsqueeze(0).expand(ms, 4)
                def_sh_hi = self.default_jnt_range[0::3, 1].unsqueeze(0).expand(ms, 4)
                lo_sj = torch.where(sj_dir < -0.5, torch.clamp(lock_sh, def_sh_lo, def_sh_hi - 0.03), def_sh_lo)
                hi_sj = torch.where(sj_dir > 0.5, torch.clamp(lock_sh, def_sh_lo + 0.03, def_sh_hi), def_sh_hi)
                jnt_ranges[sj_ids.unsqueeze(1), sh_jids.unsqueeze(0), :] = torch.stack((lo_sj, hi_sj), dim=-1)
                self.stance_jam_leg_mask[sj_ids] = sj_mask
                self.stance_jam_lock_rad[sj_ids] = lock_sh
                self.stance_jam_dir[sj_ids] = sj_dir
                # Schmitt-trigger initiation: only latch a step if residual shoulder splay > 6.5 deg (0.113 rad)
                step_cand = sj_mask & (rem_after_lock > 0.113)
                has_step_cand = step_cand.any(dim=-1)
                init_sel = torch.where(step_cand, rem_after_lock, torch.full_like(d_sh, -1.0)).argmax(dim=-1)
                self.stance_step_leg[sj_ids] = (
                    torch.nn.functional.one_hot(init_sel, num_classes=4).to(torch.bool) & has_step_cand.unsqueeze(-1)
                )

        # 2. Rigid physical hard-stop strictly on free/gesturing limbs (`leg_support < 0.5` ONLY;
        #    NEVER on `leg_support >= 0.5` stance legs, where hover observations collide with grounded standing!)
        seg_jam = self.jam_episode[ids] & (torch.rand(n, device=dev) < 0.80)
        if not bool(seg_jam.any()):
            return
        cand_local = torch.nonzero(seg_jam, as_tuple=False).squeeze(-1)
        sub_ids = ids[cand_local]
        m = len(sub_ids)

        qs = q_start[cand_local]
        qg = self.current_goal_rad[sub_ids]
        dq43 = (qg - qs).reshape(m, 4, 3)
        leg_travel = dq43.abs().amax(dim=-1)
        usable4 = self.usable_mask[sub_ids].reshape(m, 4, 3).all(dim=-1)
        sup4 = self.leg_support[sub_ids]
        free_pref = sup4 < 0.5

        valid_leg = (leg_travel > 0.40) & usable4 & free_pref
        use_leg = valid_leg
        ok_mask = use_leg.any(dim=-1)
        if not bool(ok_mask.any()):
            return

        scores = torch.where(use_leg, 1.0 + torch.rand_like(leg_travel), torch.zeros_like(leg_travel))
        leg_sel = scores.argmax(dim=-1)
        leg_oh = torch.nn.functional.one_hot(leg_sel, num_classes=4).to(torch.bool)
        leg_oh_12 = leg_oh.repeat_interleave(3, dim=-1)

        # Intermediate stop at 22%..55% of requested limb travel, projected onto closed 4-bar manifold
        alpha = 0.22 + 0.33 * torch.rand((m, 1), device=dev)
        q_mix = torch.where(leg_oh_12, qs + alpha * (qg - qs), qg)
        q_mid, _ = self.manifold.project_batch_rad(q_mix)

        rem = (qg - q_mid) * leg_oh_12.to(torch.float32)
        rem43 = rem.reshape(m, 4, 3)
        sh_blk = leg_oh & (rem43[..., 0].abs() > 0.20)
        ca_gt_cr = rem43[..., 1].abs() >= rem43[..., 2].abs()
        ca_blk = leg_oh & ca_gt_cr & (rem43[..., 1].abs() > 0.20)
        cr_blk = leg_oh & (~ca_gt_cr) & (rem43[..., 2].abs() > 0.20)
        j_blk = torch.stack((sh_blk, ca_blk, cr_blk), dim=-1).reshape(m, 12) & ok_mask.unsqueeze(-1)
        valid_jam_env = j_blk.any(dim=-1)
        if not bool(valid_jam_env.any()):
            return

        # Keep goal static on jammed segments so the unreachable posture is crisp and unambiguous
        active_sub = sub_ids[valid_jam_env]
        self.osc_active[active_sub] = False
        self.osc_amp_rad[active_sub] = 0.0

        j_dir = torch.where(j_blk, torch.sign(rem), torch.zeros_like(rem))
        def_lo = self.default_jnt_range[:, 0].unsqueeze(0).expand(m, 12)
        def_hi = self.default_jnt_range[:, 1].unsqueeze(0).expand(m, 12)
        new_lo = torch.where(j_dir < -0.5, torch.clamp(q_mid, def_lo, def_hi - 0.03), def_lo)
        new_hi = torch.where(j_dir > 0.5, torch.clamp(q_mid, def_lo + 0.03, def_hi), def_hi)
        new_range = torch.stack((new_lo, new_hi), dim=-1)
        jnt_ranges[sub_ids.unsqueeze(1), self.mj_joint_ids.unsqueeze(0), :] = new_range

        self.jam_leg_mask[sub_ids] = leg_oh & valid_jam_env.unsqueeze(-1)
        self.jam_joint_mask[sub_ids] = j_blk
        self.jam_dir[sub_ids] = j_dir
        self.jam_stop_rad[sub_ids] = q_mid
        self.jam_mid_rad[sub_ids] = torch.where(valid_jam_env.unsqueeze(-1), q_mid, qg)

    def _sample_goals(self, ids: torch.Tensor, q_start_override: torch.Tensor | None = None):
        n = len(ids)
        if n == 0:
            return
        dev = self._env.device
        susp = self.is_suspended[ids]
        # 26% return-to-stand, 74% diverse goal bank (grounded envs use grounded-feasible subset;
        # suspended/unloaded envs sample all 2048 goals including arbitrary 4-leg air motions)
        to_stand = torch.rand(n, device=dev) < 0.26
        bank_idx_g = torch.randint(0, self.grounded_goal_count, (n,), device=dev)
        bank_idx_s = torch.randint(0, len(self.goal_bank_rad), (n,), device=dev)
        bank_idx = torch.where(susp, bank_idx_s, bank_idx_g)
        bank_idx = torch.where(to_stand, torch.zeros_like(bank_idx), bank_idx)

        q_base = self.goal_bank_rad[bank_idx]
        foot_base = self.goal_bank_foot[bank_idx]
        sup_base = self.goal_bank_support[bank_idx]

        self.base_goal_rad[ids] = q_base
        self.base_goal_foot[ids] = foot_base
        self.current_goal_rad[ids] = q_base
        self.current_goal_foot[ids] = foot_base
        self.leg_support[ids] = sup_base
        self.speed_scale[ids, 0] = 0.25 + 0.75 * torch.rand(n, device=dev)
        self.goal_timer[ids] = torch.randint(55, 135, (n,), device=dev)

        # 25% of non-stand goals oscillate 1-4 joints dynamically at 0.8..2.5 Hz
        osc = (~to_stand) & (torch.rand(n, device=dev) < 0.25)
        self.osc_active[ids] = osc
        self.osc_step[ids] = 0
        self.osc_hz[ids, 0] = 0.8 + 1.7 * torch.rand(n, device=dev)

        # Prefer oscillating lifted/free legs when grounded so waves/drumming/shakes look crisp;
        # in suspended worlds or 4-leg stances, oscillate 1-4 joints freely.
        amp = (0.12 + 0.30 * torch.rand((n, 12), device=dev)) * (
            torch.where(torch.rand((n, 12), device=dev) < 0.5, 1.0, -1.0)
        )
        free_legs = sup_base < 0.5  # (n, 4)
        has_free = free_legs.any(dim=-1) & (~susp)
        free_joint_mask = free_legs.repeat_interleave(3, dim=-1) & (torch.rand((n, 12), device=dev) < 0.75)
        rand_joint_mask = torch.rand((n, 12), device=dev) < 0.25
        joint_mask = torch.where(has_free.unsqueeze(-1), free_joint_mask, rand_joint_mask)
        # Ensure at least one joint oscillates when osc is True
        none_picked = ~joint_mask.any(dim=-1)
        fallback_j = torch.randint(0, 12, (n,), device=dev)
        joint_mask[torch.arange(n, device=dev), fallback_j] |= none_picked
        self.osc_amp_rad[ids] = torch.where(osc.unsqueeze(-1) & joint_mask, amp, 0.0)

        q_start = (
            q_start_override.to(torch.float32)
            if q_start_override is not None
            else self._entity.data.joint_pos[ids][:, self.joint_ids]
        )
        self._inject_goal_obstructions(ids, q_start)

    def _update_suspended_wrench(self):
        if len(self.suspended_ids) == 0:
            return
        robot = self._entity.data
        s_ids = self.suspended_ids
        pos_w = robot.root_link_pos_w[s_ids]
        quat_w = robot.root_link_quat_w[s_ids]
        lin_vel_w = robot.root_link_vel_w[s_ids, :3]
        ang_vel_w = robot.root_link_vel_w[s_ids, 3:6]

        delta_pos = self.suspended_target_pos - pos_w
        f_w = 22.0 * delta_pos - 4.5 * lin_vel_w
        f_w[:, 2] = self.total_mass_kg * 9.81 + 45.0 * delta_pos[:, 2] - 6.5 * lin_vel_w[:, 2]

        w, x, y, z = quat_w.unbind(-1)
        z_wx = 2.0 * (x * z + w * y)
        z_wy = 2.0 * (y * z - w * x)
        align_tau = torch.stack((z_wy, -z_wx, torch.zeros_like(z_wx)), dim=-1)
        tau_w = 0.65 * align_tau - 0.06 * ang_vel_w

        self._entity.write_external_wrench_to_sim(
            f_w.unsqueeze(1), tau_w.unsqueeze(1), env_ids=s_ids, body_ids=[0]
        )

    def _update_stance_friction_locks(self):
        """Pin stance-jammed shoulders whenever the foot is on the carpet (< 8 mm lift),
        re-locking if set down early and permanently unlocking only once |q_sh - goal_sh| <= 2.6 deg.
        """
        active_locked = self.stance_jam_leg_mask & (~self.stance_jam_unlocked)
        if not bool(active_locked.any()):
            self.stance_step_leg[:] = False
            return
        in_contact = self._env.scene["feet_ground_contact"].data.found > 0  # (N, 4)
        foot_z_w = self._entity.data.site_pos_w[:, self.foot_site_ids, 2]
        self.stance_jam_floor_z = torch.where(
            active_locked & in_contact,
            torch.minimum(self.stance_jam_floor_z, foot_z_w),
            self.stance_jam_floor_z,
        )
        q_all = self._entity.data.joint_pos[:, self.joint_ids].reshape(-1, 4, 3)
        q_sh = q_all[..., 0]
        goal_sh = self.current_goal_rad.reshape(-1, 4, 3)[..., 0]
        d_rem = goal_sh - q_sh
        sh_err = d_rem.abs()

        # Permanently unlock once the shoulder swings inside 3.0 deg (0.052 rad) of goal
        arrived = active_locked & (sh_err <= 0.052)
        if bool(arrived.any()):
            self.stance_jam_unlocked = self.stance_jam_unlocked | arrived
            self.stance_jam_airborne = self.stance_jam_airborne & (~arrived)
            env_a, leg_a = torch.nonzero(arrived, as_tuple=True)
            sh_a = self.mj_joint_ids[leg_a * 3]
            self._env.sim.model.jnt_range[env_a, sh_a, :] = self.default_jnt_range[leg_a * 3, :]
            active_locked = self.stance_jam_leg_mask & (~self.stance_jam_unlocked)
            if not bool(active_locked.any()):
                self.stance_step_leg[:] = False
                return

        floor_known = self.stance_jam_floor_z < 1e5
        cleared_pile = (~in_contact) & floor_known & ((foot_z_w - self.stance_jam_floor_z) >= 0.0045)

        # Newly lifted >= 4.5 mm clear of floor (zero ground contact) -> free shoulder joint range while airborne
        newly_airborne = active_locked & (~self.stance_jam_airborne) & cleared_pile
        if bool(newly_airborne.any()):
            self.stance_jam_airborne = self.stance_jam_airborne | newly_airborne
            env_u, leg_u = torch.nonzero(newly_airborne, as_tuple=True)
            sh_u = self.mj_joint_ids[leg_u * 3]
            self._env.sim.model.jnt_range[env_u, sh_u, :] = self.default_jnt_range[leg_u * 3, :]

        # Touched back down (ground contact restored) before reaching goal -> carpet re-locks at current q_sh
        touched_down = active_locked & self.stance_jam_airborne & in_contact
        if bool(touched_down.any()):
            self.stance_jam_airborne = self.stance_jam_airborne & (~touched_down)
            new_dir = torch.sign(d_rem)
            self.stance_jam_lock_rad = torch.where(touched_down, q_sh, self.stance_jam_lock_rad)
            self.stance_jam_dir = torch.where(touched_down, new_dir, self.stance_jam_dir)
            env_l, leg_l = torch.nonzero(touched_down, as_tuple=True)
            sh_l = self.mj_joint_ids[leg_l * 3]
            def_lo = self.default_jnt_range[leg_l * 3, 0]
            def_hi = self.default_jnt_range[leg_l * 3, 1]
            lk = q_sh[env_l, leg_l]
            dr = new_dir[env_l, leg_l]
            lo_new = torch.where(dr < -0.5, torch.clamp(lk, def_lo, def_hi - 0.03), def_lo)
            hi_new = torch.where(dr > 0.5, torch.clamp(lk, def_lo + 0.03, def_hi), def_hi)
            self._env.sim.model.jnt_range[env_l, sh_l, :] = torch.stack((lo_new, hi_new), dim=-1)

        dist_to_lock = self.stance_jam_dir * (self.stance_jam_lock_rad - q_sh)
        pinned = active_locked & (~self.stance_jam_airborne) & in_contact & (dist_to_lock <= 0.035)
        self.stance_jam_age = torch.where(pinned, self.stance_jam_age + 1, self.stance_jam_age)

        # Schmitt-trigger single-leg sequencer with stand-before-step priority:
        # - Do NOT initiate a shoulder micro-step while any stance leg's carrier is still deeply
        #   crouched/folded (|ca_err| > 14 deg / 0.24 rad) — stand up on all 4 legs first!
        # - Continue an already-latched step down to <= 3.0 deg (0.052 rad)
        # - Initiate a NEW step strictly when shoulder error > 6.5 deg (0.113 rad)
        ca_err = (self.current_goal_rad.reshape(-1, 4, 3)[..., 1] - q_all[..., 1]).abs()
        stance_upright = (~((self.leg_support > 0.5) & (ca_err > 0.24))).all(dim=-1, keepdim=True)
        keep_mask = self.stance_step_leg & active_locked & (sh_err > 0.052) & stance_upright
        keep_cur = keep_mask.any(dim=-1)
        start_mask = active_locked & (sh_err > 0.113) & stance_upright
        next_scores = torch.where(start_mask, sh_err, torch.full_like(sh_err, -1.0))
        next_oh = torch.nn.functional.one_hot(next_scores.argmax(dim=-1), num_classes=4).to(torch.bool) & start_mask.any(
            dim=-1, keepdim=True
        )
        self.stance_step_leg = torch.where(keep_cur.unsqueeze(-1), keep_mask, next_oh)

    def _advance_goals_50hz(self, exclude_ids: torch.Tensor | None = None):
        active_env = torch.ones(self._env.num_envs, dtype=torch.bool, device=self._env.device)
        if exclude_ids is not None and len(exclude_ids) > 0:
            active_env[exclude_ids] = False
        self.goal_timer = torch.where(active_env, self.goal_timer - 1, self.goal_timer)
        expired_mask = active_env & (self.goal_timer <= 0)
        if bool(expired_mask.any()):
            expired = torch.nonzero(expired_mask, as_tuple=False).squeeze(-1)
            self._sample_goals(expired)
            active_env[expired] = False

        # Static-shape vectorized oscillation update across all N envs (compiled forward_fn, zero dynamic shapes)
        osc_run = self.osc_active & active_env
        self.osc_step = torch.where(osc_run, self.osc_step + 1, self.osc_step)
        t = self.osc_step.to(torch.float32).unsqueeze(-1) * 0.02
        phase = 2.0 * math.pi * self.osc_hz * t
        delta = torch.where(self.osc_active.unsqueeze(-1), self.osc_amp_rad * torch.sin(phase), 0.0)
        q_cand = self.base_goal_rad + delta
        q43 = q_cand.to(torch.float64).reshape(-1, 4, 3)
        q43 = q43.clamp(self.body.low, self.body.high)
        q43 = torch.maximum(torch.minimum(q43, self.target_lims_rad[..., 1]), self.target_lims_rad[..., 0])
        pts, fvalid = self.forward_fn(q43)
        base43 = self.base_goal_rad.to(torch.float64).reshape(-1, 4, 3)
        base_foot43 = self.base_goal_foot.reshape(-1, 4, 3)
        foot_cand = ((pts - self.body.origin) / self.body.scale).clamp(-1.0, 1.0).to(torch.float32)
        use_cand = self.osc_active.unsqueeze(-1) & fvalid
        q_next = torch.where(use_cand.unsqueeze(-1), q43.to(torch.float32), base43.to(torch.float32))
        foot_next = torch.where(use_cand.unsqueeze(-1), foot_cand, base_foot43)
        self.current_goal_rad.copy_(q_next.reshape(-1, 12))
        self.current_goal_foot.copy_(foot_next.reshape(-1, 12))

    def _snapshot_p4_packet(self, *, add_mux_spikes: bool = True) -> torch.Tensor:
        joint_vel = self.sensors.joint_velocity
        if add_mux_spikes:
            # Simulate CD74HC4067 multiplexer channel-switch crosstalk spikes (e.g. 20..110 deg/s stationary)
            spike_mask = torch.rand_like(joint_vel) < 0.04
            spike_mag = (0.35 + 1.55 * torch.rand_like(joint_vel)) * torch.where(
                torch.rand_like(joint_vel) < 0.5, 1.0, -1.0
            )
            joint_vel = joint_vel + torch.where(spike_mask, spike_mag, 0.0)
        proj_grav = -gravity(self.sensors.quaternion)
        pkt = torch.cat(
            (
                self.sensors.joint,
                joint_vel,
                self.delayed_targets,
                self.sensors.gyro,
                self.sensors.accel / 9.81,
                proj_grav,
            ),
            dim=-1,
        )
        return torch.nan_to_num(pkt, nan=0.0, posinf=1.0, neginf=-1.0)

    def reset_from_joint_state(self, env_ids, q_proj_rad: torch.Tensor):
        ids = torch.arange(self._env.num_envs, device=self._env.device) if env_ids is None else env_ids
        if len(ids) == 0:
            return
        dev = self._env.device
        q64 = q_proj_rad.to(dtype=torch.float64, device=dev)
        logical, physical = self.body.pwm(q64)
        phys32 = physical.to(torch.float32)
        pts, _ = self.body.forward(logical.reshape(-1, 4, 3))
        init_act = ((pts - self.body.origin) / self.body.scale).clamp(-1.0, 1.0).reshape(-1, 12).to(torch.float32)

        self.logical[ids] = logical
        self.targets[ids] = phys32
        self.delayed_targets[ids] = phys32
        self.cmd_delay_buf[:, ids] = phys32.unsqueeze(0)
        self._raw[ids] = 0.0
        self.prev_raw_action[ids] = 0.0
        self.prev_action_delta[ids] = 0.0
        self.applied_action[ids] = init_act
        self.prev_applied_action[ids] = init_act
        self.prev_applied_delta[ids] = 0.0

        n = len(ids)
        # 15% low-latency/on-chip worlds (40..80 ms total), 85% Wi-Fi host-streamed worlds (100..240 ms total)
        wifi_world = torch.rand(n, device=dev) < 0.85
        cmd_d = torch.where(
            wifi_world,
            torch.randint(1, MAX_CMD_DELAY_TICKS + 1, (n,), device=dev),
            torch.randint(0, 2, (n,), device=dev),
        )
        obs_d = torch.where(
            wifi_world,
            torch.randint(2, MAX_OBS_DELAY_TICKS + 1, (n,), device=dev),
            torch.randint(0, 2, (n,), device=dev),
        )
        self.cmd_delay_ticks[ids] = cmd_d
        self.obs_delay_ticks[ids] = obs_d
        self.pkt_hold_prob[ids] = torch.where(wifi_world, 0.20, 0.04)

        # Simulate 4th-wire usability faults on 35% of episodes (including rear carriers 1 & 4)
        self.jam_episode[ids] = torch.rand(n, device=dev) < DEFAULT_JAM_EPISODE_PROB
        self.stance_jam_episode[ids] = (~self.is_suspended[ids]) & (~self.jam_episode[ids]) & (
            torch.rand(n, device=dev) < DEFAULT_STANCE_JAM_PROB
        )
        usable = torch.ones((n, 12), dtype=torch.bool, device=dev)
        fault_ep = (~self.jam_episode[ids]) & (~self.stance_jam_episode[ids]) & (torch.rand(n, device=dev) < 0.35)
        random_drop = torch.rand((n, 12), device=dev) < 0.18
        rear_carrier_drop = torch.zeros((n, 12), dtype=torch.bool, device=dev)
        rear_carrier_drop[:, 1] = torch.rand(n, device=dev) < 0.65
        rear_carrier_drop[:, 4] = torch.rand(n, device=dev) < 0.65
        drop_mask = fault_ep.unsqueeze(-1) & (random_drop | rear_carrier_drop)
        self.usable_mask[ids] = usable & (~drop_mask)

        self.sensors.reset(ids, q_proj_rad.to(torch.float32))
        self._sample_goals(ids, q_start_override=q_proj_rad)
        self._update_suspended_wrench()
        self.pending_reset = ids

    def reset(self, env_ids=None):
        ids = torch.arange(self._env.num_envs, device=self._env.device) if env_ids is None else env_ids
        if len(ids) == 0:
            return
        positions = self._entity.data.joint_pos[ids][:, self.joint_ids]
        self.reset_from_joint_state(ids, positions)

    def process_actions(self, actions: torch.Tensor):
        clamped = actions.clamp(-1.0, 1.0)
        self.prev_action_delta.copy_(self._raw - self.prev_raw_action)
        self.prev_raw_action.copy_(self._raw)
        self._raw.copy_(clamped)

        eff_foot = (self.current_goal_foot + POSE_RESIDUAL_SCALE * self._raw).clamp(-1.0, 1.0)
        self.prev_applied_delta.copy_(self.applied_action - self.prev_applied_action)
        self.prev_applied_action.copy_(self.applied_action)
        self.logical, targets, applied = self.step_pose_cmd(eff_foot, self.logical, self.speed_scale)
        self.targets.copy_(targets)
        self.applied_action.copy_(applied)
        self.cmd_delay_buf = torch.roll(self.cmd_delay_buf, 1, dims=0)
        self.cmd_delay_buf[0] = self.targets
        self.delayed_targets.copy_(self.cmd_delay_buf[self.cmd_delay_ticks, self.env_arange])
        q_true = self._entity.data.joint_pos[:, self.joint_ids]
        dist_to_stop = self.jam_dir * (self.jam_stop_rad - q_true)
        hit_joint = self.jam_joint_mask & (dist_to_stop <= 0.035)
        hit_leg = hit_joint.reshape(-1, 4, 3).any(dim=-1) & self.jam_leg_mask
        self.jam_contacted = self.jam_contacted | hit_leg
        self.jam_contact_age = torch.where(
            self.jam_contacted, self.jam_contact_age + 1, torch.zeros_like(self.jam_contact_age)
        )
        self._update_suspended_wrench()
        self._update_stance_friction_locks()

    def apply_actions(self):
        robot = self._entity.data
        self.sensors.sample(
            robot.joint_pos[:, self.joint_ids],
            self._env.scene["robot/accel"].data,
            self._env.scene["robot/gyro"].data,
        )
        self._entity.set_joint_position_target(self.delayed_targets, joint_ids=self.joint_ids)

    def _build_features_from_p4_frame(self, p4_frame: torch.Tensor) -> torch.Tensor:
        usable_f = self.usable_mask.to(torch.float32)
        meas_rad = p4_frame[:, 0:12]
        meas_vel = p4_frame[:, 12:24]
        p4_cmd_rad = p4_frame[:, 24:36]
        gyro = p4_frame[:, 36:39]
        accel_g = p4_frame[:, 39:42]
        proj_grav = p4_frame[:, 42:45]

        joint_rad = torch.where(self.usable_mask, meas_rad, p4_cmd_rad)
        joint_vel = torch.where(self.usable_mask, meas_vel, torch.zeros_like(meas_vel))

        features = torch.cat(
            (
                joint_rad,
                joint_vel,
                usable_f,
                gyro,
                accel_g,
                proj_grav,
                self.current_goal_rad,
                self.current_goal_foot,
                self.leg_support,
                self.speed_scale,
                self.applied_action,
            ),
            dim=-1,
        )
        return torch.nan_to_num(features, nan=0.0, posinf=1.0, neginf=-1.0)

    def observations(self) -> torch.Tensor:
        pending = self.pending_reset
        if pending is not None:
            self.sensors.imu(
                self._env.scene["robot/accel"].data[pending],
                self._env.scene["robot/gyro"].data[pending],
                0.0,
                ids=pending,
            )
            self.pending_reset = None

        if self.history_step != self._env.common_step_counter:
            if self.history_step is not None:
                self._advance_goals_50hz(exclude_ids=pending)
            p4_now = self._snapshot_p4_packet(add_mux_spikes=True)
            self.obs_delay_buf = torch.roll(self.obs_delay_buf, 1, dims=0)
            self.obs_delay_buf[0] = p4_now
            if pending is not None:
                p4_clean = self._snapshot_p4_packet(add_mux_spikes=False)[pending]
                self.obs_delay_buf[:, pending] = p4_clean.unsqueeze(0)
                self.held_p4_frame[pending] = p4_clean
            arrived = self.obs_delay_buf[self.obs_delay_ticks, self.env_arange]
            hold_mask = torch.rand(self._env.num_envs, device=self._env.device) < self.pkt_hold_prob
            if pending is not None:
                hold_mask[pending] = False
            self.held_p4_frame = torch.where(hold_mask.unsqueeze(-1), self.held_p4_frame, arrived)
            features = self._build_features_from_p4_frame(self.held_p4_frame)
            self.history = torch.roll(self.history, 1, 1)
            self.history[:, 0] = features
            if pending is not None:
                # Match PoseObservationHistory step-0 priming with earliest real scan
                self.history[pending] = features[pending].unsqueeze(1)
            self.history_step = self._env.common_step_counter
        elif pending is not None:
            p4_clean = self._snapshot_p4_packet(add_mux_spikes=False)[pending]
            self.obs_delay_buf[:, pending] = p4_clean.unsqueeze(0)
            self.held_p4_frame[pending] = p4_clean
            features = self._build_features_from_p4_frame(self.held_p4_frame)
            self.history[pending] = features[pending].unsqueeze(1)
        return self.history.flatten(1)

    def privileged_observations(self) -> torch.Tensor:
        q_true = self._entity.data.joint_pos[:, self.joint_ids]
        v_true = self._entity.data.joint_vel[:, self.joint_ids]
        q_cmd = self.logical.to(torch.float32)
        contacts = (self._env.scene["feet_ground_contact"].data.found > 0).to(torch.float32)
        lin_vel = torch.nan_to_num(env_mdp.base_lin_vel(self._env), nan=0.0, posinf=0.0, neginf=0.0)
        susp = self.is_suspended.to(torch.float32).unsqueeze(-1)
        delays = torch.stack(
            (
                self.cmd_delay_ticks.to(torch.float32) / float(MAX_CMD_DELAY_TICKS),
                self.obs_delay_ticks.to(torch.float32) / float(MAX_OBS_DELAY_TICKS),
            ),
            dim=-1,
        )
        jam_3 = self.jam_contacted.repeat_interleave(3, dim=-1).to(torch.float32)
        jam_active_dir = self.jam_dir * jam_3
        jam_stop_delta = (self.jam_stop_rad - q_true) * self.jam_joint_mask.to(torch.float32)
        sjam_locked = (self.stance_jam_leg_mask & (~self.stance_jam_unlocked)).to(torch.float32)
        priv = torch.cat(
            (
                q_true,
                v_true,
                q_cmd,
                contacts,
                lin_vel,
                susp,
                delays,
                jam_active_dir,
                jam_stop_delta,
                sjam_locked,
            ),
            dim=-1,
        )
        return torch.nan_to_num(priv, nan=0.0, posinf=0.0, neginf=0.0)

    def close(self):
        pass


def actor_observations(env):
    return env.action_manager.get_term("pose").observations()


def critic_privileged_observations(env):
    return env.action_manager.get_term("pose").privileged_observations()


def make_pose_env_cfg(config: EnvironmentConfig, num_envs: int = 1024, *, include_assembly: bool = True):
    config = replace(
        config,
        collision_profile="locomotion",
        balance_enabled=False,
        heading_feedback_enabled=False,
        control_hz=50,
        physics_hz=500,
        episode_seconds=16.0,
        foot_action_scale_mm=list(POSE_FOOT_SCALE_MM),
    )
    cfg = make_microduck_velocity_env_cfg(play=False, rough=False)

    shadow = GaitEnvironment(config, include_assembly=include_assembly, include_visuals=False)
    try:
        shadow.reset(seed=1)
        home = shadow.data.qpos.copy()
        total_mass_kg = float(shadow.model.body_subtreemass[1])
        xml = ET.fromstring(build_xml(config, include_assembly=include_assembly, include_visuals=False))
        initial = {
            shadow.model.joint(i).name: float(home[shadow.model.jnt_qposadr[i]])
            for i in range(1, shadow.model.njnt)
        }
    finally:
        shadow.close()

    for element in list(xml.find("worldbody")):
        if element.tag != "body":
            xml.find("worldbody").remove(element)
    xml.remove(xml.find("actuator"))
    xml.remove(xml.find("option"))
    for name, limits in zip(JOINTS, config.target_limits_deg):
        xml.find(f".//joint[@name='{name}']").set("range", " ".join(map(str, np.deg2rad(limits))))
    for geom in xml.iter("geom"):
        geom.set("group", "1")
    foot_geoms = []
    for leg in LEGS:
        for geom in xml.find(f".//body[@name='{leg}_pickup_body']").findall("geom"):
            geom.set("priority", "1")
            foot_geoms.append(geom.get("name"))
    foot_geoms = tuple(foot_geoms)
    spec_xml = ET.tostring(xml, encoding="unicode")
    lag = round(config.actuator_delay_s * config.physics_hz)

    cfg.scene.entities = {
        "robot": EntityCfg(
            spec_fn=lambda: mujoco.MjSpec.from_string(spec_xml),
            init_state=EntityCfg.InitialStateCfg(pos=(0.0, 0.0, float(home[2])), joint_pos=initial),
            articulation=EntityArticulationInfoCfg(
                actuators=(
                    MG90SActuatorCfg(
                        target_names_expr=JOINTS,
                        stiffness=config.servo_kp,
                        damping=config.servo_kd,
                        effort_limit=config.torque_nm,
                        speed_rad_s=math.radians(config.motor_no_load_speed_deg_s),
                        delay_min_lag=lag,
                        delay_max_lag=lag,
                    ),
                )
            ),
        )
    }
    cfg.scene.sensors = (
        ContactSensorCfg(
            name="feet_ground_contact",
            primary=ContactMatch(
                mode="subtree", pattern=tuple(f"{leg}_pickup_body" for leg in LEGS), entity="robot"
            ),
            secondary=ContactMatch(mode="body", pattern="terrain"),
            fields=("found", "force"),
            reduce="netforce",
            num_slots=1,
            track_air_time=True,
        ),
    )
    cfg.scene.num_envs = num_envs
    cfg.scene.terrain.terrain_type = "generator"
    cfg.scene.terrain.max_init_terrain_level = 2
    cfg.scene.terrain.terrain_generator = TerrainGeneratorCfg(
        size=(6.0, 6.0),
        border_width=12.0,
        num_rows=4,
        num_cols=4,
        add_lights=False,
        curriculum=False,
        sub_terrains={
            "flat": terrain_gen.BoxFlatTerrainCfg(proportion=0.65),
            "gentle_slope": LearningSlopeCfg(
                proportion=0.20,
                slope_range=(0.0, math.tan(math.radians(6.0))),
                platform_width=0.6,
                vertical_scale=0.001,
            ),
            "gentle_wave": LearningWaveCfg(
                proportion=0.15,
                amplitude_range=(0.003, 0.010),
                num_waves=3,
                horizontal_scale=0.10,
                vertical_scale=0.001,
            ),
        },
    )
    cfg.viewer.body_name = "torso"
    cfg.actions = {
        "pose": PoseActionCfg(
            entity_name="robot",
            environment=asdict(config),
            total_mass_kg=total_mass_kg,
            goal_bank_size=2048,
        )
    }
    cfg.observations = {
        "actor": ObservationGroupCfg(
            terms={"sensors": ObservationTermCfg(func=actor_observations)},
            concatenate_terms=True,
            enable_corruption=False,
        ),
        "critic": ObservationGroupCfg(
            terms={
                "sensors": ObservationTermCfg(func=actor_observations),
                "privileged": ObservationTermCfg(func=critic_privileged_observations),
            },
            concatenate_terms=True,
            enable_corruption=False,
        ),
    }
    cfg.commands = {}
    cfg.curriculum = {}

    mass_randomization = deepcopy(cfg.events["randomize_mass_inertia"])
    com_randomization = deepcopy(cfg.events["randomize_com"])
    cfg.events = {
        "mg90s_force_fields": EventTermCfg(func=mg90s_force_fields, mode="startup"),
        "pose_joint_range_fields": EventTermCfg(func=pose_joint_range_fields, mode="startup"),
        "reset_pose_worlds": EventTermCfg(func=pose_mdp.reset_pose_worlds, mode="reset"),
        "foot_friction": EventTermCfg(
            func=gait_mdp.randomize_multisurface_friction,
            mode="reset",
            params={"asset_cfg": SceneEntityCfg("robot", geom_names=foot_geoms), "ranges": (0.10, 2.05)},
        ),
        "push_grounded_robot": EventTermCfg(
            func=push_grounded_robot, mode="interval", interval_range_s=(2.0, 4.5)
        ),
    }
    if config.randomization:
        mass_randomization.params["asset_cfg"].body_names = (".*",)
        mass_randomization.params["alpha_range"] = (
            math.log(1 - config.randomization) / 2,
            math.log(1 + config.randomization) / 2,
        )
        cfg.events["randomize_mass_inertia"] = mass_randomization
        com_randomization.params["asset_cfg"].body_names = ("torso",)
        com_randomization.params["ranges"] = {0: (-0.016, 0.012), 1: (-0.012, 0.012), 2: (-0.006, 0.006)}
        cfg.events["randomize_com"] = com_randomization
        cfg.events["randomize_actuators"] = EventTermCfg(func=randomize_pose_actuators, mode="reset")

    cfg.rewards = {
        "pose_tracking": RewardTermCfg(func=pose_mdp.pose_tracking_reward, weight=5.0),
        "stance_step_clearance": RewardTermCfg(func=pose_mdp.stance_step_clearance_reward, weight=1.75),
        "jam_compliance": RewardTermCfg(func=pose_mdp.jam_compliance_cost, weight=-3.5),
        "grounded_balance": RewardTermCfg(func=pose_mdp.grounded_balance_cost, weight=-1.8),
        "action_smoothness": RewardTermCfg(func=pose_mdp.action_smoothness_cost, weight=-0.16),
        "settle_damping": RewardTermCfg(func=pose_mdp.settle_damping_cost, weight=-0.10),
        "stance_slip": RewardTermCfg(func=pose_mdp.stance_slip_cost, weight=-0.75),
    }
    cfg.terminations = {
        "time_out": cfg.terminations["time_out"],
        "nan_state": TerminationTermCfg(func=gait_mdp.invalid_physics),
        "tipped_over": TerminationTermCfg(func=pose_mdp.tipped_over_termination),
    }
    cfg.sim.mujoco.timestep = 1 / config.physics_hz
    cfg.sim.mujoco.integrator = "implicitfast"
    cfg.sim.mujoco.solver = "cg"
    cfg.sim.mujoco.iterations = 50
    cfg.sim.nconmax = 64
    cfg.sim.njmax = 256
    cfg.decimation = config.physics_hz // config.control_hz
    cfg.episode_length_s = config.episode_seconds
    return cfg, config


def _calibrate_critic_on_actor(runner, wrapped, device: str, *, rollout_steps: int = 180, sweeps: int = 4):
    """Fit critic normalizer + MLP via Bellman sweeps to the current actor under current env dynamics."""
    actor = runner.alg.actor
    critic = runner.alg.critic
    mlp = actor.mlp
    critic_mlp = critic.mlp
    critic_opt = torch.optim.AdamW(critic_mlp.parameters(), lr=1.5e-3, weight_decay=1e-5)
    gamma = float(getattr(runner.alg, "gamma", 0.99))

    actor.obs_normalizer.eval()
    critic.obs_normalizer.train(True)
    wrapped.reset()
    with torch.no_grad():
        for _ in range(80):
            obs_td = wrapped.get_observations()
            critic.update_normalization(obs_td)
            a_norm = actor.obs_normalizer(obs_td["actor"])
            act = mlp(a_norm).clamp(-8.0, 8.0).tanh()
            wrapped.step(act)

    critic.obs_normalizer.eval()
    wrapped.reset()
    c_obs_list, next_c_obs_list, rew_list, done_list, timeout_list = [], [], [], [], []
    try:
        with torch.no_grad():
            for _ in range(rollout_steps):
                obs_td = wrapped.get_observations()
                c_norm = critic.obs_normalizer(obs_td["critic"])
                act = actor(obs_td, stochastic_output=False)
                next_obs_td, rew, dones, extras = wrapped.step(act)
                next_c_norm = critic.obs_normalizer(next_obs_td["critic"])
                timeouts = extras.get("time_outs", torch.zeros_like(dones, dtype=torch.bool))
                c_obs_list.append(c_norm.detach())
                next_c_obs_list.append(next_c_norm.detach())
                rew_list.append(rew.to(torch.float32).detach())
                done_list.append((dones > 0).to(torch.float32).detach())
                timeout_list.append(timeouts.to(torch.float32).detach())

        c_all = torch.cat(c_obs_list, dim=0)
        n_c = c_all.shape[0]
        for sweep in range(sweeps):
            with torch.no_grad():
                if sweep == 0:
                    running_ret = torch.zeros_like(rew_list[-1])
                else:
                    running_ret = critic_mlp(next_c_obs_list[-1]).squeeze(-1)
                returns = [None] * len(rew_list)
                for t in range(len(rew_list) - 1, -1, -1):
                    v_boot = critic_mlp(next_c_obs_list[t]).squeeze(-1) if sweep > 0 else torch.zeros_like(running_ret)
                    cont = torch.where(done_list[t] > 0.5, timeout_list[t] * v_boot, running_ret)
                    running_ret = rew_list[t] + gamma * cont
                    returns[t] = running_ret
            ret_all = torch.cat(returns, dim=0).unsqueeze(-1)
            for _ in range(4):
                perm = torch.randperm(n_c, device=device)
                for start in range(0, n_c, 4096):
                    idx = perm[start : start + 4096]
                    v_pred = critic_mlp(c_all[idx])
                    c_loss = (v_pred - ret_all[idx]).square().mean()
                    critic_opt.zero_grad()
                    c_loss.backward()
                    torch.nn.utils.clip_grad_norm_(critic_mlp.parameters(), 2.0)
                    critic_opt.step()
        with torch.no_grad():
            critic_mse = float((critic_mlp(c_all[:8192]) - ret_all[:8192]).square().mean().item())
    finally:
        actor.obs_normalizer.train(True)
        critic.obs_normalizer.train(True)
    wrapped.reset()
    return critic_mse


def _kinematic_warmstart(runner, wrapped, env, device: str):
    """Warm-start residual actor (u ~ 0 + CoM stance shift) and critic normalizer/MLP before PPO."""
    pose_term: PoseAction = env.action_manager.get_term("pose")
    actor = runner.alg.actor
    critic = runner.alg.critic
    mlp = actor.mlp
    opt = torch.optim.AdamW(mlp.parameters(), lr=1.5e-3, weight_decay=1e-5)

    # Pass 1: populate actor & critic observation normalizer statistics with zero-residual goal-slew rollouts
    wrapped.reset()
    actor.obs_normalizer.train(True)
    critic.obs_normalizer.train(True)
    u_zero = torch.zeros_like(pose_term.applied_action)
    with torch.no_grad():
        for _ in range(160):
            obs_td = wrapped.get_observations()
            actor.update_normalization(obs_td)
            critic.update_normalization(obs_td)
            wrapped.step(u_zero)

    # Pass 2: 2 DAgger rounds fitting residual actor MLP -> 0 everywhere + lateral CoM shift on 3-leg/2-paw stances
    actor.obs_normalizer.eval()
    critic.obs_normalizer.eval()
    warmstart_mae = 0.0
    stance_shift_u = 0.048 / POSE_RESIDUAL_SCALE
    try:
        for rollout_steps, epochs, policy_prob in ((120, 12, 0.0), (100, 12, 0.7)):
            xs, ys = [], []
            with torch.no_grad():
                for _ in range(rollout_steps):
                    obs = wrapped.get_observations()["actor"]
                    norm_obs = actor.obs_normalizer(obs)
                    u_kin = torch.zeros_like(pose_term.applied_action)
                    sup = pose_term.leg_support
                    partial = (sup.sum(dim=-1) < 3.5) & (~pose_term.is_suspended)
                    if bool(partial.any()):
                        # Leg y signs in body frame: RL(+1=left), RR(-1=right), FL(+1=left), FR(-1=right);
                        # shifting torso toward stance legs (`desired_feet = world_foot - trans`) moves stance feet inboard
                        free_left = ((sup[:, 0] < 0.5) | (sup[:, 2] < 0.5)) & partial
                        free_right = ((sup[:, 1] < 0.5) | (sup[:, 3] < 0.5)) & partial
                        shift_u_y = torch.where(free_left, stance_shift_u, torch.where(free_right, -stance_shift_u, 0.0))
                        for leg_i in range(4):
                            stance_i = (sup[:, leg_i] > 0.5) & partial
                            u_kin[:, leg_i * 3 + 1] = torch.where(
                                stance_i, shift_u_y.clamp(-0.90, 0.90), u_kin[:, leg_i * 3 + 1]
                            )
                    target_logits = torch.atanh(u_kin)
                    xs.append(norm_obs.detach())
                    ys.append(target_logits.detach())
                    if policy_prob > 0.0 and torch.rand((), device=device).item() < policy_prob:
                        act = mlp(norm_obs).clamp(-8.0, 8.0).tanh()
                    else:
                        act = u_kin
                    wrapped.step(act)

            x_all = torch.cat(xs, dim=0)
            y_all = torch.cat(ys, dim=0)
            y_tanh = y_all.tanh()
            n_samples = x_all.shape[0]
            batch_size = 4096
            for _ in range(epochs):
                perm = torch.randperm(n_samples, device=device)
                for start in range(0, n_samples, batch_size):
                    idx = perm[start : start + batch_size]
                    pred = mlp(x_all[idx])
                    loss = 0.25 * (pred - y_all[idx]).square().mean() + 2.0 * (pred.tanh() - y_tanh[idx]).square().mean()
                    opt.zero_grad()
                    loss.backward()
                    torch.nn.utils.clip_grad_norm_(mlp.parameters(), 2.0)
                    opt.step()
            for g in opt.param_groups:
                g["lr"] *= 0.5
            with torch.no_grad():
                warmstart_mae = float((mlp(x_all[:8192]).tanh() - y_tanh[:8192]).abs().mean().item())
    finally:
        actor.obs_normalizer.train(True)
        critic.obs_normalizer.train(True)

    critic_mse = _calibrate_critic_on_actor(runner, wrapped, device, rollout_steps=180, sweeps=4)
    if hasattr(actor.distribution, "log_std_param"):
        actor.distribution.log_std_param.data.fill_(math.log(0.14))
    runner.alg.optimizer.state.clear()
    if torch.device(device).type == "cuda":
        torch.cuda.empty_cache()
    wrapped.reset()
    return {"warmstart_action_mae": warmstart_mae, "warmstart_critic_mse": critic_mse}


def _dagger_jam_warmstart(runner, wrapped, env, raw_ckpt: dict, prev_scale: float, device: str):
    """Distill v4 teacher + closed-loop friction-unloading micro-steps + rigid-jam recoil via DAgger."""
    pose_term: PoseAction = env.action_manager.get_term("pose")
    actor = runner.alg.actor
    critic = runner.alg.critic
    mlp = actor.mlp

    t_sd = raw_ckpt["actor_state_dict"]
    t_mean = t_sd["obs_normalizer._mean"].to(device)
    t_std = t_sd["obs_normalizer._std"].to(device)
    w0, b0 = t_sd["mlp.0.weight"], t_sd["mlp.0.bias"]
    w1, b1 = t_sd["mlp.2.weight"], t_sd["mlp.2.bias"]
    w2, b2 = t_sd["mlp.4.weight"], t_sd["mlp.4.bias"]
    w3, b3 = t_sd["mlp.6.weight"], t_sd["mlp.6.bias"]
    teacher_mlp = torch.nn.Sequential(
        torch.nn.Linear(w0.shape[1], w0.shape[0]),
        torch.nn.ELU(),
        torch.nn.Linear(w1.shape[1], w1.shape[0]),
        torch.nn.ELU(),
        torch.nn.Linear(w2.shape[1], w2.shape[0]),
        torch.nn.ELU(),
        torch.nn.Linear(w3.shape[1], w3.shape[0]),
    ).to(device)
    for idx, (w, b) in ((0, (w0, b0)), (2, (w1, b1)), (4, (w2, b2)), (6, (w3, b3))):
        teacher_mlp[idx].weight.data.copy_(w.to(device))
        teacher_mlp[idx].bias.data.copy_(b.to(device))
    teacher_mlp.eval()

    opt = torch.optim.AdamW(mlp.parameters(), lr=1.0e-3, weight_decay=1e-5)
    scale_ratio = float(prev_scale) / float(POSE_RESIDUAL_SCALE)
    dagger_mae = 0.0
    jam_dagger_mae = 0.0

    def _compute_expert_u(obs_raw: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        t_norm = (obs_raw - t_mean) / t_std.clamp_min(1e-6)
        u_teacher = (teacher_mlp(t_norm).clamp(-8.0, 8.0).tanh() * scale_ratio).clamp(-0.95, 0.95)
        q_true = pose_term._entity.data.joint_pos[:, pose_term.joint_ids]
        delay_gate = pose_term.obs_delay_ticks.unsqueeze(-1) + 2
        ready_leg = pose_term.jam_leg_mask & pose_term.jam_contacted & (pose_term.jam_contact_age >= delay_gate)
        ready_j = ready_leg.repeat_interleave(3, dim=-1)

        u_out = u_teacher
        sample_w = torch.ones_like(u_teacher)

        # 1. Ground-contact friction jam ONLY: Schmitt-trigger single-leg step (>6.5 deg start, <=3.0 deg release)
        #    gated by stand-before-step (all stance carriers within 14 deg of goal before lifting any paw).
        active_locked = pose_term.stance_jam_leg_mask & (~pose_term.stance_jam_unlocked)
        ca_err = (pose_term.current_goal_rad - q_true).abs().reshape(-1, 4, 3)[..., 1]
        stance_upright = (~((pose_term.leg_support > 0.5) & (ca_err > 0.24))).all(dim=-1, keepdim=True)
        sjam_ready = (
            active_locked
            & stance_upright
            & (pose_term.stance_jam_age >= delay_gate)
            & (~ready_leg.any(dim=-1, keepdim=True))
        )
        sh_err = (pose_term.current_goal_rad - q_true).abs().reshape(-1, 4, 3)[..., 0]
        latched_ready = pose_term.stance_step_leg & sjam_ready & (sh_err > 0.052)
        has_latched = latched_ready.any(dim=-1, keepdim=True)
        start_cand = sjam_ready & (sh_err > 0.113)
        has_start = start_cand.any(dim=-1, keepdim=True)
        fb_scores = torch.where(start_cand, sh_err, torch.full_like(sh_err, -1.0))
        fb_oh = torch.nn.functional.one_hot(fb_scores.argmax(dim=-1), num_classes=4).to(torch.bool) & has_start
        step_leg_oh = torch.where(has_latched, latched_ready, fb_oh)
        has_step = step_leg_oh.any(dim=-1)

        # Sub-6.5 deg locked carpet splays OR deeply crouched stance legs hold calm zero-lift goal tracking
        hold_or_stand = active_locked.any(dim=-1) & (~has_step) & (~ready_leg.any(dim=-1))
        u_out = torch.where(hold_or_stand.unsqueeze(-1), torch.zeros_like(u_out), u_out)
        sample_w = torch.where(hold_or_stand.unsqueeze(-1), torch.full_like(sample_w, 6.0), sample_w)

        if bool(has_step.any()):
            _, curr_foot = pose_term.manifold.project_batch_rad(q_true)
            curr_f43 = curr_foot.reshape(-1, 4, 3)
            goal_f43 = pose_term.current_goal_foot.reshape(-1, 4, 3)
            in_contact = env.scene["feet_ground_contact"].data.found > 0  # (N, 4)
            airborne = getattr(pose_term, "stance_jam_airborne", ~in_contact)

            # Full calibrated carpet-clearing lift (z_norm +0.18 -> ~22 mm real clearance, bounded
            # strictly inside the -27.87 deg calibrated carrier floor by PoseManifold).
            xy_contact = 0.50 * curr_f43[..., :2] + 0.50 * goal_f43[..., :2]
            z_contact = (curr_f43[..., 2] + 0.18).clamp(-1.0, 0.85)
            xy_air = goal_f43[..., :2]
            z_air = (torch.maximum(curr_f43[..., 2], goal_f43[..., 2]) + 0.15).clamp(-1.0, 0.84)

            step_xy = torch.where((~airborne).unsqueeze(-1), xy_contact, xy_air)
            step_z = torch.where(~airborne, z_contact, z_air).unsqueeze(-1)
            step_f43 = torch.cat((step_xy, step_z), dim=-1)

            teach_f43 = (pose_term.current_goal_foot + float(POSE_RESIDUAL_SCALE) * u_teacher).clamp(-1.0, 1.0).reshape(-1, 4, 3)
            other_locked = active_locked & (~step_leg_oh)
            base_sup_xy = torch.where(other_locked.unsqueeze(-1), curr_f43[..., :2], teach_f43[..., :2])

            left_single = step_leg_oh[:, 0] | step_leg_oh[:, 2]
            right_single = step_leg_oh[:, 1] | step_leg_oh[:, 3]
            rear_single = step_leg_oh[:, 0] | step_leg_oh[:, 1]
            front_single = step_leg_oh[:, 2] | step_leg_oh[:, 3]
            shift_y = 14.0 / 155.0
            shift_x = 9.0 / 155.0
            brace_z = torch.full((env.num_envs,), -8.0 / 180.0, device=device)
            com_shift_y = torch.where(left_single, shift_y, torch.where(right_single, -shift_y, 0.0))
            com_shift_x = torch.where(rear_single, -shift_x, torch.where(front_single, shift_x, 0.0))

            support_tripod = (~step_leg_oh) & (pose_term.leg_support > 0.5) & has_step.unsqueeze(-1)
            step_diag_03 = step_leg_oh[:, 0] | step_leg_oh[:, 3]
            step_diag_12 = step_leg_oh[:, 1] | step_leg_oh[:, 2]
            diag_mask_12 = torch.tensor([False, True, True, False], device=device).unsqueeze(0)
            diag_mask_03 = torch.tensor([True, False, False, True], device=device).unsqueeze(0)
            brace_leg = support_tripod & (
                (step_diag_03.unsqueeze(-1) & diag_mask_12) | (step_diag_12.unsqueeze(-1) & diag_mask_03)
            )

            teach_x = (base_sup_xy[..., 0] + torch.where(support_tripod, com_shift_x.unsqueeze(-1), 0.0)).clamp(-1.0, 1.0)
            teach_y = (
                base_sup_xy[..., 1] + torch.where(support_tripod & (~other_locked), com_shift_y.unsqueeze(-1), 0.0)
            ).clamp(-1.0, 1.0)
            teach_z = (teach_f43[..., 2] + torch.where(brace_leg, brace_z.unsqueeze(-1), 0.0)).clamp(-1.0, 1.0)
            teach_shifted = torch.stack((teach_x, teach_y, teach_z), dim=-1)

            target_f43 = torch.where(step_leg_oh.unsqueeze(-1), step_f43, teach_shifted)
            u_step = ((target_f43.reshape(-1, 12) - pose_term.current_goal_foot) / float(POSE_RESIDUAL_SCALE)).clamp(-0.96, 0.96)
            step_j = step_leg_oh.repeat_interleave(3, dim=-1)
            sup_j = support_tripod.repeat_interleave(3, dim=-1)
            u_out = torch.where(has_step.unsqueeze(-1), u_step, u_out)
            sample_w = torch.where(step_j, torch.full_like(sample_w, 14.0), torch.where(sup_j, torch.full_like(sample_w, 4.5), sample_w))

        # 2. Rigid physical obstacle (`jam_contacted`): compliant recoil onto q_true + 3.15 deg feeler preload
        if bool(ready_leg.any()):
            blocked_j = ready_j & pose_term.jam_joint_mask
            q_ideal = torch.where(blocked_j, q_true + 0.055 * pose_term.jam_dir, q_true)
            _, foot_ideal = pose_term.manifold.project_batch_rad(q_ideal)
            u_recoil = ((foot_ideal - pose_term.current_goal_foot) / float(POSE_RESIDUAL_SCALE)).clamp(-0.96, 0.96)
            u_out = torch.where(ready_j, u_recoil, u_out)
            sample_w = torch.where(ready_j, torch.full_like(sample_w, 18.0), sample_w)

        return u_out, sample_w

    def _equivariant_logits(raw_x: torch.Tensor) -> torch.Tensor:
        mir_x = raw_x[:, actor.obs_mirror_perm] * actor.obs_mirror_sign
        f_out = mlp(actor.obs_normalizer(raw_x))
        m_out = mlp(actor.obs_normalizer(mir_x))[:, actor.act_mirror_perm] * actor.act_mirror_sign
        return 0.5 * (f_out + m_out)

    saved_jam_prob = DEFAULT_JAM_EPISODE_PROB
    try:
        globals()["DEFAULT_JAM_EPISODE_PROB"] = 0.20
        # Refresh observation normalizers on splayed + carpet-snag + rigid-jam distribution
        actor.obs_normalizer.train(True)
        critic.obs_normalizer.train(True)
        wrapped.reset()
        with torch.no_grad():
            for _ in range(70):
                obs_td = wrapped.get_observations()
                actor.update_normalization(obs_td)
                critic.update_normalization(obs_td)
                u_warm, _ = _compute_expert_u(obs_td["actor"])
                wrapped.step(u_warm)
        if hasattr(actor, "symmetrize_normalizer"):
            actor.symmetrize_normalizer()
        actor.obs_normalizer.eval()
        critic.obs_normalizer.eval()
        for round_i, (rollout_steps, epochs, student_prob) in enumerate(
            ((240, 22, 0.0), (260, 22, 0.55), (260, 22, 0.85), (260, 22, 0.95))
        ):
            wrapped.reset()
            xs, ys, ws = [], [], []
            with torch.no_grad():
                for _ in range(rollout_steps):
                    obs_td = wrapped.get_observations()
                    obs_actor = obs_td["actor"]
                    u_exp, w_exp = _compute_expert_u(obs_actor)
                    y_logit = torch.atanh(u_exp.clamp(-0.97, 0.97))
                    xs.append(obs_actor.detach())
                    ys.append(y_logit.detach())
                    ws.append(w_exp.detach())
                    if student_prob > 0.0 and torch.rand((), device=device).item() < student_prob:
                        act = _equivariant_logits(obs_actor).clamp(-8.0, 8.0).tanh()
                    else:
                        act = u_exp
                    wrapped.step(act)

            x_all = torch.cat(xs, dim=0)
            y_all = torch.cat(ys, dim=0)
            w_all = torch.cat(ws, dim=0)
            y_tanh = y_all.tanh()
            n_s = x_all.shape[0]
            for _ in range(epochs):
                perm = torch.randperm(n_s, device=device)
                for start in range(0, n_s, 4096):
                    idx = perm[start : start + 4096]
                    pred = _equivariant_logits(x_all[idx])
                    wb = w_all[idx]
                    loss = (
                        wb * (0.20 * (pred - y_all[idx]).square() + 3.0 * (pred.tanh() - y_tanh[idx]).square())
                    ).sum() / wb.sum().clamp_min(1.0)
                    opt.zero_grad()
                    loss.backward()
                    torch.nn.utils.clip_grad_norm_(mlp.parameters(), 2.0)
                    opt.step()
            for g in opt.param_groups:
                g["lr"] *= 0.72
            with torch.no_grad():
                jam_mask = w_all > 5.0
                pred_sample = _equivariant_logits(x_all[:8192]).tanh()
                dagger_mae = float((pred_sample - y_tanh[:8192]).abs().mean().item())
                if bool(jam_mask.any()):
                    # Evaluate in chunks to keep GPU VRAM minimal
                    jm_errs = []
                    for start in range(0, n_s, 8192):
                        sl = slice(start, min(start + 8192, n_s))
                        m_sl = jam_mask[sl]
                        if bool(m_sl.any()):
                            p_sl = _equivariant_logits(x_all[sl]).tanh()
                            jm_errs.append((p_sl[m_sl] - y_tanh[sl][m_sl]).abs())
                    jam_dagger_mae = float(torch.cat(jm_errs).mean().item()) if jm_errs else 0.0
                else:
                    jam_dagger_mae = 0.0
    finally:
        globals()["DEFAULT_JAM_EPISODE_PROB"] = saved_jam_prob
        actor.obs_normalizer.train(True)
        critic.obs_normalizer.train(True)

    critic_mse = _calibrate_critic_on_actor(runner, wrapped, device, rollout_steps=200, sweeps=6)
    if hasattr(actor.distribution, "log_std_param"):
        actor.distribution.log_std_param.data.fill_(math.log(0.06))
    runner.alg.optimizer.state.clear()
    if torch.device(device).type == "cuda":
        torch.cuda.empty_cache()
    wrapped.reset()
    return {"dagger_action_mae": dagger_mae, "dagger_jam_action_mae": jam_dagger_mae, "calibrated_critic_mse": critic_mse}


def train(
    directory: str | Path,
    config: EnvironmentConfig,
    *,
    iterations: int,
    num_envs: int = 1024,
    device: str = "cuda:0",
    seed: int = 1,
    resume: str | Path | None = None,
    actor_hidden_dims=DEFAULT_HIDDEN_DIMS,
    critic_hidden_dims=DEFAULT_HIDDEN_DIMS,
    warmstart: bool = True,
):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    save_json(directory / "progress.json", {"state": "starting", "iterations": iterations, "steps": 0})
    env = None
    try:
        cfg, config = make_pose_env_cfg(config, num_envs=num_envs)
        cfg.seed = seed
        cfg.scene.terrain.terrain_generator.seed = seed

        agent = deepcopy(MicroduckRlCfg)
        agent.logger = "tensorboard"
        agent.experiment_name = "ainekio_neural_pose"
        agent.upload_model = False
        agent.actor.class_name = "experiments.freestyle.neural_pose.trainer:ResidualPoseMLPModel"
        agent.actor.hidden_dims = tuple(int(d) for d in actor_hidden_dims)
        agent.critic.hidden_dims = tuple(int(d) for d in critic_hidden_dims)
        agent.algorithm.entropy_coef = 0.0005
        agent.actor.distribution_cfg = {
            "class_name": "gateway.neural_gait.microduck_policy:FootGaussianDistribution",
            "init_std": 0.14,
            "std_type": "log",
        }
        agent.save_interval = max(1, math.ceil(1_000_000 / (num_envs * agent.num_steps_per_env)))

        manifest = {
            "kind": "neural-pose-mjlab",
            "recipe": RECIPE,
            "algorithm": "PPO",
            "schema": POSE_SCHEMA,
            "obs_size": POSE_OBS_SIZE,
            "actor_hidden_dims": list(agent.actor.hidden_dims),
            "critic_hidden_dims": list(agent.critic.hidden_dims),
            "foot_action_scale_mm": list(POSE_FOOT_SCALE_MM),
            "pose_residual_scale": POSE_RESIDUAL_SCALE,
            "rewards": {name: term.weight for name, term in cfg.rewards.items()},
            "environment": asdict(config),
            "environment_version": ENVIRONMENT_VERSION,
            "representation": representation_identity(),
            "training_mujoco_version": mujoco.__version__,
            "simulation_workers": num_envs,
            "seed": seed,
            "device": device,
            "policy": None,
        }
        save_json(directory / "manifest.json", manifest)
        save_json(directory / "environment.json", asdict(config))

        env = ManagerBasedRlEnv(cfg, device=device)
        wrapped = RslRlVecEnvWrapper(env, clip_actions=1.0)
        runner = AinekioOnPolicyRunner(wrapped, asdict(agent), str(directory / "learner"), device)

        actor_params = sum(p.numel() for p in runner.alg.actor.parameters())
        critic_params = sum(p.numel() for p in runner.alg.critic.parameters())
        manifest["actor_parameters"] = int(actor_params)
        manifest["critic_parameters"] = int(critic_params)

        if resume:
            ckpt_p = Path(resume)
            ckpt_file = ckpt_p if ckpt_p.is_file() else ckpt_p / "learner.pt"
            ckpt_path = str(ckpt_file)
            prev_manifest_path = ckpt_file.with_name("manifest.json")
            prev_scale = POSE_RESIDUAL_SCALE
            if prev_manifest_path.is_file():
                prev_scale = float(
                    json.loads(prev_manifest_path.read_text()).get("pose_residual_scale", POSE_RESIDUAL_SCALE)
                )
            raw_ckpt = torch.load(ckpt_path, map_location="cpu", weights_only=False)
            has_opt = "optimizer_state_dict" in raw_ckpt
            critic_sd = raw_ckpt.get("critic_state_dict", {})
            critic_compatible = (
                "mlp.0.weight" in critic_sd
                and tuple(critic_sd["mlp.0.weight"].shape)
                == tuple(runner.alg.critic.state_dict()["mlp.0.weight"].shape)
                and abs(prev_scale - POSE_RESIDUAL_SCALE) < 1e-6
            )
            runner.load(
                ckpt_path,
                load_cfg={
                    "actor": True,
                    "critic": critic_compatible,
                    "optimizer": False,
                    "iteration": False,
                    "rnd": False,
                },
                map_location=device,
            )
            if hasattr(runner.alg.actor, "symmetrize_normalizer"):
                runner.alg.actor.symmetrize_normalizer()
            manifest["resumed_from"] = str(ckpt_p)
            if abs(prev_scale - POSE_RESIDUAL_SCALE) > 1e-6:
                scale_ratio = prev_scale / POSE_RESIDUAL_SCALE
                with torch.no_grad():
                    runner.alg.actor.mlp[-1].weight.mul_(scale_ratio)
                    runner.alg.actor.mlp[-1].bias.mul_(scale_ratio)
            if not critic_compatible:
                save_json(
                    directory / "progress.json",
                    {"state": "dagger_jam_warmstart", "iterations": iterations, "steps": 0},
                )
                ws_info = _dagger_jam_warmstart(runner, wrapped, env, raw_ckpt, prev_scale, device)
                manifest["warmstart"] = {
                    "resumed_actor_from": str(ckpt_p),
                    "prev_residual_scale": prev_scale,
                    "new_residual_scale": POSE_RESIDUAL_SCALE,
                    **ws_info,
                }
            else:
                save_json(
                    directory / "progress.json",
                    {"state": "critic_recalibration", "iterations": iterations, "steps": 0},
                )
                critic_mse = _calibrate_critic_on_actor(runner, wrapped, device, rollout_steps=160, sweeps=4)
                if hasattr(runner.alg.actor.distribution, "log_std_param"):
                    runner.alg.actor.distribution.log_std_param.data.fill_(math.log(0.06))
                runner.alg.optimizer.state.clear()
                manifest["warmstart"] = {
                    "resumed_actor_from": str(ckpt_p),
                    "calibrated_critic_mse": critic_mse,
                }
            if hasattr(runner, "alg") and hasattr(runner.alg, "learning_rate"):
                runner.alg.learning_rate = 8.0e-5
                for group in runner.alg.optimizer.param_groups:
                    group["lr"] = runner.alg.learning_rate
            save_json(directory / "manifest.json", manifest)
        elif warmstart:
            save_json(directory / "progress.json", {"state": "warmstart", "iterations": iterations, "steps": 0})
            ws_info = _kinematic_warmstart(runner, wrapped, env, device)
            manifest["warmstart"] = ws_info
            save_json(directory / "manifest.json", manifest)

        original_log = runner.logger.log

        def progress(**values):
            original_log(**values)
            completed = values["it"] - values["start_it"] + 1
            ep_info = values.get("ep_infos") or []
            mae_vals = []
            gest_vals = []
            jam_vals = []
            for x in ep_info:
                src = x.get("log", x) if isinstance(x, dict) else {}
                if "Pose/joint_mae_deg" in src:
                    mae_vals.append(float(torch.as_tensor(src["Pose/joint_mae_deg"]).float().mean().item()))
                if "Pose/gesture_leg_mae_deg" in src:
                    gest_vals.append(float(torch.as_tensor(src["Pose/gesture_leg_mae_deg"]).float().mean().item()))
                if "Pose/jam_stall_deg" in src:
                    jam_vals.append(float(torch.as_tensor(src["Pose/jam_stall_deg"]).float().mean().item()))
            save_json(
                directory / "progress.json",
                {
                    "state": "training",
                    "iterations": completed,
                    "total_iterations": iterations,
                    "steps": completed * num_envs * agent.num_steps_per_env,
                    "rollout_seconds": values["collect_time"],
                    "update_seconds": values["learn_time"],
                    "joint_mae_deg": round(sum(mae_vals) / len(mae_vals), 3) if mae_vals else None,
                    "gesture_leg_mae_deg": round(sum(gest_vals) / len(gest_vals), 3) if gest_vals else None,
                    "jam_stall_deg": round(sum(jam_vals) / len(jam_vals), 3) if jam_vals else None,
                },
            )

        if hasattr(runner.logger, "git_status_repos"):
            runner.logger.git_status_repos = []
        runner.logger.log = progress
        runner.learn(iterations, init_at_random_ep_len=True)
        runner.save(str(directory / "learner.pt"))
        runner.export_policy_to_onnx(str(directory), "policy.onnx")

        from mjlab.rl.exporter_utils import attach_metadata_to_onnx

        attach_metadata_to_onnx(
            str(directory / "policy.onnx"),
            {
                "ainekio_schema": POSE_SCHEMA,
                "ainekio_action": "normalized-pose-foot-offsets-v1",
                "ainekio_foot_scale_mm": ",".join(str(x) for x in POSE_FOOT_SCALE_MM),
                "ainekio_residual_scale": str(POSE_RESIDUAL_SCALE),
                "checkpoint_sha256": hashlib.sha256((directory / "learner.pt").read_bytes()).hexdigest(),
            },
        )
        # Validate ONNX load & deterministic output immediately
        actor = NeuralPoseActor(directory / "policy.onnx")
        sample_obs = wrapped.get_observations()["actor"][:2].detach().cpu().numpy()
        pred, _ = actor.predict(sample_obs, deterministic=True)
        assert pred.shape == (2, 12) and np.isfinite(pred).all()

        steps = iterations * num_envs * agent.num_steps_per_env
        manifest.update(policy="policy.onnx", steps=steps, iterations=iterations)
        save_json(directory / "manifest.json", manifest)
        save_json(
            directory / "progress.json",
            {
                "state": "complete",
                "steps": steps,
                "iterations": iterations,
                "actor_parameters": int(actor_params),
                "policy": str(directory / "policy.onnx"),
            },
        )
    except BaseException as error:
        progress_path = directory / "progress.json"
        prev = json.loads(progress_path.read_text()) if progress_path.exists() else {}
        save_json(progress_path, dict(prev, state="error", error=str(error)))
        raise
    finally:
        if env is not None:
            env.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(DEFAULT_ENV_JSON))
    parser.add_argument("--directory", required=True)
    parser.add_argument("--iterations", type=int)
    parser.add_argument("--steps", type=int, default=16_000_000)
    parser.add_argument("--num-envs", type=int, default=1024)
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--resume")
    parser.add_argument("--actor-hidden-dims", default="512,256,128")
    parser.add_argument("--critic-hidden-dims", default="512,256,128")
    parser.add_argument("--no-warmstart", action="store_true")
    args = parser.parse_args()

    actor_dims = tuple(int(x) for x in args.actor_hidden_dims.split(",") if x.strip())
    critic_dims = tuple(int(x) for x in args.critic_hidden_dims.split(",") if x.strip())
    config = EnvironmentConfig(**json.loads(Path(args.config).read_text()))
    iterations = (
        args.iterations
        if args.iterations is not None
        else math.ceil(args.steps / (args.num_envs * MicroduckRlCfg.num_steps_per_env))
    )
    train(
        args.directory,
        config,
        iterations=iterations,
        num_envs=args.num_envs,
        device=args.device,
        seed=args.seed,
        resume=args.resume,
        actor_hidden_dims=actor_dims,
        critic_hidden_dims=critic_dims,
        warmstart=not args.no_warmstart,
    )


if __name__ == "__main__":
    main()
