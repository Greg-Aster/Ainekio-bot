"""Ainekio task for the imported MicroDuck mjlab training implementation.

The upstream velocity factory, foot rewards, PPO runner and normalized ONNX
exporter are executed directly. Ainekio owns the embodiment, sensor/foot-action
interfaces, tracking objective and disturbance curriculum. This module never
connects to a physical robot.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import asdict, dataclass, replace
import hashlib
import json
import math
import shutil
from pathlib import Path
import xml.etree.ElementTree as ET

import mujoco
import numpy as np
import torch

from mjlab.actuator.builtin_actuator import BuiltinPositionActuatorCfg
from mjlab.actuator.actuator import Actuator
from mjlab.utils.spec import create_position_actuator
from mjlab.entity import EntityCfg, EntityArticulationInfoCfg
from mjlab.envs import ManagerBasedRlEnv
from mjlab.managers import ObservationTermCfg, EventTermCfg, CurriculumTermCfg, RewardTermCfg, TerminationTermCfg
from mjlab.managers.event_manager import requires_model_fields
from mjlab.managers.action_manager import ActionTerm, ActionTermCfg
from mjlab.managers.observation_manager import ObservationGroupCfg
from mjlab.managers.scene_entity_config import SceneEntityCfg
from mjlab.rl import RslRlVecEnvWrapper
from mjlab.rl.runner import MjlabOnPolicyRunner
from mjlab.sensor import ContactMatch, ContactSensorCfg, ObjRef, RingPatternCfg, TerrainHeightSensorCfg
import mjlab.terrains as terrain_gen
from mjlab.terrains.terrain_generator import TerrainGeneratorCfg
from mjlab.envs import mdp as env_mdp

# Installed from the pinned, unmodified source under vendor/microduck_rl.
from mjlab_microduck.tasks import MicroduckOnPolicyRunner
from mjlab_microduck.tasks.microduck_velocity_env_cfg import (
    make_microduck_velocity_env_cfg, MicroduckRlCfg,
)

from .artifacts import save_json
from .contract import PROPRIO_SCHEMA, JOINTS, LEGS
from .environment import (EnvironmentConfig, GaitEnvironment, build_xml,
                          representation_identity, ENVIRONMENT_VERSION, GEOMETRY)
from .native import motor_force_range

RECIPE = "microduck-mjlab-v1"
UPSTREAM = Path(__file__).with_name("vendor") / "microduck_rl" / "UPSTREAM.json"
TASK_REVISION = 18
DEFAULT_ACTOR_HIDDEN_DIMS = (128, 64, 32)


@dataclass(kw_only=True)
class LearningStairsCfg(terrain_gen.BoxPyramidStairsTerrainCfg):
    def function(self,difficulty,spec,rng):
        if difficulty < .2:
            return terrain_gen.BoxFlatTerrainCfg(size=self.size).function(difficulty,spec,rng)
        return super().function((difficulty-.2)/.8,spec,rng)


@dataclass(kw_only=True)
class ElevatedRingPatternCfg(RingPatternCfg):
    z_offset: float = 0.10

    def generate_rays(self, mj_model, device):
        local_offsets, local_directions = super().generate_rays(mj_model, device)
        local_offsets = local_offsets.clone()
        local_offsets[:, 2] = self.z_offset
        return local_offsets, local_directions


@dataclass(kw_only=True)
class LearningSlopeCfg(terrain_gen.HfPyramidSlopedTerrainCfg):
    def function(self,difficulty,spec,rng):
        # The first of five difficulty bands is genuinely flat in every column.
        if difficulty < .2:
            return terrain_gen.BoxFlatTerrainCfg(size=self.size).function(difficulty,spec,rng)
        return super().function((difficulty-.2)/.8,spec,rng)


@dataclass(kw_only=True)
class LearningObstaclesCfg(terrain_gen.HfDiscreteObstaclesTerrainCfg):
    def function(self,difficulty,spec,rng):
        if difficulty < .2:
            return terrain_gen.BoxFlatTerrainCfg(size=self.size).function(difficulty,spec,rng)
        return super().function((difficulty-.2)/.8,spec,rng)


@dataclass(kw_only=True)
class LearningWaveCfg(terrain_gen.HfWaveTerrainCfg):
    def function(self,difficulty,spec,rng):
        if difficulty < .2:
            return terrain_gen.BoxFlatTerrainCfg(size=self.size).function(difficulty,spec,rng)
        return super().function((difficulty-.2)/.8,spec,rng)


class AinekioOnPolicyRunner(MicroduckOnPolicyRunner):
    def save(self, path, infos=None):
        # The upstream velocity save annotates a joint_pos action and cannot
        # describe Ainekio's foot-offset action. Keep its checkpoint owner;
        # the final export below attaches the actual Ainekio contract instead.
        MjlabOnPolicyRunner.save(self, path, infos)
        # The imported runner also saves during learning. Keep the existing
        # resume entrypoint current, rather than creating it only after export.
        latest=Path(self.logger.log_dir).parent/"learner.pt"
        if Path(path).resolve()!=latest.resolve():
            temporary=latest.with_suffix(".pt.tmp")
            shutil.copyfile(path,temporary)
            temporary.replace(latest)


@requires_model_fields("actuator_forcerange")
def mg90s_force_fields(env, env_ids):
    """Allocate the same speed-dependent force ranges independently per world."""


class MG90SActuator(Actuator):
    """Existing Ainekio position-servo plant expressed in mjlab tensors."""
    @property
    def command_field(self):
        return "position"

    def edit_spec(self, spec, target_names):
        # This must remain a custom actuator: mjlab fuses builtin actuators and
        # bypasses their compute(), which would lose the MG90S force envelope.
        for name in target_names:
            self._mjs_actuators.append(create_position_actuator(spec, name,
                stiffness=self.cfg.stiffness, damping=self.cfg.damping,
                effort_limit=self.cfg.effort_limit, armature=self.cfg.armature,
                frictionloss=self.cfg.frictionloss, viscous_damping=self.cfg.viscous_damping,
                transmission_type=self.cfg.transmission_type))

    def compute(self, cmd):
        effort_scale = getattr(self, "effort_scale", None)
        limit = self.cfg.effort_limit if effort_scale is None else self.cfg.effort_limit * effort_scale
        lower, upper = motor_force_range(cmd.vel, limit,
                                        self.cfg.speed_rad_s, array=torch)
        ranges = self.entity.data.model.actuator_forcerange
        ranges[:, self._global_ctrl_ids, 0] = lower
        ranges[:, self._global_ctrl_ids, 1] = upper
        # Keep PD inside MuJoCo's implicit integration, matching environment.py.
        return cmd.position_target


@dataclass(kw_only=True)
class MG90SActuatorCfg(BuiltinPositionActuatorCfg):
    speed_rad_s: float

    def build(self, entity, target_ids, target_names):
        return MG90SActuator(self, entity, target_ids, target_names)


@dataclass(kw_only=True)
class FootActionCfg(ActionTermCfg):
    environment: dict

    def build(self, env):
        return FootAction(self, env)


class FootAction(ActionTerm):
    """GPU foot decoding and sensor acquisition; no host state copies."""
    def __init__(self,cfg,env):
        super().__init__(cfg,env)
        from .tensor_body import TensorBody
        from .tensor_sensors import TensorSensors
        from .contract import PROPRIO_FEATURES, PROPRIO_SAMPLES
        self.config=EnvironmentConfig(**cfg.environment)
        self.body=TensorBody(json.loads(GEOMETRY.read_text()),self.config,device=env.device)
        self.sensors=TensorSensors(self.config,env.num_envs,env.device)
        self.joint_ids,_=self._entity.find_joints(JOINTS,preserve_order=True)
        self._raw=torch.zeros((env.num_envs,12),device=env.device)
        self.logical=self.body.q0.reshape(1,12).expand(env.num_envs,-1).clone()
        self.logical,self.targets=self.body.pwm(self.logical)
        self.targets=self.targets.to(self._raw.dtype)
        self.history=torch.zeros((env.num_envs,PROPRIO_SAMPLES,PROPRIO_FEATURES),device=env.device)
        self.mean_dq=torch.zeros((env.num_envs,12),dtype=torch.float32,device=env.device)
        self.foot_home_pos_m=(self.body.origin*1e-3).to(torch.float32)
        self.prev_foot_pos_m=self.foot_home_pos_m.unsqueeze(0).expand(env.num_envs,-1,-1).clone()
        self.mean_foot_pos_m=self.foot_home_pos_m.unsqueeze(0).expand(env.num_envs,-1,-1).clone()
        self.mean_amp_q=torch.zeros((env.num_envs,4),dtype=torch.float32,device=env.device)
        self.mean_amp_z_m=torch.zeros((env.num_envs,4),dtype=torch.float32,device=env.device)
        self.history_step=None
        self.coverage=torch.zeros(2,device=env.device)
        self.reset(None)
        self.decode_command=self.body.command
        if torch.device(env.device).type == "cuda" and env.num_envs >= 64:
            self.decode_command=torch.compile(self.body.command,fullgraph=True,dynamic=False)

    @property
    def action_dim(self):return 12

    @property
    def raw_action(self):return self._raw

    def reset(self,env_ids=None):
        ids=slice(None) if env_ids is None else env_ids
        self._raw[ids]=0;self.logical[ids]=self.body.q0.reshape(12)
        logical,physical=self.body.pwm(self.logical[ids])
        self.logical[ids]=logical;self.targets[ids]=physical.to(self._raw.dtype)
        self.history[ids]=0
        self.mean_dq[ids]=0;self.prev_foot_pos_m[ids]=self.foot_home_pos_m;self.mean_foot_pos_m[ids]=self.foot_home_pos_m
        self.mean_amp_q[ids]=0;self.mean_amp_z_m[ids]=0
        positions=self._entity.data.joint_pos[:,self.joint_ids]
        self.sensors.reset(ids,positions[ids])
        self.pending_reset=ids

    def process_actions(self,actions):
        self._raw.copy_(actions.clamp(-1,1))
        self.logical,targets=self.decode_command(self._raw,self.logical)
        self.targets.copy_(targets)

    def apply_actions(self):
        robot=self._entity.data
        self.sensors.sample(robot.joint_pos[:,self.joint_ids],
            self._env.scene["robot/accel"].data,self._env.scene["robot/gyro"].data)
        self._entity.set_joint_position_target(self.targets,joint_ids=self.joint_ids)

    def observations(self):
        pending=self.pending_reset
        if pending is not None:
            self.sensors.imu(self._env.scene["robot/accel"].data[pending],
                             self._env.scene["robot/gyro"].data[pending],0.,ids=pending)
            self.pending_reset=None
        command=self._env.command_manager.get_command("twist")
        features=self.sensors.features(command,self._raw)
        if self.history_step != self._env.common_step_counter:
            self.history=torch.roll(self.history,1,1);self.history[:,0]=features
            self.history_step=self._env.common_step_counter
            self.coverage[0]+=self.sensors.feedback_initialized.sum()
            self.coverage[1]+=self.sensors.initialized.sum()
        elif pending is not None:
            self.history[pending,0]=features[pending]
        return self.history.flatten(1)

    def close(self):
        pass


def sensor_observations(env):
    return env.action_manager.get_term("feet").observations()


def make_config(config, num_envs=64, *, play=False, include_assembly=True):
    """Adapt the upstream task to Ainekio's physics, sensors and objective."""
    if config.observation_schema != PROPRIO_SCHEMA:
        raise ValueError("Expected the proprioceptive observation schema")
    action_scale = list(config.foot_action_scale_mm) if config.foot_action_scale_mm else [45.0, 25.0, 30.0]
    config=replace(config,collision_profile="locomotion",balance_enabled=False,heading_feedback_enabled=False,control_hz=50,physics_hz=500,foot_action_scale_mm=action_scale)
    cfg = make_microduck_velocity_env_cfg(play=play, rough=False)
    # Obtain the maintained four-bar closure pose, installed CAD and total mass.
    shadow = GaitEnvironment(config, include_assembly=include_assembly, include_visuals=False)
    try:
        shadow.reset(seed=1)
        home = shadow.data.qpos.copy()
        xml = ET.fromstring(build_xml(config, include_assembly=include_assembly, include_visuals=False))
        initial = {shadow.model.joint(i).name: float(home[shadow.model.jnt_qposadr[i]])
                   for i in range(1, shadow.model.njnt)}
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
    lag = round(config.actuator_delay_s*config.physics_hz)
    cfg.scene.entities = {"robot": EntityCfg(
        spec_fn=lambda: mujoco.MjSpec.from_string(spec_xml),
        init_state=EntityCfg.InitialStateCfg(pos=(0., 0., float(home[2])), joint_pos=initial),
        articulation=EntityArticulationInfoCfg(actuators=(MG90SActuatorCfg(
            target_names_expr=JOINTS, stiffness=config.servo_kp, damping=config.servo_kd,
            effort_limit=config.torque_nm, speed_rad_s=math.radians(config.motor_no_load_speed_deg_s),
            delay_min_lag=lag, delay_max_lag=lag),))) }
    feet = tuple(leg+"_reference" for leg in LEGS)
    cfg.scene.sensors = (
        ContactSensorCfg(name="feet_ground_contact",
            primary=ContactMatch(mode="subtree", pattern=tuple(leg+"_pickup_body" for leg in LEGS), entity="robot"),
            secondary=ContactMatch(mode="body", pattern="terrain"), fields=("found", "force"),
            reduce="netforce", num_slots=1, track_air_time=True),
        TerrainHeightSensorCfg(name="foot_height_scan",
            frame=tuple(ObjRef(type="site", name=n, entity="robot") for n in feet),
            pattern=ElevatedRingPatternCfg(rings=(RingPatternCfg.Ring(.015, 2),), include_center=True, z_offset=.10),
            ray_alignment="yaw", max_distance=1., exclude_parent_body=True, include_geom_groups=(0,)))
    cfg.scene.num_envs = num_envs
    cfg.scene.terrain.terrain_type="generator"
    cfg.scene.terrain.max_init_terrain_level=0
    cfg.scene.terrain.terrain_generator=TerrainGeneratorCfg(
        size=(8.,8.),border_width=20.,num_rows=5,num_cols=5,add_lights=False,curriculum=True,
        sub_terrains={
            "flat":terrain_gen.BoxFlatTerrainCfg(proportion=.20),
            "slope_up":LearningSlopeCfg(proportion=.20,
                slope_range=(0.,math.tan(math.radians(8))),platform_width=.5,vertical_scale=.001),
            "cable_ledges":LearningStairsCfg(proportion=.25,
                step_height_range=(.004,.018),step_width=.18,platform_width=1.2,border_width=.5),
            "obstacles":LearningObstaclesCfg(proportion=.20,
                obstacle_width_range=(.10,.26),obstacle_height_range=(.005,.018),
                num_obstacles=12,platform_width=.45,horizontal_scale=.10,vertical_scale=.001),
            "waves":LearningWaveCfg(proportion=.15,
                amplitude_range=(.004,.014),num_waves=3,horizontal_scale=.10,vertical_scale=.001)})
    cfg.viewer.body_name = "torso"
    cfg.actions = {"feet": FootActionCfg(entity_name="robot", environment=asdict(config))}
    cfg.observations = {name: ObservationGroupCfg(
        terms={"sensors": ObservationTermCfg(func=sensor_observations)},
        concatenate_terms=True, enable_corruption=False) for name in ("actor", "critic")}
    cfg.observations["critic"].terms["training_velocity"]=ObservationTermCfg(
        func=lambda env:torch.nan_to_num(env_mdp.base_lin_vel(env),nan=0.,posinf=0.,neginf=0.))
    # Remove MicroDuck head commands, encoder bias, BAM and biped reset/DR.
    # Those are replaced by Ainekio's native sensor/calibration and MG90S plant.
    twist = cfg.commands["twist"]
    cfg.commands = {"twist": twist}
    twist.heading_command = False
    twist.ranges.heading = None
    twist.rel_heading_envs = 0.
    twist.ranges.lin_vel_x = (-.22,.26)
    twist.ranges.lin_vel_y = (-.08,.08)
    twist.ranges.ang_vel_z = (-1.2,1.2)
    mass_randomization = deepcopy(cfg.events["randomize_mass_inertia"])
    com_randomization = deepcopy(cfg.events["randomize_com"])
    cfg.events = {name: cfg.events[name] for name in ("reset_base", "reset_robot_joints", "foot_friction")}
    from . import microduck_mdp as ainekio_mdp
    cfg.events["mg90s_force_fields"] = EventTermCfg(func=mg90s_force_fields, mode="startup")
    if config.randomization:
        mass_randomization.params["asset_cfg"].body_names = (".*",)
        mass_randomization.params["alpha_range"] = (
            math.log(1-config.randomization)/2, math.log(1+config.randomization)/2)
        cfg.events["randomize_mass_inertia"] = mass_randomization
        com_randomization.params["asset_cfg"].body_names = ("torso",)
        com_randomization.params["ranges"] = {0: (-0.020, 0.012), 1: (-0.012, 0.012), 2: (-0.006, 0.006)}
        cfg.events["randomize_com"] = com_randomization
        cfg.events["randomize_actuators"] = EventTermCfg(func=ainekio_mdp.randomize_actuators, mode="reset")
    cfg.events["reset_base"]=EventTermCfg(func=ainekio_mdp.reset_base,mode="reset")
    cfg.events["foot_friction"]=EventTermCfg(func=ainekio_mdp.randomize_multisurface_friction,
        mode="reset",params={"asset_cfg":SceneEntityCfg("robot",geom_names=foot_geoms),"ranges":(0.14,1.45)})
    cfg.events["push_robot"]=EventTermCfg(func=ainekio_mdp.push_robot,
        mode="interval",interval_range_s=(2.,5.))
    keep = ("body_ang_vel", "foot_clearance", "foot_swing_height", "foot_slip")
    cfg.rewards = {name: cfg.rewards[name] for name in keep}
    for term in cfg.rewards.values():
        asset = term.params.get("asset_cfg")
        if asset is not None:
            if asset.body_names:
                asset.body_names = ("torso",)
            if asset.site_names:
                asset.site_names = feet
    cfg.rewards["foot_clearance"]=RewardTermCfg(func=ainekio_mdp.foot_clearance,weight=-.2,
        params=dict(cfg.rewards["foot_clearance"].params,sensor_name="feet_ground_contact",
                    target_height=.022,max_free_height=.042))
    cfg.rewards["foot_swing_height"]=RewardTermCfg(func=ainekio_mdp.foot_swing_height,weight=-.05,
        params=dict(cfg.rewards["foot_swing_height"].params,target_height=.022,max_free_height=.042))
    cfg.rewards["foot_slip"]=RewardTermCfg(func=ainekio_mdp.foot_slip,weight=-.32,
        params=cfg.rewards["foot_slip"].params)
    cfg.rewards.update({
        "tracking_twist":RewardTermCfg(func=ainekio_mdp.tracking_twist,weight=3.5),
        "upright_cost":RewardTermCfg(func=ainekio_mdp.upright_cost,weight=-1.5),
        "tracked_air_time":RewardTermCfg(func=ainekio_mdp.tracked_air_time,weight=1.5),
        "alternating_stride":RewardTermCfg(func=ainekio_mdp.alternating_stride,weight=2.0),
        "action_change":RewardTermCfg(func=ainekio_mdp.action_change,weight=-.01),
        "action_size":RewardTermCfg(func=ainekio_mdp.action_size,weight=-.005),
        "standing_pose":RewardTermCfg(func=ainekio_mdp.standing_pose,weight=-.5)})
    cfg.rewards["body_ang_vel"].weight=-.005
    # Per-step cost budgets prevent one finite physics excursion from
    # dominating PPO returns. They do not alter plant state or motion limits.
    for name,limit in {"body_ang_vel":20.,"foot_slip":1.5,
                       "foot_clearance":1.5,"foot_swing_height":1.,"standing_pose":2.5}.items():
        term=cfg.rewards[name]
        cfg.rewards[name]=RewardTermCfg(func=ainekio_mdp.BoundedCost,weight=term.weight,
            params={"function":term.func,"parameters":term.params,"limit":limit})
    cfg.curriculum = {"walking_difficulty": CurriculumTermCfg(func=ainekio_mdp.WalkingDifficulty,
        params={"widths":[.1,.07,.30]})}
    cfg.terminations = {name: term for name, term in cfg.terminations.items()
                        if name in ("time_out", "fell_over", "nan_state")}
    cfg.terminations["nan_state"].func=ainekio_mdp.invalid_physics
    cfg.terminations["body_collapsed"]=TerminationTermCfg(func=ainekio_mdp.body_collapsed)
    cfg.sim.mujoco.timestep = 1/config.physics_hz
    cfg.sim.mujoco.integrator = "implicitfast"
    # Avoid the float32 Newton Hessian factorization failure on this small
    # closed-chain plant (mujoco_warp#1415). CG solves the same constraints
    # without that factorization; retain the model, timestep and actuator law.
    cfg.sim.mujoco.solver = "cg"
    cfg.sim.mujoco.iterations = 50
    cfg.sim.nconmax = 128
    # Three constraint rows per allocated contact, plus linkage equalities,
    # joint limits and friction rows. The old 256 could not hold that budget.
    cfg.sim.njmax = 512
    cfg.decimation = config.physics_hz//config.control_hz
    cfg.episode_length_s = config.episode_seconds
    return cfg


