"""Neural gait learning, policy artifacts and evaluation; no robot transport."""

import argparse
from copy import deepcopy
from dataclasses import asdict, replace
import gzip
import hashlib
import io
import json
import math
import os
import shutil
from pathlib import Path
import subprocess
import sys
import time

import gymnasium as gym
import numpy as np
import torch
from stable_baselines3 import PPO, SAC
from stable_baselines3.sac.policies import LOG_STD_MIN, LOG_STD_MAX
from stable_baselines3.common.buffers import RolloutBuffer
from stable_baselines3.common.callbacks import BaseCallback
from stable_baselines3.common.logger import Logger, JSONOutputFormat
from stable_baselines3.common.distributions import DiagGaussianDistribution, SquashedDiagGaussianDistribution
from stable_baselines3.common.policies import ActorCriticPolicy
from stable_baselines3.common.vec_env import SubprocVecEnv
from stable_baselines3.common.running_mean_std import RunningMeanStd

from .contract import (SCHEMA, DEPTH_SCHEMA, HISTORY_SCHEMA, SCHEMAS, OBSERVATION_SIZE,
    COMMAND_SLICE, HISTORY_SIZE, HISTORY_START, HISTORY_SAMPLES, HISTORY_ROW_SIZE,
    CRITIC_FEATURES, observation_size)
from .environment import (
    EnvironmentConfig,
    make_environment,
    body_control_config,
    GEOMETRY,
    ENVIRONMENT_VERSION,
    POLICY_ENVIRONMENT_VERSIONS,
    representation_identity,
)


LOCOMOTION_RECIPE = "playground-ppo-v1"
# Per-update sample budget and minibatch divisor of the published recipe. Its
# n_steps=24 assumes thousands of GPU-parallel envs; sizing the rollout by
# transition count keeps the same budget on this host's CPU workers.
ROLLOUT_TRANSITIONS = 2048
MINIBATCH_DIVISOR = 4
# SB3 VecNormalize clips normalized observations to this bound. Without it, the
# observation coordinates that are constant under a request set (an unused
# command axis, an absent depth grid) divide by ~sqrt(epsilon) and amplify noise
# by ~1e4 into the first layer.
OBSERVATION_CLIP = 10.0
# Trust region for the configured epochs. clip_range already bounds each step;
# a tighter target_kl made SB3 abandon the epoch loop before optimizer.step().
TRUST_REGION_KL = 0.08


class PreciseSquashedGaussian(SquashedDiagGaussianDistribution):
    """Keep saturated sampled actions invertible when PPO replays likelihoods."""

    def sample(self):
        self.gaussian_actions = DiagGaussianDistribution.sample(self)
        return torch.tanh(self.gaussian_actions.double())


class PreciseActionRolloutBuffer(RolloutBuffer):
    """Preserve sampled action precision through storage and minibatch access."""

    def reset(self):
        super().reset()
        self.actions = np.zeros((self.buffer_size, self.n_envs, self.action_dim), dtype=np.float64)

    def _get_samples(self, batch_inds, env=None):
        samples = super()._get_samples(batch_inds, env)
        return samples._replace(actions=self.to_torch(self.actions[batch_inds]))


class ActionSpaceGaussian(DiagGaussianDistribution):
    """Explore around the bounded target, without tanh crushing the noise.

    SB3 retains raw samples for likelihood training and clips only commands sent
    to the environment (and predict results). The existing action range remains.
    """

    def proba_distribution(self, mean_actions, log_std):
        return super().proba_distribution(torch.tanh(mean_actions), log_std)


class GaitPPOPolicy(ActorCriticPolicy):
    """Bounded foot-action policy with explicitly frozen or learned exploration."""

    def __init__(self, *args, learned_std=False, action_coordinates="latent",
                 value_learning_rate=None, exploration_learning_rate=None,
                 command_units=(1., 1., 1.), normalize_observations=False, **kwargs):
        self.normalize_observations = normalize_observations
        self.learned_std = learned_std
        if action_coordinates not in ("latent", "action", "linear"):
            raise ValueError("Unknown PPO exploration coordinates")
        self.action_coordinates = action_coordinates
        self.value_learning_rate = value_learning_rate
        self.exploration_learning_rate = exploration_learning_rate
        units = np.asarray(command_units, dtype=float)
        if units.shape != (3,) or not np.all(np.isfinite(units)) or np.any(units <= 0):
            raise ValueError("Command units require three finite positive scales")
        self.command_units = units.tolist()
        observation_space = args[0] if args else kwargs["observation_space"]
        if observation_space.shape == (HISTORY_SIZE,):
            # Separate feature views, not a second controller. The actor never
            # receives the simulator-only pace/reference used by the critic.
            kwargs["share_features_extractor"] = False
        super().__init__(*args, **kwargs)
        if normalize_observations:
            size = observation_space.shape
            self.register_buffer("observation_mean", torch.zeros(size, dtype=torch.float64))
            self.register_buffer("observation_variance", torch.ones(size, dtype=torch.float64))
            self.register_buffer("observation_count", torch.tensor(1e-4, dtype=torch.float64))

    def update_observation_statistics(self, observations):
        """SB3 running moments, owned/saved by the policy used by every consumer."""
        if not self.normalize_observations:
            return
        moments = RunningMeanStd(shape=self.observation_space.shape)
        moments.mean = self.observation_mean.cpu().numpy().copy()
        moments.var = self.observation_variance.cpu().numpy().copy()
        moments.count = float(self.observation_count)
        moments.update(np.asarray(observations).reshape(-1, *self.observation_space.shape))
        with torch.no_grad():
            self.observation_mean.copy_(torch.as_tensor(moments.mean, device=self.device))
            self.observation_variance.copy_(torch.as_tensor(moments.var, device=self.device))
            self.observation_count.fill_(moments.count)

    def extract_features(self, obs, features_extractor=None):
        features = super().extract_features(obs, features_extractor)
        def normalized(values):
            values = values.clone()
            if self.normalize_observations:
                values = (values-self.observation_mean.to(values)) / torch.sqrt(
                    self.observation_variance.to(values)+1e-8)
                values = values.clamp(-OBSERVATION_CLIP, OBSERVATION_CLIP)
            values[:, COMMAND_SLICE] /= values.new_tensor(self.command_units)
            if values.shape[-1] == HISTORY_SIZE:
                for index in range(HISTORY_SAMPLES):
                    start = HISTORY_START+index*HISTORY_ROW_SIZE+58
                    values[:, start:start+3] /= values.new_tensor(self.command_units)
            return values
        if isinstance(features, tuple):
            actor, critic = (normalized(value) for value in features)
            if actor.shape[-1] == HISTORY_SIZE:
                actor[:, -CRITIC_FEATURES:] = 0
            return actor, critic
        return normalized(features)

    def get_distribution(self, obs):
        # SB3's convenience prediction methods bypass ActorCriticPolicy's
        # extract_features override. Route all paths through the same units.
        features = self.extract_features(obs)
        actor = features[0] if isinstance(features, tuple) else features
        return self._get_action_dist_from_latent(self.mlp_extractor.forward_actor(actor))

    def predict_values(self, obs):
        features = self.extract_features(obs)
        value = features[1] if isinstance(features, tuple) else features
        return self.value_net(self.mlp_extractor.forward_critic(value))

    def _build(self, lr_schedule):
        distribution = {"latent": PreciseSquashedGaussian, "action": ActionSpaceGaussian,
                        "linear": DiagGaussianDistribution}[self.action_coordinates]
        self.action_dist = distribution(int(np.prod(self.action_space.shape)))
        self._squash_output = self.action_coordinates == "latent"
        super()._build(lr_schedule)
        self.log_std.requires_grad_(self.learned_std)
        if self.value_learning_rate is not None:
            self.configure_value_learning(self.value_learning_rate)
        if self.exploration_learning_rate is not None:
            self.configure_exploration_learning(self.exploration_learning_rate)

    def _configure_optimizer_group(self, role, parameters, rate):
        if not math.isfinite(rate) or rate <= 0:
            raise ValueError("Optimizer learning rate must be finite and positive")
        if not any(group.get("gait_role") == role for group in self.optimizer.param_groups):
            # Keep this one Adam optimizer and its parameter-keyed moments.
            # Only group membership/rates change, including legacy one-group saves.
            ids = {id(parameter) for parameter in parameters}
            template = dict(next(group for group in self.optimizer.param_groups
                                 if any(id(parameter) in ids for parameter in group["params"])))
            for group in self.optimizer.param_groups:
                group.setdefault("gait_role", "actor")
                group["params"] = [parameter for parameter in group["params"] if id(parameter) not in ids]
            self.optimizer.add_param_group({**template, "params": parameters, "gait_role": role})
        for group in self.optimizer.param_groups:
            if group.get("gait_role") == role:
                group["lr"] = rate
        # Save/load reconstructs groups in this canonical order, even if options
        # were applied to an existing model in a different order.
        self.optimizer.param_groups.sort(key=lambda group:
            {"actor": 0, "value": 1, "exploration": 2}[group["gait_role"]])

    def configure_value_learning(self, rate):
        values = list(self.mlp_extractor.value_net.parameters()) + list(self.value_net.parameters())
        self._configure_optimizer_group("value", values, rate)
        self.value_learning_rate = rate

    def configure_exploration_learning(self, rate):
        if not self.learned_std:
            raise ValueError("Exploration learning rate requires a policy with learned standard deviation")
        self._configure_optimizer_group("exploration", [self.log_std], rate)
        self.exploration_learning_rate = rate

    def _get_constructor_parameters(self):
        parameters = super()._get_constructor_parameters()
        parameters["normalize_observations"] = self.normalize_observations
        parameters["learned_std"] = self.learned_std
        parameters["action_coordinates"] = self.action_coordinates
        parameters["value_learning_rate"] = self.value_learning_rate
        parameters["exploration_learning_rate"] = self.exploration_learning_rate
        parameters["command_units"] = self.command_units
        return parameters


class GaitPPO(PPO):
    """SB3 PPO with rates for the existing actor, value and exploration parameters."""

    def collect_rollouts(self, env, callback, rollout_buffer, n_rollout_steps):
        # Update from the completed preceding batch, then freeze normalization
        # across this rollout AND its PPO epochs. Old/new likelihoods use the
        # same feature transform; no separate inference-side normalizer exists.
        if rollout_buffer.full and self.policy.normalize_observations:
            self.policy.update_observation_statistics(rollout_buffer.observations)
        return super().collect_rollouts(env, callback, rollout_buffer, n_rollout_steps)

    def _update_learning_rate(self, optimizers):
        super()._update_learning_rate(optimizers)
        for role, rate in (("value", self.policy.value_learning_rate),
                           ("exploration", self.policy.exploration_learning_rate)):
            if rate is None:
                continue
            for group in self.policy.optimizer.param_groups:
                if group.get("gait_role") == role:
                    group["lr"] = rate
            self.logger.record(f"train/{role}_learning_rate", rate)


def configure_action_exploration(model, standard_deviation):
    """Explicit PPO handoff; preserve actor/value weights and their Adam state."""
    values = np.asarray(standard_deviation, dtype=float)
    if (not isinstance(model, PPO) or not isinstance(model.policy, GaitPPOPolicy)
            or values.shape != model.action_space.shape
            or not np.all(np.isfinite(values)) or np.any(values <= 0)):
        raise ValueError("Action exploration requires twelve positive PPO standard deviations")
    policy = model.policy
    before = dict(coordinates=policy.action_coordinates,
                  standard_deviation=policy.log_std.detach().exp().cpu().tolist())
    policy.action_coordinates = "linear" if policy.action_coordinates == "linear" else "action"
    distribution = DiagGaussianDistribution if policy.action_coordinates == "linear" else ActionSpaceGaussian
    policy.action_dist = distribution(int(np.prod(model.action_space.shape)))
    policy._squash_output = False
    with torch.no_grad():
        policy.log_std.copy_(torch.as_tensor(np.log(values), device=policy.log_std.device,
                                           dtype=policy.log_std.dtype))
    # The noise parameter has changed units; its moments no longer describe the
    # new parameterization. All actor/value parameter moments remain intact.
    policy.optimizer.state.pop(policy.log_std, None)
    model.policy_kwargs["action_coordinates"] = policy.action_coordinates
    return dict(source=before, target=dict(coordinates=policy.action_coordinates, standard_deviation=values.tolist()),
                reset_optimizer_parameters=["log_std"])


