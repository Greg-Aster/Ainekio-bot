"""Separate local neural gait inference/training service, with no robot transport."""

import argparse
from dataclasses import asdict, replace
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

from .contract import SCHEMA, SCHEMAS, PROPRIO_SCHEMA, foot_offsets, vector
from .artifacts import save_json, summarize_commands

SUPPORTED_KINDS = ("microduck-mjlab", "pupper-mjx")


def evaluation_summary(value):
    """Dashboard trial measurements; full time series stay in the run artifact."""
    if not isinstance(value, dict):
        return value
    result = dict(value)
    if "episodes" in result:
        result["episodes"] = [
            {key: item for key, item in row.items() if key != "progress_intervals"}
            for row in result["episodes"]
        ]
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
            or identifier.startswith("-")
            or any(c not in "0123456789abcdefghijklmnopqrstuvwxyz-" for c in identifier)
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
                model_id=self.model_id,
                checkpoint_id=self.checkpoint_id,
                kind=self.kind,
                selection_error=self.selection_error,
                device=self.device,
                environment=self.environment,
                training_id=training_id,
                training_running=training is not None and training.poll() is None,
            )
        if not include_runs:
            return result
        runs = []
        paths = {
            p.parent: p
            for pattern in ("*/environment.json", "*/manifest.json")
            for p in self.directory.glob(pattern)
        }
        for path in sorted(paths.values(), key=lambda p: p.stat().st_mtime, reverse=True):
            manifest_path = path.with_name("manifest.json")
            manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
            kind = manifest.get("kind")
            if kind not in SUPPORTED_KINDS and path.parent.name != training_id:
                continue
            progress = path.with_name("progress.json")
            value = (
                json.loads(progress.read_text())
                if progress.exists()
                else {"state": "starting"}
            )
            value.pop("evaluation", None)
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
                if "command_results" not in measured and measured.get("episodes"):
                    measured["command_results"] = summarize_commands(measured.get("episodes", []))
                checkpoint["evaluation"] = evaluation_summary(measured)
            video = path.with_name("progress-video.json")
            if path.parent.name == training_id and training.poll() not in (None, 0):
                value.update(state="error", exit_code=training.returncode)
            runs.append(
                dict(
                    id=path.parent.name,
                    **{**value, **({"kind": kind} if kind else {})},
                    algorithm=manifest.get("algorithm"),
                    recipe=manifest.get("recipe"),
                    training_device=manifest.get("device"),
                    simulation_workers=manifest.get("simulation_workers"),
                    evaluation=(
                        evaluation_summary(json.loads(evaluation.read_text()))
                        if evaluation.exists()
                        else None
                    ),
                    has_policy=bool(manifest.get("policy") and (path.parent / manifest["policy"]).is_file()),
                    has_replay=path.with_name("replay.mp4").exists(),
                    has_footage=any(
                        clip.is_file() and ".tmp." not in clip.name
                        for clip in (path.parent / "clips").glob("*.mp4")
                    ),
                    has_progress_video=path.with_name("progress-video.mp4").exists(),
                    progress_video=json.loads(video.read_text()) if video.exists() else None,
                    checkpoints=checkpoint_rows,
                    rendering=render_active or (rendering is not None and rendering.poll() is None),
                    render_exit_code=rendering.poll() if rendering else None,
                )
            )
        defaults = self.environment or {}
        return dict(result, runs=runs, defaults=defaults)

    def load(self, identifier, checkpoint_id=None):
        path = self.run_path(identifier)
        manifest = json.loads((path / "manifest.json").read_text())
        kind = manifest.get("kind")
        if kind not in SUPPORTED_KINDS:
            raise ValueError("Select a MicroDuck or Pupper MJX checkpoint")
        if kind == "microduck-mjlab" and not manifest.get("policy"):
            raise ValueError("This MicroDuck run has no exported policy yet")
        if kind == "pupper-mjx" and not manifest.get("policy"):
            raise ValueError("This Pupper MJX run has no exported policy yet")
        from .environment import POLICY_ENVIRONMENT_VERSIONS, representation_identity
        if (
            manifest["schema"] not in SCHEMAS
            or manifest.get("environment_version") not in POLICY_ENVIRONMENT_VERSIONS
            or manifest.get("representation") != representation_identity()
        ):
            raise ValueError("Checkpoint representation differs from the current robot environment")
        checkpoint = manifest["policy"]
        if checkpoint_id is not None:
            rows = json.loads((path / "checkpoints.json").read_text())
            selected = next((row for row in rows if row["id"] == checkpoint_id), None)
            if selected is None:
                raise ValueError("Choose a published checkpoint from this run")
            checkpoint = selected["policy"]
        if kind == "microduck-mjlab":
            from .microduck_actor import MicroduckActor
            model = MicroduckActor(path / checkpoint)
        else:
            from .pupper_mjx_actor import PupperMjxActor
            model = PupperMjxActor(path / checkpoint, environment=manifest["environment"])
        with self.lock:
            old_model = self.model
            self.model, self.model_id, self.environment = (
                model,
                identifier,
                manifest["environment"],
            )
            self.checkpoint_id = checkpoint_id
            self.kind = kind
            self.selection_error = None
            save_json(
                self.directory / "selected.json",
                dict(model_id=identifier, checkpoint_id=checkpoint_id),
            )
            if old_model is not None and old_model is not model and hasattr(old_model, "close"):
                old_model.close()
        return self.status()

    def infer(self, observation, *, model_id=None, checkpoint_id=None, walk_context=None):
        values = np.asarray(vector(observation), dtype=np.float32)
        started = time.monotonic()
        with self.lock:
            if self.model is None:
                raise ValueError("No neural gait checkpoint selected")
            if model_id is not None and (model_id, checkpoint_id) != (self.model_id, self.checkpoint_id):
                raise ValueError("Inference checkpoint differs from the owning Walk")
            limits = self.environment["target_limits_deg"]
            if observation["target_limits_deg"] != limits:
                raise ValueError("Observation action domain differs from the selected checkpoint")
            if self.kind == "pupper-mjx":
                result = self.model.infer_observation(observation, walk_context=walk_context)
                resolved = result["resolved"]
                return dict(
                    schema=self.environment.get("observation_schema", SCHEMA),
                    model_id=self.model_id,
                    checkpoint_id=self.checkpoint_id,
                    action=result["action"].tolist(),
                    raw_action=result["raw_action"].tolist(),
                    motor_targets_rad=result["motor_targets_rad"].tolist(),
                    motor_targets_deg=result["motor_targets_deg"].tolist(),
                    requested_foot_offset_mm=result["requested_foot_offset_mm"].tolist(),
                    fitted_foot_offset_mm=resolved["applied_offset_mm"].tolist() if resolved else None,
                    targets_deg=resolved["ramped_angles"].tolist() if resolved else None,
                    nominal_goal_deg=resolved["nominal_goal_angles"].tolist() if resolved else None,
                    leg_fit=resolved["leg_fit"].tolist() if resolved else None,
                    elapsed_s=time.monotonic() - started,
                    execution="preview_only",
                    targets_resolved_by="existing P4 Walk kinematics",
                )
            action, _ = self.model.predict(values, deterministic=True)
            identifier, selected_checkpoint = self.model_id, self.checkpoint_id
            schema = self.environment.get("observation_schema", SCHEMA)
            from .native import BodyModel
            native = BodyModel(self.environment["robot"])
            requested = foot_offsets(action, self.environment["foot_action_scale_mm"])
            try:
                resolved = native.foot_target(
                    np.asarray(requested).reshape(4, 3),
                    self.environment["reference_joint_deg"],
                    observation["target_deg"],
                    self.environment["joint_speed_deg_s"],
                    1 / self.environment["control_hz"],
                )
            finally:
                native.close()
        return dict(
            schema=schema,
            model_id=identifier,
            checkpoint_id=selected_checkpoint,
            action=action.tolist(),
            requested_foot_offset_mm=requested,
            fitted_foot_offset_mm=resolved["applied_offset_mm"].tolist() if resolved else None,
            targets_deg=resolved["ramped_angles"].tolist() if resolved else None,
            target_rejected=resolved is None,
            elapsed_s=time.monotonic() - started,
            execution="preview_only",
        )

    def start_training(self, payload):
        recipe = payload.get("recipe", "microduck-mjlab-v1")
        if recipe != "microduck-mjlab-v1":
            raise ValueError("Unsupported training recipe; only MicroDuck mjlab training is active here")
        source = payload.get("resume")
        prior = json.loads((self.run_path(source) / "manifest.json").read_text()) if source else {}
        if prior and prior.get("kind") != "microduck-mjlab":
            raise ValueError("Only MicroDuck mjlab runs can be resumed here")
        return self.start_microduck_training(payload, prior)

    def start_microduck_training(self, payload, prior):
        """Launch the MicroDuck mjlab trainer subprocess."""
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
                raise ValueError("Supply Ainekio's environment for MicroDuck training")
            config = EnvironmentConfig(**environment)
            config = replace(
                config,
                observation_schema=PROPRIO_SCHEMA,
                collision_profile="locomotion",
                balance_enabled=False,
                heading_feedback_enabled=False,
                control_hz=50,
                physics_hz=500,
            )
            if prior and prior["environment"] != asdict(config):
                raise ValueError("Resume uses the saved robot/sensor contract; start a new run to change it")
            root = Path(__file__).resolve().parents[3]
            python = os.environ.get(
                "AINEKIO_MICRODUCK_PYTHON",
                str(root / "build/microduck-training-env/bin/python"),
            )
            if not Path(python).is_file():
                raise ValueError("Install the imported MicroDuck training environment first; see the gateway README")
            identifier = uuid4().hex
            path = self.run_path(identifier)
            path.mkdir()
            save_json(path / "environment.json", asdict(config))
            iterations = math.ceil(steps / (workers * 24))
            command = [
                python,
                "-m",
                "gateway.neural_gait.microduck",
                "--directory",
                str(path),
                "--config",
                str(path / "environment.json"),
                "--iterations",
                str(iterations),
                "--num-envs",
                str(workers),
                "--device",
                str(payload.get("device", prior.get("device", "cuda:0"))),
                "--seed",
                str(payload.get("seed", prior.get("seed", 1))),
            ]
            if payload.get("resume"):
                command += ["--resume", str(self.run_path(payload["resume"]))]
            with (path / "training.log").open("w") as log:
                self.training = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
            self.training_id = identifier
            return dict(run_id=identifier, state="starting", iterations=iterations, recipe="microduck-mjlab-v1")

    def render(self, identifier, progress=False):
        from .environment import POLICY_ENVIRONMENT_VERSIONS, representation_identity
        with self.lock:
            path = self.run_path(identifier)
            manifest = json.loads((path / "manifest.json").read_text())
            if manifest.get("kind") not in SUPPORTED_KINDS:
                raise ValueError("Replay supports MicroDuck and Pupper MJX runs only")
            if (
                manifest.get("schema") not in SCHEMAS
                or manifest.get("environment_version") not in POLICY_ENVIRONMENT_VERSIONS
                or manifest.get("representation") != representation_identity()
            ):
                raise ValueError("Cannot replay this older checkpoint in a changed environment")
            if progress and identifier == self.training_id and self.training.poll() is None:
                return dict(run_id=identifier, state="comparison_after_training")
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
        self.bytes(code, json.dumps(value, allow_nan=False).encode(), "application/json")

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
                return self.reply(
                    200,
                    self.server.runtime.status(
                        include_runs=parse_qs(parsed.query).get("history", ["1"])[0] != "0"
                    ),
                )
            if parsed.path in ("/replay", "/image", "/progress-video", "/footage"):
                identifier = parse_qs(parsed.query)["id"][0]
                path = self.server.runtime.run_path(identifier)
                filename, content_type = (
                    ("replay.mp4", "video/mp4")
                    if parsed.path == "/replay"
                    else ("environment.png", "image/png")
                )
                if parsed.path == "/progress-video":
                    filename, content_type = "progress-video.mp4", "video/mp4"
                if parsed.path == "/footage":
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
                result = runtime.infer(
                    payload["observation"],
                    **{
                        key: payload[key]
                        for key in ("model_id", "checkpoint_id", "walk_context")
                        if key in payload
                    },
                )
            elif self.path == "/load":
                result = runtime.load(payload["model_id"], payload.get("checkpoint_id"))
            elif self.path == "/train":
                result = runtime.start_training(payload)
            elif self.path == "/render":
                result = runtime.render(payload["model_id"], payload.get("progress", False))
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
