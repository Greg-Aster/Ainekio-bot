"""GPU MuJoCo (mjlab) PPO trainer, evaluator & ONNX exporter for V1 8-servo Neural Gait.

Trains an embedded-ready int8-quantizable 50 Hz velocity-tracking policy matching
Slave/software/models/v1-8servo/v1_microduck.c:
  - Schema: "ainekio-v1-neural-gait-v1-proprio"
  - Actor obs: 36 features x 15 causal frames = 540 floats (newest frame at [0..35])
  - Actor MLP: ObsNormalizer(540) -> 128 -> 64 -> 32 -> 8 (ELU hidden, Tanh output)
  - Action: 8 normalized [-1, 1] joint targets scaled by (42 deg hip, 55 deg knee)
  - Physics: full-speed MG90S (0.216 Nm stall, 10.47 rad/s = 600 deg/s), 500 Hz substeps.

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

from gateway.neural_gait.artifacts import save_json
from gateway.neural_gait.microduck import (
    AinekioOnPolicyRunner,
    LearningObstaclesCfg,
    LearningSlopeCfg,
    LearningWaveCfg,
    MG90SActuatorCfg,
    mg90s_force_fields,
)
from gateway.neural_gait.v1_environment import (
    V1_FOOT_RADIUS_M,
    V1_JOINTS,
    V1_LEGS,
    build_v1_xml,
    load_v1_geometry,
)

V1_SCHEMA = "ainekio-v1-neural-gait-v2-cpg"
V1_FEATURES = 38
V1_SAMPLES = 8
V1_OBS_SIZE = V1_FEATURES * V1_SAMPLES  # 304
V1_GAIT_HZ = 3.0
V1_ACTION_SCALE_DEG = (45.0, 90.0)      # (hip_deg, knee_deg) -> full [-45,+45] hip & [-15,+90] knee travel
V1_HIP_LIMITS_RAD = (math.radians(-45.0), math.radians(45.0))
V1_KNEE_LIMITS_RAD = (math.radians(-15.0), math.radians(115.0))
V1_DEFAULT_HIDDEN_DIMS = (128, 64, 32)


@dataclass(kw_only=True)
class V1JointActionCfg(ActionTermCfg):
    hip_scale_deg: float = V1_ACTION_SCALE_DEG[0]
    knee_scale_deg: float = V1_ACTION_SCALE_DEG[1]
    sensor_noise: bool = True

    def build(self, env):
        return V1JointAction(self, env)


class V1JointAction(ActionTerm):
    """8-DOF direct joint position action + exact 36x15 proprioceptive history buffer."""

    def __init__(self, cfg: V1JointActionCfg, env):
        super().__init__(cfg, env)
        self.cfg = cfg
        self.joint_ids, _ = self._entity.find_joints(V1_JOINTS, preserve_order=True)
        self.foot_site_ids, _ = self._entity.find_sites(
            tuple(f"{leg}_foot" for leg in V1_LEGS), preserve_order=True
        )
        dev = env.device
        self.action_scale_rad = torch.tensor(
            [math.radians(cfg.hip_scale_deg)] * 4 + [math.radians(cfg.knee_scale_deg)] * 4,
            dtype=torch.float32,
            device=dev,
        )
        self.joint_lo = torch.tensor(
            [V1_HIP_LIMITS_RAD[0]] * 4 + [V1_KNEE_LIMITS_RAD[0]] * 4,
            dtype=torch.float32,
            device=dev,
        )
        self.joint_hi = torch.tensor(
            [V1_HIP_LIMITS_RAD[1]] * 4 + [V1_KNEE_LIMITS_RAD[1]] * 4,
            dtype=torch.float32,
            device=dev,
        )
        self._raw = torch.zeros((env.num_envs, 8), dtype=torch.float32, device=dev)
        self.prev_action = torch.zeros((env.num_envs, 8), dtype=torch.float32, device=dev)
        self.targets_rad = torch.zeros((env.num_envs, 8), dtype=torch.float32, device=dev)
        self.history = torch.zeros((env.num_envs, V1_SAMPLES, V1_FEATURES), dtype=torch.float32, device=dev)
        self.prev_lin_vel_b = torch.zeros((env.num_envs, 3), dtype=torch.float32, device=dev)
        self.avg_vel_b = torch.zeros((env.num_envs, 3), dtype=torch.float32, device=dev)  # [vx, vy, wz] EMA
        self.phase_rad = torch.zeros(env.num_envs, dtype=torch.float32, device=dev)
        self.last_obs_step = -1
        self.sensor_noise = bool(cfg.sensor_noise)
        self.reset(None)

    @property
    def action_dim(self) -> int:
        return 8

    @property
    def raw_action(self) -> torch.Tensor:
        return self._raw

    def reset(self, env_ids=None) -> None:
        dev = self._env.device
        ids = torch.arange(self._env.num_envs, device=dev) if env_ids is None else env_ids
        if len(ids) == 0:
            return
        self._raw[ids] = 0.0
        self.prev_action[ids] = 0.0
        self.targets_rad[ids] = 0.0
        self.history[ids] = 0.0
        self.prev_lin_vel_b[ids] = 0.0
        self.avg_vel_b[ids] = 0.0
        self.phase_rad[ids] = torch.rand(len(ids), device=dev) * (2.0 * math.pi)

    def process_actions(self, actions: torch.Tensor) -> None:
        self.prev_action.copy_(self._raw)
        clipped = torch.nan_to_num(actions, nan=0.0, posinf=1.0, neginf=-1.0).clamp(-1.0, 1.0)
        self._raw.copy_(clipped)
        self.targets_rad = torch.clamp(clipped * self.action_scale_rad, self.joint_lo, self.joint_hi)
        self.phase_rad = (self.phase_rad + 2.0 * math.pi * V1_GAIT_HZ * float(self._env.step_dt)) % (2.0 * math.pi)
        # Update 0.25s EMA of body-frame [vx, vy, wz] so rhythmic trot surge is scored smoothly
        robot = self._entity
        inst = torch.cat([robot.data.root_link_lin_vel_b[:, :2], robot.data.root_link_ang_vel_b[:, 2:3]], dim=-1)
        inst = torch.nan_to_num(inst, nan=0.0, posinf=0.0, neginf=0.0)
        self.avg_vel_b.mul_(0.85).add_(inst, alpha=0.15)

    def apply_actions(self) -> None:
        self._entity.set_joint_position_target(self.targets_rad, joint_ids=self.joint_ids)

    def _build_frame(self) -> torch.Tensor:
        robot = self._entity
        q = robot.data.joint_pos[:, self.joint_ids]
        dq = robot.data.joint_vel[:, self.joint_ids]
        gyro = robot.data.root_link_ang_vel_b
        lin_vel_b = robot.data.root_link_lin_vel_b
        proj_grav = robot.data.projected_gravity_b  # [0, 0, -1] when upright!
        # Specific force in body frame (g units): (dv/dt)/g - proj_grav -> [0, 0, +1] upright!
        dt = float(self._env.step_dt)
        lin_acc_b = (lin_vel_b - self.prev_lin_vel_b) / max(dt, 1e-4)
        self.prev_lin_vel_b.copy_(lin_vel_b)
        accel_g = (lin_acc_b / 9.81 - proj_grav).clamp(-4.0, 4.0)

        if self.sensor_noise:
            q = q + torch.randn_like(q) * 0.012        # ~0.7 deg 4th-wire ADC noise
            dq = dq + torch.randn_like(dq) * 0.18      # ~10 deg/s velocity noise
            gyro = gyro + torch.randn_like(gyro) * 0.04
            accel_g = accel_g + torch.randn_like(accel_g) * 0.03
            proj_grav = proj_grav + torch.randn_like(proj_grav) * 0.015
            proj_grav = proj_grav / proj_grav.norm(dim=-1, keepdim=True).clamp_min(1e-6)

        cmd = self._env.command_manager.get_command("twist")[:, :3]
        moving = (torch.norm(cmd[:, :2], dim=-1) + 0.12 * torch.abs(cmd[:, 2])) > 0.02
        ph_sin = torch.where(moving, torch.sin(self.phase_rad), torch.zeros_like(self.phase_rad)).unsqueeze(-1)
        ph_cos = torch.where(moving, torch.cos(self.phase_rad), torch.zeros_like(self.phase_rad)).unsqueeze(-1)
        frame = torch.cat([q, dq, gyro, accel_g, proj_grav, cmd, self._raw, ph_sin, ph_cos], dim=-1)
        return torch.nan_to_num(frame, nan=0.0, posinf=0.0, neginf=0.0)

    def observations(self) -> torch.Tensor:
        step = int(getattr(self._env, "common_step_counter", 0))
        if step != self.last_obs_step:
            frame = self._build_frame()
            self.history = torch.roll(self.history, shifts=1, dims=1)
            self.history[:, 0, :] = frame
            self.last_obs_step = step
        return self.history.reshape(self._env.num_envs, V1_OBS_SIZE)


def _v1_actor_obs(env) -> torch.Tensor:
    return env.action_manager.get_term("joints").observations()


def _v1_critic_priv(env) -> torch.Tensor:
    robot = env.scene["robot"]
    term = env.action_manager.get_term("joints")
    lin_vel_b = torch.nan_to_num(robot.data.root_link_lin_vel_b, nan=0.0)
    root_z = robot.data.root_link_pos_w[:, 2:3]
    contact = env.scene["feet_ground_contact"].data.found.float()
    foot_z = robot.data.site_pos_w[:, term.foot_site_ids, 2]
    return torch.nan_to_num(torch.cat([lin_vel_b, root_z, contact, foot_z], dim=-1), nan=0.0)


# =============================================================================
# V1 Reward & Termination Terms (Baseline-subtracted MicroDuck tracking!)
# =============================================================================
def _rew_track_twist(env) -> torch.Tensor:
    """Baseline-subtracted 3D twist tracking (adapted from Ainekio microduck_mdp.py).
    At any nonzero command, standing still earns EXACTLY 0.0 reward; any true motion
    toward the commanded velocity earns immediate positive gradient."""
    robot = env.scene["robot"].data
    cmd = env.command_manager.get_command("twist")[:, :3]
    term = env.action_manager.get_term("joints")
    actual = term.avg_vel_b  # smoothed [vx, vy, wz]
    widths = torch.tensor([0.10, 0.07, 0.45], dtype=torch.float32, device=env.device)

    err = ((actual - cmd) / widths).square()
    base = (cmd / widths).square()
    q_lin = 1.0 / (1.0 + err[:, :2].sum(-1))
    b_lin = 1.0 / (1.0 + base[:, :2].sum(-1))
    q_ang = 1.0 / (1.0 + err[:, 2])
    b_ang = 1.0 / (1.0 + base[:, 2])

    d_lin = q_lin - b_lin
    d_ang = q_ang - b_ang
    h_lin = (1.0 - b_lin).clamp_min(1e-5)
    h_ang = (1.0 - b_ang).clamp_min(1e-5)

    # Directed velocity projection (zero-mean vibration cancels symmetrically!)
    lin_cmd_sq = cmd[:, :2].square().sum(-1).clamp_min(1e-6)
    lin_ratio = (actual[:, :2] * cmd[:, :2]).sum(-1) / lin_cmd_sq
    proj_v = lin_ratio.unsqueeze(-1) * cmd[:, :2]
    orth_sq = (actual[:, :2] - proj_v).square().sum(-1)
    orth_gate = torch.exp(-orth_sq / (0.055 ** 2))
    lin_prog = lin_ratio.clamp(-1.0, 1.0) * orth_gate * (b_lin < 0.96).float()

    ang_ratio = (actual[:, 2] * cmd[:, 2]) / cmd[:, 2].square().clamp_min(1e-6)
    ang_prog = ang_ratio.clamp(-1.0, 1.0) * (b_ang < 0.96).float()

    # Separate positive improvement on commanded axes from gentle drift penalty on zero-commanded axes
    # (so tiny linear drift during a pure in-place turn never overpowers the turn reward!)
    lin_moving = b_lin < 0.96
    ang_moving = b_ang < 0.96
    comp_lin = torch.where(
        lin_moving,
        torch.where(d_lin > 0.0, 0.55 * (d_lin / h_lin) + 0.45 * lin_prog.clamp_min(0.0), d_lin / h_lin.clamp_min(0.4)),
        0.15 * d_lin,
    )
    comp_ang = torch.where(
        ang_moving,
        torch.where(d_ang > 0.0, 0.55 * (d_ang / h_ang) + 0.45 * ang_prog.clamp_min(0.0), d_ang / h_ang.clamp_min(0.4)),
        0.15 * d_ang,
    )

    ang_gate = 0.45 + 0.55 * q_ang.clamp(0.0, 1.0)
    improvement = 1.5 * torch.where(comp_lin > 0.0, comp_lin * ang_gate, comp_lin) + 1.1 * comp_ang

    # Upright gate: cannot earn positive tracking while falling over
    grav = robot.projected_gravity_b
    upright = (-grav[:, 2]).clamp(0.0, 1.0) * torch.exp(-3.0 * grav[:, 0].square() - 4.0 * grav[:, 1].square())
    result = torch.where(improvement > 0.0, improvement * upright, improvement)

    env.extras["log"]["Tracking/linear_error_m_s"] = torch.norm(actual[:, :2] - cmd[:, :2], dim=-1).mean()
    env.extras["log"]["Tracking/yaw_error_rad_s"] = (actual[:, 2] - cmd[:, 2]).abs().mean()
    return torch.nan_to_num(result, nan=0.0, posinf=2.0, neginf=-2.0)


def _rew_upright(env) -> torch.Tensor:
    pg = env.scene["robot"].data.projected_gravity_b
    return torch.sum(pg[:, :2] ** 2, dim=-1).clamp(0.0, 2.0)


def _rew_base_height(env, min_z: float = 0.040) -> torch.Tensor:
    # Allow the full athletic spider walking stance (knee 25..45 deg -> root_z 44..56 mm)
    # without penalizing crouch; only penalize sagging below 40 mm belly clearance.
    z = env.scene["robot"].data.root_link_pos_w[:, 2]
    sag = torch.clamp(min_z - z, min=0.0)
    return (sag * sag).clamp(0.0, 0.01)


def _rew_base_stability(env) -> torch.Tensor:
    robot = env.scene["robot"]
    vz = robot.data.root_link_lin_vel_b[:, 2]
    ang_xy = robot.data.root_link_ang_vel_b[:, :2]
    return (0.4 * vz * vz + 0.04 * torch.sum(ang_xy * ang_xy, dim=-1)).clamp(0.0, 4.0)


def _rew_air_time(env) -> torch.Tensor:
    cmd = env.command_manager.get_command("twist")[:, :3]
    moving = (torch.norm(cmd[:, :2], dim=-1) + 0.12 * torch.abs(cmd[:, 2])) > 0.03
    sensor = env.scene["feet_ground_contact"].data
    first_contact = sensor.last_air_time > 0.0
    air = sensor.last_air_time.clamp(0.0, 0.30)
    bonus = torch.sum((air - 0.05).clamp(min=0.0) * (sensor.found > 0).float() * first_contact.float(), dim=-1)
    return bonus * moving.float()


def _rew_foot_clearance(env, target_h: float = 0.018) -> torch.Tensor:
    cmd = env.command_manager.get_command("twist")[:, :3]
    moving = (torch.norm(cmd[:, :2], dim=-1) + 0.12 * torch.abs(cmd[:, 2])) > 0.03
    robot = env.scene["robot"]
    term = env.action_manager.get_term("joints")
    foot_z = robot.data.site_pos_w[:, term.foot_site_ids, 2].clamp(0.0, 0.05)
    foot_vxy = torch.norm(robot.data.site_lin_vel_w[:, term.foot_site_ids, :2], dim=-1)
    lift = torch.clamp(foot_z / target_h, 0.0, 1.0)
    in_air = (env.scene["feet_ground_contact"].data.found == 0).float()
    return torch.mean(lift * in_air * (0.25 + foot_vxy.clamp(0.0, 0.6)), dim=-1) * moving.float()


def _rew_diagonal_trot(env) -> torch.Tensor:
    cmd = env.command_manager.get_command("twist")[:, :3]
    moving = (torch.norm(cmd[:, :2], dim=-1) + 0.12 * torch.abs(cmd[:, 2])) > 0.02
    # V1_LEGS = (FR=0, RR=1, FL=2, RL=3). Phase-locked diagonal trot:
    #   sin(ph) > 0: Pair A (FR, RL) swings (airborne) while Pair B (RR, FL) stances (contact)
    #   sin(ph) < 0: Pair B (RR, FL) swings (airborne) while Pair A (FR, RL) stances (contact)
    term = env.action_manager.get_term("joints")
    s = torch.sin(term.phase_rad)
    c = (env.scene["feet_ground_contact"].data.found > 0).float()
    a_swing_b_stance = (1.0 - c[:, 0]) * (1.0 - c[:, 3]) * c[:, 1] * c[:, 2]
    b_swing_a_stance = (1.0 - c[:, 1]) * (1.0 - c[:, 2]) * c[:, 0] * c[:, 3]
    sync = torch.where(s > 0.15, a_swing_b_stance, torch.where(s < -0.15, b_swing_a_stance, torch.zeros_like(s)))
    return sync * moving.float()


def _rew_foot_slip(env) -> torch.Tensor:
    robot = env.scene["robot"]
    term = env.action_manager.get_term("joints")
    in_contact = (env.scene["feet_ground_contact"].data.found > 0).float()
    vxy = torch.norm(robot.data.site_lin_vel_w[:, term.foot_site_ids, :2], dim=-1)
    return torch.sum(in_contact * vxy.clamp(0.0, 1.0), dim=-1)


def _rew_stand_still(env) -> torch.Tensor:
    cmd = env.command_manager.get_command("twist")[:, :3]
    still = (torch.norm(cmd[:, :2], dim=-1) + 0.12 * torch.abs(cmd[:, 2])) < 0.025
    robot = env.scene["robot"]
    term = env.action_manager.get_term("joints")
    q = robot.data.joint_pos[:, term.joint_ids]
    dq = robot.data.joint_vel[:, term.joint_ids]
    cost = torch.sum(q * q, dim=-1) + 0.04 * torch.sum(dq * dq, dim=-1)
    return cost.clamp(0.0, 4.0) * still.float()


def _rew_action_rate(env) -> torch.Tensor:
    term = env.action_manager.get_term("joints")
    return torch.sum((term.raw_action - term.prev_action) ** 2, dim=-1).clamp(0.0, 8.0)


def _rew_joint_limit_margin(env) -> torch.Tensor:
    robot = env.scene["robot"]
    term = env.action_manager.get_term("joints")
    q = robot.data.joint_pos[:, term.joint_ids]
    margin = 0.08  # ~4.5 deg buffer from hard stops
    over_hi = torch.clamp(q - (term.joint_hi - margin), min=0.0)
    over_lo = torch.clamp((term.joint_lo + margin) - q, min=0.0)
    return torch.sum(over_hi + over_lo, dim=-1).clamp(0.0, 4.0)


def _term_flipped_or_collapsed(env) -> torch.Tensor:
    robot = env.scene["robot"]
    pg_z = robot.data.projected_gravity_b[:, 2]
    z = robot.data.root_link_pos_w[:, 2]
    bad_nan = ~torch.isfinite(z) | ~torch.isfinite(pg_z)
    # Upright pg_z is -1.0; flipped past ~65 deg is > -0.42; collapsed belly is z < 0.026 m
    return bad_nan | (pg_z > -0.42) | (z < 0.026)


def _randomize_v1_actuators(env, env_ids):
    ids = torch.arange(env.num_envs, device=env.device) if env_ids is None else env_ids
    if len(ids) == 0:
        return
    robot = env.scene["robot"]
    act = robot.actuators[0]
    if not hasattr(act, "effort_scale") or act.effort_scale is None:
        act.effort_scale = torch.ones((env.num_envs, 8), dtype=torch.float32, device=env.device)
    act.effort_scale[ids] = 0.80 + 0.30 * torch.rand((len(ids), 8), device=env.device)


def _push_v1_robot(env, env_ids):
    ids = torch.arange(env.num_envs, device=env.device) if env_ids is None else env_ids
    if len(ids) == 0:
        return
    robot = env.scene["robot"]
    vel = robot.data.root_link_vel_w[ids].clone()
    vel[:, 0:2] += (torch.rand((len(ids), 2), device=env.device) * 2.0 - 1.0) * 0.14
    vel[:, 5] += (torch.rand((len(ids),), device=env.device) * 2.0 - 1.0) * 0.6
    robot.write_root_link_velocity_to_sim(vel, env_ids=ids)


def make_v1_env_cfg(num_envs: int = 2048, *, play: bool = False, rough: bool = True):
    """Build the mjlab ManagerBasedRlEnvCfg for the V1 8-servo P4 robot."""
    geo = load_v1_geometry()
    stand_z = float(geo["standing_root_height_mm"]) * 1e-3
    xml = ET.fromstring(build_v1_xml(geo, include_floor=False))
    # Strip actuator & option so mjlab EntityCfg + SimulationCfg own them cleanly.
    act_el = xml.find("actuator")
    if act_el is not None:
        xml.remove(act_el)
    opt_el = xml.find("option")
    if opt_el is not None:
        xml.remove(opt_el)
    sens_el = xml.find("sensor")
    if sens_el is not None:
        xml.remove(sens_el)
    for geom in xml.iter("geom"):
        geom.set("group", "1")
    foot_geoms = tuple(f"{leg}_foot_geom" for leg in V1_LEGS)
    for gname in foot_geoms:
        g = xml.find(f".//geom[@name='{gname}']")
        if g is not None:
            g.set("priority", "1")
    spec_xml = ET.tostring(xml, encoding="unicode")

    cfg = make_microduck_velocity_env_cfg(play=play, rough=False)
    # 10 ms command delay = 5 physics substeps at 500 Hz (realistic PCA9685 50 Hz hold)
    lag = 5
    cfg.scene.entities = {
        "robot": EntityCfg(
            spec_fn=lambda: mujoco.MjSpec.from_string(spec_xml),
            init_state=EntityCfg.InitialStateCfg(
                pos=(0.0, 0.0, stand_z + 0.002),
                # Seed neutral athletic stance (knees at +28 deg -> 31 mm hip stride radius!)
                joint_pos={j: (math.radians(28.0) if j.endswith("_knee") else 0.0) for j in V1_JOINTS},
            ),
            articulation=EntityArticulationInfoCfg(
                actuators=(
                    MG90SActuatorCfg(
                        target_names_expr=V1_JOINTS,
                        stiffness=2.0,
                        damping=0.035,
                        effort_limit=0.18,
                        speed_rad_s=10.47,  # Full MG90S 600 deg/s speed!
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
                mode="geom",
                pattern=foot_geoms,
                entity="robot",
            ),
            secondary=ContactMatch(mode="body", pattern="terrain"),
            fields=("found", "force"),
            reduce="netforce",
            num_slots=1,
            track_air_time=True,
        ),
    )
    cfg.scene.num_envs = num_envs
    if rough and not play:
        cfg.scene.terrain.terrain_type = "generator"
        cfg.scene.terrain.max_init_terrain_level = 1
        cfg.scene.terrain.terrain_generator = TerrainGeneratorCfg(
            size=(6.0, 6.0),
            border_width=10.0,
            num_rows=4,
            num_cols=4,
            add_lights=False,
            curriculum=False,
            sub_terrains={
                "flat": terrain_gen.BoxFlatTerrainCfg(proportion=0.65),
                "slope": LearningSlopeCfg(
                    proportion=0.20,
                    slope_range=(0.0, math.tan(math.radians(5.0))),
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
    cfg.actions = {
        "joints": V1JointActionCfg(
            entity_name="robot",
            hip_scale_deg=V1_ACTION_SCALE_DEG[0],
            knee_scale_deg=V1_ACTION_SCALE_DEG[1],
            sensor_noise=not play,
        )
    }
    cfg.observations = {
        "actor": ObservationGroupCfg(
            terms={"proprio": ObservationTermCfg(func=_v1_actor_obs)},
            concatenate_terms=True,
            enable_corruption=False,
        ),
        "critic": ObservationGroupCfg(
            terms={
                "proprio": ObservationTermCfg(func=_v1_actor_obs),
                "priv": ObservationTermCfg(func=_v1_critic_priv),
            },
            concatenate_terms=True,
            enable_corruption=False,
        ),
    }

    twist = cfg.commands["twist"]
    cfg.commands = {"twist": twist}
    twist.heading_command = False
    twist.ranges.heading = None
    twist.rel_heading_envs = 0.0
    twist.rel_standing_envs = 0.10
    twist.rel_forward_envs = 0.35
    twist.ranges.lin_vel_x = (-0.16, 0.18)
    twist.ranges.lin_vel_y = (-0.10, 0.10)
    twist.ranges.ang_vel_z = (-1.5, 1.5)

    # Events & domain randomization
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
        fric_dr.params["ranges"] = (0.50, 1.35)
        cfg.events["randomize_mass_inertia"] = mass_dr
        cfg.events["randomize_com"] = com_dr
        cfg.events["foot_friction"] = fric_dr
        cfg.events["randomize_actuators"] = EventTermCfg(func=_randomize_v1_actuators, mode="reset")
        cfg.events["push_robot"] = EventTermCfg(
            func=_push_v1_robot, mode="interval", interval_range_s=(3.5, 6.5)
        )

    cfg.rewards = {
        "track_twist": RewardTermCfg(func=_rew_track_twist, weight=5.0),
        "upright": RewardTermCfg(func=_rew_upright, weight=-2.0),
        "base_height": RewardTermCfg(func=_rew_base_height, weight=-10.0, params={"min_z": 0.040}),
        "base_stability": RewardTermCfg(func=_rew_base_stability, weight=-0.25),
        "air_time": RewardTermCfg(func=_rew_air_time, weight=2.0),
        "foot_clearance": RewardTermCfg(func=_rew_foot_clearance, weight=2.2),
        "diagonal_trot": RewardTermCfg(func=_rew_diagonal_trot, weight=1.5),
        "foot_slip": RewardTermCfg(func=_rew_foot_slip, weight=-0.35),
        "stand_still": RewardTermCfg(func=_rew_stand_still, weight=-0.8),
        "action_rate": RewardTermCfg(func=_rew_action_rate, weight=-0.015),
        "joint_limits": RewardTermCfg(func=_rew_joint_limit_margin, weight=-0.3),
    }

    cfg.curriculum = {}
    cfg.terminations = {
        "time_out": TerminationTermCfg(func=env_mdp.time_out, time_out=True),
        "fell_or_collapsed": TerminationTermCfg(func=_term_flipped_or_collapsed),
    }

    cfg.sim.mujoco.timestep = 0.002  # 500 Hz physics
    cfg.sim.mujoco.integrator = "implicitfast"
    cfg.sim.mujoco.solver = "newton"
    cfg.sim.mujoco.iterations = 20
    cfg.sim.nconmax = 64
    cfg.sim.njmax = 128
    cfg.decimation = 10  # 50 Hz control
    cfg.episode_length_s = 15.0
    return cfg


def train_v1_gait(
    directory: Path,
    *,
    iterations: int = 450,
    num_envs: int = 2048,
    device: str = "cuda:0",
    seed: int = 42,
    hidden_dims: tuple[int, int, int] = V1_DEFAULT_HIDDEN_DIMS,
    rough: bool = True,
) -> Path:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    save_json(directory / "progress.json", {"state": "starting", "iterations": iterations, "steps": 0})
    env = None
    try:
        cfg = make_v1_env_cfg(num_envs=num_envs, play=False, rough=rough)
        cfg.seed = seed
        if cfg.scene.terrain.terrain_generator is not None:
            cfg.scene.terrain.terrain_generator.seed = seed

        agent = deepcopy(MicroduckRlCfg)
        agent.logger = "tensorboard"
        agent.experiment_name = "ainekio_v1_microduck"
        agent.upload_model = False
        agent.actor.hidden_dims = tuple(int(d) for d in hidden_dims)
        agent.critic.hidden_dims = (256, 128, 64)
        agent.actor.distribution_cfg = {
            "class_name": "gateway.neural_gait.microduck_policy:FootGaussianDistribution",
            "init_std": 0.9,
            "std_type": "log",
        }
        agent.save_interval = max(1, iterations // 5)

        geo = load_v1_geometry()
        manifest = {
            "kind": "v1-microduck-mjlab",
            "model": "v1-8servo",
            "geometry_id": geo["geometry_id"],
            "mass_kg": geo["mass_kg"],
            "mass_measured": geo["mass_measured"],
            "schema": V1_SCHEMA,
            "action": "normalized-joint-deg-v1",
            "action_scale_deg": list(V1_ACTION_SCALE_DEG),
            "actor_hidden_dims": list(hidden_dims),
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
                "ainekio_schema": V1_SCHEMA,
                "ainekio_action": "normalized-joint-deg-v1",
                "ainekio_action_scale_deg": json.dumps(list(V1_ACTION_SCALE_DEG)),
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


def evaluate_v1_policy(onnx_path: Path, output_json: Path | None = None) -> dict:
    """Evaluate a trained V1 neural gait ONNX policy in standalone CPU MuJoCo."""
    import onnxruntime as ort

    geo = load_v1_geometry()
    model = mujoco.MjModel.from_xml_string(build_v1_xml(geo))
    sess = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
    in_name = sess.get_inputs()[0].name
    out_name = sess.get_outputs()[0].name

    qpos_ids = [model.jnt_qposadr[mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, j)] for j in V1_JOINTS]
    qvel_ids = [model.jnt_dofadr[mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, j)] for j in V1_JOINTS]
    foot_sids = [mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_SITE, f"{leg}_foot") for leg in V1_LEGS]
    scale_rad = np.array([math.radians(V1_ACTION_SCALE_DEG[0])] * 4 + [math.radians(V1_ACTION_SCALE_DEG[1])] * 4, dtype=np.float32)
    lo_rad = np.array([V1_HIP_LIMITS_RAD[0]] * 4 + [V1_KNEE_LIMITS_RAD[0]] * 4, dtype=np.float32)
    hi_rad = np.array([V1_HIP_LIMITS_RAD[1]] * 4 + [V1_KNEE_LIMITS_RAD[1]] * 4, dtype=np.float32)

    scenarios = {
        "stand": (0.0, 0.0, 0.0),
        "walk_fwd": (0.14, 0.0, 0.0),
        "walk_fast": (0.18, 0.0, 0.0),
        "walk_back": (-0.14, 0.0, 0.0),
        "turn_left": (0.0, 0.0, 1.2),
        "turn_right": (0.0, 0.0, -1.2),
        "crab_left": (0.0, 0.09, 0.0),
        "crab_right": (0.0, -0.09, 0.0),
    }
    results = {}
    for name, (vx_cmd, vy_cmd, wz_cmd) in scenarios.items():
        data = mujoco.MjData(model)
        mujoco.mj_forward(model, data)
        hist = np.zeros((V1_SAMPLES, V1_FEATURES), dtype=np.float32)
        prev_act = np.zeros(8, dtype=np.float32)
        prev_vb = np.zeros(3, dtype=np.float32)
        vx_list, vy_list, wz_list, z_list, spd_list, clear_list = [], [], [], [], [], []
        survived = True
        steps = 250  # 5.0 seconds @ 50 Hz
        for step in range(steps):
            q = np.array([data.qpos[i] for i in qpos_ids], dtype=np.float32)
            dq = np.array([data.qvel[i] for i in qvel_ids], dtype=np.float32)
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
            cmd_mag = math.hypot(vx_cmd, vy_cmd) + 0.12 * abs(wz_cmd)
            if cmd_mag > 0.02:
                ph = 2.0 * math.pi * V1_GAIT_HZ * (step * 0.02)
                ph_vec = np.array([math.sin(ph), math.cos(ph)], dtype=np.float32)
            else:
                ph_vec = np.zeros(2, dtype=np.float32)
            frame = np.concatenate([q, dq, gyro, acc_g, proj_grav, np.array([vx_cmd, vy_cmd, wz_cmd], dtype=np.float32), prev_act, ph_vec])
            hist = np.roll(hist, 1, axis=0)
            hist[0] = frame
            obs = hist.reshape(1, V1_OBS_SIZE)
            raw_out = sess.run([out_name], {in_name: obs})[0][0]
            act = np.clip(raw_out, -1.0, 1.0).astype(np.float32)
            prev_act = act
            ctrl = np.clip(act * scale_rad, lo_rad, hi_rad)
            data.ctrl[:] = ctrl
            for _ in range(10):
                # Enforce exact MG90S torque-velocity envelope matching training
                jv = np.array([data.qvel[i] for i in qvel_ids], dtype=np.float64)
                max_tau = 0.18
                no_load = 10.47
                for idx in range(8):
                    lo_f = -max_tau * max(0.0, 1.0 + jv[idx] / no_load)
                    hi_f = max_tau * max(0.0, 1.0 - jv[idx] / no_load)
                    model.actuator_forcerange[idx, 0] = lo_f
                    model.actuator_forcerange[idx, 1] = hi_f
                mujoco.mj_step(model, data)
            if step >= 50:  # Measure steady-state after 1.0 s acceleration
                vx_list.append(float(vb[0]))
                vy_list.append(float(vb[1]))
                wz_list.append(float(gyro[2]))
                z_list.append(float(data.qpos[2] * 1e3))
                spd_list.append(float(np.rad2deg(np.abs(dq)).max()))
                clear_list.append(float(max(data.site_xpos[s][2] for s in foot_sids) * 1e3))
            if proj_grav[2] > -0.42 or data.qpos[2] < 0.026:
                survived = False
                break
        results[name] = {
            "survived": survived,
            "cmd_vx_vy_wz": [vx_cmd, vy_cmd, wz_cmd],
            "achieved_vx_m_s": round(float(np.mean(vx_list)) if vx_list else 0.0, 4),
            "achieved_vy_m_s": round(float(np.mean(vy_list)) if vy_list else 0.0, 4),
            "achieved_wz_rad_s": round(float(np.mean(wz_list)) if wz_list else 0.0, 4),
            "mean_root_z_mm": round(float(np.mean(z_list)) if z_list else 0.0, 2),
            "peak_joint_speed_deg_s": round(float(np.max(spd_list)) if spd_list else 0.0, 1),
            "mean_peak_foot_clearance_mm": round(float(np.mean(clear_list)) if clear_list else 0.0, 2),
        }
    report = {
        "model": "v1-8servo",
        "geometry_id": geo["geometry_id"],
        "mass_kg": geo["mass_kg"],
        "mass_measured": geo["mass_measured"],
        "basis": "MuJoCo CPU simulation with MG90S torque-velocity envelope; not physical hardware qualification",
        "scenarios": results,
    }
    if output_json is not None:
        save_json(output_json, report)
    return report


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--directory", type=Path, required=True)
    p.add_argument("--iterations", type=int, default=450)
    p.add_argument("--num-envs", type=int, default=2048)
    p.add_argument("--device", default="cuda:0")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--flat-only", action="store_true")
    p.add_argument("--evaluate-only", action="store_true")
    args = p.parse_args()
    if args.evaluate_only:
        report = evaluate_v1_policy(args.directory / "policy.onnx", args.directory / "evaluation.json")
        print(json.dumps(report, indent=2))
        return
    onnx_path = train_v1_gait(
        args.directory,
        iterations=args.iterations,
        num_envs=args.num_envs,
        device=args.device,
        seed=args.seed,
        rough=not args.flat_only,
    )
    report = evaluate_v1_policy(onnx_path, args.directory / "evaluation.json")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
