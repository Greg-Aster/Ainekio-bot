"""GPU MuJoCo (mjlab) PPO trainer, ONNX exporter & evaluator for V3 12-servo Neural Pose.

Trains a reflection-equivariant goal-anchored residual policy matching
`experiments/freestyle/neural_pose/v3_contract.py` ("ainekio-v3-neural-pose-v1"):
  - Actor obs: 86 features x 15 causal frames = 1290 floats
  - Architecture: Exact L/R mirror-equivariant ResidualV3PoseMLPModel (256 -> 128 -> 64 -> 12)
  - Full DS3225 PRO capability (3.43 Nm, 800 deg/s = 13.96 rad/s) & Option A-1 4-bar dynamics.

Simulation-only evidence (`mass_measured=false`, `physical_qualified=false`).
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
import torch.nn as nn

ROOT = Path(__file__).resolve().parents[3]
for p in (str(ROOT / "Master"), str(ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

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
from mjlab_microduck.tasks.microduck_velocity_env_cfg import (
    MicroduckRlCfg,
    make_microduck_velocity_env_cfg,
)
from rsl_rl.models.mlp_model import MLPModel, _OnnxMLPModel, _TorchMLPModel

from gateway.neural_gait.artifacts import save_json
from gateway.neural_gait.microduck import AinekioOnPolicyRunner, MG90SActuatorCfg, mg90s_force_fields, motor_force_range
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
from experiments.freestyle.neural_pose.v3_contract import (
    SLICE_GOAL,
    V3_CANONICAL_POSTURES_DEG,
    V3_CANONICAL_SUPPORT,
    V3_JOINT_HALF_DEG,
    V3_JOINT_HI_DEG,
    V3_JOINT_LO_DEG,
    V3_JOINT_MID_DEG,
    V3_POSE_FEATURES,
    V3_POSE_OBS_SIZE,
    V3_POSE_SAMPLES,
    V3_POSE_SCHEMA,
    deg_to_norm,
    norm_to_deg,
    v3_pose_mirror_tables,
)

V3_POSE_DEFAULT_HIDDEN_DIMS = (256, 128, 64)
V3_POSE_RESIDUAL_SCALE = 0.35


def _register_v3_mirror_buffers(module: nn.Module, *, persistent: bool) -> None:
    obs_p, obs_s, act_p, act_s = v3_pose_mirror_tables()
    module.register_buffer("obs_mirror_perm", torch.tensor(obs_p, dtype=torch.long), persistent=persistent)
    module.register_buffer("obs_mirror_sign", torch.tensor(obs_s, dtype=torch.float32), persistent=persistent)
    module.register_buffer("act_mirror_perm", torch.tensor(act_p, dtype=torch.long), persistent=persistent)
    module.register_buffer("act_mirror_sign", torch.tensor(act_s, dtype=torch.float32), persistent=persistent)


class _V3ResidualTorchMLPModel(_TorchMLPModel):
    def __init__(self, model: MLPModel, residual_scale: float = V3_POSE_RESIDUAL_SCALE) -> None:
        super().__init__(model)
        self.residual_scale = float(residual_scale)
        _register_v3_mirror_buffers(self, persistent=True)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        goal_norm = x[:, SLICE_GOAL]
        x_mir = x[:, self.obs_mirror_perm] * self.obs_mirror_sign
        u_fwd = super().forward(x)
        u_mir = super().forward(x_mir)[:, self.act_mirror_perm] * self.act_mirror_sign
        u = 0.5 * (u_fwd + u_mir)
        return torch.clamp(goal_norm + self.residual_scale * u, -1.0, 1.0)


class _V3ResidualOnnxMLPModel(_OnnxMLPModel):
    def __init__(self, model: MLPModel, verbose: bool, residual_scale: float = V3_POSE_RESIDUAL_SCALE) -> None:
        super().__init__(model, verbose)
        self.residual_scale = float(residual_scale)
        _register_v3_mirror_buffers(self, persistent=True)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        goal_norm = x[:, SLICE_GOAL]
        x_mir = x[:, self.obs_mirror_perm] * self.obs_mirror_sign
        u_fwd = super().forward(x)
        u_mir = super().forward(x_mir)[:, self.act_mirror_perm] * self.act_mirror_sign
        u = 0.5 * (u_fwd + u_mir)
        return torch.clamp(goal_norm + self.residual_scale * u, -1.0, 1.0)


class ResidualV3PoseMLPModel(MLPModel):
    """Left-right reflection-equivariant goal-anchored residual MLP for V3 12-DOF Neural Pose."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        _register_v3_mirror_buffers(self, persistent=False)

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

    def as_jit(self) -> nn.Module:
        self.symmetrize_normalizer()
        return _V3ResidualTorchMLPModel(self, residual_scale=V3_POSE_RESIDUAL_SCALE)

    def as_onnx(self, verbose: bool) -> nn.Module:
        self.symmetrize_normalizer()
        return _V3ResidualOnnxMLPModel(self, verbose, residual_scale=V3_POSE_RESIDUAL_SCALE)


