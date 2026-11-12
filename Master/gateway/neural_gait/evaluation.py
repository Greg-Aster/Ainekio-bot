"""Simulation rollout evaluation and artifact loader for MicroDuck and Pupper MJX."""

from copy import deepcopy
import json
import math
from pathlib import Path

import gymnasium as gym
import numpy as np

from .artifacts import summarize_commands
from .environment import make_environment

SUPPORTED_KINDS = ("microduck-mjlab", "pupper-mjx")


def load_policy(directory, checkpoint=None):
    """Load an exported MicroDuck ONNX or Pupper MJX RTNeural policy."""
    directory = Path(directory)
    manifest = json.loads((directory / "manifest.json").read_text())
    kind = manifest.get("kind")
    if kind == "microduck-mjlab":
        from .microduck_actor import MicroduckActor
        target = checkpoint or manifest.get("policy")
        if not target:
            raise ValueError("This MicroDuck run has no exported policy yet")
        return MicroduckActor(directory / target)
    if kind == "pupper-mjx":
        from .pupper_mjx_actor import PupperMjxActor
        target = checkpoint or manifest.get("policy")
        if not target:
            raise ValueError("This Pupper MJX run has no exported policy yet")
        return PupperMjxActor(directory / target, environment=manifest.get("environment"))
    raise ValueError(f"Unsupported neural gait policy kind {kind!r}; expected MicroDuck or Pupper MJX")


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
    if round(bounds[0] * config.control_hz) < 1:
        raise ValueError("Command switch interval must span at least one control step")
    seconds = rng.uniform(*bounds) if rng is not None and bounds[0] != bounds[1] else bounds[0]
    return round(seconds * config.control_hz)


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
        self.request = dict(
            start_step=start,
            scheduled_end_step=min(round(self.env.config.episode_seconds * self.env.config.control_hz), start + interval),
            command_index=self.index,
            command=list(self.commands[self.index]),
        )

    def reset(self, **kwargs):
        observation, info = self.env.reset(**kwargs)
        self.index = self.commands.index(getattr(self.env, "requested_command", self.env.config.command))
        self._request(0)
        return observation, info

    def step(self, action):
        observation, reward, terminated, truncated, info = self.env.step(action)
        if not (terminated or truncated) and self.env.steps == self.request["scheduled_end_step"]:
            self.index = (self.index + 1) % len(self.commands)
            observation = self.env.set_command(self.commands[self.index])
            self._request(self.env.steps)
        return observation, reward, terminated, truncated, info


def begin_command_segment(env, scheduled):
    rotation = env.data.xmat[env.model.body("torso").id].reshape(3, 3)
    heading = float(np.arctan2(rotation[1, 0], rotation[0, 0]))
    return dict(
        scheduled,
        end_step=scheduled["start_step"],
        transitions=0,
        seconds=0.0,
        reward=0.0,
        start_position_m=env.data.qpos[:3].tolist(),
        displacement_m=[0.0, 0.0, 0.0],
        command_reference_travel_m=[0.0, 0.0],
        start_heading_rad=heading,
        end_heading_rad=heading,
        heading_change_rad=0.0,
        fallen=False,
    )


def record_command_segment(segment, env, reward, info):
    for name, value in info.get("reward_components", {}).items():
        components = segment.setdefault("reward_components", {})
        components[name] = components.get(name, 0.0) + value
    for name, value in info.get("motion_metrics", {}).items():
        metrics = segment.setdefault("motion_metric_sums", {})
        metrics[name] = metrics.get(name, 0.0) + value
    segment["transitions"] += 1
    segment["end_step"] = segment["start_step"] + segment["transitions"]
    segment["seconds"] = segment["transitions"] / env.config.control_hz
    segment["reward"] += float(reward)
    segment["displacement_m"] = (env.data.qpos[:3] - segment["start_position_m"]).tolist()
    segment["command_reference_travel_m"] = (
        np.asarray(segment["command_reference_travel_m"])
        + np.asarray(info["velocity_command_m_s"]) / env.config.control_hz
    ).tolist()
    delta = info["heading_rad"] - segment["end_heading_rad"]
    segment["heading_change_rad"] += float(np.arctan2(np.sin(delta), np.cos(delta)))
    segment["end_heading_rad"] = float(info["heading_rad"])
    segment["fallen"] |= bool(info["fallen"])


def evaluation_seed_list(seeds):
    if seeds is None:
        return None
    if (not isinstance(seeds, (list, tuple)) or not seeds
            or any(type(seed) is not int or seed < 0 for seed in seeds)):
        raise ValueError("Evaluation seeds require a nonempty list of nonnegative integers")
    return list(seeds)