def configure_command_units(model, units):
    """Change internal feature units while retaining the current policy function.

    Raw SI observations, requests and robot limits are unchanged. Adam's moments
    are gradients in weight coordinates, so transform them inversely to weights.
    """
    values = np.asarray(units, dtype=float)
    if (not isinstance(model, GaitPPO) or values.shape != (3,)
            or not np.all(np.isfinite(values)) or np.any(values <= 0)):
        raise ValueError("PPO command units require three finite positive scales")
    policy = model.policy
    previous = list(policy.command_units)
    ratio = values/np.asarray(previous)
    with torch.no_grad():
        for network in (policy.mlp_extractor.policy_net, policy.mlp_extractor.value_net):
            weight = network[0].weight
            scale = weight.new_tensor(ratio)
            state = policy.optimizer.state.get(weight, {})
            slices = [COMMAND_SLICE]
            if weight.shape[1] == HISTORY_SIZE:
                slices += [slice(HISTORY_START+i*HISTORY_ROW_SIZE+58,
                                 HISTORY_START+i*HISTORY_ROW_SIZE+61) for i in range(HISTORY_SAMPLES)]
            for columns in slices:
                weight[:, columns] *= scale
                for key, power in (("exp_avg", 1), ("exp_avg_sq", 2), ("max_exp_avg_sq", 2)):
                    if key in state:
                        state[key][:, columns] /= scale**power
    policy.command_units = values.tolist()
    model.policy_kwargs["command_units"] = values.tolist()
    return dict(source=previous, target=values.tolist(),
                weights="first-layer command columns multiplied by target/source units",
                optimizer="first and second moments transformed into new weight coordinates")


def policy_algorithm(manifest):
    """Resolve existing artifact labels without guessing an unknown algorithm."""
    algorithm = manifest.get("algorithm", "SAC")
    if algorithm in ("SAC", "DAgger behavior cloning of SAC actor"):
        return "SAC"
    if algorithm == "PPO":
        return "PPO"
    raise ValueError(f"Unsupported neural gait artifact algorithm: {algorithm!r}")


def require_sac_training(manifest):
    if policy_algorithm(manifest) != "SAC":
        raise ValueError("SAC imitation cannot consume a PPO artifact; "
                         "use PPO resume or explicit PPO weights-only initialization")


def load_policy(directory, checkpoint="policy.zip", *, device="cpu", env=None):
    """One artifact loader for inference and replay, including legacy SAC runs."""
    directory = Path(directory)
    manifest = json.loads((directory / "manifest.json").read_text())
    owner = {"SAC": SAC, "PPO": GaitPPO}[policy_algorithm(manifest)]
    if manifest.get("schema") == HISTORY_SCHEMA and owner is not GaitPPO:
        raise ValueError("History schema requires the asymmetric GaitPPO actor/critic")
    return owner.load(directory / checkpoint, device=device, env=env)


def save_json(path, value):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, indent=2, allow_nan=False))
    tmp.replace(path)


def save_replay(model, directory):
    """Persist the complete SB3 buffer without storing its empty slots verbatim."""
    directory = Path(directory)
    target = directory / "replay.pkl.gz"
    temporary = directory / "replay.pending.pkl.gz"
    try:
        with gzip.open(temporary, "wb", compresslevel=1) as compressed, io.BufferedWriter(compressed) as stream:
            model.save_replay_buffer(stream)
        temporary.replace(target)
        (directory / "replay.pkl").unlink(missing_ok=True)
    finally:
        temporary.unlink(missing_ok=True)


def load_replay(model, directory):
    """Read compressed buffers and retain exact-resume support for older runs."""
    directory = Path(directory)
    compressed = directory / "replay.pkl.gz"
    if compressed.exists():
        with gzip.open(compressed, "rb") as archive, io.BufferedReader(archive) as stream:
            model.load_replay_buffer(stream)
        return True
    legacy = directory / "replay.pkl"
    if legacy.exists():
        model.load_replay_buffer(legacy)
        return True
    return False


def request_interval_steps(config, command_switch_seconds=None, command_switch_range=None, rng=None):
    """Validate requested timing and draw one offline request interval when due."""
    if command_switch_seconds is not None and command_switch_range is not None:
        raise ValueError("Choose fixed command-switch seconds or a command-switch range")
    bounds = command_switch_range
    if bounds is None:
        duration = config.episode_seconds if command_switch_seconds is None else command_switch_seconds
        bounds = [duration, duration]
    if (len(bounds) != 2 or not all(np.isfinite(value) and value > 0 for value in bounds)
            or bounds[0] > bounds[1]):
        raise ValueError("Command-switch range requires ordered positive finite seconds")
    if round(bounds[0]*config.control_hz) < 1:
        raise ValueError("Command switch interval must span at least one control step")
    seconds = rng.uniform(*bounds) if rng is not None and bounds[0] != bounds[1] else bounds[0]
    return round(seconds*config.control_hz)


def request_timing(prior, command_switch_seconds=None, command_switch_range=None):
    """An omitted timing request inherits the source task; explicit input replaces it."""
    previous = {key: prior.get(key) for key in ("command_switch_seconds", "command_switch_range")}
    selected = (previous if command_switch_seconds is None and command_switch_range is None else
                dict(command_switch_seconds=command_switch_seconds, command_switch_range=command_switch_range))
    changes = {key: dict(source=previous[key], target=value) for key, value in selected.items()
               if previous[key] != value}
    return selected, changes


class CommandRequests(gym.Wrapper):
    """Offline requested tasks; all body/sensor/motion state stays in the environment."""

    def __init__(self, env, commands, command_switch_seconds=None, command_switch_range=None):
        super().__init__(env)
        self.commands = deepcopy(commands)
        self.timing = dict(command_switch_seconds=command_switch_seconds,
                           command_switch_range=command_switch_range)
        request_interval_steps(env.config, **self.timing)

    def _request(self, start):
        interval = request_interval_steps(self.env.config, rng=self.env.np_random, **self.timing)
        self.request = dict(start_step=start,
            scheduled_end_step=min(round(self.env.config.episode_seconds*self.env.config.control_hz), start+interval),
            command_index=self.index, command=list(self.commands[self.index]))

    def reset(self, **kwargs):
        observation, info = self.env.reset(**kwargs)
        self.index = self.commands.index(getattr(self.env, "requested_command", self.env.config.command))
        self._request(0)
        return observation, info

    def step(self, action):
        observation, reward, terminated, truncated, info = self.env.step(action)
        if not (terminated or truncated) and self.env.steps == self.request["scheduled_end_step"]:
            self.index = (self.index+1) % len(self.commands)
            observation = self.env.set_command(self.commands[self.index])
            self._request(self.env.steps)
        # The reward/info describe the action just executed. The observation
        # already contains the next request before the actor selects its action.
        return observation, reward, terminated, truncated, info


def command_schedule(config, commands, start_index=0, command_switch_seconds=None):
    """An offline episode's requested commands, independent of physical state."""
    horizon = round(config.episode_seconds*config.control_hz)
    interval = request_interval_steps(config, command_switch_seconds)
    return [dict(start_step=step, scheduled_end_step=min(horizon, step+interval),
                 command_index=(start_index+index)%len(commands),
                 command=list(commands[(start_index+index)%len(commands)]))
            for index, step in enumerate(range(0, horizon, interval))]


def begin_command_segment(env, scheduled):
    rotation = env.data.xmat[env.model.body("torso").id].reshape(3, 3)
    heading = float(np.arctan2(rotation[1, 0], rotation[0, 0]))
    return dict(scheduled, end_step=scheduled["start_step"], transitions=0, seconds=0.,
                reward=0., start_position_m=env.data.qpos[:3].tolist(),
                displacement_m=[0.,0.,0.], command_reference_travel_m=[0.,0.],
                start_heading_rad=heading, end_heading_rad=heading,
                heading_change_rad=0., fallen=False)


def record_command_segment(segment, env, reward, info):
    for name, value in info.get("reward_components", {}).items():
        components = segment.setdefault("reward_components", {})
        components[name] = components.get(name, 0.) + value
    for name, value in info.get("motion_metrics", {}).items():
        metrics = segment.setdefault("motion_metric_sums", {})
        metrics[name] = metrics.get(name, 0.) + value
    segment["transitions"] += 1
    segment["end_step"] = segment["start_step"]+segment["transitions"]
    segment["seconds"] = segment["transitions"]/env.config.control_hz
    segment["reward"] += float(reward)
    segment["displacement_m"] = (env.data.qpos[:3]-segment["start_position_m"]).tolist()
    segment["command_reference_travel_m"] = (
        np.asarray(segment["command_reference_travel_m"])
        +np.asarray(info["velocity_command_m_s"])/env.config.control_hz).tolist()
    delta = info["heading_rad"]-segment["end_heading_rad"]
    segment["heading_change_rad"] += float(np.arctan2(np.sin(delta), np.cos(delta)))
    segment["end_heading_rad"] = float(info["heading_rad"])
    segment["fallen"] |= bool(info["fallen"])


def summarize_commands(episodes):
    """Measured progress for each requested twist, including request transitions.

    Older artifacts without command-frame measurements remain unavailable;
    world-frame displacement cannot substitute for these measurements.
    """
    grouped = {}
    for episode in episodes:
        for segment in episode.get("command_segments") or [episode]:
            required = ("command", "seconds", "command_reference_travel_m", "heading_change_rad", "reward")
            if any(key not in segment for key in required) or segment["seconds"] <= 0:
                return None
            key = tuple(segment["command"])
            row = grouped.setdefault(key, dict(command=list(key), seconds=0.,
                travel=[0.,0.], heading=0., reward=0.))
            row["seconds"] += segment["seconds"]
            for axis in range(2):
                row["travel"][axis] += segment["command_reference_travel_m"][axis]
            row["heading"] += segment["heading_change_rad"]
            row["reward"] += segment["reward"]
    return [dict(command=row["command"], seconds=row["seconds"],
                 measured_velocity_command_m_s=[value/row["seconds"] for value in row["travel"]],
                 measured_yaw_rate_rad_s=row["heading"]/row["seconds"],
                 mean_reward_per_second=row["reward"]/row["seconds"])
            for row in grouped.values()]


