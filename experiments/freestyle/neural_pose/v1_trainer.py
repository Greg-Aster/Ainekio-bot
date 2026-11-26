"""GPU MuJoCo (mjlab) PPO trainer, evaluator & ONNX exporter for V1 8-DOF Neural Pose.

Trains a left-right reflection-equivariant, goal-anchored residual MLP policy
matching experiments/freestyle/neural_pose/v1_contract.py:
  - Schema: "ainekio-v1-neural-pose-v1"
  - Actor obs: 54 features x 15 causal frames = 810 floats (newest frame at [0..53])
  - Architecture: goal_norm + residual_scale * 0.5 * (MLP(x) + M_act(MLP(M_obs(x))))
  - Output: 8 normalized [-1, 1] joint position targets covering full mechanical range
    (hips [-45, +45] deg, knees [-15, +115] deg) at full MG90S capability (600 deg/s).

All evaluation metrics are MuJoCo simulation evidence (CAD-estimated 0.376 kg mass,
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
from gateway.neural_gait.microduck import (
    AinekioOnPolicyRunner,
    LearningSlopeCfg,
    LearningWaveCfg,
    MG90SActuatorCfg,
    mg90s_force_fields,
)
from gateway.neural_gait.v1_environment import (
    V1_JOINTS,
    V1_LEGS,
    build_v1_xml,
    load_v1_geometry,
)
from experiments.freestyle.neural_pose.v1_contract import (
    V1_CANONICAL_POSTURES_DEG,
    V1_CANONICAL_SUPPORT,
    V1_JOINT_CENTER_DEG,
    V1_JOINT_HALF_SPAN_DEG,
    V1_JOINT_MAX_DEG,
    V1_JOINT_MIN_DEG,
    V1_POSE_FEATURES,
    V1_POSE_GOAL_SLICE,
    V1_POSE_OBS_SIZE,
    V1_POSE_SAMPLES,
    V1_POSE_SCHEMA,
    deg_to_norm,
    norm_to_deg,
    v1_pose_mirror_tables,
)

V1_POSE_RESIDUAL_SCALE = 0.35
V1_POSE_DEFAULT_HIDDEN_DIMS = (256, 128, 64)


def _register_v1_mirror_buffers(module: torch.nn.Module, *, persistent: bool) -> None:
    obs_p, obs_s, act_p, act_s = v1_pose_mirror_tables()
    module.register_buffer("obs_mirror_perm", torch.tensor(obs_p, dtype=torch.long), persistent=persistent)
    module.register_buffer("obs_mirror_sign", torch.tensor(obs_s, dtype=torch.float32), persistent=persistent)
    module.register_buffer("act_mirror_perm", torch.tensor(act_p, dtype=torch.long), persistent=persistent)
    module.register_buffer("act_mirror_sign", torch.tensor(act_s, dtype=torch.float32), persistent=persistent)


class _V1ResidualTorchMLPModel(_TorchMLPModel):
    def __init__(self, model: MLPModel, residual_scale: float = V1_POSE_RESIDUAL_SCALE) -> None:
        super().__init__(model)
        self.residual_scale = float(residual_scale)
        _register_v1_mirror_buffers(self, persistent=True)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        goal_norm = x[:, V1_POSE_GOAL_SLICE]
        x_mir = x[:, self.obs_mirror_perm] * self.obs_mirror_sign
        u_fwd = super().forward(x)
        u_mir = super().forward(x_mir)[:, self.act_mirror_perm] * self.act_mirror_sign
        u = 0.5 * (u_fwd + u_mir)
        return torch.clamp(goal_norm + self.residual_scale * u, -1.0, 1.0)


class _V1ResidualOnnxMLPModel(_OnnxMLPModel):
    def __init__(self, model: MLPModel, verbose: bool, residual_scale: float = V1_POSE_RESIDUAL_SCALE) -> None:
        super().__init__(model, verbose)
        self.residual_scale = float(residual_scale)
        _register_v1_mirror_buffers(self, persistent=True)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        goal_norm = x[:, V1_POSE_GOAL_SLICE]
        x_mir = x[:, self.obs_mirror_perm] * self.obs_mirror_sign
        u_fwd = super().forward(x)
        u_mir = super().forward(x_mir)[:, self.act_mirror_perm] * self.act_mirror_sign
        u = 0.5 * (u_fwd + u_mir)
        return torch.clamp(goal_norm + self.residual_scale * u, -1.0, 1.0)


class ResidualV1PoseMLPModel(MLPModel):
    """Left-right reflection-equivariant goal-anchored residual MLP for V1 8-DOF Neural Pose."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        _register_v1_mirror_buffers(self, persistent=False)

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
        return _V1ResidualTorchMLPModel(self, residual_scale=V1_POSE_RESIDUAL_SCALE)

    def as_onnx(self, verbose: bool) -> torch.nn.Module:
        self.symmetrize_normalizer()
        return _V1ResidualOnnxMLPModel(self, verbose, residual_scale=V1_POSE_RESIDUAL_SCALE)