@dataclass(kw_only=True)
class V3PoseActionCfg(ActionTermCfg):
    sensor_noise: bool = True

    def build(self, env):
        return V3PoseAction(self, env)


class V3PoseAction(ActionTerm):
    """12-DOF V3 Neural Pose goal sampler, speed ramp, and 86x15 proprioceptive history."""

    def __init__(self, cfg: V3PoseActionCfg, env):
        super().__init__(cfg, env)
        self.cfg = cfg
        dev = env.device
        n = env.num_envs
        self.joint_ids, _ = self._entity.find_joints(V3_JOINTS, preserve_order=True)

        self.mid_rad = torch.tensor([math.radians(m) for m in V3_JOINT_MID_DEG], dtype=torch.float32, device=dev)
        self.half_rad = torch.tensor([math.radians(h) for h in V3_JOINT_HALF_DEG], dtype=torch.float32, device=dev)
        self.lo_rad = torch.tensor([math.radians(v) for v in V3_JOINT_LO_DEG], dtype=torch.float32, device=dev)
        self.hi_rad = torch.tensor([math.radians(v) for v in V3_JOINT_HI_DEG], dtype=torch.float32, device=dev)

        # Canonical goal library on GPU
        canon_names = list(V3_CANONICAL_POSTURES_DEG.keys())
        self.canon_goals_norm = torch.tensor(
            [deg_to_norm(V3_CANONICAL_POSTURES_DEG[k]) for k in canon_names],
            dtype=torch.float32,
            device=dev,
        )
        self.canon_support = torch.tensor(
            [V3_CANONICAL_SUPPORT[k] for k in canon_names],
            dtype=torch.float32,
            device=dev,
        )

        self._raw = torch.zeros((n, 12), dtype=torch.float32, device=dev)
        self.prev_action = torch.zeros((n, 12), dtype=torch.float32, device=dev)
        self.cmd_rad = torch.zeros((n, 12), dtype=torch.float32, device=dev)
        self.goal_norm = torch.zeros((n, 12), dtype=torch.float32, device=dev)
        self.goal_rad = torch.zeros((n, 12), dtype=torch.float32, device=dev)
        self.support = torch.ones((n, 4), dtype=torch.float32, device=dev)
        self.speed_scale = torch.ones((n, 1), dtype=torch.float32, device=dev)
        self.goal_timer = torch.zeros(n, dtype=torch.float32, device=dev)
        self.history = torch.zeros((n, V3_POSE_SAMPLES, V3_POSE_FEATURES), dtype=torch.float32, device=dev)
        self.prev_lin_vel_b = torch.zeros((n, 3), dtype=torch.float32, device=dev)
        self.sensor_noise = bool(cfg.sensor_noise)
        self.last_obs_step = -1
        self.reset(None)

    @property
    def action_dim(self) -> int:
        return 12

    @property
    def raw_action(self) -> torch.Tensor:
        return self._raw

    def _sample_goals(self, ids: torch.Tensor) -> None:
        dev = self._env.device
        k = len(ids)
        if k == 0:
            return
        u = torch.rand(k, device=dev)
        num_c = self.canon_goals_norm.shape[0]
        idx = torch.randint(0, num_c, (k,), device=dev)
        g_norm = self.canon_goals_norm[idx].clone()
        sup = self.canon_support[idx].clone()

        # 55% canonical (+ small jitter), 30% smooth random 4-legged pose, 15% single-leg lift
        jitter_mask = u < 0.55
        if jitter_mask.any():
            g_norm[jitter_mask] = torch.clamp(
                g_norm[jitter_mask] + torch.randn_like(g_norm[jitter_mask]) * 0.08, -0.95, 0.95
            )
        rand_mask = (u >= 0.55) & (u < 0.85)
        if rand_mask.any():
            m = int(rand_mask.sum())
            g_norm[rand_mask] = torch.empty((m, 12), device=dev).uniform_(-0.75, 0.75)
            sup[rand_mask] = 1.0
        lift_mask = u >= 0.85
        if lift_mask.any():
            m = int(lift_mask.sum())
            g_rand = torch.empty((m, 12), device=dev).uniform_(-0.35, 0.35)
            s_rand = torch.ones((m, 4), device=dev)
            lifted = torch.randint(0, 4, (m,), device=dev)
            for row_i in range(m):
                l = int(lifted[row_i])
                s_rand[row_i, l] = 0.0
                g_rand[row_i, 3 * l] = -0.35
                g_rand[row_i, 3 * l + 1] = 0.65
                g_rand[row_i, 3 * l + 2] = 0.75
            g_norm[lift_mask] = g_rand
            sup[lift_mask] = s_rand

        self.goal_norm[ids] = g_norm
        self.goal_rad[ids] = torch.clamp(g_norm * self.half_rad + self.mid_rad, self.lo_rad, self.hi_rad)
        self.support[ids] = sup
        # Full-speed default (70% at 1.0, 30% scaled speed 0.35..1.0)
        spd = torch.where(
            torch.rand(k, device=dev) < 0.70,
            torch.ones(k, device=dev),
            torch.empty(k, device=dev).uniform_(0.35, 1.0),
        )
        self.speed_scale[ids] = spd.unsqueeze(-1)
        self.goal_timer[ids] = torch.empty(k, device=dev).uniform_(2.5, 4.5)

    def reset(self, env_ids=None) -> None:
        dev = self._env.device
        ids = torch.arange(self._env.num_envs, device=dev) if env_ids is None else env_ids
        if len(ids) == 0:
            return
        stand_norm = torch.tensor(deg_to_norm([0.0] * 12), dtype=torch.float32, device=dev)
        self._raw[ids] = stand_norm
        self.prev_action[ids] = stand_norm
        self.cmd_rad[ids] = 0.0
        self.history[ids] = 0.0
        self.prev_lin_vel_b[ids] = 0.0
        self._sample_goals(ids)
        self.last_obs_step = -1

    def process_actions(self, actions: torch.Tensor) -> None:
        self.prev_action.copy_(self._raw)
        residual = torch.clamp(torch.nan_to_num(actions, nan=0.0), -1.0, 1.0)
        act = torch.clamp(self.goal_norm + V3_POSE_RESIDUAL_SCALE * residual, -1.0, 1.0)
        self._raw.copy_(act)
        desired_rad = torch.clamp(act * self.half_rad + self.mid_rad, self.lo_rad, self.hi_rad)

        # Respect requested speed_scale up to full DS3225 PRO 800 deg/s (no unrequested slowdown)
        max_step = V3_SERVO_NO_LOAD_RAD_S * self.speed_scale * self._env.step_dt
        delta = torch.clamp(desired_rad - self.cmd_rad, -max_step, max_step)
        self.cmd_rad.add_(delta).clamp_(self.lo_rad, self.hi_rad)

        # Periodically transition to a new goal within each episode
        self.goal_timer.sub_(self._env.step_dt)
        resample_ids = torch.nonzero(self.goal_timer <= 0.0, as_tuple=False).squeeze(-1)
        if len(resample_ids) > 0:
            self._sample_goals(resample_ids)

    def apply_actions(self) -> None:
        self._entity.set_joint_position_target(self.cmd_rad, joint_ids=self.joint_ids)

    def observation(self) -> torch.Tensor:
        step = int(self._env.common_step_counter)
        if step == self.last_obs_step:
            return self.history.reshape(self._env.num_envs, V3_POSE_OBS_SIZE)
        self.last_obs_step = step

        robot = self._entity.data
        q = robot.joint_pos[:, self.joint_ids]
        dq = robot.joint_vel[:, self.joint_ids]
        gyro = robot.root_link_ang_vel_b
        lin_vel_b = robot.root_link_lin_vel_b
        grav = robot.projected_gravity_b
        dt = float(self._env.step_dt)
        accel_b = (lin_vel_b - self.prev_lin_vel_b) / dt - 9.81 * grav
        self.prev_lin_vel_b.copy_(lin_vel_b)
        accel_g = torch.clamp(accel_b / 9.81, -4.0, 4.0)

        if self.sensor_noise:
            q = q + torch.randn_like(q) * math.radians(0.8)
            dq = dq + torch.randn_like(dq) * math.radians(8.0)
            gyro = gyro + torch.randn_like(gyro) * 0.03
            accel_g = accel_g + torch.randn_like(accel_g) * 0.03
            grav = grav + torch.randn_like(grav) * 0.015

        usable = torch.ones_like(q)
        row = torch.cat(
            [q, self.cmd_rad, dq, usable, gyro, accel_g, grav, self.goal_norm, self.support, self.speed_scale, self._raw],
            dim=-1,
        )
        row = torch.nan_to_num(row, nan=0.0, posinf=10.0, neginf=-10.0)
        self.history[:, 1:].copy_(self.history[:, :-1].clone())
        self.history[:, 0].copy_(row)
        return self.history.reshape(self._env.num_envs, V3_POSE_OBS_SIZE)


