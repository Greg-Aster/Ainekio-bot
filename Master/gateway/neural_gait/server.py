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
import torch

from .contract import SCHEMA, SCHEMAS, foot_offsets, vector
from .environment import EnvironmentConfig, body_control_config, ENVIRONMENT_VERSION, POLICY_ENVIRONMENT_VERSIONS, representation_identity
from .training import load_policy, policy_algorithm, request_interval_steps, request_timing, resume_environment_changes, resume_reward_changes, save_json, summarize_commands, training_recipe, requested_commands


class Runtime:
    def __init__(self, directory, device="cpu"):
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.device = device
        self.model = self.model_id = self.environment = None
        self.training = self.training_id = None
        self.renders = {}
        self.lock = threading.RLock()
        self.selection_error = None
        torch.set_num_threads(1)
        selected = self.directory / "selected.json"
        if selected.exists():
            try:
                self.load(json.loads(selected.read_text())["model_id"])
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

    def status(self):
        with self.lock:
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
                rendering = self.renders.get(path.parent.name)
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
                    if "command_results" not in measured:
                        measured["command_results"] = summarize_commands(measured.get("episodes", []))
                video = path.with_name("progress-video.json")
                if (
                    path.parent.name == self.training_id
                    and self.training.poll() not in (None, 0)
                ):
                    value.update(state="error", exit_code=self.training.returncode)
                runs.append(
                    dict(
                        id=path.parent.name,
                        **value,
                        initialization=manifest.get("initialization"),
                        recipe=manifest.get("recipe"),
                        training_device=manifest.get("device"),
                        simulation_workers=manifest.get("simulation_workers"),
                        automatic_footage=manifest.get("automatic_footage"),
                        evaluation=(
                            json.loads(evaluation.read_text())
                            if evaluation.exists()
                            else None
                        ),
                        has_policy=path.with_name("policy.zip").exists(),
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
            return dict(
                schema=(self.environment or {}).get("observation_schema", SCHEMA),
                model_id=self.model_id,
                selection_error=self.selection_error,
                device=self.device,
                runs=runs,
                environment=self.environment,
                defaults=asdict(EnvironmentConfig(execution_backend="body_control")),
                training_id=self.training_id,
                training_running=self.training is not None
                and self.training.poll() is None,
            )

    def load(self, identifier):
        path = self.run_path(identifier)
        manifest = json.loads((path / "manifest.json").read_text())
        if (manifest["schema"] not in SCHEMAS or manifest.get("environment_version") not in POLICY_ENVIRONMENT_VERSIONS
                or manifest.get("representation") != representation_identity()):
            raise ValueError("Checkpoint representation differs from the current robot environment")
        model = load_policy(path, device=self.device)
        with self.lock:
            self.model, self.model_id, self.environment = (
                model,
                identifier,
                manifest["environment"],
            )
            self.selection_error = None
            save_json(self.directory / "selected.json", dict(model_id=identifier))
        return self.status()

    def infer(self, observation):
        values = np.asarray(vector(observation), dtype=np.float32)
        started = time.monotonic()
        with self.lock:
            if self.model is None:
                raise ValueError("No neural gait checkpoint selected")
            limits = self.environment["target_limits_deg"]
            if observation["target_limits_deg"] != limits:
                raise ValueError(
                    "Observation action domain differs from the selected checkpoint"
                )
            action, _ = self.model.predict(values, deterministic=True)
            identifier = self.model_id
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
            schema=self.environment.get("observation_schema", SCHEMA),
            model_id=identifier,
            action=action.tolist(),
            requested_foot_offset_mm=requested,
            fitted_foot_offset_mm=resolved["applied_offset_mm"].tolist() if resolved else None,
            targets_deg=resolved["ramped_angles"].tolist() if resolved else None,
            target_rejected=resolved is None,
            elapsed_s=time.monotonic() - started,
            execution="preview_only",
        )

    def start_training(self, payload):
        with self.lock:
            if self.training is not None and self.training.poll() is None:
                raise ValueError("A gait training run is already active")
            steps = payload["steps"]
            if type(steps) is not int or steps <= 0:
                raise ValueError("Training steps must be a positive integer")
            checkpoint_every = payload.get("checkpoint_every")
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
            if previous:
                policy_algorithm(prior)
            recipe = training_recipe(prior, payload.get("recipe"),
                                     initialize_from=payload.get("initialize_from"))
            algorithm = policy_algorithm(prior) if previous else ("PPO" if recipe else "SAC")
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
            if recipe and not previous:
                environment["reward_profile"] = "locomotion"
            config = body_control_config(EnvironmentConfig(**environment))
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
                self.device,
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
            if command_units is not None:
                command += ["--command-units", *map(str, command_units)]
            if checkpoint_every is not None:
                command += ["--checkpoint-every", str(checkpoint_every)]
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

    def render(self, identifier, progress=False):
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
                return self.reply(200, self.server.runtime.status())
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
                result = runtime.infer(payload["observation"])
            elif self.path == "/load":
                result = runtime.load(payload["model_id"])
            elif self.path == "/train":
                result = runtime.start_training(payload)
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