def evaluate(model, config, seeds=None, commands=None, command_switch_seconds=None,
             command_switch_range=None, progress=None, compact=False):
    if compact:
        seeds = (1000,)
    if seeds is None:
        varied = any((command_switch_range is not None, config.randomization, config.feedback_noise_raw_std,
                      config.imu_accel_noise_std, config.imu_gyro_noise_std))
        seeds = range(1000, 1008) if varied else (1000,)
    seeds = tuple(seeds)
    commands = commands or [config.command]
    scenarios = getattr(config, "scenarios", []) or [None]
    if compact:
        scenarios = scenarios[:1]
    total = len(commands)*len(seeds)*len(scenarios)
    env = make_environment(config, include_visuals=False, commands=commands)
    switching = command_switch_seconds is not None or command_switch_range is not None
    requests = CommandRequests(env, commands, command_switch_seconds, command_switch_range) if switching else env
    rows = []
    try:
        if progress:
            progress(0, total)
        for command_index, command, scenario_index, scenario, seed in (
                (i, command, j, scenario, seed) for i, command in enumerate(commands)
                for j, scenario in enumerate(scenarios) for seed in seeds):
            options = {"command": command}
            if scenario is not None:
                options["scenario"] = scenario["id"]
            obs, reset_info = requests.reset(seed=seed, options=options)
            segments = [begin_command_segment(env, requests.request)] if switching else []
            progress_intervals = []
            start = env.data.qpos[:3].copy()
            reward = 0.0
            travel_reward = 0.0
            fallen = False
            rejected = 0
            moving_targets = 0
            contacts = np.zeros(4)
            clearance = np.full(4,-np.inf)
            clearance_observed = np.zeros(4, dtype=int)
            upright = 1.0
            body_travel = np.zeros(3)
            command_travel = np.zeros(2)
            rotation = env.data.xmat[env.model.body("torso").id].reshape(3, 3)
            initial_heading = float(np.arctan2(rotation[1, 0], rotation[0, 0]))
            previous_heading = unwrapped_heading = initial_heading
            maximum_heading_deviation = 0.0
            slip_squared_sum = 0.0
            maximum_tracking_error = 0.0
            fit_reduced_frames = fit_observed_frames = jam_frames = 0
            previous_target_step = np.zeros(12)
            motion_metric_sums = {}
            # Held-out episodes measure actual simulated chassis displacement.
            for step in range(round(config.episode_seconds * config.control_hz)):
                if segments and step and step == requests.request["start_step"]:
                    segments.append(begin_command_segment(env, requests.request))
                # One-second reporting intervals expose early motion followed
                # by rest. Split at request changes too; never mix directions.
                # This records evaluation only and does not schedule the robot.
                if (not progress_intervals or step % config.control_hz == 0
                        or list(env.config.command) != progress_intervals[-1]["command"]):
                    progress_intervals.append(begin_command_segment(env,
                        dict(start_step=step, command=list(env.config.command))))
                action = (
                    env.last_action.copy()
                    if model is None
                    else model.predict(obs, deterministic=True)[0]
                )
                previous_target = env.last_target.copy()
                previous_action = env.last_action.copy()
                raw_mean = (model.policy.action_dist.distribution.mean.detach().cpu().numpy()[0].copy()
                            if isinstance(model, PPO) and not model.policy.squash_output else None)
                obs, r, terminated, truncated, info = requests.step(action)
                target_step = env.last_target-previous_target
                metrics = dict(
                    requested_foot_step_squared_mm2=float(np.mean(((action-previous_action)*
                        np.tile(config.foot_action_scale_mm, 4))**2)),
                    target_step_squared_deg2=float(np.mean(target_step**2)),
                    target_acceleration_squared_deg2_s4=float(np.mean(
                        ((target_step-previous_target_step)*config.control_hz**2)**2)))
                if raw_mean is not None:
                    metrics["raw_mean_outside_fraction"] = float(np.mean(np.abs(raw_mean) > 1))
                    metrics["raw_mean_excess_squared"] = float(np.mean(np.maximum(np.abs(raw_mean)-1, 0)**2))
                info["motion_metrics"] = metrics
                for name, value in metrics.items():
                    motion_metric_sums[name] = motion_metric_sums.get(name, 0.)+value
                previous_target_step = target_step
                if segments:
                    record_command_segment(segments[-1], env, r, info)
                record_command_segment(progress_intervals[-1], env, r, info)
                feet = env.foot_measurements()
                contacts += feet["contact"]
                clearance_valid = np.asarray(feet.get("clearance_valid", [True]*4))
                clearance = np.maximum(clearance, np.where(clearance_valid, feet["clearance_m"], -np.inf))
                clearance_observed += clearance_valid
                upright = min(upright, info["upright"])
                body_travel += np.asarray(info["velocity_body_m_s"])/config.control_hz
                command_travel += np.asarray(info["velocity_command_m_s"])/config.control_hz
                heading = info["heading_rad"]
                change = heading-previous_heading
                unwrapped_heading += float(np.arctan2(np.sin(change), np.cos(change)))
                previous_heading = heading
                maximum_heading_deviation = max(maximum_heading_deviation,
                                                 abs(unwrapped_heading-initial_heading))
                slip_squared_sum += info["contact_slip_speed_squared_m2_s2"]
                maximum_tracking_error = max(maximum_tracking_error, float(np.max(
                    np.abs(env.last_target-np.rad2deg(env.data.qpos[env.qadr])))))
                if info.get("foot_fit") is not None:
                    fit_observed_frames += 1
                    fit_reduced_frames += int(np.any(np.asarray(info["foot_fit"]) < 1))
                jam_frames += int(info["jammed_joints"] != 0)
                rejected += int(info["target_rejected"])
                moving_targets += int(np.max(np.abs(env.last_target-previous_target)) > 1e-6)
                reward += r
                travel_reward += info["travel_reward"]
                if terminated or truncated:
                    fallen = info["fallen"]
                    break
            seconds = (step + 1) / config.control_hz
            rows.append(
                dict(
                    seed=seed,
                    command=list(command),
                    **({"scenario_id": scenario["id"], "scenario_index": scenario_index} if scenario else {}),
                    progress_intervals=progress_intervals,
                    **({"command_segments": segments, "command_switch_seconds": command_switch_seconds,
                        "command_switch_range": command_switch_range} if segments else {}),
                    **({"command_index": command_index} if len(commands) > 1 else {}),
                    reward=reward,
                    mean_total_reward_per_step=reward/(step+1),
                    mean_travel_reward_per_step=travel_reward/(step+1),
                    motion_metric_means={name: value/(step+1) for name, value in motion_metric_sums.items()},
                    seconds=seconds,
                    fallen=fallen,
                    displacement_m=(env.data.qpos[:3] - start).tolist(),
                    forward_m_s=float((env.data.qpos[0] - start[0]) / seconds),
                    rejected_frames=rejected,
                    moving_target_frames=moving_targets,
                    minimum_upright=upright,
                    body_frame_travel_m=body_travel.tolist(),
                    command_reference_travel_m=command_travel.tolist(),
                    world_heading_unwrapped_rad=unwrapped_heading,
                    heading_change_rad=unwrapped_heading-initial_heading,
                    maximum_heading_deviation_rad=maximum_heading_deviation,
                    mean_contact_slip_speed_squared_m2_s2=slip_squared_sum/(step+1),
                    maximum_joint_tracking_error_deg=maximum_tracking_error,
                    fit_reduced_frames=fit_reduced_frames if fit_observed_frames else None,
                    fit_observed_frames=fit_observed_frames,
                    execution_backend=config.execution_backend,
                    body_terminal=info.get("body_terminal"),
                    body_rejection=info.get("body_rejection"),
                    producer_failure=info.get("producer_failure"),
                    consumed_sample=info.get("consumed_sample"),
                    jam_frames=jam_frames,
                    foot_contact_fraction=(contacts/(step+1)).tolist(),
                    peak_lower_leg_clearance_m=[float(value) if math.isfinite(value) else None for value in clearance],
                    clearance_observed_frames=clearance_observed.tolist(),
                )
            )
            if progress:
                progress(len(rows), total)
    finally:
        env.close()
    return dict(
        scope="simulation_only",
        evaluation_scope="compact_checkpoint" if compact else "full_configured_suite",
        travel_frames=dict(displacement_m="fixed world frame",
            command_reference_travel_m="command-start horizontal reference, following requested turn",
            body_frame_travel_m="integrated instantaneous full3D measured body frame"),
        policy_kind="held_standing_reference" if model is None else "neural_foot_offsets",
        trial_variation="configured physics, sensor or request-timing variation; otherwise one deterministic reference trial",
        episodes=rows,
        command_results=summarize_commands(rows),
        mean_forward_m_s=float(np.mean([r["forward_m_s"] for r in rows])),
        falls=sum(r["fallen"] for r in rows),
        mean_reward=float(np.mean([r["reward"] for r in rows])),
    )


class Progress(BaseCallback):
    def __init__(self, directory, steps, config, checkpoint_every=10000, commands=None,
                 command_switch_seconds=None, command_switch_range=None):
        super().__init__()
        self.directory = directory
        self.steps = steps
        self.started = time.monotonic()
        self.last = 0
        self.config = config
        self.commands = commands
        self.command_switch_seconds = command_switch_seconds
        self.command_switch_range = command_switch_range
        self.checkpoint_every = checkpoint_every
        self.checkpoints = []
        self.checkpoint_step = None
        self.start_step = 0
        self.renderer = None
        self.imitation_updates = 0
        self.checkpoint_identity = None

    def report(self, state, **details):
        step = self.model.num_timesteps
        save_json(self.directory / "progress.json", dict(
            state=state, steps=step, steps_this_run=step-self.start_step,
            requested_steps=self.steps, imitation_updates=self.imitation_updates,
            optimizer_updates=getattr(self.model, "_n_updates", None),
            optimizer_update_unit="epochs" if isinstance(self.model, PPO) else "gradient_steps",
            elapsed_s=time.monotonic()-self.started, **details))

    def evaluate(self, model, purpose, *, compact=False, **details):
        self.report("evaluating", evaluation_purpose=purpose, **details)
        return evaluate(model, self.config, commands=self.commands, compact=compact,
            command_switch_seconds=self.command_switch_seconds,
            command_switch_range=self.command_switch_range,
            progress=lambda completed, total: self.report("evaluating",
                evaluation_purpose=purpose, completed_episodes=completed,
                total_episodes=total, **details))

    def checkpoint(self, *, aggregation_round=None, training_states=None):
        step = self.model.num_timesteps
        identity = f"{step:09d}"
        if self.imitation_updates:
            identity += f"-imitation{self.imitation_updates:09d}"
        if aggregation_round is not None:
            identity += f"-round{aggregation_round:03d}"
        for row in self.checkpoints:
            if row["id"] == identity:
                return row
        folder = self.directory / "checkpoints"
        folder.mkdir(exist_ok=True)
        filename = identity + ".zip"
        temporary = folder / (filename + ".pending.zip")
        self.model.save(temporary)
        temporary.replace(folder / filename)
        result = self.evaluate(self.model, "checkpoint", compact=True, checkpoint_id=identity)
        row = dict(id=identity, steps=step, policy="checkpoints/" + filename,
                   evaluation=result, evaluation_scope="one matched seed and first configured scenario per command",
                   imitation_updates=self.imitation_updates,
                   commands=self.commands or [self.config.command],
                   command_switch_seconds=self.command_switch_seconds,
                   command_switch_range=self.command_switch_range,
                   optimizer_updates=self.model._n_updates if hasattr(self.model, "_n_updates") else None,
                   optimizer_update_unit="epochs" if isinstance(self.model, PPO) else "gradient_steps",
                   aggregation_round=aggregation_round, training_states=training_states)
        self.checkpoints.append(row)
        save_json(self.directory / "checkpoints.json", self.checkpoints)
        self.checkpoint_step = step
        self.checkpoint_identity = identity
        return row

    def render_progress(self):
        if self.renderer is not None and self.renderer.poll() is None:
            return
        with (self.directory / "progress-render.log").open("a") as log:
            self.renderer = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "gateway.neural_gait.replay",
                    "--directory",
                    str(self.directory),
                    "--progress",
                    "--comparison",
                ],
                stdout=log,
                stderr=subprocess.STDOUT,
                env={**os.environ, "MUJOCO_GL": os.environ.get("MUJOCO_GL", "egl")},
            )

    def finish_rendering(self):
        if self.renderer is not None:
            self.renderer.wait()
        path = self.directory / "progress-video.json"
        status_path = self.directory / "progress.json"
        status = json.loads(status_path.read_text()) if status_path.exists() else {}
        final_id = status.get("selected_checkpoint_id", self.checkpoints[-1]["id"])
        expected = list(dict.fromkeys((self.checkpoints[0]["id"], final_id)))
        def published():
            metadata = json.loads(path.read_text()) if path.exists() else {}
            return (metadata.get("checkpoint_ids") == expected
                    and metadata.get("footage_scope") == "initial_final_matched_trial")
        if not published():
            self.render_progress()
            self.renderer.wait()
        # A coalesced renderer can exit without publishing this comparison.
        return published() and (self.renderer is None or self.renderer.returncode == 0)

    def _on_training_start(self):
        self.start_step = self.model.num_timesteps
        self.checkpoint()
        self.report("training")

    def _on_rollout_start(self):
        # SAC performs its optimizer update after collecting the preceding
        # rollout. Capture that updated policy, not the pre-update action step.
        if self.model.num_timesteps - self.checkpoint_step >= self.checkpoint_every:
            self.checkpoint()
            self.report("training")

    def _on_step(self):
        now = time.monotonic()
        if now - self.last >= 2:
            self.last = now
            self.report("training")
        return True