@dataclass(kw_only=True)
class V1PoseActionCfg(ActionTermCfg):
    residual_scale: float = V1_POSE_RESIDUAL_SCALE
    sensor_noise: bool = True

    def build(self, env):
        return V1PoseAction(self, env)


class V1PoseAction(ActionTerm):
    """Goal-anchored 8-DOF pose action, goal sampler, and 54x15 proprioceptive buffer."""

    def __init__(self, cfg: V1PoseActionCfg, env) -> None:
        super().__init__(cfg, env)
        self.cfg = cfg
        dev = env.device
        self.joint_ids, _ = self._entity.find_joints(V1_JOINTS, preserve_order=True)
        self.foot_site_ids, _ = self._entity.find_sites(
            tuple(f"{leg}_foot" for leg in V1_LEGS), preserve_order=True
        )
        self.center_rad = torch.tensor([math.radians(v) for v in V1_JOINT_CENTER_DEG], dtype=torch.float32, device=dev)
        self.span_rad = torch.tensor([math.radians(v) for v in V1_JOINT_HALF_SPAN_DEG], dtype=torch.float32, device=dev)
        self.lo_rad = torch.tensor([math.radians(v) for v in V1_JOINT_MIN_DEG], dtype=torch.float32, device=dev)
        self.hi_rad = torch.tensor([math.radians(v) for v in V1_JOINT_MAX_DEG], dtype=torch.float32, device=dev)

        # Canonical posture bank on GPU
        canon_names = list(V1_CANONICAL_POSTURES_DEG.keys())
        self.canon_deg = torch.tensor(
            [V1_CANONICAL_POSTURES_DEG[k] for k in canon_names], dtype=torch.float32, device=dev
        )
        self.canon_sup = torch.tensor(
            [V1_CANONICAL_SUPPORT[k] for k in canon_names], dtype=torch.float32, device=dev
        )

        n = env.num_envs
        self._raw = torch.zeros((n, 8), dtype=torch.float32, device=dev)
        self.applied_norm = torch.zeros((n, 8), dtype=torch.float32, device=dev)
        self.prev_applied_norm = torch.zeros((n, 8), dtype=torch.float32, device=dev)
        self.targets_rad = torch.zeros((n, 8), dtype=torch.float32, device=dev)

        self.goal_rad = torch.zeros((n, 8), dtype=torch.float32, device=dev)
        self.goal_norm = torch.zeros((n, 8), dtype=torch.float32, device=dev)
        self.leg_support = torch.ones((n, 4), dtype=torch.float32, device=dev)
        self.speed_scale = torch.ones((n, 1), dtype=torch.float32, device=dev)
        self.goal_timer = torch.zeros(n, dtype=torch.long, device=dev)
        self.usable_mask = torch.ones((n, 8), dtype=torch.float32, device=dev)

        self.history = torch.zeros((n, V1_POSE_SAMPLES, V1_POSE_FEATURES), dtype=torch.float32, device=dev)
        self.prev_lin_vel_b = torch.zeros((n, 3), dtype=torch.float32, device=dev)
        self.last_obs_step = -1
        self.sensor_noise = bool(cfg.sensor_noise)
        self.reset(None)

    @property
    def action_dim(self) -> int:
        return 8

    @property
    def raw_action(self) -> torch.Tensor:
        return self._raw

    def _sample_goals(self, ids: torch.Tensor) -> None:
        n = len(ids)
        if n == 0:
            return
        dev = self._env.device
        # 50% canonical postures, 30% smooth symmetric/bilateral poses, 20% single-leg lifts/waves
        r = torch.rand(n, device=dev)
        c_idx = torch.randint(0, len(self.canon_deg), (n,), device=dev)
        goal_deg = self.canon_deg[c_idx].clone()
        sup = self.canon_sup[c_idx].clone()

        # Random bilateral / asymmetric smooth poses
        rand_mask = (r >= 0.50) & (r < 0.80)
        n_rand = int(rand_mask.sum().item())
        if n_rand > 0:
            hips = (torch.rand((n_rand, 4), device=dev) * 2.0 - 1.0) * 35.0
            knees = -8.0 + torch.rand((n_rand, 4), device=dev) * 88.0
            goal_deg[rand_mask, :4] = hips
            goal_deg[rand_mask, 4:] = knees
            sup[rand_mask] = 1.0

        # Random single-leg lift / gesture poses (3 stance legs + 1 lifted gesturing leg)
        lift_mask = r >= 0.80
        n_lift = int(lift_mask.sum().item())
        if n_lift > 0:
            base_hips = (torch.rand((n_lift, 4), device=dev) * 2.0 - 1.0) * 18.0
            base_knees = 5.0 + torch.rand((n_lift, 4), device=dev) * 25.0
            lifted_leg = torch.randint(0, 4, (n_lift,), device=dev)
            # Map V1 leg index (0:FR, 1:RR, 2:FL, 3:RL) to (hip_j, knee_j)
            hip_map = torch.tensor([0, 1, 2, 3], device=dev)
            knee_map = torch.tensor([5, 4, 6, 7], device=dev)
            row_i = torch.arange(n_lift, device=dev)
            l_hip = hip_map[lifted_leg]
            l_knee = knee_map[lifted_leg]
            base_hips[row_i, l_hip] = (torch.rand(n_lift, device=dev) * 2.0 - 1.0) * 38.0
            base_knees[row_i, l_knee - 4] = 68.0 + torch.rand(n_lift, device=dev) * 38.0
            goal_deg[lift_mask, :4] = base_hips
            goal_deg[lift_mask, 4:] = base_knees
            l_sup = torch.ones((n_lift, 4), device=dev)
            l_sup[row_i, lifted_leg] = 0.0
            sup[lift_mask] = l_sup

        g_rad = torch.deg2rad(goal_deg).clamp(self.lo_rad, self.hi_rad)
        g_norm = ((g_rad - self.center_rad) / self.span_rad).clamp(-1.0, 1.0)
        self.goal_rad[ids] = g_rad
        self.goal_norm[ids] = g_norm
        self.leg_support[ids] = sup
        # Full speed (1.0) in 60% of transitions, explicit slower request [0.25..0.9] in 40%
        fast = torch.rand((n, 1), device=dev) < 0.60
        slow_val = 0.25 + 0.65 * torch.rand((n, 1), device=dev)
        self.speed_scale[ids] = torch.where(fast, torch.ones_like(slow_val), slow_val)
        self.goal_timer[ids] = torch.randint(120, 225, (n,), device=dev)  # 2.4..4.5 s per goal

    def reset(self, env_ids=None) -> None:
        dev = self._env.device
        ids = torch.arange(self._env.num_envs, device=dev) if env_ids is None else env_ids
        if len(ids) == 0:
            return
        self._sample_goals(ids)
        stand_norm = torch.tensor(deg_to_norm([0.0] * 8), dtype=torch.float32, device=dev)
        self._raw[ids] = 0.0
        self.applied_norm[ids] = stand_norm
        self.prev_applied_norm[ids] = stand_norm
        self.targets_rad[ids] = 0.0
        self.prev_lin_vel_b[ids] = 0.0
        # Simulate occasional 4th-wire dropout (5% of joints unavailable) so policy stays robust
        if self.sensor_noise:
            self.usable_mask[ids] = (torch.rand((len(ids), 8), device=dev) > 0.05).float()
        else:
            self.usable_mask[ids] = 1.0
        # Prime history with initial frame
        self.history[ids] = 0.0

    def process_actions(self, actions: torch.Tensor) -> None:
        # Advance goal timer and resample goals mid-episode for smooth multi-pose transitions
        self.goal_timer -= 1
        expired = torch.nonzero(self.goal_timer <= 0, as_tuple=False).squeeze(-1)
        if len(expired) > 0:
            self._sample_goals(expired)

        self.prev_applied_norm.copy_(self.applied_norm)
        u = torch.nan_to_num(actions, nan=0.0, posinf=1.0, neginf=-1.0).clamp(-1.0, 1.0)
        self._raw.copy_(u)
        desired_norm = torch.clamp(self.goal_norm + self.cfg.residual_scale * u, -1.0, 1.0)
        # Honor owner's requested speed_scale cleanly (at speed_scale=1.0 -> full MG90S 600 deg/s!)
        max_step_rad = math.radians(600.0) * float(self._env.step_dt) * self.speed_scale
        desired_rad = torch.clamp(self.center_rad + desired_norm * self.span_rad, self.lo_rad, self.hi_rad)
        cur_rad = self.targets_rad
        delta = (desired_rad - cur_rad).clamp(-max_step_rad, max_step_rad)
        self.targets_rad = torch.clamp(cur_rad + delta, self.lo_rad, self.hi_rad)
        self.applied_norm = ((self.targets_rad - self.center_rad) / self.span_rad).clamp(-1.0, 1.0)

    def apply_actions(self) -> None:
        self._entity.set_joint_position_target(self.targets_rad, joint_ids=self.joint_ids)

    def _build_frame(self) -> torch.Tensor:
        robot = self._entity
        q_true = robot.data.joint_pos[:, self.joint_ids]
        dq_true = robot.data.joint_vel[:, self.joint_ids]
        if self.sensor_noise:
            q_meas = q_true + torch.randn_like(q_true) * 0.012
            dq_meas = dq_true + torch.randn_like(dq_true) * 0.16
        else:
            q_meas = q_true
            dq_meas = dq_true
        # Where 4th-wire is unavailable, fall back to commanded target & zero velocity (exact match to contract)
        q_obs = torch.where(self.usable_mask > 0.5, q_meas, self.targets_rad)
        dq_obs = torch.where(self.usable_mask > 0.5, dq_meas, torch.zeros_like(dq_meas))

        gyro = robot.data.root_link_ang_vel_b
        lin_vel_b = robot.data.root_link_lin_vel_b
        proj_grav = robot.data.projected_gravity_b
        dt = float(self._env.step_dt)
        lin_acc_b = (lin_vel_b - self.prev_lin_vel_b) / max(dt, 1e-4)
        self.prev_lin_vel_b.copy_(lin_vel_b)
        accel_g = (lin_acc_b / 9.81 - proj_grav).clamp(-4.0, 4.0)

        if self.sensor_noise:
            gyro = gyro + torch.randn_like(gyro) * 0.035
            accel_g = accel_g + torch.randn_like(accel_g) * 0.025
            proj_grav = proj_grav + torch.randn_like(proj_grav) * 0.012
            proj_grav = proj_grav / proj_grav.norm(dim=-1, keepdim=True).clamp_min(1e-6)

        frame = torch.cat(
            [
                q_obs,
                dq_obs,
                self.usable_mask,
                gyro,
                accel_g,
                proj_grav,
                self.goal_norm,
                self.leg_support,
                self.speed_scale,
                self.applied_norm,
            ],
            dim=-1,
        )
        return torch.nan_to_num(frame, nan=0.0, posinf=0.0, neginf=0.0)

    def observations(self) -> torch.Tensor:
        step = int(getattr(self._env, "common_step_counter", 0))
        if step != self.last_obs_step:
            frame = self._build_frame()
            self.history = torch.roll(self.history, shifts=1, dims=1)
            self.history[:, 0, :] = frame
            self.last_obs_step = step
        return self.history.reshape(self._env.num_envs, V1_POSE_OBS_SIZE)