def evaluate(model, config, seeds=None, commands=None, command_switch_seconds=None,
             command_switch_range=None, progress=None, compact=False):
    if compact:
        seeds = (1000,)
    if seeds is None:
        camera = getattr(config, "depth_camera", None) or {}
        odometry = camera.get("odometry") or {}
        camera_varied = any(camera.get(key, 0.0) for key in ("noise_std_m", "dropout_probability")) or any(
            odometry.get(key, 0.0) for key in
            ("position_noise_std_m", "rotation_noise_std_rad", "log_scale_std", "dropout_probability"))
        startup = camera.get("startup_latency_s", 0.0)
        camera_varied |= isinstance(startup, (list, tuple)) and startup[0] != startup[1]
        varied = any((
            command_switch_range is not None,
            getattr(config, "randomization", 0.0),
            getattr(config, "feedback_noise_raw_std", 0.0),
            getattr(config, "imu_accel_noise_std", 0.0),
            getattr(config, "imu_gyro_noise_std", 0.0),
            camera_varied,
        ))
        seeds = range(1000, 1008) if varied else (1000,)
    seeds = tuple(seeds)
    commands = commands or [config.command]
    scenarios = getattr(config, "scenarios", []) or [None]
    if compact:
        scenarios = scenarios[:1]
    reuse_standing = model is None and command_switch_range is None and all(
        getattr(config, name, None) == 0.0 for name in (
            "randomization", "feedback_noise_raw_std", "imu_accel_noise_std", "imu_gyro_noise_std"))
    total = len(commands) * len(scenarios) * (1 if reuse_standing else len(seeds))
    env = make_environment(config, include_visuals=False, commands=commands)
    switching = command_switch_seconds is not None or command_switch_range is not None
    requests = CommandRequests(env, commands, command_switch_seconds, command_switch_range) if switching else env
    rows = []
    standing_references = {}
    simulated = 0
    try:
        if progress:
            progress(0, total)
        for command_index, command, scenario_index, scenario, seed in (
                (i, command, j, scenario, seed)
                for i, command in enumerate(commands)
                for j, scenario in enumerate(scenarios)
                for seed in seeds):
            reference_key = (command_index, scenario_index)
            if reference_key in standing_references:
                reference = standing_references[reference_key]
                rows.append(dict(deepcopy(reference), seed=seed, reused_from_seed=reference["seed"]))
                continue
            options = {"command": command}
            if scenario is not None:
                options["scenario"] = scenario["id"]
            obs, _ = requests.reset(seed=seed, options=options)
            if model is not None and hasattr(model, "reset"):
                model.reset()
            segments = [begin_command_segment(env, requests.request)] if switching else []
            progress_intervals = []
            start = env.data.qpos[:3].copy()
            reward = 0.0
            travel_reward = 0.0
            fallen = False
            rejected = 0
            moving_targets = 0
            contacts = np.zeros(4)
            clearance = np.full(4, -np.inf)
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
            reward_component_sums = {}
            for step in range(round(config.episode_seconds * config.control_hz)):
                if segments and step and step == requests.request["start_step"]:
                    segments.append(begin_command_segment(env, requests.request))
                if (not progress_intervals or step % config.control_hz == 0
                        or list(env.config.command) != progress_intervals[-1]["command"]):
                    progress_intervals.append(begin_command_segment(
                        env, dict(start_step=step, command=list(env.config.command))))
                action = (
                    env.last_action.copy()
                    if model is None
                    else model.predict(obs, deterministic=True)[0]
                )
                previous_target = env.last_target.copy()
                previous_action = env.last_action.copy()
                obs, r, terminated, truncated, info = requests.step(action)
                target_step = env.last_target - previous_target
                metrics = dict(
                    requested_foot_step_squared_mm2=float(np.mean(
                        ((action - previous_action) * np.tile(config.foot_action_scale_mm, 4)) ** 2)),
                    target_step_squared_deg2=float(np.mean(target_step ** 2)),
                    target_acceleration_squared_deg2_s4=float(np.mean(
                        ((target_step - previous_target_step) * config.control_hz ** 2) ** 2)),
                )
                info["motion_metrics"] = metrics
                for name, value in metrics.items():
                    motion_metric_sums[name] = motion_metric_sums.get(name, 0.0) + value
                previous_target_step = target_step
                if segments:
                    record_command_segment(segments[-1], env, r, info)
                record_command_segment(progress_intervals[-1], env, r, info)
                feet = env.foot_measurements()
                contacts += feet["contact"]
                clearance_valid = np.asarray(feet.get("clearance_valid", [True] * 4))
                clearance = np.maximum(clearance, np.where(clearance_valid, feet["clearance_m"], -np.inf))
                clearance_observed += clearance_valid
                upright = min(upright, info["upright"])
                body_travel += np.asarray(info["velocity_body_m_s"]) / config.control_hz
                command_travel += np.asarray(info["velocity_command_m_s"]) / config.control_hz
                heading = info["heading_rad"]
                change = heading - previous_heading
                unwrapped_heading += float(np.arctan2(np.sin(change), np.cos(change)))
                previous_heading = heading
                maximum_heading_deviation = max(
                    maximum_heading_deviation, abs(unwrapped_heading - initial_heading))
                slip_squared_sum += info["contact_slip_speed_squared_m2_s2"]
                maximum_tracking_error = max(maximum_tracking_error, float(np.max(
                    np.abs(env.last_target - np.rad2deg(env.data.qpos[env.qadr])))))
                if info.get("foot_fit") is not None:
                    fit_observed_frames += 1
                    fit_reduced_frames += int(np.any(np.asarray(info["foot_fit"]) < 1))
                jam_frames += int(info["jammed_joints"] != 0)
                rejected += int(info["target_rejected"])
                moving_targets += int(np.max(np.abs(env.last_target - previous_target)) > 1e-6)
                reward += r
                travel_reward += info["travel_reward"]
                for name, value in info.get("reward_components", {}).items():
                    reward_component_sums[name] = reward_component_sums.get(name, 0.0) + value
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
                    mean_total_reward_per_step=reward / (step + 1),
                    mean_travel_reward_per_step=travel_reward / (step + 1),
                    reward_components_per_second={name: value / seconds for name, value in reward_component_sums.items()} if seconds else {},
                    motion_metric_means={name: value / (step + 1) for name, value in motion_metric_sums.items()},
                    seconds=seconds,
                    fallen=fallen,
                    displacement_m=(env.data.qpos[:3] - start).tolist(),
                    forward_m_s=float((env.data.qpos[0] - start[0]) / seconds) if seconds else None,
                    rejected_frames=rejected,
                    moving_target_frames=moving_targets,
                    minimum_upright=upright,
                    body_frame_travel_m=body_travel.tolist(),
                    command_reference_travel_m=command_travel.tolist(),
                    world_heading_unwrapped_rad=unwrapped_heading,
                    heading_change_rad=unwrapped_heading - initial_heading,
                    maximum_heading_deviation_rad=maximum_heading_deviation,
                    mean_contact_slip_speed_squared_m2_s2=slip_squared_sum / (step + 1),
                    maximum_joint_tracking_error_deg=maximum_tracking_error,
                    fit_reduced_frames=fit_reduced_frames if fit_observed_frames else None,
                    fit_observed_frames=fit_observed_frames,
                    execution_backend=config.execution_backend,
                    body_terminal=info.get("body_terminal"),
                    body_rejection=info.get("body_rejection"),
                    producer_failure=info.get("producer_failure"),
                    geometry_rejection=info.get("geometry_rejection"),
                    consumed_sample=info.get("consumed_sample"),
                    jam_frames=jam_frames,
                    foot_contact_fraction=(contacts / (step + 1)).tolist(),
                    peak_lower_leg_clearance_m=[float(value) if math.isfinite(value) else None for value in clearance],
                    clearance_observed_frames=clearance_observed.tolist(),
                )
            )
            simulated += 1
            if reuse_standing:
                standing_references[reference_key] = rows[-1]
            if progress:
                progress(simulated, total)
    finally:
        env.close()
    return dict(
        scope="simulation_only",
        evaluation_scope="compact_checkpoint" if compact else "full_configured_suite",
        evaluation_seeds=list(seeds),
        travel_frames=dict(
            displacement_m="fixed world frame",
            command_reference_travel_m="command-start horizontal reference, following requested turn",
            body_frame_travel_m="integrated instantaneous full3D measured body frame",
        ),
        policy_kind=("held_standing_reference" if model is None else "neural_foot_offsets"),
        trial_variation=(
            "Held reference has no seed-dependent physics or controller inputs; reused rows identify their source seed"
            if len(rows) > simulated
            else "configured physics, sensor or request-timing variation; otherwise one deterministic reference trial"
        ),
        simulated_episodes=simulated,
        reused_episodes=len(rows) - simulated,
        episodes=rows,
        command_results=summarize_commands(rows),
        mean_forward_m_s=(float(np.mean([r["forward_m_s"] for r in rows]))
                          if all(r["forward_m_s"] is not None for r in rows) else None),
        falls=sum(r["fallen"] for r in rows),
        mean_reward=float(np.mean([r["reward"] for r in rows])),
    )
