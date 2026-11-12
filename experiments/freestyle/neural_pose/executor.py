"""50 Hz closed-loop host executor for the Neural Pose & Emote Controller.

Streams 50 Hz `walk_target` foot offsets over the existing `walk_nominal_v1`
gateway protocol using live IMU + 4th-wire feedback (falling back cleanly to
commanded model angles on faulted/clipped channels).
"""
from __future__ import annotations

from contextlib import asynccontextmanager
import asyncio
import copy
import math
import os
from pathlib import Path
from uuid import uuid4

from .actor import NeuralPoseActor
from .contract import JOINTS, PoseObservationHistory, assemble_pose_features
from .goals import PoseManifold, compile_goal_segments, usable_joint_angles_deg

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_ACTIVE_POLICY = ROOT / "experiments/freestyle/artifacts/neural-pose-active/policy.onnx"


def resolve_active_policy_path() -> Path | None:
    override = os.environ.get("AINEKIO_NEURAL_POSE_POLICY")
    if override is not None:
        if override.strip().lower() in ("", "0", "none", "off", "false"):
            return None
        candidate = Path(override)
        return candidate if candidate.exists() else None
    return DEFAULT_ACTIVE_POLICY if DEFAULT_ACTIVE_POLICY.exists() else None


class NeuralPoseRuntime:
    """Lazy-cached ONNX policy + closed-chain manifold with automatic hot-reload on mtime change."""

    def __init__(self):
        self._cached_key: tuple[str, int] | None = None
        self._actor: NeuralPoseActor | None = None
        self._manifold: PoseManifold | None = None

    def load(self) -> tuple[NeuralPoseActor, PoseManifold] | None:
        policy_path = resolve_active_policy_path()
        if policy_path is None:
            return None
        resolved = policy_path.resolve()
        stat = resolved.stat()
        key = (str(resolved), int(stat.st_mtime_ns))
        if self._cached_key != key or self._actor is None or self._manifold is None:
            actor = NeuralPoseActor(resolved)
            env_json = resolved.parent / "environment.json"
            manifold = PoseManifold(env_json) if env_json.exists() else PoseManifold()
            self._actor = actor
            self._manifold = manifold
            self._cached_key = key
        return self._actor, self._manifold


def _sample_snapshot(obs: dict) -> dict:
    return {
        "time_us": (obs.get("feedback") or {}).get("device_us"),
        "joints": {
            j: (obs["joints"][j].get("filtered_model_deg", obs["joints"][j].get("model_deg")))
            for j in JOINTS
            if j in (obs.get("joints") or {})
        },
        "imu": obs.get("imu"),
    }