def _pose_actor_obs(env) -> torch.Tensor:
    return env.action_manager.get_term("pose").observations()


def _pose_critic_priv(env) -> torch.Tensor:
    robot = env.scene["robot"]
    term = env.action_manager.get_term("pose")
    q_err = robot.data.joint_pos[:, term.joint_ids] - term.goal_rad
    lin_vel = robot.data.root_link_lin_vel_b
    contact = env.scene["feet_ground_contact"].data.found.float()
    root_z = robot.data.root_link_pos_w[:, 2:3]
    return torch.nan_to_num(torch.cat([q_err, lin_vel, contact, root_z], dim=-1), nan=0.0)


# =============================================================================
# V1 Neural Pose Rewards & Terminations
# =============================================================================
def _rew_pose_tracking(env) -> torch.Tensor:
    robot = env.scene["robot"]
    term = env.action_manager.get_term("pose")
    q = robot.data.joint_pos[:, term.joint_ids]
    err_sq = torch.mean((q - term.goal_rad) ** 2, dim=-1)
    # Sharp exponential tracking reward + fine precision bonus near goal (< 3 deg)
    return 0.65 * torch.exp(-err_sq / 0.04) + 0.35 * torch.exp(-err_sq / 0.004)


def _rew_pose_upright(env) -> torch.Tensor:
    # Keep chassis upright (allowing natural pitch for bow/sit/lay_down, penalizing roll & flip!)
    pg = env.scene["robot"].data.projected_gravity_b
    # Penalize lateral roll strongly and extreme pitch
    return (2.0 * pg[:, 1] ** 2 + 0.5 * torch.clamp(torch.abs(pg[:, 0]) - 0.35, min=0.0) ** 2).clamp(0.0, 2.0)