def _v3_pose_obs_actor(env) -> torch.Tensor:
    return env.action_manager.get_term("pose").observation()


def _v3_pose_obs_critic(env) -> torch.Tensor:
    term = env.action_manager.get_term("pose")
    obs = term.observation()
    robot = env.scene["robot"].data
    feet_c = (env.scene["feet_ground_contact"].data.found > 0).float()
    return torch.cat([obs, robot.root_link_lin_vel_b, robot.root_link_pos_w[:, 2:3], feet_c], dim=-1)


def _rew_pose_tracking(env) -> torch.Tensor:
    term = env.action_manager.get_term("pose")
    q = env.scene["robot"].data.joint_pos[:, term.joint_ids]
    err_rad = torch.abs(q - term.goal_rad)
    mae = torch.mean(err_rad, dim=-1)
    fine = torch.exp(-mae / math.radians(5.0))
    coarse = torch.exp(-mae / math.radians(22.0))
    return 0.65 * fine + 0.35 * coarse


def _rew_support_contact(env) -> torch.Tensor:
    term = env.action_manager.get_term("pose")
    contact = (env.scene["feet_ground_contact"].data.found > 0).float()
    match = 1.0 - torch.abs(contact - term.support)
    return torch.mean(match, dim=-1)


def _rew_pose_upright(env) -> torch.Tensor:
    pg = env.scene["robot"].data.projected_gravity_b
    return torch.sum(pg[:, :2] ** 2, dim=-1).clamp(0.0, 2.0)


