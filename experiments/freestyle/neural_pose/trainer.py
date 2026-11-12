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
)
from .goals import DEFAULT_ENV_JSON, STAND_ANGLES_DEG, PoseManifold, _ensure_native_library
from . import mdp as pose_mdp

_ensure_native_library()

RECIPE = "ainekio-neural-pose-mjlab-v1"
DEFAULT_HIDDEN_DIMS = (512, 256, 128)


@requires_model_fields("actuator_gainprm", "actuator_biasprm")
def randomize_pose_actuators(env, env_ids):
    """Randomize servo Kp/Kd, torque envelope, and 4th-wire ADC scale/offset per episode."""
    ids = torch.arange(env.num_envs, device=env.device) if env_ids is None else env_ids
    n = len(ids)
    if n == 0:
        return
    pose_term = env.action_manager.get_term("pose")
    base_kp = float(pose_term.config.servo_kp)
    base_kd = float(pose_term.config.servo_kd)

    kp_mult = 0.85 + 0.30 * torch.rand((n, 12), device=env.device)
    kd_mult = 0.85 + 0.35 * torch.rand((n, 12), device=env.device)
    effort_mult = 0.82 + 0.28 * torch.rand((n, 12), device=env.device)

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
    """Apply occasional external velocity nudges to grounded worlds for reactive balance recovery."""
    ids = torch.arange(env.num_envs, device=env.device) if env_ids is None else env_ids
    if len(ids) == 0:
        return
    pose_term = env.action_manager.get_term("pose")
    grounded_ids = ids[~pose_term.is_suspended[ids]]
    if len(grounded_ids) == 0:
        return
    asset = env.scene["robot"]
    limits = torch.tensor([0.14, 0.12, 0.0, 0.35, 0.35, 0.0], device=env.device)
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
        self.body = self.manifold.body
        self.sensors = TensorSensors(self.config, env.num_envs, env.device)

        self.joint_ids, _ = self._entity.find_joints(JOINTS, preserve_order=True)
        self.foot_site_ids, _ = self._entity.find_sites(
            tuple(f"{leg}_reference" for leg in LEGS), preserve_order=True
        )

        # 70% grounded worlds, 30% supported/suspended-in-air (legs unloaded) worlds
        n_grounded = int(round(env.num_envs * 0.70))
        self.is_suspended = torch.arange(env.num_envs, device=env.device) >= n_grounded
        self.suspended_ids = torch.nonzero(self.is_suspended, as_tuple=False).squeeze(-1)

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
        if torch.device(env.device).type == "cuda":
            torch.cuda.empty_cache()

        self._raw = torch.zeros((env.num_envs, 12), dtype=torch.float32, device=env.device)
        self.prev_raw_action = torch.zeros_like(self._raw)
        self.prev_action_delta = torch.zeros_like(self._raw)

        self.logical = self.body.q0.reshape(1, 12).expand(env.num_envs, -1).clone()
        self.logical, self.targets = self.body.pwm(self.logical)
        self.targets = self.targets.to(torch.float32)

        # Goal & oscillation buffers
        self.base_goal_rad = self.stand_q_rad.unsqueeze(0).expand(env.num_envs, -1).clone()
        self.current_goal_rad = self.base_goal_rad.clone()
        self.current_goal_foot = self.stand_foot_norm.unsqueeze(0).expand(env.num_envs, -1).clone()
        self.leg_support = torch.ones((env.num_envs, 4), dtype=torch.float32, device=env.device)
        self.speed_scale = torch.full((env.num_envs, 1), 0.75, dtype=torch.float32, device=env.device)

        self.goal_timer = torch.zeros(env.num_envs, dtype=torch.long, device=env.device)
        self.osc_active = torch.zeros(env.num_envs, dtype=torch.bool, device=env.device)
        self.osc_amp_rad = torch.zeros((env.num_envs, 12), dtype=torch.float32, device=env.device)
        self.osc_hz = torch.ones((env.num_envs, 1), dtype=torch.float32, device=env.device)
        self.osc_step = torch.zeros(env.num_envs, dtype=torch.long, device=env.device)

        # 4th-wire ADC usability mask (simulates clipped/faulted feedback wires like joints 1 & 4)
        self.usable_mask = torch.ones((env.num_envs, 12), dtype=torch.bool, device=env.device)

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
        self.decode_command = self.body.command
        self.forward_fn = self.body.forward

        self.reset(None)
        if torch.device(env.device).type == "cuda" and env.num_envs >= 64:
            self.decode_command = torch.compile(self.body.command, fullgraph=True, dynamic=False)
            self.forward_fn = torch.compile(self.body.forward, fullgraph=True, dynamic=False)

    @property
    def action_dim(self):
        return 12

    @property
    def raw_action(self):
        return self._raw

    def _sample_goals(self, ids: torch.Tensor):
        n = len(ids)
        if n == 0:
            return
        dev = self._env.device
        susp = self.is_suspended[ids]
        # 15% return-to-stand, 85% diverse goal bank (grounded envs use grounded-feasible subset;
        # suspended/unloaded envs sample all 2048 goals including arbitrary 4-leg air motions)
        to_stand = torch.rand(n, device=dev) < 0.15
        bank_idx_g = torch.randint(0, self.grounded_goal_count, (n,), device=dev)
        bank_idx_s = torch.randint(0, len(self.goal_bank_rad), (n,), device=dev)
        bank_idx = torch.where(susp, bank_idx_s, bank_idx_g)
        bank_idx = torch.where(to_stand, torch.zeros_like(bank_idx), bank_idx)

        q_base = self.goal_bank_rad[bank_idx]
        foot_base = self.goal_bank_foot[bank_idx]
        sup_base = self.goal_bank_support[bank_idx]

        self.base_goal_rad[ids] = q_base
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

    def _advance_goals_50hz(self):
        self.goal_timer -= 1
        if bool((self.goal_timer <= 0).any()):
            expired = torch.nonzero(self.goal_timer <= 0, as_tuple=False).squeeze(-1)
            self._sample_goals(expired)

        # Static-shape vectorized oscillation update across all N envs (compiled forward_fn, zero dynamic shapes)
        self.osc_step = torch.where(self.osc_active, self.osc_step + 1, self.osc_step)
        t = self.osc_step.to(torch.float32).unsqueeze(-1) * 0.02
        phase = 2.0 * math.pi * self.osc_hz * t
        delta = torch.where(self.osc_active.unsqueeze(-1), self.osc_amp_rad * torch.sin(phase), 0.0)
        q_cand = self.base_goal_rad + delta
        q43 = q_cand.to(torch.float64).reshape(-1, 4, 3)
        q43 = q43.clamp(self.body.low, self.body.high)
        q43 = torch.maximum(torch.minimum(q43, self.target_lims_rad[..., 1]), self.target_lims_rad[..., 0])
        pts, fvalid = self.forward_fn(q43)
        base43 = self.base_goal_rad.to(torch.float64).reshape(-1, 4, 3)
        base_foot43 = self.current_goal_foot.reshape(-1, 4, 3)
        foot_cand = ((pts - self.body.origin) / self.body.scale).clamp(-1.0, 1.0).to(torch.float32)
        use_cand = self.osc_active.unsqueeze(-1) & fvalid
        q_next = torch.where(use_cand.unsqueeze(-1), q43.to(torch.float32), base43.to(torch.float32))
        foot_next = torch.where(use_cand.unsqueeze(-1), foot_cand, base_foot43)
        self.current_goal_rad.copy_(q_next.reshape(-1, 12))
        self.current_goal_foot.copy_(foot_next.reshape(-1, 12))

    def reset_from_joint_state(self, env_ids, q_proj_rad: torch.Tensor):
        ids = torch.arange(self._env.num_envs, device=self._env.device) if env_ids is None else env_ids
        if len(ids) == 0:
            return
        q64 = q_proj_rad.to(dtype=torch.float64, device=self._env.device)
        logical, physical = self.body.pwm(q64)
        pts, _ = self.body.forward(logical.reshape(-1, 4, 3))
        init_act = ((pts - self.body.origin) / self.body.scale).clamp(-1.0, 1.0).reshape(-1, 12).to(torch.float32)

        self.logical[ids] = logical
        self.targets[ids] = physical.to(torch.float32)
        self._raw[ids] = init_act
        self.prev_raw_action[ids] = init_act
        self.prev_action_delta[ids] = 0.0

        # Simulate 4th-wire usability faults on 35% of episodes (including rear carriers 1 & 4)
        n = len(ids)
        usable = torch.ones((n, 12), dtype=torch.bool, device=self._env.device)
        fault_ep = torch.rand(n, device=self._env.device) < 0.35
        random_drop = torch.rand((n, 12), device=self._env.device) < 0.18
        rear_carrier_drop = torch.zeros((n, 12), dtype=torch.bool, device=self._env.device)
        rear_carrier_drop[:, 1] = torch.rand(n, device=self._env.device) < 0.65
        rear_carrier_drop[:, 4] = torch.rand(n, device=self._env.device) < 0.65
        drop_mask = fault_ep.unsqueeze(-1) & (random_drop | rear_carrier_drop)
        self.usable_mask[ids] = usable & (~drop_mask)

        self.sensors.reset(ids, q_proj_rad.to(torch.float32))
        self._sample_goals(ids)
        self._update_suspended_wrench()
        self.pending_reset = ids

    def reset(self, env_ids=None):
        ids = torch.arange(self._env.num_envs, device=self._env.device) if env_ids is None else env_ids
        if len(ids) == 0:
            return
        positions = self._entity.data.joint_pos[ids][:, self.joint_ids]
        self.reset_from_joint_state(ids, positions)

    def process_actions(self, actions: torch.Tensor):
        self._advance_goals_50hz()
        clamped = actions.clamp(-1.0, 1.0)
        new_delta = clamped - self._raw
        self.prev_action_delta.copy_(new_delta)
        self.prev_raw_action.copy_(self._raw)
        self._raw.copy_(clamped)
        self.logical, targets = self.decode_command(self._raw, self.logical)
        self.targets.copy_(targets)
        self._update_suspended_wrench()

    def apply_actions(self):
        robot = self._entity.data
        self.sensors.sample(
            robot.joint_pos[:, self.joint_ids],
            self._env.scene["robot/accel"].data,
            self._env.scene["robot/gyro"].data,
        )
        self._entity.set_joint_position_target(self.targets, joint_ids=self.joint_ids)

    def _build_features(self) -> torch.Tensor:
        usable_f = self.usable_mask.to(torch.float32)
        cmd_rad = self.logical.to(torch.float32)
        joint_rad = torch.where(self.usable_mask, self.sensors.joint, cmd_rad)
        joint_vel = torch.where(self.usable_mask, self.sensors.joint_velocity, torch.zeros_like(cmd_rad))
        proj_grav = -gravity(self.sensors.quaternion)

        features = torch.cat(
            (
                joint_rad,
                joint_vel,
                usable_f,
                self.sensors.gyro,
                self.sensors.accel / 9.81,
                proj_grav,
                self.current_goal_rad,
                self.current_goal_foot,
                self.leg_support,
                self.speed_scale,
                self._raw,
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
        features = self._build_features()
        if self.history_step != self._env.common_step_counter:
            self.history = torch.roll(self.history, 1, 1)
            self.history[:, 0] = features
            if pending is not None:
                # Match PoseObservationHistory step-0 priming with earliest real scan
                self.history[pending] = features[pending].unsqueeze(1)
            self.history_step = self._env.common_step_counter
        elif pending is not None:
            self.history[pending] = features[pending].unsqueeze(1)
        return self.history.flatten(1)

    def privileged_observations(self) -> torch.Tensor:
        q_true = self._entity.data.joint_pos[:, self.joint_ids]
        v_true = self._entity.data.joint_vel[:, self.joint_ids]
        contacts = (self._env.scene["feet_ground_contact"].data.found > 0).to(torch.float32)
        lin_vel = torch.nan_to_num(env_mdp.base_lin_vel(self._env), nan=0.0, posinf=0.0, neginf=0.0)
        susp = self.is_suspended.to(torch.float32).unsqueeze(-1)
        priv = torch.cat((q_true, v_true, contacts, lin_vel, susp), dim=-1)
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
        "reset_pose_worlds": EventTermCfg(func=pose_mdp.reset_pose_worlds, mode="reset"),
        "foot_friction": EventTermCfg(
            func=gait_mdp.randomize_multisurface_friction,
            mode="reset",
            params={"asset_cfg": SceneEntityCfg("robot", geom_names=foot_geoms), "ranges": (0.20, 1.35)},
        ),
        "push_grounded_robot": EventTermCfg(
            func=push_grounded_robot, mode="interval", interval_range_s=(2.5, 5.5)
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
        "pose_tracking": RewardTermCfg(func=pose_mdp.pose_tracking_reward, weight=4.5),
        "grounded_balance": RewardTermCfg(func=pose_mdp.grounded_balance_cost, weight=-1.6),
        "action_smoothness": RewardTermCfg(func=pose_mdp.action_smoothness_cost, weight=-0.035),
        "settle_damping": RewardTermCfg(func=pose_mdp.settle_damping_cost, weight=-0.025),
        "stance_slip": RewardTermCfg(func=pose_mdp.stance_slip_cost, weight=-0.30),
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


def _kinematic_warmstart(runner, wrapped, env, device: str):
    """Warm-start the (512, 256, 128) MLP across the full 12-servo workspace before PPO."""
    pose_term: PoseAction = env.action_manager.get_term("pose")
    actor = runner.alg.actor
    mlp = actor.mlp
    opt = torch.optim.AdamW(mlp.parameters(), lr=1.5e-3, weight_decay=1e-5)

    # Pass 1: populate observation normalizer statistics with smooth kinematic rollouts
    wrapped.reset()
    actor.obs_normalizer.train(True)
    with torch.no_grad():
        for _ in range(120):
            obs = wrapped.get_observations()["actor"]
            _ = actor.obs_normalizer(obs)
            pts, _ = pose_term.forward_fn(pose_term.logical.reshape(-1, 4, 3))
            cur_norm = ((pts - pose_term.body.origin) / pose_term.body.scale).clamp(-1.0, 1.0).reshape(-1, 12).to(torch.float32)
            step_lim = 0.14 * pose_term.speed_scale
            kin_act = (cur_norm + (pose_term.current_goal_foot - cur_norm).clamp(-step_lim, step_lim)).clamp(-0.98, 0.98)
            wrapped.step(kin_act)

    # Pass 2: 2 DAgger rounds fitting MLP -> inverse_tanh(kin_act)
    actor.obs_normalizer.eval()
    warmstart_mae = 0.0
    try:
        for rollout_steps, epochs, policy_prob in ((140, 14, 0.0), (120, 14, 0.7)):
            xs, ys = [], []
            with torch.no_grad():
                for _ in range(rollout_steps):
                    obs = wrapped.get_observations()["actor"]
                    norm_obs = actor.obs_normalizer(obs)
                    pts, _ = pose_term.forward_fn(pose_term.logical.reshape(-1, 4, 3))
                    cur_norm = ((pts - pose_term.body.origin) / pose_term.body.scale).clamp(-1.0, 1.0).reshape(-1, 12).to(torch.float32)
                    step_lim = 0.16 * pose_term.speed_scale
                    kin_act = (cur_norm + (pose_term.current_goal_foot - cur_norm).clamp(-step_lim, step_lim)).clamp(-0.97, 0.97)
                    # Add slight stance weight-shift toward lifted leg during grounded 3-leg gestures
                    sup = pose_term.leg_support
                    partial = (sup.sum(dim=-1) < 3.5) & (~pose_term.is_suspended)
                    if bool(partial.any()):
                        # Leg y signs in body frame: RL(+1), RR(-1), FL(+1), FR(-1)
                        free_left = ((sup[:, 0] < 0.5) | (sup[:, 2] < 0.5)) & partial
                        free_right = ((sup[:, 1] < 0.5) | (sup[:, 3] < 0.5)) & partial
                        shift_y = torch.where(free_left, -0.055, torch.where(free_right, 0.055, 0.0))
                        for leg_i in range(4):
                            stance_i = (sup[:, leg_i] > 0.5) & partial
                            kin_act[:, leg_i * 3 + 1] = torch.where(
                                stance_i, (kin_act[:, leg_i * 3 + 1] + shift_y).clamp(-0.97, 0.97), kin_act[:, leg_i * 3 + 1]
                            )
                    target_logits = torch.atanh(kin_act)
                    xs.append(norm_obs.detach())
                    ys.append(target_logits.detach())
                    if policy_prob > 0.0 and torch.rand((), device=device).item() < policy_prob:
                        act = mlp(norm_obs).clamp(-8.0, 8.0).tanh()
                    else:
                        act = kin_act
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
                    loss = 0.20 * (pred - y_all[idx]).square().mean() + 2.0 * (pred.tanh() - y_tanh[idx]).square().mean()
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

    if hasattr(actor.distribution, "log_std_param"):
        actor.distribution.log_std_param.data.fill_(-1.35)
    runner.alg.optimizer.state.clear()
    if torch.device(device).type == "cuda":
        torch.cuda.empty_cache()
    wrapped.reset()
    return {"warmstart_action_mae": warmstart_mae}


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
        agent.actor.hidden_dims = tuple(int(d) for d in actor_hidden_dims)
        agent.critic.hidden_dims = tuple(int(d) for d in critic_hidden_dims)
        agent.actor.distribution_cfg = {
            "class_name": "gateway.neural_gait.microduck_policy:FootGaussianDistribution",
            "init_std": 0.35,
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
            ckpt_path = str(Path(resume) / "learner.pt")
            has_opt = "optimizer_state_dict" in torch.load(ckpt_path, map_location="cpu", weights_only=False)
            runner.load(
                ckpt_path,
                load_cfg={"actor": True, "critic": True, "optimizer": has_opt, "iteration": has_opt, "rnd": False},
                map_location=device,
            )
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
            for x in ep_info:
                src = x.get("log", x) if isinstance(x, dict) else {}
                if "Pose/joint_mae_deg" in src:
                    mae_vals.append(float(torch.as_tensor(src["Pose/joint_mae_deg"]).float().mean().item()))
                if "Pose/gesture_leg_mae_deg" in src:
                    gest_vals.append(float(torch.as_tensor(src["Pose/gesture_leg_mae_deg"]).float().mean().item()))
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
                },
            )

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