def _rew_support_contact(env) -> torch.Tensor:
    # Reward stance legs maintaining ground contact and lifted legs staying airborne
    term = env.action_manager.get_term("pose")
    in_contact = (env.scene["feet_ground_contact"].data.found > 0).float()
    sup = term.leg_support
    match = sup * in_contact + (1.0 - sup) * (1.0 - in_contact)
    return torch.mean(match, dim=-1)


def _rew_pose_stability(env) -> torch.Tensor:
    robot = env.scene["robot"]
    v = robot.data.root_link_lin_vel_b
    w = robot.data.root_link_ang_vel_b
    return (torch.sum(v * v, dim=-1) + 0.1 * torch.sum(w * w, dim=-1)).clamp(0.0, 4.0)


def _rew_pose_action_rate(env) -> torch.Tensor:
    term = env.action_manager.get_term("pose")
    return torch.sum((term.applied_norm - term.prev_applied_norm) ** 2, dim=-1).clamp(0.0, 4.0)


def _rew_pose_residual_reg(env) -> torch.Tensor:
    term = env.action_manager.get_term("pose")
    return torch.mean(term.raw_action ** 2, dim=-1)


def _term_pose_flipped(env) -> torch.Tensor:
    pg_z = env.scene["robot"].data.projected_gravity_b[:, 2]
    z = env.scene["robot"].data.root_link_pos_w[:, 2]
    return ~torch.isfinite(pg_z) | ~torch.isfinite(z) | (pg_z > -0.25)