def _rew_pose_stability(env) -> torch.Tensor:
    robot = env.scene["robot"].data
    lin = torch.sum(robot.root_link_lin_vel_b ** 2, dim=-1)
    ang = torch.sum(robot.root_link_ang_vel_b ** 2, dim=-1)
    return (0.4 * lin + 0.08 * ang).clamp(0.0, 4.0)


def _rew_action_rate(env) -> torch.Tensor:
    term = env.action_manager.get_term("pose")
    return torch.mean((term._raw - term.prev_action) ** 2, dim=-1)


def _rew_residual_reg(env) -> torch.Tensor:
    term = env.action_manager.get_term("pose")
    return torch.mean((term._raw - term.goal_norm) ** 2, dim=-1)


def _term_flipped(env) -> torch.Tensor:
    return env.scene["robot"].data.projected_gravity_b[:, 2] > -0.25


def _v3_robot_spec_fn(geo: dict):
    xml = build_v3_xml(geo, floor=False)
    root = ET.fromstring(xml)
    for elem in root.findall("actuator"):
        root.remove(elem)
    for wb in root.findall("worldbody"):
        for g in list(wb.findall("geom")):
            if g.attrib.get("name") == "floor":
                wb.remove(g)
    clean_xml = ET.tostring(root, encoding="unicode")

    def _build():
        return mujoco.MjSpec.from_string(clean_xml)

    return _build