def evaluate_run(directory, *, episode_seconds=8., seeds=(1000, 1001)):
    """Evaluate a trained MicroDuck policy in GaitEnvironment and record evaluation.json."""
    from .microduck_actor import MicroduckActor
    from .evaluation import evaluate
    directory=Path(directory)
    config=EnvironmentConfig(**json.loads((directory/"environment.json").read_text()))
    eval_config=replace(config,episode_seconds=episode_seconds,randomization=0.)
    baseline=evaluate(None,eval_config,seeds=seeds)
    actor=MicroduckActor(directory/"policy.onnx")
    candidate=evaluate(actor,eval_config,seeds=seeds)
    report=dict(baseline=baseline,candidate=candidate,selected=dict(id="final",policy="policy.onnx",evaluation=candidate))
    save_json(directory/"evaluation.json",report)
    checkpoints_path=directory/"checkpoints.json"
    if checkpoints_path.exists():
        checkpoints=json.loads(checkpoints_path.read_text())
        for item in checkpoints:
            if item.get("id")=="final":
                item["evaluation"]=candidate
        save_json(checkpoints_path,checkpoints)
    return report


def _distill_from_teacher(runner, wrapped, teacher_dir, device):
    """Distill a larger teacher actor into a compact P4 L2-cache-resident student actor."""
    ckpt_path=Path(teacher_dir)/"learner.pt"
    loaded=torch.load(str(ckpt_path),map_location=device,weights_only=False)
    runner.alg.critic.load_state_dict(loaded["critic_state_dict"],strict=True)
    t_sd=loaded["actor_state_dict"]
    student_actor=runner.alg.actor
    for key in ("_mean","_var","_std","count"):
        full_key=f"obs_normalizer.{key}"
        if full_key in t_sd and hasattr(student_actor.obs_normalizer,key):
            getattr(student_actor.obs_normalizer,key).data.copy_(t_sd[full_key].to(device))
    w0,b0=t_sd["mlp.0.weight"],t_sd["mlp.0.bias"]
    w1,b1=t_sd["mlp.2.weight"],t_sd["mlp.2.bias"]
    w2,b2=t_sd["mlp.4.weight"],t_sd["mlp.4.bias"]
    w3,b3=t_sd["mlp.6.weight"],t_sd["mlp.6.bias"]
    teacher_mlp=torch.nn.Sequential(
        torch.nn.Linear(w0.shape[1],w0.shape[0]),torch.nn.ELU(),
        torch.nn.Linear(w1.shape[1],w1.shape[0]),torch.nn.ELU(),
        torch.nn.Linear(w2.shape[1],w2.shape[0]),torch.nn.ELU(),
        torch.nn.Linear(w3.shape[1],w3.shape[0]),
    ).to(device)
    for idx,(w,b) in ((0,(w0,b0)),(2,(w1,b1)),(4,(w2,b2)),(6,(w3,b3))):
        teacher_mlp[idx].weight.data.copy_(w.to(device))
        teacher_mlp[idx].bias.data.copy_(b.to(device))
    teacher_mlp.eval()
    student_mlp=student_actor.mlp
    opt=torch.optim.AdamW(student_mlp.parameters(),lr=1.5e-3,weight_decay=1e-5)
    was_training=student_actor.obs_normalizer.training
    student_actor.obs_normalizer.eval()
    final_action_mae=0.
    try:
        wrapped.reset()
        for dagger_round,(rollout_steps,epochs,student_prob) in enumerate(((200,20,0.0),(150,20,0.8))):
            xs,ys=[],[]
            with torch.no_grad():
                for _ in range(rollout_steps):
                    obs_actor=wrapped.get_observations()["actor"]
                    norm_obs=student_actor.obs_normalizer(obs_actor)
                    t_logits=torch.nan_to_num(teacher_mlp(norm_obs),nan=0.,posinf=8.,neginf=-8.).clamp(-8.,8.)
                    xs.append(norm_obs.detach())
                    ys.append(t_logits.detach())
                    if student_prob>0. and torch.rand((),device=device).item()<student_prob:
                        act=student_mlp(norm_obs).clamp(-8.,8.).tanh()
                    else:
                        act=t_logits.tanh()
                    wrapped.step(act)
            x_all=torch.cat(xs,dim=0)
            y_all=torch.cat(ys,dim=0)
            y_tanh=y_all.tanh()
            n=x_all.shape[0]
            batch_size=4096
            for _ in range(epochs):
                perm=torch.randperm(n,device=device)
                for start in range(0,n,batch_size):
                    idx=perm[start:start+batch_size]
                    pred=student_mlp(x_all[idx])
                    loss=0.25*(pred-y_all[idx]).square().mean()+2.0*(pred.tanh()-y_tanh[idx]).square().mean()
                    opt.zero_grad()
                    loss.backward()
                    torch.nn.utils.clip_grad_norm_(student_mlp.parameters(),2.0)
                    opt.step()
            for g in opt.param_groups:
                g["lr"]*=0.5
            with torch.no_grad():
                final_action_mae=float((student_mlp(x_all[:8192]).tanh()-y_tanh[:8192]).abs().mean().item())
    finally:
        student_actor.obs_normalizer.train(was_training)
    if hasattr(student_actor.distribution,"log_std_param"):
        student_actor.distribution.log_std_param.data.fill_(-1.25)
    runner.alg.optimizer.state.clear()
    wrapped.reset()
    return {"teacher":str(teacher_dir),"distilled_action_mae":final_action_mae}