def _randomize_pose_actuators(env, env_ids):
    ids = torch.arange(env.num_envs, device=env.device) if env_ids is None else env_ids
    if len(ids) == 0:
        return
    act = env.scene["robot"].actuators[0]
    if not hasattr(act, "effort_scale") or act.effort_scale is None:
        act.effort_scale = torch.ones((env.num_envs, 8), dtype=torch.float32, device=env.device)
    act.effort_scale[ids] = 0.78 + 0.32 * torch.rand((len(ids), 8), device=env.device)


def _push_pose_robot(env, env_ids):
    ids = torch.arange(env.num_envs, device=env.device) if env_ids is None else env_ids
    if len(ids) == 0:
        return
    robot = env.scene["robot"]
    vel = robot.data.root_link_vel_w[ids].clone()
    vel[:, 0:2] += (torch.rand((len(ids), 2), device=env.device) * 2.0 - 1.0) * 0.12
    vel[:, 3:6] += (torch.rand((len(ids), 3), device=env.device) * 2.0 - 1.0) * 0.5
    robot.write_root_link_velocity_to_sim(vel, env_ids=ids)


def make_v1_pose_env_cfg(num_envs: int = 2048, *, play: bool = False):
    geo = load_v1_geometry()
    stand_z = float(geo["standing_root_height_mm"]) * 1e-3
    xml = ET.fromstring(build_v1_xml(geo, include_floor=False))
    for tag in ("actuator", "option", "sensor"):
        el = xml.find(tag)
        if el is not None:
            xml.remove(el)
    for geom in xml.iter("geom"):
        geom.set("group", "1")
    foot_geoms = tuple(f"{leg}_foot_geom" for leg in V1_LEGS)
    for gname in foot_geoms:
        g = xml.find(f".//geom[@name='{gname}']")
        if g is not None:
            g.set("priority", "1")
    spec_xml = ET.tostring(xml, encoding="unicode")

    cfg = make_microduck_velocity_env_cfg(play=play, rough=False)
    lag = 5
    cfg.scene.entities = {
        "robot": EntityCfg(
            spec_fn=lambda: mujoco.MjSpec.from_string(spec_xml),
            init_state=EntityCfg.InitialStateCfg(
                pos=(0.0, 0.0, stand_z + 0.002),
                joint_pos={j: 0.0 for j in V1_JOINTS},
            ),
            articulation=EntityArticulationInfoCfg(
                actuators=(
                    MG90SActuatorCfg(
                        target_names_expr=V1_JOINTS,
                        stiffness=2.0,
                        damping=0.035,
                        effort_limit=0.18,
                        speed_rad_s=10.47,
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
            primary=ContactMatch(mode="geom", pattern=foot_geoms, entity="robot"),
            secondary=ContactMatch(mode="body", pattern="terrain"),
            fields=("found", "force"),
            reduce="netforce",
            num_slots=1,
            track_air_time=False,
        ),
    )
    cfg.scene.num_envs = num_envs
    if not play:
        cfg.scene.terrain.terrain_type = "generator"
        cfg.scene.terrain.max_init_terrain_level = 1
        cfg.scene.terrain.terrain_generator = TerrainGeneratorCfg(
            size=(6.0, 6.0),
            border_width=10.0,
            num_rows=3,
            num_cols=3,
            add_lights=False,
            curriculum=False,
            sub_terrains={
                "flat": terrain_gen.BoxFlatTerrainCfg(proportion=0.60),
                "slope": LearningSlopeCfg(
                    proportion=0.25,
                    slope_range=(0.0, math.tan(math.radians(6.0))),
                    platform_width=0.6,
                    vertical_scale=0.001,
                ),
                "waves": LearningWaveCfg(
                    proportion=0.15,
                    amplitude_range=(0.002, 0.008),
                    num_waves=3,
                    horizontal_scale=0.10,
                    vertical_scale=0.001,
                ),
            },
        )
    else:
        cfg.scene.terrain.terrain_type = "plane"
        cfg.scene.terrain.terrain_generator = None

    cfg.viewer.body_name = "torso"
    cfg.actions = {"pose": V1PoseActionCfg(entity_name="robot", sensor_noise=not play)}
    cfg.observations = {
        "actor": ObservationGroupCfg(
            terms={"proprio": ObservationTermCfg(func=_pose_actor_obs)},
            concatenate_terms=True,
            enable_corruption=False,
        ),
        "critic": ObservationGroupCfg(
            terms={
                "proprio": ObservationTermCfg(func=_pose_actor_obs),
                "priv": ObservationTermCfg(func=_pose_critic_priv),
            },
            concatenate_terms=True,
            enable_corruption=False,
        ),
    }
    cfg.commands = {}

    mass_dr = deepcopy(cfg.events["randomize_mass_inertia"])
    com_dr = deepcopy(cfg.events["randomize_com"])
    fric_dr = deepcopy(cfg.events["foot_friction"])
    reset_base = deepcopy(cfg.events["reset_base"])
    reset_joints = deepcopy(cfg.events["reset_robot_joints"])
    cfg.events = {
        "reset_base": reset_base,
        "reset_robot_joints": reset_joints,
        "mg90s_force_fields": EventTermCfg(func=mg90s_force_fields, mode="startup"),
    }
    if not play:
        mass_dr.params["asset_cfg"].body_names = (".*",)
        mass_dr.params["alpha_range"] = (-0.14, 0.14)
        com_dr.params["asset_cfg"].body_names = ("torso",)
        com_dr.params["ranges"] = {0: (-0.012, 0.012), 1: (-0.008, 0.008), 2: (-0.005, 0.005)}
        fric_dr.params["asset_cfg"] = SceneEntityCfg("robot", geom_names=foot_geoms)
        fric_dr.params["ranges"] = (0.45, 1.35)
        cfg.events["randomize_mass_inertia"] = mass_dr
        cfg.events["randomize_com"] = com_dr
        cfg.events["foot_friction"] = fric_dr
        cfg.events["randomize_actuators"] = EventTermCfg(func=_randomize_pose_actuators, mode="reset")
        cfg.events["push_robot"] = EventTermCfg(
            func=_push_pose_robot, mode="interval", interval_range_s=(3.0, 5.5)
        )

    cfg.rewards = {
        "pose_tracking": RewardTermCfg(func=_rew_pose_tracking, weight=5.0),
        "support_contact": RewardTermCfg(func=_rew_support_contact, weight=1.5),
        "pose_upright": RewardTermCfg(func=_rew_pose_upright, weight=-2.5),
        "pose_stability": RewardTermCfg(func=_rew_pose_stability, weight=-0.6),
        "action_rate": RewardTermCfg(func=_rew_pose_action_rate, weight=-0.04),
        "residual_reg": RewardTermCfg(func=_rew_pose_residual_reg, weight=-0.02),
    }
    cfg.curriculum = {}
    cfg.terminations = {
        "time_out": TerminationTermCfg(func=env_mdp.time_out, time_out=True),
        "flipped": TerminationTermCfg(func=_term_pose_flipped),
    }

    cfg.sim.mujoco.timestep = 0.002
    cfg.sim.mujoco.integrator = "implicitfast"
    cfg.sim.mujoco.solver = "newton"
    cfg.sim.mujoco.iterations = 20
    cfg.sim.nconmax = 96
    cfg.sim.njmax = 256
    cfg.decimation = 10
    cfg.episode_length_s = 12.0
    return cfg


def train_v1_pose(
    directory: Path,
    *,
    iterations: int = 250,
    num_envs: int = 2048,
    device: str = "cuda:0",
    seed: int = 7,
    hidden_dims: tuple[int, int, int] = V1_POSE_DEFAULT_HIDDEN_DIMS,
) -> Path:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    save_json(directory / "progress.json", {"state": "starting", "iterations": iterations, "steps": 0})
    env = None
    try:
        cfg = make_v1_pose_env_cfg(num_envs=num_envs, play=False)
        cfg.seed = seed
        if cfg.scene.terrain.terrain_generator is not None:
            cfg.scene.terrain.terrain_generator.seed = seed

        agent = deepcopy(MicroduckRlCfg)
        agent.logger = "tensorboard"
        agent.experiment_name = "ainekio_v1_neural_pose"
        agent.upload_model = False
        agent.actor.class_name = "experiments.freestyle.neural_pose.v1_trainer:ResidualV1PoseMLPModel"
        agent.actor.hidden_dims = tuple(int(d) for d in hidden_dims)
        agent.critic.hidden_dims = (256, 128, 64)
        agent.actor.distribution_cfg = {
            "class_name": "gateway.neural_gait.microduck_policy:FootGaussianDistribution",
            "init_std": 0.45,
            "std_type": "log",
        }
        agent.save_interval = max(1, iterations // 4)

        geo = load_v1_geometry()
        manifest = {
            "kind": "v1-neural-pose-mjlab",
            "model": "v1-8servo",
            "geometry_id": geo["geometry_id"],
            "mass_kg": geo["mass_kg"],
            "mass_measured": geo["mass_measured"],
            "schema": V1_POSE_SCHEMA,
            "action": "normalized-v1-joint-targets-v1",
            "residual_scale": V1_POSE_RESIDUAL_SCALE,
            "actor_hidden_dims": list(hidden_dims),
            "reflection_equivariant": True,
            "num_envs": num_envs,
            "iterations": iterations,
            "seed": seed,
            "device": device,
            "physical_qualified": False,
        }
        save_json(directory / "manifest.json", manifest)

        env = ManagerBasedRlEnv(cfg, device=device)
        wrapped = RslRlVecEnvWrapper(env, clip_actions=1.0)
        runner = AinekioOnPolicyRunner(wrapped, asdict(agent), str(directory / "learner"), device)

        original_log = runner.logger.log

        def _progress(**values):
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
        runner.save(str(directory / "learner.pt"))

        onnx_path = directory / "policy.onnx"
        runner.export_policy_to_onnx(str(directory), "policy.onnx")
        from mjlab.rl.exporter_utils import attach_metadata_to_onnx

        attach_metadata_to_onnx(
            str(onnx_path),
            {
                "ainekio_model": "v1-8servo",
                "ainekio_geometry_id": geo["geometry_id"],
                "ainekio_schema": V1_POSE_SCHEMA,
                "ainekio_action": "normalized-v1-joint-targets-v1",
                "ainekio_residual_scale": str(V1_POSE_RESIDUAL_SCALE),
                "ainekio_reflection_equivariant": "true",
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


def evaluate_v1_pose_policy(onnx_path: Path, output_json: Path | None = None) -> dict:
    """Evaluate a trained V1 Neural Pose ONNX policy across all canonical postures + equivariance."""
    import onnxruntime as ort

    geo = load_v1_geometry()
    model = mujoco.MjModel.from_xml_string(build_v1_xml(geo))
    sess = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
    in_name = sess.get_inputs()[0].name
    out_name = sess.get_outputs()[0].name

    qpos_ids = [model.jnt_qposadr[mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, j)] for j in V1_JOINTS]
    qvel_ids = [model.jnt_dofadr[mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, j)] for j in V1_JOINTS]

    # 1. Exact reflection equivariance check on random inputs
    obs_p, obs_s, act_p, act_s = v1_pose_mirror_tables()
    rng = np.random.default_rng(123)
    x_rand = rng.uniform(-0.5, 0.5, size=(16, V1_POSE_OBS_SIZE)).astype(np.float32)
    x_mir = x_rand[:, obs_p] * np.array(obs_s, dtype=np.float32)
    y_fwd = np.vstack([sess.run([out_name], {in_name: x_rand[i : i + 1]})[0] for i in range(len(x_rand))])
    y_mir = (
        np.vstack([sess.run([out_name], {in_name: x_mir[i : i + 1]})[0] for i in range(len(x_mir))])[:, act_p]
        * np.array(act_s, dtype=np.float32)
    )
    equivariance_max_err = float(np.max(np.abs(y_fwd - y_mir)))

    # 2. Closed-loop CPU MuJoCo rollout across all canonical postures
    posture_results = {}
    for pname, goal_deg in V1_CANONICAL_POSTURES_DEG.items():
        support = V1_CANONICAL_SUPPORT[pname]
        goal_norm = np.array(deg_to_norm(goal_deg), dtype=np.float32)
        goal_arr = np.array(goal_deg, dtype=np.float32)
        data = mujoco.MjData(model)
        mujoco.mj_forward(model, data)
        hist = np.zeros((V1_POSE_SAMPLES, V1_POSE_FEATURES), dtype=np.float32)
        prev_act = np.array(deg_to_norm([0.0] * 8), dtype=np.float32)
        prev_vb = np.zeros(3, dtype=np.float32)
        survived = True
        peak_spd = 0.0
        for step in range(150):  # 3.0 s @ 50 Hz
            q_rad = np.array([data.qpos[i] for i in qpos_ids], dtype=np.float32)
            dq_rad = np.array([data.qvel[i] for i in qvel_ids], dtype=np.float32)
            peak_spd = max(peak_spd, float(np.rad2deg(np.abs(dq_rad)).max()))
            quat = data.qpos[3:7].astype(np.float64)
            w, x, y, z = quat
            R = np.array([
                [1 - 2*(y*y + z*z), 2*(x*y - w*z), 2*(x*z + w*y)],
                [2*(x*y + w*z), 1 - 2*(x*x + z*z), 2*(y*z - w*x)],
                [2*(x*z - w*y), 2*(y*z + w*x), 1 - 2*(x*x + y*y)],
            ])
            vb = (R.T @ data.qvel[0:3]).astype(np.float32)
            gyro = (R.T @ data.qvel[3:6]).astype(np.float32)
            proj_grav = np.array([-2*(x*z - w*y), -2*(y*z + w*x), 1 - 2*(w*w + z*z)], dtype=np.float32)
            acc_g = np.clip(((vb - prev_vb) / 0.02) / 9.81 - proj_grav, -4.0, 4.0)
            prev_vb = vb.copy()
            frame = np.concatenate([
                q_rad, dq_rad, np.ones(8, dtype=np.float32),
                gyro, acc_g, proj_grav, goal_norm,
                np.array(support, dtype=np.float32),
                np.array([1.0], dtype=np.float32),
                prev_act,
            ])
            hist = np.roll(hist, 1, axis=0)
            hist[0] = frame
            out_norm = np.clip(sess.run([out_name], {in_name: hist.reshape(1, V1_POSE_OBS_SIZE)})[0][0], -1.0, 1.0)
            prev_act = out_norm.astype(np.float32)
            target_deg = norm_to_deg(out_norm)
            data.ctrl[:] = np.deg2rad(target_deg)
            for _ in range(10):
                jv = np.array([data.qvel[i] for i in qvel_ids], dtype=np.float64)
                for idx in range(8):
                    model.actuator_forcerange[idx, 0] = -0.18 * max(0.0, 1.0 + jv[idx] / 10.47)
                    model.actuator_forcerange[idx, 1] = 0.18 * max(0.0, 1.0 - jv[idx] / 10.47)
                mujoco.mj_step(model, data)
            if proj_grav[2] > -0.25:
                survived = False
                break
        final_deg = np.rad2deg([data.qpos[i] for i in qpos_ids])
        mae_deg = float(np.mean(np.abs(final_deg - goal_arr)))
        max_err_deg = float(np.max(np.abs(final_deg - goal_arr)))
        posture_results[pname] = {
            "survived": survived,
            "final_mae_deg": round(mae_deg, 2),
            "final_max_err_deg": round(max_err_deg, 2),
            "peak_joint_speed_deg_s": round(peak_spd, 1),
            "final_root_z_mm": round(float(data.qpos[2] * 1e3), 2),
        }

    report = {
        "model": "v1-8servo",
        "geometry_id": geo["geometry_id"],
        "mass_kg": geo["mass_kg"],
        "mass_measured": geo["mass_measured"],
        "reflection_equivariance_max_err": equivariance_max_err,
        "basis": "MuJoCo CPU simulation with MG90S torque-velocity envelope; not physical hardware qualification",
        "postures": posture_results,
    }
    if output_json is not None:
        save_json(output_json, report)
    return report


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--directory", type=Path, required=True)
    p.add_argument("--iterations", type=int, default=250)
    p.add_argument("--num-envs", type=int, default=2048)
    p.add_argument("--device", default="cuda:0")
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--evaluate-only", action="store_true")
    args = p.parse_args()
    if args.evaluate_only:
        report = evaluate_v1_pose_policy(args.directory / "policy.onnx", args.directory / "evaluation.json")
        print(json.dumps(report, indent=2))
        return
    onnx_path = train_v1_pose(
        args.directory,
        iterations=args.iterations,
        num_envs=args.num_envs,
        device=args.device,
        seed=args.seed,
    )
    report = evaluate_v1_pose_policy(onnx_path, args.directory / "evaluation.json")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