def make_v3_pose_env_cfg(num_envs: int = 2048, play: bool = False):
    geo = load_v3_geometry()
    z_stand = float(geo["standing_shoulder_height_mm"]) / 1000.0
    cfg = make_microduck_velocity_env_cfg(play=play)
    cfg.scene.num_envs = num_envs
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
            delay_min_lag=0,
            delay_max_lag=0,
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

    cfg.actions = {"pose": V3PoseActionCfg(entity_name="robot", sensor_noise=not play)}
    cfg.commands = {}

    cfg.observations = {
        "actor": ObservationGroupCfg(
            terms={"proprio": ObservationTermCfg(func=_v3_pose_obs_actor)},
            enable_corruption=False,
        ),
        "critic": ObservationGroupCfg(
            terms={"privileged": ObservationTermCfg(func=_v3_pose_obs_critic)},
            enable_corruption=False,
        ),
    }

    cfg.events = {
        "mg90s_force_fields": EventTermCfg(func=mg90s_force_fields, mode="startup"),
        "reset_base": EventTermCfg(
            func=env_mdp.reset_root_state_uniform,
            mode="reset",
            params={
                "pose_range": {"x": (-0.1, 0.1), "y": (-0.1, 0.1), "yaw": (-math.pi, math.pi)},
                "velocity_range": {},
            },
        ),
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
            func=env_mdp.dr.geom_friction,
            mode="startup",
            params={
                "asset_cfg": SceneEntityCfg("robot", geom_names=list(foot_geoms)),
                "operation": "abs",
                "ranges": (0.75, 1.25),
            },
        ),
    }

    cfg.rewards = {
        "pose_tracking": RewardTermCfg(func=_rew_pose_tracking, weight=4.5),
        "support_contact": RewardTermCfg(func=_rew_support_contact, weight=0.9),
        "pose_upright": RewardTermCfg(func=_rew_pose_upright, weight=-1.2),
        "pose_stability": RewardTermCfg(func=_rew_pose_stability, weight=-0.20),
        "action_rate": RewardTermCfg(func=_rew_action_rate, weight=-0.02),
        "residual_reg": RewardTermCfg(func=_rew_residual_reg, weight=-0.05),
    }

    cfg.curriculum = {}
    cfg.terminations = {
        "time_out": TerminationTermCfg(func=env_mdp.time_out, time_out=True),
        "flipped": TerminationTermCfg(func=_term_flipped),
    }

    cfg.sim.mujoco.timestep = 0.002
    cfg.sim.mujoco.integrator = "implicitfast"
    cfg.sim.mujoco.solver = "newton"
    cfg.sim.mujoco.iterations = 30
    cfg.sim.nconmax = 96
    cfg.sim.njmax = 256
    cfg.decimation = 10
    cfg.episode_length_s = 12.0
    return cfg


