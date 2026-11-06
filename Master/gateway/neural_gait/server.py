"""Separate local neural gait inference/training service, with no robot transport."""

import argparse
from dataclasses import asdict
import fcntl
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import urlsplit, parse_qs
from uuid import uuid4

import numpy as np

from .contract import SCHEMA, SCHEMAS, HISTORY_SCHEMA, PENDING_SCHEMA, foot_offsets, vector
from .artifacts import save_json, summarize_commands


def evaluation_summary(value):
    """Dashboard trial measurements; full time series stay in the run artifact."""
    if not isinstance(value, dict):
        return value
    result = dict(value)
    if "episodes" in result:
        result["episodes"] = [{key: item for key, item in row.items()
                               if key != "progress_intervals"} for row in result["episodes"]]
    for key in ("baseline", "candidate"):
        if key in result:
            result[key] = evaluation_summary(result[key])
    return result


class Runtime:
    def __init__(self, directory, device="cpu"):
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.device = device
        self.model = self.model_id = self.checkpoint_id = self.environment = None
        self.training = self.training_id = None
        self.renders = {}
        self.lock = threading.RLock()
        self.selection_error = None
        self.kind = None
        self.rng = np.random.default_rng()
        self.demonstrations = {}
        selected = self.directory / "selected.json"
        if selected.exists():
            try:
                selection = json.loads(selected.read_text())
                self.load(selection["model_id"], selection.get("checkpoint_id"))
            except (ValueError, KeyError, OSError) as error:
                self.selection_error = str(error)

    def run_path(self, identifier):
        if (
            not isinstance(identifier, str)
            or not identifier
            or any(c not in "0123456789abcdef-" for c in identifier)
        ):
            raise ValueError("Expected a model/run identifier")
        return self.directory / identifier

    def status(self, *, include_runs=True):
        # Movement admission only needs the selected model contract. Training
        # history can be large and must neither delay admission nor hold the
        # inference/selection lock while scanning artifacts.
        with self.lock:
            training, training_id, renders = self.training, self.training_id, dict(self.renders)
            result = dict(
                schema=(self.environment or {}).get("observation_schema", SCHEMA),
                model_id=self.model_id, checkpoint_id=self.checkpoint_id,
                kind=self.kind,
                selection_error=self.selection_error,
                device=self.device, environment=self.environment,
                training_id=training_id,
                training_running=training is not None and training.poll() is None)
        if not include_runs:
            return result
        runs = []
        paths = {
            p.parent: p
            for pattern in ("*/environment.json", "*/manifest.json")
            for p in self.directory.glob(pattern)
        }
        for path in sorted(
            paths.values(),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        ):
            progress = path.with_name("progress.json")
            value = (
                json.loads(progress.read_text())
                if progress.exists()
                else {"state": "starting"}
            )
            value.pop("evaluation", None)
            manifest_path = path.with_name("manifest.json")
            manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
            evaluation = path.with_name("evaluation.json")
            rendering = renders.get(path.parent.name)
            render_active = False
            lock_path = path.with_name("render.lock")
            if lock_path.exists():
                with lock_path.open("r") as lock:
                    try:
                        fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
                    except BlockingIOError:
                        render_active = True
            checkpoints = path.with_name("checkpoints.json")
            checkpoint_rows = json.loads(checkpoints.read_text()) if checkpoints.exists() else []
            for checkpoint in checkpoint_rows:
                measured = checkpoint.get("evaluation", {})
                if "command_results" not in measured and measured.get('episodes'):
                    measured["command_results"] = summarize_commands(measured.get("episodes", []))
                checkpoint["evaluation"] = evaluation_summary(measured)
            video = path.with_name("progress-video.json")
            if (
                path.parent.name == training_id
                and training.poll() not in (None, 0)
            ):
                value.update(state="error", exit_code=training.returncode)
            runs.append(
                dict(
                    id=path.parent.name,
                    **{**value, **({"kind": manifest['kind']} if 'kind' in manifest else {})},
                    algorithm=manifest.get('algorithm'),
                    initialization=manifest.get("initialization"),
                    recipe=manifest.get("recipe"),
                    training_device=manifest.get("device"),
                    simulation_workers=manifest.get("simulation_workers"),
                    automatic_footage=manifest.get("automatic_footage"),
                    evaluation=(
                        evaluation_summary(json.loads(evaluation.read_text()))
                        if evaluation.exists()
                        else None
                    ),
                    has_policy=path.with_name("policy.zip").exists() or bool(manifest.get("policy") and (path.parent/manifest["policy"]).is_file()) or bool(manifest.get('kind') == 'physical-redq' and checkpoint_rows),
                    has_replay=path.with_name("replay.mp4").exists(),
                    has_footage=any(clip.is_file() and '.tmp.' not in clip.name
                                   for clip in (path.parent/'clips').glob('*.mp4')),
                    has_progress_video=path.with_name(
                        "progress-video.mp4"
                    ).exists(),
                    progress_video=(
                        json.loads(video.read_text()) if video.exists() else None
                    ),
                    checkpoints=checkpoint_rows,
                    rendering=render_active or rendering is not None and rendering.poll() is None,
                    render_exit_code=rendering.poll() if rendering else None,
                )
            )
        # History/inference never imports a simulator or training framework.
        # An empty edit uses the training owner's normal defaults on submission.
        defaults = self.environment or {}
        return dict(result, runs=runs, defaults=defaults)

    def load(self, identifier, checkpoint_id=None):
        path = self.run_path(identifier)
        manifest = json.loads((path / "manifest.json").read_text())
        if manifest.get("kind") == "microduck-mjlab" and not manifest.get("policy"):
            raise ValueError("This MicroDuck run has no exported policy yet")
        if manifest.get('kind') == 'physical-redq':
            from .redq import NumpyActor
            rows = json.loads((path/'checkpoints.json').read_text())
            if not rows:
                raise ValueError('Physical actor initialization has not finished')
            selected = next((row for row in rows if row['id'] == checkpoint_id), None) if checkpoint_id else rows[-1]
            if selected is None:
                raise ValueError('Choose a published physical checkpoint')
            model = NumpyActor.load(path/selected['policy'])
            actor_environment = model.metadata.get('environment')
            same_environment = actor_environment == manifest['environment']
            if isinstance(actor_environment, dict) and not same_environment:
                # A physical run can retain its immutable v5 checkpoints after
                # the trainer gains pending-action inputs. All other installed
                # geometry, calibration and execution fields must still match.
                schemas = {actor_environment.get('observation_schema'), manifest['environment'].get('observation_schema')}
                same_environment = (schemas == {HISTORY_SCHEMA, PENDING_SCHEMA} and
                    {k: v for k, v in actor_environment.items() if k != 'observation_schema'} ==
                    {k: v for k, v in manifest['environment'].items() if k != 'observation_schema'})
            if (not same_environment or
                    model.metadata.get('model_id') != identifier or
                    model.metadata.get('checkpoint_id') != selected['id'] or
                    model.metadata.get('action_contract') != manifest['action_contract']):
                raise ValueError('Actor and run observation/action contracts differ')
            with self.lock:
                self.model, self.model_id = model, identifier
                self.environment, self.checkpoint_id = actor_environment, selected['id']
                self.kind, self.selection_error = 'physical-redq', None
                save_json(self.directory/'selected.json', dict(model_id=identifier, checkpoint_id=selected['id']))
            return self.status()
        from .environment import POLICY_ENVIRONMENT_VERSIONS, representation_identity
        if (manifest["schema"] not in SCHEMAS or manifest.get("environment_version") not in POLICY_ENVIRONMENT_VERSIONS
                or manifest.get("representation") != representation_identity()):
            raise ValueError("Checkpoint representation differs from the current robot environment")
        checkpoint = manifest.get("policy", "policy.zip")
        if checkpoint_id is not None:
            # Select a published immutable checkpoint from its existing run;
            # continuing training must not change the reviewed deployment.
            rows = json.loads((path / "checkpoints.json").read_text())
            selected = next((row for row in rows if row["id"] == checkpoint_id), None)
            if selected is None:
                raise ValueError("Choose a published checkpoint from this run")
            checkpoint = selected["policy"]
        if manifest.get("kind") == "microduck-mjlab":
            from .microduck_actor import MicroduckActor
            model = MicroduckActor(path/checkpoint)
        else:
            from .training import load_policy
            import torch
            torch.set_num_threads(1)
            model = load_policy(path, checkpoint, device=self.device)
        with self.lock:
            self.model, self.model_id, self.environment = (
                model,
                identifier,
                manifest["environment"],
            )
            self.checkpoint_id = checkpoint_id
            self.kind = manifest.get("kind")
            self.selection_error = None
            save_json(self.directory / "selected.json",
                      dict(model_id=identifier, checkpoint_id=checkpoint_id))
        return self.status()

    def collection_end(self, robot_id, owner):
        """Retire only the native generator owned by this completed Walk."""
        with self.lock:
            state = self.demonstrations.get(robot_id)
            if state is not None and state['owner'] == owner and state['native'] is not None:
                state['native'].close()
                # Preserve the last motion identity: an already-sent HTTP
                # request cannot recreate a generator after Stop retires it.
                state['native'] = None
                return dict(retired=True)
            return dict(retired=False)

    def _native_demonstration(self, observation, request):
        from .native import BodyModel
        if not isinstance(request, dict) or request.get('source') != 'native-c':
            raise ValueError('Expected an explicit native-c demonstration request')
        robot, owner, now = request.get('robot_id'), request.get('owner'), request.get('device_us')
        gateway, epoch, walk = request.get('gateway_instance'), request.get('epoch'), request.get('walk')
        if (not isinstance(robot, str) or not robot or not isinstance(owner, str) or not owner
                or not isinstance(gateway, str) or not gateway or type(epoch) is not int or epoch < 1
                or type(walk) is not int or walk < 1
                or type(now) is not int or now < 0
                or observation.get('observation_time_s') != now / 1e6):
            raise ValueError('Native demonstration requires its Walk owner and actual observation clock')
        command = request.get('command')
        if not isinstance(command, dict):
            raise ValueError('Native demonstration requires the requested Walk controls')
        command = {key: command[key] for key in ('dir', 'speed', 'forward', 'lateral', 'turn', 'gait', 'stride', 'rate') if key in command}
        command.update(t='intent', name='walk', steps=0)
        state = self.demonstrations.get(robot)
        if state is not None and state['gateway'] == gateway:
            if (epoch, walk) < state['identity'] or ((epoch, walk) == state['identity'] and
                    (state['owner'] != owner or state['native'] is None)):
                raise ValueError('Native demonstration request belongs to a retired Walk')
        if state is None or state['owner'] != owner:
            if state is not None:
                if state['native'] is not None:
                    state['native'].close()
                del self.demonstrations[robot]
            native = BodyModel(self.environment['robot'])
            try:
                native.walk_configure(speed_deg_s=self.environment['joint_speed_deg_s'],
                                      heading_enabled=False, balance_enabled=False, model=None)
                if not native.walk_accept({**command, 'seq': 1}, now):
                    raise ValueError('Native gait rejected the demonstration controls')
            except BaseException:
                native.close()
                raise
            state = dict(native=native, owner=owner, gateway=gateway, identity=(epoch, walk),
                         command=command, sequence=1, now=now)
            self.demonstrations[robot] = state
        if now < state['now']:
            raise ValueError('Native demonstration clock moved backwards within the same Walk')
        if command != state['command']:
            sequence = state['sequence'] + 1
            if not state['native'].walk_accept({**command, 'seq': sequence, 'update': 1}, now):
                raise ValueError('Native gait rejected the updated demonstration controls')
            state.update(command=command, sequence=sequence)
        result = state['native'].walk_tick(now, observation['target_deg'])
        state['now'] = now
        if result is None or result['failed']:
            raise ValueError('Native gait could not produce the requested demonstration target')
        # The production generator fits this frame to installed calibration.
        # With all teacher corrections disabled it is the physical target before
        # heading/balance correction, not the unconstrained generator pose.
        angles = result['balanced_angles']
        offsets = state['native'].foot_offsets_for_angles(angles, self.environment['reference_joint_deg'])
        action = (np.asarray(offsets) / np.asarray(self.environment['foot_action_scale_mm'])).reshape(12)
        if not np.isfinite(action).all() or np.any(np.abs(action) > 1.):
            raise ValueError('Native demonstration exceeds the configured geometry-derived action encoding')
        provenance = dict(source='native-c', owner=owner, device_us=now, command=command,
            label_contract='native-c-calibrated-target-v1', target_joint_deg=angles.tolist(),
            nominal_joint_deg=result['nominal_angles'].tolist(), phase=float(result['phase']),
            heading_enabled=False, balance_enabled=False, learned_corrections_enabled=False)
        return action, provenance

    def infer(self, observation, *, explore=False, model_id=None, checkpoint_id=None, noise=None, demonstration=None):
        values = np.asarray(vector(observation), dtype=np.float32)
        started = time.monotonic()
        with self.lock:
            if self.model is None:
                raise ValueError("No neural gait checkpoint selected")
            if model_id is not None and (model_id, checkpoint_id) != (self.model_id, self.checkpoint_id):
                raise ValueError('Inference checkpoint differs from the owning Walk')
            if noise is not None:
                if explore is not True or self.kind != 'physical-redq':
                    raise ValueError('Explicit exploration noise requires an exploratory physical REDQ request')
                if (not isinstance(noise, list) or len(noise) != 12
                        or any(type(value) not in (int, float) for value in noise)
                        or not np.isfinite(noise).all()):
                    raise ValueError('Exploration noise must contain twelve finite numbers')
                noise = np.asarray(noise, dtype=np.float32)
                if not np.isfinite(noise).all():
                    raise ValueError('Exploration noise must contain twelve finite float32 numbers')
            limits = self.environment["target_limits_deg"]
            if observation["target_limits_deg"] != limits:
                raise ValueError(
                    "Observation action domain differs from the selected checkpoint"
                )
            if self.kind == 'physical-redq':
                inputs = ({'pending_actions': observation['pending_actions']}
                          if self.model.metadata.get('pending_input_dim', 0) else {})
                provenance = None
                if demonstration is not None:
                    if explore is not True or noise is not None:
                        raise ValueError('Native demonstrations require explicit collection without policy noise')
                    action, provenance = self._native_demonstration(observation, demonstration)
                else:
                    action = self.model.act(values, deterministic=not explore, rng=self.rng, noise=noise, **inputs)
                return dict(schema=self.environment['observation_schema'], model_id=self.model_id,
                    checkpoint_id=self.checkpoint_id, action=action.tolist(),
                    requested_foot_offset_mm=foot_offsets(action, self.environment['foot_action_scale_mm']),
                    elapsed_s=time.monotonic()-started, execution='preview_only',
                    exploration=bool(explore and provenance is None),
                    **({'demonstration': provenance} if provenance is not None else {}),
                    targets_resolved_by='existing P4 Walk kinematics')
            if demonstration is not None:
                raise ValueError('Native demonstration collection requires a physical actor contract')
            if explore:
                raise ValueError('Stochastic physical trials require a physical REDQ actor')
            action, _ = self.model.predict(values, deterministic=True)
            identifier, checkpoint_id = self.model_id, self.checkpoint_id
            schema = self.environment.get("observation_schema", SCHEMA)
            from .native import BodyModel
            native = BodyModel(self.environment["robot"])
            requested = foot_offsets(action, self.environment["foot_action_scale_mm"])
            try:
                resolved = native.foot_target(np.asarray(requested).reshape(4,3),
                    self.environment["reference_joint_deg"], observation["target_deg"],
                    self.environment["joint_speed_deg_s"], 1/self.environment["control_hz"])
            finally:
                native.close()
        return dict(
            schema=schema, model_id=identifier, checkpoint_id=checkpoint_id,
            action=action.tolist(),
            requested_foot_offset_mm=requested,
            fitted_foot_offset_mm=resolved["applied_offset_mm"].tolist() if resolved else None,
            targets_deg=resolved["ramped_angles"].tolist() if resolved else None,
            target_rejected=resolved is None,
            elapsed_s=time.monotonic() - started,
            execution="preview_only",
        )

    def start_training(self, payload):
        source = payload.get("resume")
        prior = json.loads((self.run_path(source)/"manifest.json").read_text()) if source else {}
        if payload.get("recipe") == "microduck-mjlab-v1" or prior.get("kind") == "microduck-mjlab":
            return self.start_microduck_training(payload, prior)
        from .environment import EnvironmentConfig, body_control_config, representation_identity
        from .training import (policy_algorithm, request_interval_steps, request_timing,
            resume_environment_changes, resume_reward_changes, training_recipe, requested_commands,
            locomotion_config, evaluation_seed_list)
        with self.lock:
            if self.training is not None and self.training.poll() is None:
                raise ValueError("A gait training run is already active")
            source = payload.get("resume") or payload.get("initialize_from")
            prior = json.loads((self.run_path(source)/"manifest.json").read_text()) if source else {}
            steps = payload["steps"]
            if type(steps) is not int or steps <= 0:
                raise ValueError("Training steps must be a positive integer")
            checkpoint_every = payload.get("checkpoint_every")
            evaluation_seeds = evaluation_seed_list(payload.get("evaluation_seeds"))
            if checkpoint_every is not None and (type(checkpoint_every) is not int or checkpoint_every <= 0):
                raise ValueError("Checkpoint interval must be a positive number of training transitions")
            learning_rate = payload.get("learning_rate")
            if learning_rate is not None and (type(learning_rate) not in (int, float)
                    or not math.isfinite(learning_rate) or learning_rate <= 0):
                raise ValueError("Learning rate must be finite and positive")
            value_learning_rate = payload.get("value_learning_rate")
            if value_learning_rate is not None and (type(value_learning_rate) not in (int, float)
                    or not math.isfinite(value_learning_rate) or value_learning_rate <= 0):
                raise ValueError("Value learning rate must be finite and positive")
            exploration_learning_rate = payload.get("exploration_learning_rate")
            if exploration_learning_rate is not None and (type(exploration_learning_rate) not in (int, float)
                    or not math.isfinite(exploration_learning_rate) or exploration_learning_rate <= 0):
                raise ValueError("Exploration learning rate must be finite and positive")
            if payload.get("resume") and payload.get("initialize_from"):
                raise ValueError("Choose resume or weights-only initialization")
            source = payload.get("resume") or payload.get("initialize_from")
            previous = self.run_path(source) if source else None
            prior = (
                json.loads((previous / "manifest.json").read_text()) if previous else {}
            )
            # Inference may run on CPU while the learner uses CUDA. Preserve a
            # resumed run's device/seed unless the training request changes them.
            device = payload.get("device", prior.get("requested_device", prior.get("device", self.device)))
            seed = payload.get("seed", prior.get("seed", 1))
            if previous:
                policy_algorithm(prior)
            recipe = training_recipe(prior, payload.get("recipe"),
                                     initialize_from=payload.get("initialize_from"))
            algorithm = "PPO" if recipe else policy_algorithm(prior) if previous else "SAC"
            value_warmup_steps = payload.get("value_warmup_steps", 0)
            if (type(value_warmup_steps) is not int or value_warmup_steps < 0
                    or value_warmup_steps and algorithm != "PPO"):
                raise ValueError("Value warm-start requires PPO and nonnegative steps")
            if value_learning_rate is not None and algorithm != "PPO":
                raise ValueError("Separate value learning rate requires PPO")
            if exploration_learning_rate is not None and algorithm != "PPO":
                raise ValueError("Separate exploration learning rate requires PPO")
            command_units = payload.get("command_units")
            if command_units is not None:
                if (algorithm != "PPO" or not isinstance(command_units, list)
                        or len(command_units) != 3 or any(type(v) not in (int, float)
                        or not math.isfinite(v) or v <= 0 for v in command_units)):
                    raise ValueError("PPO command units require three finite positive scales")
            action_noise_std = payload.get("action_noise_std")
            if action_noise_std is not None:
                if (algorithm != "PPO" or not isinstance(action_noise_std, list)
                        or len(action_noise_std) != 12 or any(type(v) not in (int, float)
                        or not math.isfinite(v) or v <= 0 for v in action_noise_std)):
                    raise ValueError("Action exploration requires twelve positive PPO standard deviations")
            workers = payload.get("workers", prior.get("simulation_workers", 1))
            if type(workers) is not int or workers < 1:
                raise ValueError("Simulation workers must be a positive integer")
            environment = dict(payload.get("environment", prior.get("environment", {})))
            # UI/default requests run through Body Control. Historical replay
            # remains selected by each artifact's recorded backend.
            environment["execution_backend"] = "body_control"
            config = body_control_config(EnvironmentConfig(**environment))
            if recipe and (not previous or payload.get("initialize_from")):
                config = locomotion_config(config)
            commands = requested_commands(config, payload.get("commands"), prior)
            checkpoint = payload.get("resume_checkpoint", "policy.zip")
            initialize_checkpoint = payload.get("initialize_checkpoint", "policy.zip")
            if payload.get("initialize_from"):
                checkpoint_path = (previous / initialize_checkpoint).resolve()
                if not checkpoint_path.is_relative_to(previous) or not checkpoint_path.is_file():
                    raise ValueError("Choose an existing initialization checkpoint within its source run")
            if payload.get("resume"):
                resume_environment_changes(prior, config)
                resume_reward_changes(prior)
                checkpoint_path = (previous / checkpoint).resolve()
                if not checkpoint_path.is_relative_to(previous) or not checkpoint_path.is_file():
                    raise ValueError("Choose an existing checkpoint within the resumed run")
            timing, _ = request_timing(prior, payload.get("command_switch_seconds"),
                                       payload.get("command_switch_range"))
            request_interval_steps(config, **timing)
            if previous and prior.get("representation") != representation_identity():
                raise ValueError(
                    "The environment changed; start a new run instead of mixing replay data"
                )
            identifier = uuid4().hex
            path = self.run_path(identifier)
            path.mkdir()
            save_json(path / "environment.json", asdict(config))
            command = [
                sys.executable,
                "-m",
                "gateway.neural_gait.training",
                "--directory",
                str(path),
                "--steps",
                str(steps),
                "--config",
                str(path / "environment.json"),
                "--device",
                str(device),
                "--seed",
                str(seed),
                "--workers",
                str(workers),
            ]
            if payload.get("resume"):
                command += ["--resume", str(previous), "--resume-checkpoint", checkpoint]
            elif previous:
                command += ["--initialize-from", str(previous)]
            if timing["command_switch_seconds"] is not None:
                command += ["--command-switch-seconds", str(timing["command_switch_seconds"])]
            if timing["command_switch_range"] is not None:
                command += ["--command-switch-range", *map(str, timing["command_switch_range"])]
            if learning_rate is not None:
                command += ["--learning-rate", str(learning_rate)]
            if action_noise_std is not None:
                command += ["--action-noise-std", *map(str, action_noise_std)]
            if value_learning_rate is not None:
                command += ["--value-learning-rate", str(value_learning_rate)]
            if value_warmup_steps:
                command += ["--value-warmup-steps", str(value_warmup_steps)]
            if command_units is not None:
                command += ["--command-units", *map(str, command_units)]
            if checkpoint_every is not None:
                command += ["--checkpoint-every", str(checkpoint_every)]
            if evaluation_seeds is not None:
                command += ["--evaluation-seeds", *map(str, evaluation_seeds)]
            if exploration_learning_rate is not None:
                command += ["--exploration-learning-rate", str(exploration_learning_rate)]
            if payload.get("initialize_from"):
                command += ["--initialize-checkpoint", initialize_checkpoint]
            if payload.get("recipe"):
                command += ["--recipe", recipe]
            if payload.get("commands") is not None:
                for requested in commands:
                    command += ["--command", *map(str, requested)]
            with (path / "training.log").open("w") as log:
                self.training = subprocess.Popen(
                    command, stdout=log, stderr=subprocess.STDOUT
                )
            self.training_id = identifier
            return dict(run_id=identifier, state="starting")

    def start_microduck_training(self, payload, prior):
        """The existing trainer process lifecycle also owns imported mjlab runs."""
        from .environment import EnvironmentConfig
        with self.lock:
            if self.training is not None and self.training.poll() is None:
                raise ValueError("A gait training run is already active")
            steps = payload["steps"]
            workers = payload.get("workers", prior.get("simulation_workers", 1024))
            if type(steps) is not int or steps <= 0 or type(workers) is not int or workers <= 0:
                raise ValueError("Training steps and parallel environments must be positive integers")
            environment = payload.get("environment", prior.get("environment"))
            if not environment:
                raise ValueError("Supply Ainekio's environment including its camera profile for MicroDuck training")
            config = EnvironmentConfig(**environment)
            from .contract import PROPRIO_SCHEMA, PROPRIO_CAMERA_SCHEMA
            from dataclasses import replace
            stage=payload.get("stage",prior.get("stage","proprio"))
            if stage not in ("proprio","camera"):
                raise ValueError("Choose proprio or camera training stage")
            config=replace(config,observation_schema=PROPRIO_CAMERA_SCHEMA if stage=="camera" else PROPRIO_SCHEMA,
                           collision_profile="locomotion",balance_enabled=False,heading_feedback_enabled=False,control_hz=50,physics_hz=500)
            if stage=="camera" and not config.depth_camera:
                raise ValueError("The camera stage needs the installed optical camera profile")
            if prior and prior["environment"] != asdict(config):
                raise ValueError("Resume uses the saved robot/sensor contract; start a new run to change it")
            root = Path(__file__).resolve().parents[3]
            python = os.environ.get("AINEKIO_MICRODUCK_PYTHON", str(root/"build/microduck-training-env/bin/python"))
            if not Path(python).is_file():
                raise ValueError("Install the imported MicroDuck training environment first; see the gateway README")
            identifier = uuid4().hex
            path = self.run_path(identifier)
            path.mkdir()
            save_json(path/"environment.json", asdict(config))
            iterations = math.ceil(steps/(workers*24))
            command = [python, "-m", "gateway.neural_gait.microduck", "--directory", str(path),
                "--config", str(path/"environment.json"), "--iterations", str(iterations),
                "--num-envs", str(workers), "--device", str(payload.get("device", prior.get("device", "cuda:0"))),
                "--seed", str(payload.get("seed", prior.get("seed", 1))), "--stage", stage]
            if payload.get("resume"):
                command += ["--resume", str(self.run_path(payload["resume"]))]
            elif payload.get("initialize_from"):
                command += ["--initialize-from", str(self.run_path(payload["initialize_from"]))]
            with (path/"training.log").open("w") as log:
                self.training = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
            self.training_id = identifier
            return dict(run_id=identifier, state="starting", iterations=iterations, recipe="microduck-mjlab-v1")


    def physical_create(self, payload):
        from .physical import physical_environment
        algorithm = payload.get('algorithm', 'REDQ')
        if algorithm != 'REDQ':
            raise ValueError('Unknown physical learning algorithm')
        with self.lock:
            if self.training is not None and self.training.poll() is None:
                raise ValueError('A gait training run is already active')
            environment = physical_environment(payload['environment'])
            path = self.run_path(uuid4().hex)
            path.mkdir()
            save_json(path/'environment.json', environment)
            save_json(path/'progress.json', dict(kind='physical-redq', state='initializing'))
            with (path/'training.log').open('a') as log:
                self.training = subprocess.Popen([sys.executable, '-m', 'gateway.neural_gait.physical',
                    '--directory', str(path), '--create-config', str(path/'environment.json'),
                    '--seed', str(payload.get('seed', 0)), '--algorithm', algorithm], stdout=log, stderr=subprocess.STDOUT)
            self.training_id = path.name
            return dict(run_id=path.name, state='initializing', movement_started=False)

    def physical_train(self, payload):
        with self.lock:
            if self.training is not None and self.training.poll() is None:
                raise ValueError('A gait training run is already active')
            path = self.run_path(payload['model_id'])
            manifest = json.loads((path/'manifest.json').read_text())
            updates, recordings = payload.get('updates'), payload.get('recordings')
            if manifest.get('kind') != 'physical-redq' or type(updates) is not int or updates <= 0:
                raise ValueError('Select a physical run and positive update count')
            if not isinstance(recordings, list) or not recordings or any(not isinstance(p, str) or not p for p in recordings):
                raise ValueError('Supply physical recording directories')
            method = payload.get('method', 'reinforcement')
            if method not in ('reinforcement', 'imitation'):
                raise ValueError('Choose reinforcement or imitation training')
            fit_all = payload.get('fit_all', False)
            if type(fit_all) is not bool:
                raise ValueError('fit_all must be a boolean')
            if fit_all and method != 'imitation':
                raise ValueError('fit_all applies only to imitation training')
            with (path/'training.log').open('a') as log:
                self.training = subprocess.Popen([sys.executable, '-m', 'gateway.neural_gait.physical',
                    '--directory', str(path), '--recordings', *recordings, '--updates', str(updates),
                    '--device', payload.get('device', 'cuda'),
                    *(['--imitate'] if method == 'imitation' else []),
                    *(['--fit-all'] if fit_all else [])], stdout=log, stderr=subprocess.STDOUT)
            self.training_id = path.name
            return dict(run_id=path.name, state='starting', movement_started=False)

    def render(self, identifier, progress=False):
        from .environment import POLICY_ENVIRONMENT_VERSIONS, representation_identity
        with self.lock:
            path = self.run_path(identifier)
            manifest = json.loads((path / "manifest.json").read_text())
            if (manifest.get("schema") not in SCHEMAS
                    or manifest.get("environment_version") not in POLICY_ENVIRONMENT_VERSIONS
                    or manifest.get("representation") != representation_identity()):
                raise ValueError(
                    "Cannot replay this older checkpoint in a changed environment"
                )
            if (
                progress
                and identifier == self.training_id
                and self.training.poll() is None
            ):
                return dict(
                    run_id=identifier, state="comparison_after_training"
                )
            key = identifier + ("-progress" if progress else "")
            process = self.renders.get(key)
            if process is None or process.poll() is not None:
                env = {**os.environ, "MUJOCO_GL": os.environ.get("MUJOCO_GL", "egl")}
                with (path / "render.log").open("w") as log:
                    self.renders[key] = subprocess.Popen(
                        [
                            sys.executable,
                            "-m",
                            "gateway.neural_gait.replay",
                            "--directory",
                            str(path),
                        ]
                        + (["--progress"] if progress else []),
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        env=env,
                    )
            return dict(run_id=identifier, state="rendering")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, code, value):
        self.bytes(
            code, json.dumps(value, allow_nan=False).encode(), "application/json"
        )

    def bytes(self, code, data, content_type):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        try:
            parsed = urlsplit(self.path)
            if parsed.path == "/status":
                return self.reply(200, self.server.runtime.status(
                    include_runs=parse_qs(parsed.query).get("history", ["1"])[0] != "0"))
            if parsed.path in ("/replay", "/image", "/progress-video", '/footage'):
                identifier = parse_qs(parsed.query)["id"][0]
                path = self.server.runtime.run_path(identifier)
                filename, content_type = (
                    ("replay.mp4", "video/mp4")
                    if parsed.path == "/replay"
                    else ("environment.png", "image/png")
                )
                if parsed.path == "/progress-video":
                    filename, content_type = "progress-video.mp4", "video/mp4"
                if parsed.path == '/footage':
                    from .replay import write_footage
                    with tempfile.TemporaryFile() as archive:
                        write_footage(path, archive)
                        self.send_response(200)
                        self.send_header("Content-Type", "application/zip")
                        self.send_header("Content-Length", str(archive.tell()))
                        self.end_headers()
                        archive.seek(0)
                        shutil.copyfileobj(archive, self.wfile)
                    return
                return self.bytes(200, (path / filename).read_bytes(), content_type)
            self.reply(404, {"error": "Unknown endpoint"})
        except (ValueError, KeyError, OSError, TypeError) as error:
            self.reply(400, {"error": str(error)})

    def do_POST(self):
        try:
            payload = json.loads(
                self.rfile.read(int(self.headers.get("Content-Length", 0)))
            )
            runtime = self.server.runtime
            if self.path == "/infer":
                result = runtime.infer(payload["observation"], **{key: payload[key] for key in
                    ('explore', 'model_id', 'checkpoint_id', 'noise', 'demonstration') if key in payload})
            elif self.path == '/collection-end':
                result = runtime.collection_end(payload['robot_id'], payload['owner'])
            elif self.path == "/load":
                result = runtime.load(payload["model_id"], payload.get("checkpoint_id"))
            elif self.path == "/train":
                result = runtime.start_training(payload)
            elif self.path == '/physical-create':
                result = runtime.physical_create(payload)
            elif self.path == '/physical-train':
                result = runtime.physical_train(payload)
            elif self.path == "/render":
                result = runtime.render(
                    payload["model_id"], payload.get("progress", False)
                )
            else:
                return self.reply(404, {"error": "Unknown endpoint"})
            self.reply(200, result)
        except (ValueError, KeyError, OSError, TypeError) as error:
            self.reply(400, {"error": str(error)})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8796)
    parser.add_argument("--directory", required=True)
    parser.add_argument("--device", default="cpu")
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.runtime = Runtime(args.directory, args.device)
    print(
        json.dumps(
            {"listening": f"http://127.0.0.1:{args.port}", "directory": args.directory}
        ),
        flush=True,
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