async def execute_neural_pose_program(
    bridge,
    job: dict,
    program: list[dict],
    obs: dict,
    *,
    generation_index: int,
    sequence_options: dict,
    runtime: NeuralPoseRuntime,
):
    """Execute a Freestyle or Motion Library program through the 50 Hz Neural Pose policy."""
    loaded = runtime.load()
    if loaded is None:
        raise RuntimeError("Neural pose policy is not available")
    actor, manifold = loaded

    robot = job["robot_id"]
    gateway = bridge.gateway
    start_index = int(job.get("start_index", 0))
    sub_program = program[start_index:]
    if not sub_program:
        return obs

    segments = await asyncio.to_thread(compile_goal_segments, sub_program, obs, manifold)
    for seg in segments:
        seg["index"] += start_index

    tick_event = asyncio.Event()

    def _on_gateway_event(event: dict):
        if event.get("robot_id") == robot and event.get("t") == "imu":
            tick_event.set()

    gateway.subscribe_events(_on_gateway_event)
    walk_seq: int | None = None
    history = PoseObservationHistory()
    sample_idx = 0
    consumed_sample = 0
    sent_actions: dict[int, list[float]] = {}
    _, prev_action = manifold.project_angles_deg(usable_joint_angles_deg(obs))
    hold_goal_deg, hold_goal_foot = manifold.project_angles_deg(usable_joint_angles_deg(obs))
    hold_support = manifold.infer_leg_support(hold_goal_deg)

    async def _ensure_host_stream():
        nonlocal walk_seq, sample_idx, consumed_sample, prev_action
        connection = gateway._connection(robot)
        if walk_seq is not None and connection._owns_walk(walk_seq) and walk_seq in connection.pending:
            return connection
        if "walk_nominal_v1" not in connection.features:
            raise ValueError(f"Robot {robot} does not advertise walk_nominal_v1 for 50 Hz neural pose control")
        history.reset()
        sample_idx = 0
        consumed_sample = 0
        sent_actions.clear()
        cur_obs = gateway.body_sensor_observation(robot)
        _, prev_action = manifold.project_angles_deg(usable_joint_angles_deg(cur_obs))
        seq = await gateway.queue_intent(
            "walk",
            {
                "dir": "fwd",
                "gait": "walk",
                "steps": 0,
                "speed": 100,
                "source": "host",
                "twist": [0.0, 0.0, 0.0],
                "geometry": manifold.geometry_id,
                "reference_cd": [round(v * 100) for v in manifold.reference_joint_deg],
            },
            robot_id=robot,
            **sequence_options,
        )
        # Recovery admission runs at first body motion command; clear sequence_options thereafter
        sequence_options.clear()
        pending = connection.pending.get(seq)
        if pending is not None:
            ack = await asyncio.shield(pending.acknowledgement)
            job["receipts"].append(ack)
            bridge.record(job, "command_receipt", ack, sequence=seq)
            if ack.get("t") != "ack":
                raise RuntimeError("Body rejected host pose stream: " + str(ack))
        walk_seq = seq
        return connection

    async def _step_50hz(
        connection,
        goal_deg: list[float],
        goal_foot_norm: list[float],
        leg_support: list[float],
        speed_scale: float,
    ) -> dict:
        nonlocal sample_idx, consumed_sample, prev_action
        if bridge.active.get(robot) != job["id"]:
            raise RuntimeError("Neural pose job was superseded")
        if walk_seq is None or not connection._owns_walk(walk_seq) or walk_seq not in connection.pending:
            raise RuntimeError("Host 50 Hz pose stream lost ownership")

        sensor = gateway.body_sensor_observation(robot)
        motion = (sensor.get("imu") or {}).get("motion") or {}
        if motion.get("sequence") == walk_seq:
            dev_sample = int(motion.get("nominal_sample") or 0)
            if dev_sample > consumed_sample and dev_sample in sent_actions:
                prev_action = sent_actions[dev_sample]
                consumed_sample = dev_sample
                for k in [k for k in sent_actions if k <= dev_sample]:
                    sent_actions.pop(k, None)

        joints_map = sensor["joints"]
        imu = sensor["imu"]
        measured_deg = [joints_map[j].get("filtered_model_deg") for j in JOINTS]
        commanded_deg = [joints_map[j].get("commanded_model_deg") for j in JOINTS]
        velocity_deg_s = [joints_map[j].get("velocity_deg_s") or 0.0 for j in JOINTS]
        usable_flags = [bool(joints_map[j].get("feedback_usable", False)) for j in JOINTS]

        feat = assemble_pose_features(
            measured_deg=measured_deg,
            commanded_deg=commanded_deg,
            velocity_deg_s=velocity_deg_s,
            usable_flags=usable_flags,
            orientation_wxyz=imu["orientation_wxyz"],
            angular_rate_rad_s=imu["angular_rate_rad_s"],
            acceleration_m_s2=imu["acceleration_m_s2"],
            goal_joint_deg=goal_deg,
            goal_foot_norm=goal_foot_norm,
            leg_support=leg_support,
            speed_scale=speed_scale,
            previous_action=prev_action,
        )
        dev_us = (sensor.get("feedback") or {}).get("device_us")
        t_obs = float(dev_us) / 1e6 if isinstance(dev_us, (int, float)) and dev_us > 0 else gateway.clock()
        obs_vec = history.push_and_project(t_obs, feat)
        act_list, feet_mm = actor.infer_feet_mm(obs_vec)

        sample_idx += 1
        sent_actions[sample_idx] = act_list
        await connection.send_command(
            {
                "t": "walk_target",
                "walk": walk_seq,
                "sample": sample_idx,
                "geometry": manifold.geometry_id,
                "feet_mm": feet_mm,
            },
            received_at=gateway.clock(),
        )
        return sensor

    try:
        for seg_pos, seg in enumerate(segments):
            idx = seg["index"]
            action = seg["action"]
            kind = seg["kind"]
            args = action.get("arguments") or {}

            job["operation_index"] = idx
            job["current_action"] = action
            job["remaining_program"] = copy.deepcopy(program[idx + 1 :])
            job["packet_progress"] = None
            bridge.record(
                job,
                "operation_started",
                {
                    "generation_index": generation_index,
                    "action_index": idx,
                    "action": action,
                    "observation": obs,
                },
            )

            if kind == "face":
                scoped = any(item["name"] != "face" for item in program)
                face_token = (job.get("face_token") or "fs_" + uuid4().hex[:24]) if scoped else None
                seq = await gateway.queue_intent(
                    "face",
                    {"expr": seg["expr"], **({"token": face_token} if scoped else {})},
                    robot_id=robot,
                )
                if scoped:
                    job["face_token"] = face_token
                bridge.record(
                    job,
                    "face_submitted",
                    {
                        "expression": seg["expr"],
                        "scope": "program" if scoped else "normal_face_selection",
                        "generation_index": generation_index,
                        "action_index": idx,
                    },
                    sequence=seq,
                )
                job["completed_operation_index"] = idx
                job["current_action"] = None
                continue

            before_sensor = gateway.body_sensor_observation(robot)
            receipt_start = len(job["receipts"])

            if kind in ("pose_goal", "oscillate_goal", "hold"):
                connection = await _ensure_host_stream()
                t_start = gateway.clock()

                if kind == "pose_goal":
                    goal_deg = seg["goal_deg"]
                    goal_foot = seg["goal_foot_norm"]
                    support = seg["leg_support"]
                    spd = seg["speed_scale"]
                    duration_s = seg["duration_s"]
                    bridge.record(
                        job,
                        "motion_prepared",
                        {
                            "action_index": idx,
                            "start": {j: seg["start_deg"][i] for i, j in enumerate(JOINTS)},
                            "target": {j: goal_deg[i] for i, j in enumerate(JOINTS)},
                            "control": "neural_pose_50hz",
                            "duration_s": duration_s,
                        },
                    )
                    settled_frames = 0
                    while True:
                        elapsed = gateway.clock() - t_start
                        tick_event.clear()
                        sensor_now = await _step_50hz(connection, goal_deg, goal_foot, support, spd)
                        if elapsed >= duration_s:
                            break
                        if elapsed >= 0.26:
                            usable_errs = []
                            usable_vels = []
                            for i, j in enumerate(JOINTS):
                                jd = sensor_now["joints"][j]
                                if jd.get("feedback_usable") and isinstance(jd.get("filtered_model_deg"), (int, float)):
                                    usable_errs.append(abs(float(jd["filtered_model_deg"]) - goal_deg[i]))
                                    usable_vels.append(abs(float(jd.get("velocity_deg_s") or 0.0)))
                            if len(usable_errs) >= 6 and max(usable_errs) <= 4.5 and max(usable_vels) <= 22.0:
                                settled_frames += 1
                                if settled_frames >= 3:
                                    break
                            else:
                                settled_frames = 0
                        try:
                            await asyncio.wait_for(tick_event.wait(), timeout=0.022)
                        except asyncio.TimeoutError:
                            pass
                    hold_goal_deg, hold_goal_foot, hold_support = goal_deg, goal_foot, support

                elif kind == "oscillate_goal":
                    osc_dur = seg["cycles"] / seg["hz"]
                    total_dur = seg["duration_s"]
                    end_deg = seg["end_deg"]
                    _, end_foot = manifold.project_angles_deg(end_deg)
                    support = seg["leg_support"]
                    spd = seg["speed_scale"]
                    bridge.record(
                        job,
                        "motion_prepared",
                        {
                            "action_index": idx,
                            "target": {j: end_deg[i] for i, j in enumerate(JOINTS)},
                            "control": "neural_pose_50hz",
                            "duration_s": total_dur,
                        },
                    )
                    while True:
                        elapsed = gateway.clock() - t_start
                        tick_event.clear()
                        if elapsed < osc_dur:
                            cand = list(seg["base_deg"])
                            phase = 2.0 * math.pi * seg["hz"] * elapsed
                            for j_idx, c_deg, a_deg in zip(
                                seg["joint_indices"], seg["centers_deg"], seg["amplitudes_deg"]
                            ):
                                cand[j_idx] = c_deg + a_deg * math.sin(phase)
                            g_deg, g_foot = manifold.project_angles_deg(cand)
                        else:
                            g_deg, g_foot = end_deg, end_foot
                        await _step_50hz(connection, g_deg, g_foot, support, spd)
                        if elapsed >= total_dur:
                            break
                        try:
                            await asyncio.wait_for(tick_event.wait(), timeout=0.022)
                        except asyncio.TimeoutError:
                            pass
                    hold_goal_deg, hold_goal_foot, hold_support = end_deg, end_foot, support

                elif kind == "hold":
                    hold_dur = max(0.02, float(seg["seconds"]))
                    while True:
                        elapsed = gateway.clock() - t_start
                        tick_event.clear()
                        await _step_50hz(connection, hold_goal_deg, hold_goal_foot, hold_support, 0.5)
                        if elapsed >= hold_dur:
                            break
                        try:
                            await asyncio.wait_for(tick_event.wait(), timeout=0.022)
                        except asyncio.TimeoutError:
                            pass

            elif kind == "gait":
                from ..program import gait_intents

                walk_seq = None
                for intent in gait_intents(args):
                    seq = await gateway.queue_intent("walk", intent, robot_id=robot, **sequence_options)
                    sequence_options.clear()
                    await bridge._receipt(job, seq, obs["epoch"])
                hold_goal_deg, hold_goal_foot = manifold.project_angles_deg(
                    usable_joint_angles_deg(gateway.body_sensor_observation(robot))
                )
                hold_support = manifold.infer_leg_support(hold_goal_deg)

            elif kind in ("stop", "release"):
                walk_seq = None
                detach = kind == "release"
                seq = await gateway.estop(robot_id=robot, detach=detach, **sequence_options)
                sequence_options.clear()
                await bridge._receipt(job, seq, obs["epoch"], acknowledgement=True)

            # Finalize operation record
            job["completed_operation_index"] = idx
            job["completed_action"] = copy.deepcopy(action)
            job["current_action"] = None
            job["packet_progress"] = None

            # Only hit full calibration/feedback RPC on the very last segment; intermediate
            # 50 Hz segments use zero-latency body_sensor_observation so transitions have 0 gap!
            is_last = seg_pos == len(segments) - 1
            after_sensor = gateway.body_sensor_observation(robot)
            initial_rec = {**_sample_snapshot(before_sensor), "action": action}
            if action["name"] in ("move", "pose") and kind == "pose_goal":
                moving = [args["joint"]] if action["name"] == "move" else list(args["joints"])
                targets = [args["angle_deg"]] if action["name"] == "move" else list(args["angles_deg"])
                ref = args.get("reference", "absolute")
                home_map = {j: (obs["joints"][j].get("home_deg", 0.0)) for j in JOINTS}
                start_map = {j: seg["start_deg"][i] for i, j in enumerate(JOINTS)}
                initial_rec["correction_delta_deg"] = {
                    j: (
                        angle
                        if ref == "current"
                        else angle + (home_map[j] if ref == "home" else 0.0) - start_map[j]
                    )
                    for j, angle in zip(moving, targets)
                }
            after_rec = _sample_snapshot(after_sensor)
            after_rec["receipts"] = copy.deepcopy(job["receipts"][receipt_start:])
            job["history"].extend([initial_rec, after_rec])
            bridge.record(
                job,
                "operation_completed",
                {
                    "generation_index": generation_index,
                    "action_index": idx,
                    "before": initial_rec,
                    "after": after_rec,
                },
            )
            if is_last:
                obs = await bridge.connected_observation(job)
                job["observation"] = obs

        # Lock final posture smoothly in place if our 50 Hz host stream is still active
        if walk_seq is not None and bridge.active.get(robot) == job["id"] and not job.get("cancellation_requested"):
            connection = gateway._connections.get(robot)
            if connection is not None and connection._owns_walk(walk_seq):
                @asynccontextmanager
                async def _mark_hold(seq: int):
                    job["neural_pose_hold_seq"] = seq
                    yield

                hold_seq = await gateway.estop(robot_id=robot, detach=False, on_sequence=_mark_hold)
                await bridge._receipt(job, hold_seq, job["epoch"], acknowledgement=True)
                obs = await bridge.connected_observation(job)
                job["observation"] = obs
        return obs
    except Exception:
        if walk_seq is not None and bridge.active.get(robot) == job["id"]:
            connection = gateway._connections.get(robot)
            if connection is not None and connection._owns_walk(walk_seq):
                try:
                    await gateway.estop(robot_id=robot, detach=False)
                except Exception:
                    pass
        raise
    finally:
        gateway.unsubscribe_events(_on_gateway_event)