def resume_environment_changes(manifest, config):
    """Resume compatible PPO weights/optimizer with fresh curriculum rollouts.

    Body Control migration and terrain/depth sampling changes are explicit;
    geometry, action meaning and observation dimensions must stay compatible.
    Historical off-policy transitions cannot be reused across these changes.
    """
    prior = asdict(EnvironmentConfig(**manifest["environment"]))
    current = asdict(config)
    changes = {key: {"from": prior[key], "to": value}
               for key, value in current.items() if prior[key] != value}
    migration = (prior["execution_backend"] == "direct"
                 and config.execution_backend == "body_control"
                 and policy_algorithm(manifest) == "PPO")
    expected = asdict(body_control_config(EnvironmentConfig(**manifest["environment"]))) if migration else dict(prior)
    if policy_algorithm(manifest) == "PPO":
        # A new terrain/sensor curriculum uses fresh on-policy transitions.
        # Schema changes still require an explicit weights-only initialization.
        for key in ("scenarios", "depth_camera", "reward_velocity_scale_m_s",
                    "reward_yaw_scale_rad_s", "reward_cross_track_cost", "reward_overspeed_cost",
                    "reward_speed_window_s", "reward_profile", "locomotion_tracking_width_m_s",
                    "locomotion_tracking_width_rad_s", "locomotion_reward_weights"):
            if key in current:
                expected[key] = current[key]
    if expected != current:
        raise ValueError("Resume requires the same environment, except PPO Body Control migration, terrain/depth sampling or reward parameter changes")
    return changes


def resume_reward_changes(manifest):
    """PPO collects fresh rewards; SAC must not reuse incompatible replay."""
    previous = manifest.get("environment_version")
    if previous == ENVIRONMENT_VERSION:
        return {}
    if policy_algorithm(manifest) == "PPO" and previous in POLICY_ENVIRONMENT_VERSIONS:
        return {"from": previous, "to": ENVIRONMENT_VERSION}
    raise ValueError("Resume requires the same environment reward contract for replay data")


def training_environment(config, workers=1, commands=None, command_switch_seconds=None,
                         command_switch_range=None):
    """Independent native feedback/physics state per simulation process."""
    if type(workers) is not int or workers < 1:
        raise ValueError("Simulation workers must be a positive integer")
    def factory():
        env = make_environment(config, include_visuals=False, commands=commands)
        if command_switch_seconds is not None or command_switch_range is not None:
            return CommandRequests(env, commands or [config.command], command_switch_seconds, command_switch_range)
        return env
    # Evaluation opens its own production executor. Keep training's singleton
    # in its existing worker process even with a single connected worker.
    return factory() if workers == 1 and config.execution_backend == "direct" else SubprocVecEnv(
        [factory for _ in range(workers)], start_method="forkserver")


def load_demonstrations(paths, config, *, allow_command_variation=False):
    """Read one authoritative sensor/action contract and retain source identities."""
    observations, actions, sources = [], [], []
    for filename in paths:
        path = Path(filename)
        metadata = json.loads(path.with_suffix(".json").read_text())
        environment = metadata.get("environment")
        if isinstance(environment, dict):
            environment = asdict(EnvironmentConfig(**environment))
        expected = asdict(config)
        if isinstance(environment, dict):
            expected["episode_seconds"] = environment["episode_seconds"]
        if allow_command_variation and isinstance(environment, dict):
            expected["command"] = environment.get("command")
        if (metadata.get("schema") != config.observation_schema
                or metadata.get("environment_version") not in POLICY_ENVIRONMENT_VERSIONS
                or environment != expected
                or metadata.get("representation") != representation_identity()):
            raise ValueError("Demonstration must use this sensor, geometry and environment contract")
        with np.load(path, allow_pickle=False) as data:
            obs = np.asarray(data["observation"], dtype=np.float32)
            act = np.asarray(data["action"], dtype=np.float32)
        if (obs.ndim != 2 or obs.shape[1] != observation_size(config.observation_schema)
                or act.shape != (len(obs), 12) or not len(obs)
                or not np.isfinite(obs).all() or not np.isfinite(act).all()
                or np.abs(act).max() > 1.000001):
            raise ValueError("Demonstration contains invalid sensor/action pairs")
        commands = metadata.get("commands") or [environment["command"]]
        if any(len(command) != 3 or not np.isfinite(command).all() for command in commands):
            raise ValueError("Demonstration commands must be three finite SI values")
        if not allow_command_variation and commands != [config.command]:
            raise ValueError("Demonstration command variation requires explicit curriculum selection")
        matches = np.zeros(len(obs), dtype=bool)
        for command in commands:
            matches |= np.all(obs[:, COMMAND_SLICE] == np.asarray(command, dtype=np.float32), axis=1)
        if not matches.all():
            raise ValueError("Demonstration observations disagree with recorded commands")
        observations.append(obs)
        actions.append(act)
        sources.append(dict(path=str(path.resolve()), transitions=len(obs),
            command=environment["command"], commands=commands,
            source_episode_seconds=environment["episode_seconds"],
            training_episode_seconds=config.episode_seconds,
            recommended_cycle_rows=metadata.get("recommended_cycle_rows"),
            sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            metadata_sha256=hashlib.sha256(path.with_suffix(".json").read_bytes()).hexdigest()))
    return np.concatenate(observations), np.concatenate(actions), sources


def fit_actor(model, observations, actions, updates, seed, progress=None):
    """Fit the existing SAC actor; closed-loop evaluation measures actual success."""
    x = torch.as_tensor(observations, device=model.device)
    y = torch.as_tensor(actions, device=model.device)
    rng = np.random.default_rng(seed)
    model.actor.set_training_mode(True)
    with torch.no_grad():
        before = float(torch.mean((model.actor(x, deterministic=True)-y)**2).sqrt())
    for update in range(updates):
        index = rng.integers(len(x), size=model.batch_size)
        loss = torch.mean((model.actor(x[index], deterministic=True)-y[index])**2)
        model.actor.optimizer.zero_grad()
        loss.backward()
        model.actor.optimizer.step()
        if progress is not None and (update+1) % 1000 == 0:
            progress(update+1)
    with torch.no_grad():
        after = float(torch.mean((model.actor(x, deterministic=True)-y)**2).sqrt())
    return dict(method="behavior_cloning", updates=updates,
                action_rmse_before=before, action_rmse_after=after,
                qualification="Training fit only; see independent closed-loop evaluation")



def imitate(model, paths, config, updates, seed, progress=None, *, allow_command_variation=False):
    observations, actions, sources = load_demonstrations(paths, config,
        allow_command_variation=allow_command_variation)
    return dict(fit_actor(model, observations, actions, updates, seed, progress),
                sources=sources)