def train(directory, config, *, iterations, num_envs=1024, device="cuda:0", seed=1,
          resume=None, distill_from=None, actor_hidden_dims=DEFAULT_ACTOR_HIDDEN_DIMS):
    directory=Path(directory)
    directory.mkdir(parents=True,exist_ok=True)
    action_scale = list(config.foot_action_scale_mm) if config.foot_action_scale_mm else [45.0, 25.0, 30.0]
    config=replace(config,observation_schema=PROPRIO_SCHEMA,collision_profile="locomotion",
                   balance_enabled=False,heading_feedback_enabled=False,control_hz=50,physics_hz=500,episode_seconds=20.,
                   foot_action_scale_mm=action_scale)
    save_json(directory/"progress.json",dict(state="starting",iterations=iterations,steps=0))
    env=None
    try:
        cfg=make_config(config,num_envs)
        cfg.seed=seed
        cfg.scene.terrain.terrain_generator.seed=seed
        agent=deepcopy(MicroduckRlCfg)
        agent.logger="tensorboard"
        agent.experiment_name="ainekio_microduck"
        agent.upload_model=False
        if actor_hidden_dims is not None:
            agent.actor.hidden_dims=tuple(int(d) for d in actor_hidden_dims)
        agent.actor.distribution_cfg={
            "class_name":"gateway.neural_gait.microduck_policy:FootGaussianDistribution",
            "init_std":1.,"std_type":"log"}
        agent.save_interval=max(1,math.ceil(500_000/(num_envs*agent.num_steps_per_env)))
        manifest=dict(kind="microduck-mjlab",recipe=RECIPE,algorithm="PPO",
            task_revision=TASK_REVISION,actor_hidden_dims=list(agent.actor.hidden_dims),
            actor_distribution=agent.actor.distribution_cfg,
            distilled_from=str(distill_from) if distill_from else None,
            resumed_from=str(resume) if resume else None,
            rewards={name:term.weight for name,term in cfg.rewards.items()},
            reward_cost_limits={name:term.params["limit"] for name,term in cfg.rewards.items()
                                if "limit" in term.params},
            tracking_widths=cfg.curriculum["walking_difficulty"].params["widths"],
            randomized_initial_episode_clocks=True,
            curriculum="Completed-episode twist tracking and survival; flat/no pushes at level zero",
            upstream=json.loads(UPSTREAM.read_text()),environment=asdict(config),
            environment_version=ENVIRONMENT_VERSION,representation=representation_identity(),
            schema=config.observation_schema,policy=None,device=device,
            adaptation_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            adapter_sources_sha256={name:hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                for name in ("microduck.py","microduck_mdp.py","microduck_policy.py",
                             "tensor_body.py","tensor_sensors.py","contract.py")},
            training_mujoco_version=mujoco.__version__,simulation_workers=num_envs,seed=seed,
            simulation_solver=cfg.sim.mujoco.solver,
            physical_qualified=False,
            sensor_contract="Sensor-derived 15-frame joint/IMU history, commanded twist and previous action",
            fidelity="GPU MuJoCo dynamics, tensor four-bar/calibration/PWM/ADC/IMU models")
        save_json(directory/"manifest.json",manifest)
        save_json(directory/"environment.json",asdict(config))
        env=ManagerBasedRlEnv(cfg,device=device)
        feet=env.action_manager.get_term("feet")
        wrapped=RslRlVecEnvWrapper(env,clip_actions=1.)
        runner=AinekioOnPolicyRunner(wrapped,asdict(agent),str(directory/"learner"),device)
        if resume:
            ckpt_path=str(Path(resume)/"learner.pt")
            has_opt="optimizer_state_dict" in torch.load(ckpt_path,map_location="cpu",weights_only=False)
            runner.load(ckpt_path,load_cfg={"actor":True,"critic":True,"optimizer":has_opt,"iteration":has_opt,"rnd":False},map_location=device)
            if hasattr(runner,"alg") and hasattr(runner.alg,"learning_rate"):
                runner.alg.learning_rate=min(float(runner.alg.learning_rate),1.5e-4)
                for group in runner.alg.optimizer.param_groups:
                    group["lr"]=runner.alg.learning_rate
        elif distill_from:
            save_json(directory/"progress.json",dict(state="distilling",iterations=iterations,steps=0))
            distill_info=_distill_from_teacher(runner,wrapped,distill_from,device)
            manifest["distillation"]=distill_info
            save_json(directory/"manifest.json",manifest)
        original_log=runner.logger.log
        def progress(**values):
            original_log(**values)
            completed=values["it"]-values["start_it"]+1
            save_json(directory/"progress.json",dict(state="training",iterations=completed,
                steps=completed*num_envs*agent.num_steps_per_env,
                rollout_seconds=values["collect_time"],update_seconds=values["learn_time"]))
        runner.logger.log=progress
        runner.learn(iterations,init_at_random_ep_len=True)
        runner.save(str(directory/"learner.pt"))
        runner.export_policy_to_onnx(str(directory),"policy.onnx")
        from mjlab.rl.exporter_utils import attach_metadata_to_onnx
        attach_metadata_to_onnx(str(directory/"policy.onnx"),{
            "ainekio_schema":config.observation_schema,"ainekio_action":"normalized-foot-offsets-v1",
            "microduck_commit":manifest["upstream"]["commit"],
            "checkpoint_sha256":hashlib.sha256((directory/"learner.pt").read_bytes()).hexdigest()})
        from .microduck_actor import MicroduckActor,sensor_influence
        actor=MicroduckActor(directory/"policy.onnx")
        # Host copies occur only after training, for export diagnostics.
        measured=wrapped.get_observations()["actor"][:4].detach().cpu().numpy()
        coverage=dict(zip(("joint_feedback","imu"),feet.coverage.cpu().tolist()))
        evidence=dict(coverage=coverage,action_sensitivity=sensor_influence(actor,measured),
            basis="Observed training inputs and counterfactual export sensitivity; not useful sensor behavior or physical qualification")
        save_json(directory/"sensor-evidence.json",evidence)
        manifest.update(policy="policy.onnx",sensor_evidence="sensor-evidence.json",sensor_coverage=coverage)
        save_json(directory/"manifest.json",manifest)
        steps=iterations*num_envs*agent.num_steps_per_env
        save_json(directory/"checkpoints.json",[dict(id="final",policy="policy.onnx",steps=steps)])
        save_json(directory/"progress.json",dict(state="complete",steps=steps,iterations=iterations,
            selected_checkpoint_id="final",sensor_coverage=coverage,physical_qualified=False))
    except BaseException as error:
        progress_path=directory/"progress.json"
        previous=json.loads(progress_path.read_text()) if progress_path.exists() else {}
        save_json(progress_path,dict(previous,state="error",error=str(error)))
        raise
    finally:
        if env is not None:
            env.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config")
    parser.add_argument("--directory",required=True)
    parser.add_argument("--iterations",type=int)
    parser.add_argument("--steps",type=int,default=20_000_000)
    parser.add_argument("--num-envs",type=int,default=1024)
    parser.add_argument("--device",default="cuda:0")
    parser.add_argument("--seed",type=int,default=1)
    parser.add_argument("--resume")
    parser.add_argument("--distill-from")
    parser.add_argument("--actor-hidden-dims",default="128,64,32")
    parser.add_argument("--evaluate",action="store_true")
    args=parser.parse_args()
    if args.evaluate:
        evaluate_run(args.directory)
        return
    if not args.config:
        parser.error("--config is required for training")
    hidden_dims=tuple(int(x) for x in args.actor_hidden_dims.split(",") if x.strip())
    config=EnvironmentConfig(**json.loads(Path(args.config).read_text()))
    config=replace(config,observation_schema=PROPRIO_SCHEMA,
                   control_hz=50,physics_hz=500,collision_profile="locomotion",balance_enabled=False,heading_feedback_enabled=False)
    iterations=args.iterations if args.iterations is not None else math.ceil(args.steps/(args.num_envs*MicroduckRlCfg.num_steps_per_env))
    train(args.directory,config,iterations=iterations,num_envs=args.num_envs,device=args.device,
          seed=args.seed,resume=args.resume,distill_from=args.distill_from,actor_hidden_dims=hidden_dims)


if __name__=="__main__":
    main()