def train_v3_pose(
    directory: Path,
    *,
    iterations: int = 250,
    num_envs: int = 2048,
    device: str = "cuda:0",
    seed: int = 7,
    hidden_dims: tuple[int, int, int] = V3_POSE_DEFAULT_HIDDEN_DIMS,
) -> Path:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    save_json(directory / "progress.json", {"state": "starting", "iterations": iterations, "steps": 0})
    env = None
    try:
        cfg = make_v3_pose_env_cfg(num_envs=num_envs, play=False)
        cfg.seed = seed

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
        agent.actor.class_name = "experiments.freestyle.neural_pose.v3_trainer:ResidualV3PoseMLPModel"
        agent.actor.distribution_cfg = {
            "class_name": "gateway.neural_gait.microduck_policy:FootGaussianDistribution",
            "init_std": 0.4,
            "std_type": "log",
        }
        agent.algorithm.entropy_coef = 0.005
        agent.algorithm.learning_rate = 8.0e-4
        agent.algorithm.desired_kl = 0.01

        geo = load_v3_geometry()
        save_json(
            directory / "manifest.json",
            {
                "model": "v3-12servo",
                "geometry_id": geo["geometry_id"],
                "schema": V3_POSE_SCHEMA,
                "obs_size": V3_POSE_OBS_SIZE,
                "features": V3_POSE_FEATURES,
                "samples": V3_POSE_SAMPLES,
                "actions": 12,
                "hidden_dims": list(hidden_dims),
                "residual_scale": V3_POSE_RESIDUAL_SCALE,
                "reflection_equivariant": True,
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
        runner.learn(iterations, init_at_random_ep_len=True)
        runner.save(str(directory / "learner.pt"))

        onnx_path = directory / "policy.onnx"
        runner.export_policy_to_onnx(str(directory), "policy.onnx")
        from mjlab.rl.exporter_utils import attach_metadata_to_onnx

        attach_metadata_to_onnx(
            str(onnx_path),
            {
                "ainekio_model": "v3-12servo",
                "ainekio_geometry_id": geo["geometry_id"],
                "ainekio_schema": V3_POSE_SCHEMA,
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


def evaluate_v3_pose_policy(onnx_path: Path, output_json: Path | None = None) -> dict:
    """Evaluate trained V3 Neural Pose ONNX policy across all 8 canonical postures + equivariance."""
    import onnxruntime as ort

    geo = load_v3_geometry()
    model = mujoco.MjModel.from_xml_string(build_v3_xml(geo))
    sess = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
    in_name = sess.get_inputs()[0].name
    out_name = sess.get_outputs()[0].name

    qpos_ids = [model.jnt_qposadr[mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, j)] for j in V3_JOINTS]
    qvel_ids = [model.jnt_dofadr[mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, j)] for j in V3_JOINTS]

    # 1. Exact reflection equivariance check (batch-1 compatible)
    obs_p, obs_s, act_p, act_s = v3_pose_mirror_tables()
    rng = np.random.default_rng(123)
    x_rand = rng.uniform(-0.5, 0.5, size=(16, V3_POSE_OBS_SIZE)).astype(np.float32)
    x_mir = x_rand[:, obs_p] * np.array(obs_s, dtype=np.float32)
    y_fwd = np.vstack([sess.run([out_name], {in_name: x_rand[i : i + 1]})[0] for i in range(len(x_rand))])
    y_mir = (
        np.vstack([sess.run([out_name], {in_name: x_mir[i : i + 1]})[0] for i in range(len(x_mir))])[:, act_p]
        * np.array(act_s, dtype=np.float32)
    )
    equivariance_max_err = float(np.max(np.abs(y_fwd - y_mir)))

    # 2. Closed-loop CPU MuJoCo rollout across all canonical postures
    posture_results = {}
    for pname, goal_deg in V3_CANONICAL_POSTURES_DEG.items():
        support = np.array(V3_CANONICAL_SUPPORT[pname], dtype=np.float32)
        goal_norm = np.array(deg_to_norm(goal_deg), dtype=np.float32)
        goal_arr = np.array(goal_deg, dtype=np.float32)
        data = mujoco.MjData(model)
        mujoco.mj_forward(model, data)
        hist = np.zeros((V3_POSE_SAMPLES, V3_POSE_FEATURES), dtype=np.float32)
        prev_act = np.array(deg_to_norm([0.0] * 12), dtype=np.float32)
        cmd_rad = np.zeros(12, dtype=np.float32)
        prev_vb = np.zeros(3, dtype=np.float32)
        survived = True
        peak_spd = 0.0
        for _step in range(150):  # 3.0 s @ 50 Hz
            q_rad = np.array([data.qpos[i] for i in qpos_ids], dtype=np.float32)
            dq_rad = np.array([data.qvel[i] for i in qvel_ids], dtype=np.float32)
            peak_spd = max(peak_spd, float(np.rad2deg(np.abs(dq_rad)).max()))
            quat = data.qpos[3:7].astype(np.float64)
            w, x, y, z = quat
            R = np.array([
                [1 - 2*(y*y + z*z), 2*(x*y - z*w), 2*(x*z + y*w)],
                [2*(x*y + z*w), 1 - 2*(x*x + z*z), 2*(y*z - x*w)],
                [2*(x*z - y*w), 2*(y*z + x*w), 1 - 2*(x*x + y*y)],
            ])
            vb = (R.T @ data.qvel[0:3]).astype(np.float32)
            gyro = (R.T @ data.qvel[3:6]).astype(np.float32)
            grav = np.array([-2*(x*z - w*y), -2*(y*z + w*x), 1 - 2*(w*w + z*z)], dtype=np.float32)
            accel_g = np.clip(((vb - prev_vb) / 0.02 - 9.81 * grav) / 9.81, -4.0, 4.0)
            prev_vb = vb.copy()

            row = np.concatenate(
                [q_rad, cmd_rad, dq_rad, np.ones(12, dtype=np.float32), gyro, accel_g, grav,
                 goal_norm, support, np.array([1.0], dtype=np.float32), prev_act]
            ).astype(np.float32)
            hist[1:] = hist[:-1]
            hist[0] = row

            act = np.clip(sess.run([out_name], {in_name: hist.reshape(1, V3_POSE_OBS_SIZE)})[0][0], -1.0, 1.0)
            prev_act = act.astype(np.float32)
            des_rad = np.radians(norm_to_deg(act)).astype(np.float32)
            max_step = V3_SERVO_NO_LOAD_RAD_S * 0.02
            cmd_rad = cmd_rad + np.clip(des_rad - cmd_rad, -max_step, max_step)
            data.ctrl[:] = cmd_rad
            for _ in range(10):
                dq_sub = np.array([data.qvel[i] for i in qvel_ids], dtype=np.float64)
                lo_f, hi_f = motor_force_range(dq_sub, V3_SERVO_EFFORT_NM, V3_SERVO_NO_LOAD_RAD_S)
                model.actuator_forcerange[:, 0] = lo_f
                model.actuator_forcerange[:, 1] = hi_f
                mujoco.mj_step(model, data)
            if grav[2] > -0.25:
                survived = False
                break

        final_deg = np.rad2deg([data.qpos[i] for i in qpos_ids])
        err = np.abs(final_deg - goal_arr)
        posture_results[pname] = {
            "survived": survived,
            "final_mae_deg": round(float(err.mean()), 2),
            "final_max_err_deg": round(float(err.max()), 2),
            "peak_joint_speed_deg_s": round(peak_spd, 1),
            "final_root_z_mm": round(float(data.qpos[2]) * 1000.0, 2),
        }

    report = {
        "model": "v3-12servo",
        "geometry_id": geo["geometry_id"],
        "mass_kg": geo["mass_kg"],
        "mass_measured": geo["mass_measured"],
        "reflection_equivariance_max_err": equivariance_max_err,
        "basis": "MuJoCo CPU closed-chain 4-bar simulation (DS3225 PRO 7.4V); not physical hardware qualification",
        "postures": posture_results,
    }
    if output_json is not None:
        save_json(output_json, report)
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description="Train & evaluate V3 12-servo Neural Pose")
    ap.add_argument("--directory", type=Path, default=ROOT / "experiments/freestyle/artifacts/neural_pose_v3")
    ap.add_argument("--iterations", type=int, default=250)
    ap.add_argument("--num-envs", type=int, default=2048)
    ap.add_argument("--device", default="cuda:0")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--evaluate-only", action="store_true")
    args = ap.parse_args()

    onnx_path = args.directory / "policy.onnx"
    if not args.evaluate_only:
        onnx_path = train_v3_pose(
            args.directory,
            iterations=args.iterations,
            num_envs=args.num_envs,
            device=args.device,
            seed=args.seed,
        )
    report = evaluate_v3_pose_policy(onnx_path, args.directory / "evaluation.json")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