def calibrate_exploration(model, observations, actions, *, seed=1, draws=64):
    """Fit bounded-action exploration to demonstrated mean-policy error.

    Only the existing log_std head changes. Saturated labels remain bounded
    actions; no inverse tanh of demonstration labels enters this calculation.
    """
    if model.actor.use_sde or draws < 2 or draws % 2:
        raise ValueError("Calibration requires diagonal Gaussian SAC and paired draws")
    x = torch.as_tensor(observations, dtype=torch.float32, device=model.device)
    y = torch.as_tensor(actions, dtype=torch.float32, device=model.device)
    generator = torch.Generator(device=model.device).manual_seed(seed)
    with torch.no_grad():
        mean, initial_log_std, _ = model.actor.get_action_dist_params(x)
        deterministic = torch.tanh(mean)
        target = ((deterministic-y)**2).mean(dim=0).sqrt()
        normal = torch.randn((draws//2, *mean.shape), generator=generator, device=model.device)
        normal = torch.cat((normal, -normal), dim=0)

        def deviation(log_std):
            return ((torch.tanh(mean+log_std.exp()*normal)-deterministic)**2).mean(dim=(0, 1)).sqrt()

        def distribution(log_std):
            gaussian = mean+log_std.exp()*normal
            bounded = torch.tanh(gaussian)
            distribution = model.actor.action_dist.proba_distribution(
                mean.repeat(draws, 1), log_std.expand_as(mean).repeat(draws, 1))
            log_prob = distribution.log_prob(bounded.reshape(-1, mean.shape[1]),
                                              gaussian.reshape(-1, mean.shape[1]))
            logs = log_std.expand_as(mean)
            expected = float(log_prob.mean())
            return dict(bounded_rms=deviation(log_std).tolist(),
                std_mean=logs.exp().mean(dim=0).tolist(),
                log_std_mean=logs.mean(dim=0).tolist(), log_std_min=logs.min(dim=0).values.tolist(),
                log_std_max=logs.max(dim=0).values.tolist(), mean_log_prob=expected,
                sample_entropy=-expected)

        before = distribution(initial_log_std)
        lower = torch.full_like(target, LOG_STD_MIN)
        upper = torch.full_like(target, LOG_STD_MAX)
        bound_limited = (target < deviation(lower)) | (target > deviation(upper))
        for _ in range(32):
            middle = (lower+upper)/2
            too_small = deviation(middle) < target
            lower = torch.where(too_small, middle, lower)
            upper = torch.where(too_small, upper, middle)
        fitted = (lower+upper)/2
        model.actor.log_std.weight.zero_()
        model.actor.log_std.bias.copy_(fitted)
        after = distribution(fitted)
        unchanged = torch.equal(deterministic, model.actor(x, deterministic=True))
    return dict(method="bounded action RMSE matched constant Gaussian head",
        seed=seed, antithetic_draws=draws, states=len(x), bounded_target_rms=target.tolist(),
        achieved_rms=after["bounded_rms"], log_std=fitted.tolist(),
        bound_limited=bound_limited.tolist(), before=before, after=after,
        deterministic_unchanged=unchanged)


def prime_imitation_replay(model, config, *, seed=1, commands=None):
    """Collect real current-reward transitions in the learner's own vector layout."""
    env = model.get_env()
    seeds = env.seed(seed)
    model._last_obs = env.reset()
    vector_steps = round(config.episode_seconds*config.control_hz)
    rows = {name: [] for name in ("observation", "action", "reward", "done", "next_observation", "timeout")}
    if commands is not None:
        rows["command"] = []
    episodes = falls = 0
    buffer = model.replay_buffer
    for _ in range(vector_steps):
        action, _ = model.predict(model._last_obs, deterministic=True)
        next_obs, reward, done, infos = env.step(action)
        position = buffer.pos
        model._store_transition(buffer, model.policy.scale_action(action), next_obs, reward, done, infos)
        for name, source in (("observation", buffer.observations), ("action", buffer.actions),
                             ("reward", buffer.rewards), ("done", buffer.dones),
                             ("next_observation", buffer.next_observations), ("timeout", buffer.timeouts)):
            rows[name].append(source[position].copy())
        if commands is not None:
            rows["command"].append([info["command"] for info in infos])
        episodes += int(np.count_nonzero(done))
        falls += sum(bool(info.get("fallen")) for info in infos)
    arrays = {name: np.asarray(values) for name, values in rows.items()}
    return dict(transitions=vector_steps*env.num_envs, vector_steps=vector_steps,
                workers=env.num_envs, seeds=seeds, episodes=episodes, falls=falls,
                environment_version=ENVIRONMENT_VERSION,
                mean_reward_per_transition=float(arrays["reward"].mean()),
                rl_steps_counted=0, optimizer_updates=0), arrays


def prepare_imitation_sac(model, paths, config, directory, *, seed=1, source_directory=None, commands=None):
    """Calibrate the BC-to-SAC distribution and seed the existing replay owner."""
    directory = Path(directory)
    varied_commands = commands if commands is not None and len(commands) > 1 else None
    x, y, sources = load_demonstrations(paths, config,
        allow_command_variation=commands is not None and commands != [config.command])
    if source_directory is not None:
        selection = Path(source_directory)/"selection.json"
        if selection.exists():
            selected_rows = json.loads(selection.read_text()).get("training_states")
            if selected_rows is not None:
                if not 0 < selected_rows <= len(x):
                    raise ValueError("Selected checkpoint demonstration prefix is unavailable")
                x, y = x[:selected_rows], y[:selected_rows]
    dataset = directory/"handoff-demonstrations.npz"
    np.savez_compressed(dataset, observation=x, action=y)
    save_json(dataset.with_suffix(".json"), dict(schema=config.observation_schema, environment_version=ENVIRONMENT_VERSION,
        environment=asdict(config), representation=representation_identity(), sources=sources,
        commands=commands or [config.command],
        rows=len(x), source_directory=str(source_directory) if source_directory else None))
    calibration = calibrate_exploration(model, x, y, seed=seed)
    replay, arrays = prime_imitation_replay(model, config, seed=seed, commands=varied_commands)
    transitions = directory/"handoff-transitions.npz"
    np.savez_compressed(transitions, **arrays)
    baseline = evaluate(None, config, seeds=replay["seeds"], commands=commands)
    baseline_steps = sum(round(row["seconds"]*config.control_hz) for row in baseline["episodes"])
    baseline_mean = sum(row["reward"] for row in baseline["episodes"])/baseline_steps
    command_counts = None
    if varied_commands is not None:
        command_counts = [int(np.all(arrays["command"] == command, axis=-1).sum()) for command in commands]
        baseline_mean = 0.0
        for index, count in enumerate(command_counts):
            cases = [row for row in baseline["episodes"] if row["command_index"] == index]
            mean = sum(row["reward"] for row in cases)/sum(round(row["seconds"]*config.control_hz) for row in cases)
            baseline_mean += mean*count/replay["transitions"]
    advantage = replay["mean_reward_per_transition"]-baseline_mean
    expected_log_prob = calibration["after"]["mean_log_prob"]
    result = dict(state="preparing", sources=sources, selected_training_states=len(x),
        demonstration_sha256=hashlib.sha256(dataset.read_bytes()).hexdigest(),
        transition_sha256=hashlib.sha256(transitions.read_bytes()).hexdigest(),
        environment_version=ENVIRONMENT_VERSION, exploration=calibration, replay=replay,
        commands=commands or [config.command], command_transition_counts=command_counts,
        baseline_weighting="Per-command standing means weighted by actual primed transition counts" if varied_commands else "Matched standing seeds",
        standing_evaluation=baseline, standing_mean_reward_per_transition=baseline_mean,
        deterministic_advantage_per_transition=advantage, entropy_budget_fraction=.1)
    denominator = abs(expected_log_prob)
    if not np.isfinite(advantage) or advantage <= 0 or not np.isfinite(denominator) or denominator == 0:
        result.update(state="not_calibrated", reason="A positive deterministic advantage and nonzero finite expected log probability are required")
        save_json(directory/"handoff.json", result)
        raise ValueError(result["reason"])
    alpha = .1*advantage/denominator
    model.target_entropy = calibration["after"]["sample_entropy"]
    model.ent_coef = "auto"
    model.log_ent_coef = torch.tensor([np.log(alpha)], dtype=torch.float32,
                                     device=model.device, requires_grad=True)
    model.ent_coef_optimizer = torch.optim.Adam([model.log_ent_coef], lr=model.lr_schedule(1))
    # BC's MSE moments are not SAC policy-gradient history. We retain the
    # fitted actor parameters while starting its new objective's optimizer fresh.
    model.actor.optimizer.state.clear()
    model.learning_starts = 0
    result.update(state="ready", initial_alpha=alpha, target_entropy=model.target_entropy,
                  learning_starts=0, temperature_optimizer_reinitialized=True,
                  actor_optimizer_state_reset=True)
    save_json(directory/"handoff.json", result)
    return result


class CycleExpert:
    """Successor of the closest cycle predecessor in requested-action space.

    No clock or rollout counter advances the teacher. The input is the same
    previous requested action available to the learned actor in its observation.
    """
    def __init__(self, actions, *, commands=None, cycle_rows=None):
        actions = np.asarray(actions, dtype=np.float32)
        if (actions.ndim != 2 or actions.shape[1] != 12
                or len(actions) < 2 or not np.isfinite(actions).all()
                or np.abs(actions).max() > 1.000001):
            raise ValueError("Cycle requires at least two finite, normalized 12-action rows")
        self.commands = deepcopy(commands)
        self.command_slices = {}
        if commands is None:
            cycles = [actions.copy()]
        else:
            if not commands or cycle_rows is None or len(commands) != len(cycle_rows):
                raise ValueError("Each command needs one explicit cycle")
            cycles, offset = [], 0
            for command, rows in zip(commands, cycle_rows):
                if len(command) != 3 or not np.isfinite(command).all():
                    raise ValueError("Cycle command must contain three finite SI values")
                key = tuple(np.asarray(command, dtype=np.float32))
                if key in self.command_slices:
                    raise ValueError("Ambiguous teacher: choose one cycle source per command")
                if (not isinstance(rows, (list, tuple)) or len(rows) != 2
                        or any(type(value) is not int for value in rows)
                        or not 0 <= rows[0] < rows[1] <= len(actions) or rows[1]-rows[0] < 2):
                    raise ValueError("Cycle rows must identify at least two source actions")
                cycle = actions[rows[0]:rows[1]].copy()
                cycles.append(cycle)
                self.command_slices[key] = slice(offset, offset+len(cycle))
                offset += len(cycle)
        self.actions = np.concatenate(cycles)
        self.predecessors = np.concatenate([np.roll(cycle, 1, axis=0) for cycle in cycles])

    def __call__(self, observation):
        rows = slice(None)
        if self.commands is not None:
            rows = self.command_slices.get(tuple(np.asarray(observation[COMMAND_SLICE], dtype=np.float32)))
            if rows is None:
                raise ValueError("No teacher cycle for the observed command")
        end = observation_size(DEPTH_SCHEMA) if len(observation) == HISTORY_SIZE else len(observation)
        index = int(np.argmin(np.sum((self.predecessors[rows]-observation[end-12:end])**2, axis=1)))
        return self.actions[rows][index].copy()


def collect_demonstration(env, expert, model, expert_mix, rng, seed, command=None,
                          *, commands=None, command_switch_seconds=None, command_switch_range=None):
    switching = command_switch_seconds is not None or command_switch_range is not None
    requests = CommandRequests(env, commands or [command or env.config.command],
                               command_switch_seconds, command_switch_range) if switching else env
    obs, _ = requests.reset(seed=seed, options={"command": command} if command is not None else None)
    initial_command = list(env.config.command)
    commands = commands or [initial_command]
    segments = [begin_command_segment(env, requests.request)] if switching else []
    observations, actions = [], []
    expert_actions, reward, fallen = 0, 0.0, False
    start = env.data.qpos[:3].copy()
    for step in range(round(env.config.episode_seconds*env.config.control_hz)):
        if segments and step and step == requests.request["start_step"]:
            segments.append(begin_command_segment(env, requests.request))
        label = expert(obs)
        observations.append(obs.copy())
        actions.append(label)
        choose_expert = model is None or rng.random() < expert_mix
        action = label if choose_expert else model.predict(obs, deterministic=True)[0]
        expert_actions += int(choose_expert)
        obs, r, terminated, truncated, info = requests.step(action)
        if segments:
            record_command_segment(segments[-1], env, r, info)
            segments[-1]["expert_actions"] = segments[-1].get("expert_actions", 0)+int(choose_expert)
        reward += r
        if terminated or truncated:
            fallen = bool(info["fallen"])
            break
    return (np.asarray(observations, dtype=np.float32),
            np.asarray(actions, dtype=np.float32),
            dict(transitions=len(observations), expert_mix=expert_mix,
                 expert_actions=expert_actions, reward=reward, fallen=fallen,
                 command=initial_command,
                 **(dict(command_segments=segments, command_switch_seconds=command_switch_seconds,
                         command_switch_range=command_switch_range,
                         command_transition_counts=[sum(row["transitions"] for row in segments
                                                        if row["command_index"] == index)
                                                    for index in range(len(commands))]) if segments else {}),
                 displacement_m=(env.data.qpos[:3]-start).tolist(), seed=seed))


def select_checkpoint(checkpoints):
    """Prefer no-fall trials, then the current environment's movement reward."""
    return max(checkpoints, key=lambda row: (
        row["evaluation"]["falls"] == 0, row["evaluation"]["mean_reward"]))


def publish_selected(directory, checkpoints):
    selected = select_checkpoint(checkpoints)
    source = directory/selected["policy"]
    temporary = directory/"policy.pending.zip"
    shutil.copyfile(source, temporary)
    temporary.replace(directory/"policy.zip")
    selection = dict(selected, selection="No falls preferred, then highest current mean reward",
                     policy_sha256=hashlib.sha256(source.read_bytes()).hexdigest())
    save_json(directory/"selection.json", selection)
    return selected


def aggregate(model, paths, config, initial_updates, seed, progress,
              cycle_start, cycle_steps, expert_mix, updates_per_round, demonstration_cycles=False,
              command_switch_seconds=None, command_switch_range=None):
    """DAgger warm-start using the existing actor, simulator and progress owner."""
    _, source_actions, sources = load_demonstrations(paths, config,
        allow_command_variation=demonstration_cycles)
    commands = [config.command]
    if demonstration_cycles:
        commands, rows, offset = [], [], 0
        for source in sources:
            if source["commands"] != [source["command"]]:
                raise ValueError("Each teacher source must contain one command and its explicit cycle")
            local = source["recommended_cycle_rows"]
            if (not isinstance(local, list) or len(local) != 2
                    or any(type(value) is not int for value in local)
                    or not 0 <= local[0] < local[1] <= source["transitions"]):
                raise ValueError("Each selected source needs valid recommended_cycle_rows")
            commands.append(source["command"])
            rows.append([offset+local[0], offset+local[1]])
            offset += source["transitions"]
        expert = CycleExpert(source_actions, commands=commands, cycle_rows=rows)
    else:
        if cycle_start < 0 or cycle_steps < 2 or cycle_start+cycle_steps > len(source_actions):
            raise ValueError("Cycle rows must identify a complete slice of the demonstration")
        expert = CycleExpert(source_actions[cycle_start:cycle_start+cycle_steps])
    progress.commands = commands
    progress.command_switch_seconds = command_switch_seconds
    progress.command_switch_range = command_switch_range
    directory = progress.directory
    cycle_path = directory/"teacher-cycle.npz"
    np.savez_compressed(cycle_path, action=expert.actions,
        command=np.asarray(commands), cycle_rows=np.asarray(
            [[value.start, value.stop] for value in expert.command_slices.values()]
            if demonstration_cycles else [[0, len(expert.actions)]]))
    provenance = dict(schema=config.observation_schema, environment_version=ENVIRONMENT_VERSION,
        environment=asdict(config), representation=representation_identity(), sources=sources,
        method="DAgger", teacher="Nearest previous requested action, then cycle successor",
        cycle_start=cycle_start, cycle_steps=cycle_steps,
        commands=commands, demonstration_cycles=demonstration_cycles,
        command_switch_seconds=command_switch_seconds,
        command_switch_range=command_switch_range,
        teacher_cycle=dict(path=cycle_path.name,
            sha256=hashlib.sha256(cycle_path.read_bytes()).hexdigest()),
        expert_mix=list(expert_mix),
        updates_per_round=updates_per_round, initial_updates=initial_updates, seed=seed,
        qualification="Offline simulation only; teacher labels are not physical measurements")
    rng = np.random.default_rng(seed)
    env = make_environment(config, include_visuals=False)
    rounds = []
    try:
        observations, actions = [], []
        for round_id in range(len(expert_mix)+1):
            collections = []
            for command in commands:
                new_x, new_y, collection = collect_demonstration(env, expert,
                    model if round_id else None, expert_mix[round_id-1] if round_id else 1.0,
                    rng, seed, command, commands=commands,
                    command_switch_seconds=command_switch_seconds, command_switch_range=command_switch_range)
                observations.append(new_x)
                actions.append(new_y)
                collections.append(collection)
            x, y = np.concatenate(observations), np.concatenate(actions)
            # Every row survives, including failures. A round's prefix length and
            # content hashes identify the exact data used by its immutable actor.
            dataset = directory/"training-data.npz"
            temporary = directory/"training-data.pending.npz"
            np.savez_compressed(temporary, observation=x, action=y)
            temporary.replace(dataset)
            metadata = dict(provenance, rows=len(x), aggregation_round=round_id)
            save_json(dataset.with_suffix(".json"), metadata)
            updates = initial_updates if not round_id else updates_per_round
            def report(done):
                save_json(directory/"progress.json", dict(state="aggregating",
                    steps=model.num_timesteps, aggregation_round=round_id,
                    imitation_updates=progress.imitation_updates+done,
                    elapsed_s=time.monotonic()-progress.started))
            report(0)
            fit = fit_actor(model, x, y, updates, seed+round_id, report)
            progress.imitation_updates += updates
            checkpoint = progress.checkpoint(aggregation_round=round_id, training_states=len(x))
            record = dict(checkpoint, fit=fit,
                collection=collections[0] if len(collections) == 1 else collections,
                dataset_sha256=hashlib.sha256(dataset.read_bytes()).hexdigest(),
                dataset_metadata=metadata,
                dataset_metadata_sha256=hashlib.sha256(dataset.with_suffix(".json").read_bytes()).hexdigest())
            rounds.append(record)
            save_json(directory/"aggregation.json", dict(provenance, rounds=rounds,
                total_imitation_updates=progress.imitation_updates, training_states=len(x)))
    finally:
        env.close()
    selected = publish_selected(directory, progress.checkpoints)
    save_json(directory/"imitation.json", dict(provenance,
        updates=selected["imitation_updates"], total_updates=progress.imitation_updates,
        selected_round=selected["aggregation_round"], selected_checkpoint_id=selected["id"]))
    return selected


def new_model(env, device, seed, *, policy_class="MlpPolicy", policy_kwargs=None,
              ent_coef="auto"):
    """One fresh SAC learner configuration for random and transferred weights."""
    if env.observation_space.shape == (HISTORY_SIZE,):
        raise ValueError("History schema requires initialization from an asymmetric GaitPPO actor/critic")
    return SAC(
        policy_class, env,
        policy_kwargs=deepcopy(policy_kwargs) if policy_kwargs is not None else dict(net_arch=[64, 64]),
        learning_starts=1000, buffer_size=100_000, batch_size=256,
        train_freq=1, gradient_steps=-1, ent_coef=ent_coef,
        seed=seed, device=device, verbose=0,
    )



def locomotion_rollout_geometry(count, budget=None):
    """Rollout length and minibatch size for this host's workers and budget.

    The published recipe reaches its per-update sample budget through thousands
    of parallel envs, so its n_steps is not portable to a CPU worker count. The
    budget caps the rollout so a short run never collects more than it requested.
    """
    count = max(1, int(count))
    n_steps = max(1, ROLLOUT_TRANSITIONS//count)
    if budget is not None:
        # Keep at least two rollouts: observation moments refresh at a rollout
        # boundary, so a single-rollout run would never update them.
        n_steps = max(1, min(n_steps, int(budget)//(2*count)))
    return n_steps, max(2, (n_steps*count)//MINIBATCH_DIVISOR)


def apply_rollout_geometry(model, n_steps, batch_size):
    """Resize a resumed rollout in place; the buffer holds no retained data.

    Mirrors OnPolicyAlgorithm._setup_model so the resized buffer keeps the
    model's own discounting instead of the constructor's defaults.
    """
    if model.n_steps == n_steps and model.batch_size == batch_size:
        return
    model.n_steps, model.batch_size = n_steps, batch_size
    model.rollout_buffer = model.rollout_buffer_class(
        n_steps, model.observation_space, model.action_space,
        device=model.device, gamma=model.gamma, gae_lambda=model.gae_lambda,
        n_envs=model.n_envs, **model.rollout_buffer_kwargs)


def new_locomotion_model(env, device="cpu", seed=1, budget=None):
    """Published PPO locomotion baseline, keeping Ainekio's foot/executor contract.

    Reference: MuJoCo Playground config/locomotion_params.py and ETH legged_gym.
    The robot's dimensions, limits and dynamics remain in the existing environment.
    """
    count = getattr(env, "num_envs", 1)
    n_steps, batch_size = locomotion_rollout_geometry(count, budget)
    return GaitPPO(GaitPPOPolicy, env, device=device, seed=seed, verbose=0,
        learning_rate=3e-4, n_steps=n_steps, batch_size=batch_size, n_epochs=5,
        gamma=.99, gae_lambda=.95, clip_range=.2, ent_coef=.01,
        max_grad_norm=1., target_kl=TRUST_REGION_KL,
        policy_kwargs=dict(net_arch=dict(pi=[512,256,128], vf=[512,256,128]),
            activation_fn=torch.nn.ELU, learned_std=True, log_std_init=math.log(.5),
            action_coordinates="linear", normalize_observations=True))


def training_recipe(prior, recipe=None, *, demonstrations=(), initialize_from=None):
    """New online training uses the maintained locomotion recipe; resumes keep theirs."""
    if recipe is not None and recipe != LOCOMOTION_RECIPE:
        raise ValueError("Unknown locomotion training recipe")
    selected = recipe or prior.get("recipe")
    if not prior and not demonstrations:
        selected = selected or LOCOMOTION_RECIPE
    if recipe and (demonstrations or initialize_from or prior and prior.get("recipe") != recipe):
        raise ValueError("Start this recipe fresh; resume its own checkpoint afterward")
    return selected


def requested_commands(config, commands=None, prior=None):
    selected = commands if commands is not None else (prior or {}).get("commands") or [config.command]
    values = np.asarray(selected, dtype=float)
    if values.ndim != 2 or values.shape[1] != 3 or not len(values) or not np.isfinite(values).all():
        raise ValueError("Commands require finite vx, vy and yaw triples")
    return values.tolist()

def initialize_model(directory, env, config, device="cpu", seed=1, checkpoint="policy.zip"):
    """Transfer learned weights into an explicit curriculum/input extension."""
    directory = Path(directory)
    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    algorithm = policy_algorithm(manifest)
    source_config = asdict(EnvironmentConfig(**manifest["environment"]))
    target_config = asdict(config)
    # Command curriculum and existing balance settings change the task/dynamics,
    # not the meaning of the policy's sensors or foot offsets. Explicit weights-
    # only initialization can transfer these; exact replay resume cannot.
    task_changes = {key: dict(source=source_config.pop(key), target=target_config.pop(key))
                    for key in ("command", "balance_enabled", "balance_tuning", "episode_seconds",
                                "scenarios", "depth_camera", "observation_schema",
                                "reward_velocity_scale_m_s", "reward_yaw_scale_rad_s",
                                "reward_cross_track_cost", "reward_overspeed_cost", "reward_speed_window_s",
                                "reward_profile", "locomotion_tracking_width_m_s",
                                "locomotion_tracking_width_rad_s", "locomotion_reward_weights")}
    task_changes = {key: value for key, value in task_changes.items()
                    if value["source"] != value["target"]}
    source_schema = manifest.get("schema")
    depth_expansion = source_schema == SCHEMA and config.observation_schema in (DEPTH_SCHEMA, HISTORY_SCHEMA)
    history_expansion = source_schema in (SCHEMA, DEPTH_SCHEMA) and config.observation_schema == HISTORY_SCHEMA
    expansion = depth_expansion or history_expansion
    if ((source_schema != config.observation_schema and not (algorithm == "PPO" and expansion))
            or manifest.get("environment_version") not in POLICY_ENVIRONMENT_VERSIONS
            or source_config != target_config
            or manifest.get("representation") != representation_identity()
            or manifest.get("geometry_sha256") != hashlib.sha256(GEOMETRY.read_bytes()).hexdigest()):
        raise ValueError("Initialization requires compatible sensor/action, geometry and configuration contracts")
    checkpoint = (directory / checkpoint).resolve()
    if not checkpoint.is_relative_to(directory.resolve()) or not checkpoint.is_file():
        raise ValueError("Choose an existing initialization checkpoint within its source run")
    source = load_policy(directory, checkpoint=str(checkpoint), device=device)
    if algorithm == "PPO":
        model = GaitPPO(source.policy_class, env, device=device, seed=seed,
            policy_kwargs=deepcopy(source.policy_kwargs), learning_rate=source.learning_rate,
            n_steps=source.n_steps, batch_size=source.batch_size, n_epochs=source.n_epochs,
            gamma=source.gamma, gae_lambda=source.gae_lambda, clip_range=source.clip_range,
            clip_range_vf=source.clip_range_vf, normalize_advantage=source.normalize_advantage,
            ent_coef=source.ent_coef, vf_coef=source.vf_coef, max_grad_norm=source.max_grad_norm,
            use_sde=source.use_sde, sde_sample_freq=source.sde_sample_freq,
            target_kl=source.target_kl, rollout_buffer_class=PreciseActionRolloutBuffer)
        weights = model.policy.state_dict()
        normalization_bias = {}
        for name, value in source.policy.state_dict().items():
            if value.shape == weights[name].shape:
                weights[name] = value
            elif expansion and name in {"observation_mean", "observation_variance"}:
                # New channels keep neutral mean=0/variance=1; retained inputs
                # keep the same transform as their copied first-layer weights.
                if depth_expansion:
                    weights[name][:OBSERVATION_SIZE-12] = value[:-12]
                    end = observation_size(DEPTH_SCHEMA)
                    weights[name][end-12:end] = value[-12:]
                else:
                    weights[name][:value.shape[0]] = value
            elif expansion and name in {"mlp_extractor.policy_net.0.weight", "mlp_extractor.value_net.0.weight"}:
                # Keep every learned proprioception/action weight exactly;
                # added depth starts neutral and learns from new rollouts.
                weights[name].zero_()
                if depth_expansion:
                    weights[name][:, :OBSERVATION_SIZE-12] = value[:, :-12]
                    depth_end = observation_size(DEPTH_SCHEMA)
                    weights[name][:, depth_end-12:depth_end] = value[:, -12:]
                else:
                    weights[name][:, :value.shape[1]] = value
                # v3 simulated/production walking supplied no vision. These
                # existing scalar slots also become active with the new sensor.
                if depth_expansion:
                    if source.policy.normalize_observations:
                        neutral = -source.policy.observation_mean[93:96] / torch.sqrt(
                            source.policy.observation_variance[93:96]+1e-8)
                        bias = name.removesuffix("weight")+"bias"
                        normalization_bias[bias] = value[:,93:96] @ neutral.to(value)
                    weights[name][:, 93:96] = 0
            else:
                raise ValueError(f"Unsupported policy input transfer for {name}")
        for name, value in normalization_bias.items():
            weights[name] = weights[name]+value
        model.policy.load_state_dict(weights)
    else:
        model = new_model(env, device, seed, policy_class=source.policy_class,
                          policy_kwargs=source.policy_kwargs, ent_coef=source.ent_coef)
        model.actor.load_state_dict(source.actor.state_dict())
        with torch.no_grad():
            if source.log_ent_coef is not None:
                model.log_ent_coef.copy_(source.log_ent_coef)
            else:
                model.ent_coef_tensor.copy_(source.ent_coef_tensor)
    prior_progress = directory / "progress.json"
    progress = json.loads(prior_progress.read_text()) if prior_progress.exists() else {}
    provenance = dict(
        source_directory=str(directory.resolve()),
        source_checkpoint_sha256=hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
        source_checkpoint=str(checkpoint.relative_to(directory.resolve())),
        source_manifest_sha256=hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        source_environment_version=manifest["environment_version"],
        training_environment_version=ENVIRONMENT_VERSION,
        source_rl_steps=source.num_timesteps, source_optimizer_updates=source._n_updates,
        source_imitation_updates=progress.get("imitation_updates", manifest.get("imitation_updates", 0)),
        net_arch=model.policy_kwargs.get("net_arch"),
        task_changes=task_changes,
        transferred=("PPO actor/value weights; added input columns zero; fresh optimizer and rollouts"
                     if algorithm == "PPO" else "Actor parameters including log_std, and entropy coefficient"),
        critic_parameters_loaded=algorithm == "PPO", target_critic_parameters_loaded=False,
        replay_loaded=False, optimizer_state_loaded=False,
        initial_rl_steps=model.num_timesteps, initial_optimizer_updates=model._n_updates,
    )
    # Input expansion initializes a different number of temporary parameters.
    # Start rollout exploration from the requested seed after transferring them,
    # so architecture size does not silently offset matched trials' RNG stream.
    model.set_random_seed(seed)
    return model, provenance


def train(directory, steps, config, resume=None, device="cpu", seed=1, workers=1,
          demonstrations=(), imitation_updates=10000, cycle_start=None, cycle_steps=None,
          expert_mix=(.7, .5, .35, .2, .1, 0, 0, 0), updates_per_round=2000,
          initialize_from=None, demonstration_cycles=False, command_switch_seconds=None,
          command_switch_range=None, resume_checkpoint="policy.zip", learning_rate=None,
          action_noise_std=None, value_learning_rate=None, command_units=None,
          checkpoint_every=None, exploration_learning_rate=None, initialize_checkpoint="policy.zip",
          recipe=None, commands=None):
    if learning_rate is not None and (not math.isfinite(learning_rate) or learning_rate <= 0):
        raise ValueError("Learning rate must be finite and positive")
    if value_learning_rate is not None and (not math.isfinite(value_learning_rate) or value_learning_rate <= 0):
        raise ValueError("Value learning rate must be finite and positive")
    if exploration_learning_rate is not None and (not math.isfinite(exploration_learning_rate)
            or exploration_learning_rate <= 0):
        raise ValueError("Exploration learning rate must be finite and positive")
    if resume and initialize_from:
        raise ValueError("Choose exact replay resume or weights-only initialization, not both")
    if initialize_from and Path(directory).resolve() == Path(initialize_from).resolve():
        raise ValueError("Initialization destination must differ from its preserved source run")
    aggregation = demonstration_cycles or cycle_start is not None or cycle_steps is not None
    if demonstration_cycles and (cycle_start is not None or cycle_steps is not None):
        raise ValueError("Choose metadata demonstration cycles or explicit cycle rows")
    if aggregation and (not demonstrations or not demonstration_cycles and (cycle_start is None or cycle_steps is None)):
        raise ValueError("Aggregation requires demonstration, cycle-start and cycle-steps")
    if aggregation and steps != 0:
        raise ValueError("Aggregation is an imitation-only run (--steps 0); resume its policy for SAC")
    if imitation_updates < 0 or updates_per_round < 1 or any(not 0 <= b <= 1 for b in expert_mix):
        raise ValueError("Imitation updates and expert mixture probabilities are invalid")
    # Honor the requested compute device: SB3 otherwise silently downgrades
    # an explicit CUDA request to CPU when installed torch is CPU-only.
    if str(device).startswith("cuda") and not torch.cuda.is_available():
        raise RuntimeError("CUDA training requested but unavailable in this interpreter; install CUDA-enabled PyTorch")
    previous = Path(initialize_from or resume) if initialize_from or resume else None
    prior_manifest = json.loads((previous/"manifest.json").read_text()) if previous else {}
    checkpoint_every = prior_manifest.get("checkpoint_every", 10000) if checkpoint_every is None else checkpoint_every
    if type(checkpoint_every) is not int or checkpoint_every <= 0:
        raise ValueError("Checkpoint interval must be a positive number of training transitions")
    recipe = training_recipe(prior_manifest, recipe, demonstrations=demonstrations,
                             initialize_from=initialize_from)
    algorithm = policy_algorithm(prior_manifest) if previous else ("PPO" if recipe else "SAC")
    if recipe and not previous:
        config = replace(config, reward_profile="locomotion")
    if previous and (demonstrations or aggregation):
        require_sac_training(prior_manifest)
    execution_changes = resume_environment_changes(prior_manifest, config) if resume else {}
    reward_changes = resume_reward_changes(prior_manifest) if resume else {}
    timing, task_changes = request_timing(prior_manifest, command_switch_seconds, command_switch_range)
    command_switch_seconds = timing["command_switch_seconds"]
    command_switch_range = timing["command_switch_range"]
    request_interval_steps(config, **timing)
    explicit_commands = commands is not None
    commands = requested_commands(config, commands, prior_manifest)
    if initialize_from and not explicit_commands and config.command != prior_manifest["environment"]["command"]:
        commands = [config.command]
    if demonstration_cycles:
        _, _, sources = load_demonstrations(demonstrations, config, allow_command_variation=True)
        commands = [source["command"] for source in sources]
        if len({tuple(np.asarray(command, dtype=np.float32)) for command in commands}) != len(commands):
            raise ValueError("Ambiguous teacher: choose one cycle source per command")
    elif aggregation:
        # Explicit legacy cycle rows select a single-command curriculum even if
        # its initial actor previously learned a broader command set.
        commands = [config.command]
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    torch.set_num_threads(1)
    save_json(directory / "environment.json", asdict(config))
    save_json(
        directory / "manifest.json",
        dict(
            schema=config.observation_schema,
            recipe=recipe,
            algorithm="DAgger behavior cloning of SAC actor" if aggregation else algorithm,
            source=("Body Control WebSocket + production P4 executor + MuJoCo physical dynamics"
                    if config.execution_backend == "body_control" else "MuJoCo physical dynamics"),
            execution_changes=execution_changes,
            execution_revision=dict(host_heading="moving_attitude_response",
                sources_sha256={name: hashlib.sha256((GEOMETRY.parent/name).read_bytes()).hexdigest()
                                for name in ("motion.c", "balance.c")}),
            reward_changes=reward_changes,
            geometry_sha256=hashlib.sha256(GEOMETRY.read_bytes()).hexdigest(),
            representation=representation_identity(),
            environment=asdict(config),
            commands=commands,
            command_switch_seconds=command_switch_seconds,
            command_switch_range=command_switch_range,
            task_changes=task_changes,
            seed=seed,
            environment_version=ENVIRONMENT_VERSION,
            assumptions=[
                "component mass distribution",
                "servo torque and gains",
                "friction",
                "no calibrated vision noise model",
            ],
            physical_qualification=False,
            steps_requested=steps,
            checkpoint_every=checkpoint_every,
            resumed_from=str(resume) if resume else None,
            resumed_checkpoint=resume_checkpoint if resume else None,
            initialized_from=str(initialize_from) if initialize_from else None,
            device=device,
            requested_device=str(device),
            simulation_workers=workers,
            optimizer_updates_per_transition=1 if algorithm == "SAC" and not aggregation else None,
            continuation="Preserved learning state; fresh simulation episodes" if resume else None,
            checkpoint_evaluation="one matched seed and first configured scenario per command",
            final_evaluation="full configured command/scenario/seed suite",
            automatic_footage="initial and published final weights; one matched trial each",
            optimization_log="optimization.jsonl",
            checkpoint_publication=("Immutable round checkpoints; policy.zip matches selection.json"
                                    if aggregation else "after the optimizer update; final checkpoint matches policy.zip"),
        ),
    )
    env = training_environment(config, workers, commands=commands, **timing)
    started = time.monotonic()
    optimization_logger = None
    try:
        initialization = None
        if resume:
            prior = Path(resume)
            manifest = json.loads((prior / "manifest.json").read_text())
            if (
                manifest["schema"] != config.observation_schema
                or manifest.get("representation") != representation_identity()
                or manifest["geometry_sha256"]
                != hashlib.sha256(GEOMETRY.read_bytes()).hexdigest()
            ):
                raise ValueError(
                    "Resume requires the same observation/action and environment contract"
                )
            model = load_policy(prior, checkpoint=resume_checkpoint, env=env, device=device)
            if algorithm == "SAC":
                if load_replay(model, prior) and model.replay_buffer.n_envs != workers:
                    raise ValueError("Resume with the original worker count to preserve replay layout")
                model.gradient_steps = -1
            else:
                # Only this recipe's own resumes are resized; a historical run
                # keeps the rollout geometry its artifact was recorded with.
                if manifest.get("recipe") == LOCOMOTION_RECIPE:
                    apply_rollout_geometry(
                        model, *locomotion_rollout_geometry(env.num_envs, steps))
                model.set_random_seed(seed)
        elif initialize_from:
            model, initialization = initialize_model(initialize_from, env, config, device, seed,
                                                     checkpoint=initialize_checkpoint)
            manifest_path = directory / "manifest.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["initialization"] = initialization
            save_json(manifest_path, manifest)
        else:
            model = (new_locomotion_model(env, device, seed, budget=steps) if recipe
                     else new_model(env, device, seed))
        manifest_path = directory / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["device"] = str(model.device)
        save_json(manifest_path, manifest)
        source_value_rate = (model.policy.value_learning_rate or
            float(model.lr_schedule(model._current_progress_remaining))) if algorithm == "PPO" else None
        source_exploration_rate = (model.policy.exploration_learning_rate or
            float(model.lr_schedule(model._current_progress_remaining))) if algorithm == "PPO" else None
        if command_units is not None:
            change = configure_command_units(model, command_units)
            manifest_path = directory / "manifest.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["command_preconditioning"] = change
            save_json(manifest_path, manifest)
        if action_noise_std is not None:
            change = configure_action_exploration(model, action_noise_std)
            manifest_path = directory / "manifest.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["exploration_change"] = change
            save_json(manifest_path, manifest)
        if learning_rate is not None:
            manifest_path = directory / "manifest.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["optimizer_changes"] = dict(learning_rate=dict(
                source=float(model.lr_schedule(model._current_progress_remaining)),
                target=learning_rate))
            save_json(manifest_path, manifest)
            # Adjust the existing optimizer's step size; retain weights, Adam
            # moments, counters, exploration and the PPO trust-region setting.
            model.learning_rate = learning_rate
            model._setup_lr_schedule()
        if value_learning_rate is not None:
            if not isinstance(model, GaitPPO):
                raise ValueError("Separate value learning rate requires PPO")
            manifest_path = directory / "manifest.json"
            manifest = json.loads(manifest_path.read_text())
            manifest.setdefault("optimizer_changes", {})["value_learning_rate"] = dict(
                source=source_value_rate,
                target=value_learning_rate)
            save_json(manifest_path, manifest)
            model.policy.configure_value_learning(value_learning_rate)
            model.policy_kwargs["value_learning_rate"] = value_learning_rate
        if exploration_learning_rate is not None:
            if not isinstance(model, GaitPPO):
                raise ValueError("Separate exploration learning rate requires PPO")
            model.policy.configure_exploration_learning(exploration_learning_rate)
            model.policy_kwargs["exploration_learning_rate"] = exploration_learning_rate
            manifest_path = directory / "manifest.json"
            manifest = json.loads(manifest_path.read_text())
            manifest.setdefault("optimizer_changes", {})["exploration_learning_rate"] = dict(
                source=source_exploration_rate, target=exploration_learning_rate)
            save_json(manifest_path, manifest)
        # Keep SB3's actual optimizer measurements alongside this run's
        # evaluation evidence; do not retain large raw rollout buffers.
        optimization_logger = Logger(str(directory),
            [JSONOutputFormat(str(directory/"optimization.jsonl"))])
        model.set_logger(optimization_logger)
        if algorithm == "PPO":
            manifest_path = directory / "manifest.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["ppo"] = dict(n_steps=model.n_steps, n_epochs=model.n_epochs,
                batch_size=model.batch_size, learned_std=model.policy.log_std.requires_grad,
                action_coordinates=model.policy.action_coordinates,
                normalize_observations=model.policy.normalize_observations,
                learning_rate=model.learning_rate, entropy_coefficient=model.ent_coef,
                gamma=model.gamma, gae_lambda=model.gae_lambda,
                network=model.policy_kwargs.get("net_arch"),
                command_units=model.policy.command_units,
                source_steps=model.num_timesteps, source_optimizer_epochs=model._n_updates,
                optimizer_count_basis="SB3 PPO _n_updates counts optimizer epochs, not minibatches")
            save_json(manifest_path, manifest)
        progress = Progress(directory, steps, config, checkpoint_every=checkpoint_every, commands=commands,
                            command_switch_seconds=command_switch_seconds, command_switch_range=command_switch_range)
        if initialization:
            progress.imitation_updates = initialization["source_imitation_updates"]
        if resume:
            prior_progress = prior/"progress.json"
            previous_status = json.loads(prior_progress.read_text()) if prior_progress.exists() else {}
            progress.imitation_updates = previous_status.get("imitation_updates", 0)
            published_path = prior/"checkpoints.json"
            published = json.loads(published_path.read_text()) if published_path.exists() else []
            source_checkpoint = next((row for row in published
                if row["policy"] == resume_checkpoint or resume_checkpoint == "policy.zip"
                and row["id"] == previous_status.get("selected_checkpoint_id")), None)
            if source_checkpoint is not None:
                # An interrupted run's status may contain only its error. The
                # exact resumed checkpoint retains its learned-history count.
                progress.imitation_updates = source_checkpoint.get("imitation_updates", progress.imitation_updates)
        selected = None
        if aggregation:
            progress.init_callback(model)
            selected = aggregate(model, demonstrations, config, imitation_updates, seed,
                                 progress, cycle_start, cycle_steps, expert_mix, updates_per_round,
                                 demonstration_cycles=demonstration_cycles,
                                 command_switch_seconds=command_switch_seconds, command_switch_range=command_switch_range)
        elif demonstrations:
            def imitation_progress(updates):
                save_json(directory / "progress.json", dict(state="imitating",
                    steps=model.num_timesteps, imitation_updates=updates,
                    imitation_updates_requested=imitation_updates,
                    elapsed_s=time.monotonic()-started))
            imitation_progress(0)
            save_json(directory / "imitation.json",
                      imitate(model, demonstrations, config, imitation_updates, seed,
                              imitation_progress, allow_command_variation=commands != [config.command]))
            progress.imitation_updates += imitation_updates
        if not aggregation:
            handoff_source = Path(initialize_from or resume) if initialize_from or resume else None
            offline_source = (initialization["source_rl_steps"] if initialization else model.num_timesteps) == 0
            handoff_paths = list(demonstrations)
            if algorithm == "SAC" and not handoff_paths and offline_source and handoff_source is not None:
                archive = handoff_source/"training-data.npz"
                if archive.exists():
                    handoff_paths = [archive]
            # Existing SAC resume retains its distribution/replay/temperature.
            # BC sources instead get a measured distribution and current-reward replay.
            if algorithm == "SAC" and steps > 0 and handoff_paths and not (resume and model.num_timesteps > 0):
                save_json(directory/"progress.json", dict(state="preparing_sac",
                    steps=model.num_timesteps, imitation_updates=progress.imitation_updates))
                prepare_imitation_sac(model, handoff_paths, config, directory, seed=seed,
                                     source_directory=None if demonstrations else handoff_source,
                                     commands=commands)
                manifest_path = directory/"manifest.json"
                manifest = json.loads(manifest_path.read_text())
                manifest["imitation_handoff"] = "handoff.json"
                save_json(manifest_path, manifest)
            model.learn(
                total_timesteps=steps,
                callback=progress,
                reset_num_timesteps=not bool(resume),
            )
            model.logger.record("time/total_timesteps", model.num_timesteps)
            model.logger.dump(step=model.num_timesteps)
            final_checkpoint = progress.checkpoint()
            model.save(directory / "policy.zip")
            if algorithm == "SAC":
                save_replay(model, directory)
        baseline = progress.evaluate(None, "standing_baseline")
        # Checkpoint probes are deliberately compact. Qualification retains the
        # full configured command/scenario/seed suite for the published weights.
        candidate_model = load_policy(directory, device=device) if selected else model
        candidate = progress.evaluate(candidate_model, "final_candidate")
        save_json(
            directory / "evaluation.json", dict(baseline=baseline, candidate=candidate)
        )
        save_json(directory / "progress.json", dict(
            state="rendering", steps=model.num_timesteps,
            optimizer_updates=model._n_updates,
            optimizer_update_unit="epochs" if algorithm == "PPO" else "gradient_steps",
            imitation_updates=selected["imitation_updates"] if selected else progress.imitation_updates,
            total_imitation_updates=progress.imitation_updates,
            selected_checkpoint_id=selected["id"] if selected else progress.checkpoint_identity,
            selected_round=selected["aggregation_round"] if selected else None,
            evaluation=candidate, elapsed_s=time.monotonic()-started,
            physical_qualification=False))
        rendered = progress.finish_rendering()
        save_json(
            directory / "progress.json",
            dict(
                state="completed",
                steps=model.num_timesteps,
                optimizer_updates=model._n_updates,
                optimizer_update_unit="epochs" if algorithm == "PPO" else "gradient_steps",
                imitation_updates=selected["imitation_updates"] if selected else progress.imitation_updates,
                total_imitation_updates=progress.imitation_updates,
                selected_checkpoint_id=selected["id"] if selected else progress.checkpoint_identity,
                selected_round=selected["aggregation_round"] if selected else None,
                elapsed_s=time.monotonic() - started,
                evaluation=candidate,
                physical_qualification=False,
                progress_video_rendered=rendered,
            ),
        )
        return candidate
    except BaseException as error:
        save_json(
            directory / "progress.json",
            dict(state="error", error=str(error), elapsed_s=time.monotonic() - started),
        )
        raise
    finally:
        if optimization_logger is not None:
            optimization_logger.close()
        env.close()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--directory", required=True)
    p.add_argument("--steps", type=int, required=True)
    p.add_argument("--config")
    source = p.add_mutually_exclusive_group()
    source.add_argument("--resume", help="Resume matching-environment SAC or PPO learning state")
    p.add_argument("--resume-checkpoint", default="policy.zip",
                   help="Recorded checkpoint within the resumed run; retains optimizer state without copying artifacts")
    source.add_argument("--initialize-from", help="Copy compatible actor weights into a fresh learner")
    p.add_argument("--initialize-checkpoint", default="policy.zip",
                   help="Recorded checkpoint in the initialization source run")
    p.add_argument("--device", default="cpu")
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--learning-rate", type=float,
                   help="Explicit optimizer step size; resume otherwise retains its saved schedule")
    p.add_argument("--action-noise-std", type=float, nargs=12,
                   help="Explicit PPO exploration std in normalized foot-action coordinates")
    p.add_argument("--recipe", choices=[LOCOMOTION_RECIPE],
                   help="Published locomotion PPO baseline; default for fresh online training")
    p.add_argument("--command", type=float, nargs=3, action="append", dest="commands",
                   help="Offline vx, vy (m/s), yaw (rad/s) request; repeat for multiple tasks")
    p.add_argument("--value-learning-rate", type=float,
                   help="PPO value-function step size, independently of the movement policy")
    p.add_argument("--exploration-learning-rate", type=float,
                   help="Step size for PPO learned exploration variance, independently of the mean policy")
    p.add_argument("--command-units", type=float, nargs=3,
                   help="PPO internal feature units for vx, vy (m/s) and yaw (rad/s); preserves initial outputs")
    p.add_argument("--checkpoint-every", type=int,
                   help="Training transitions between compact checkpoint evaluations; resume inherits its interval")
    p.add_argument("--workers", type=int, help="Simulation workers; resume defaults to the saved count")
    p.add_argument("--demonstration", action="append", default=[])
    p.add_argument("--imitation-updates", type=int, default=10000)
    p.add_argument("--cycle-start", type=int)
    p.add_argument("--cycle-steps", type=int)
    p.add_argument("--demonstration-cycles", action="store_true",
                   help="Use one sidecar recommended_cycle_rows teacher per recorded command")
    timing = p.add_mutually_exclusive_group()
    timing.add_argument("--command-switch-seconds", type=float,
                        help="Fixed offline request timing; resume inherits saved timing when omitted")
    timing.add_argument("--command-switch-range", type=float, nargs=2, metavar=("MIN", "MAX"),
                        help="Sample each offline request interval uniformly in this seconds range")
    p.add_argument("--expert-mix", type=float, nargs="+", default=[.7,.5,.35,.2,.1,0,0,0])
    p.add_argument("--updates-per-round", type=int, default=2000)
    a = p.parse_args()
    prior = json.loads((Path(a.resume)/"manifest.json").read_text()) if a.resume else {}
    config = (
        EnvironmentConfig(**json.loads(Path(a.config).read_text()))
        if a.config
        else EnvironmentConfig(**{**prior.get("environment", {}), "execution_backend": "body_control"})
    )
    if config.execution_backend == "body_control":
        config = body_control_config(config)
    workers = a.workers if a.workers is not None else prior.get("simulation_workers", 1)
    train(a.directory, a.steps, config, a.resume, a.device, a.seed, workers,
          a.demonstration, a.imitation_updates, a.cycle_start, a.cycle_steps,
          a.expert_mix, a.updates_per_round, initialize_from=a.initialize_from,
          demonstration_cycles=a.demonstration_cycles,
          command_switch_seconds=a.command_switch_seconds,
          command_switch_range=a.command_switch_range,
          resume_checkpoint=a.resume_checkpoint, learning_rate=a.learning_rate,
          action_noise_std=a.action_noise_std, value_learning_rate=a.value_learning_rate,
          command_units=a.command_units, checkpoint_every=a.checkpoint_every,
          exploration_learning_rate=a.exploration_learning_rate,
          initialize_checkpoint=a.initialize_checkpoint, recipe=a.recipe, commands=a.commands)


if __name__ == "__main__":
    # Artifacts refer to this module's canonical classes. Running the CLI with
    # -m also defines __main__ copies; dispatch through the canonical module so
    # loaded policies and configured distributions share the same identities.
    from gateway.neural_gait.training import main as run_training
    run_training()
