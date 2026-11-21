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
import torch

from .actor import NeuralPoseActor
from .contract import JOINTS, PoseObservationHistory, assemble_pose_features
from .goals import STAND_ANGLES_DEG, PoseManifold, compile_goal_segments, usable_joint_angles_deg

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

    snap = await gateway.status_snapshot()
    cal_joints = (((snap.get("robots") or {}).get(robot) or {}).get("calibration") or {}).get("joints")
    live_body = manifold.body_for_calibration(cal_joints)

    tick_event = asyncio.Event()

    def _on_gateway_event(event: dict):
        if event.get("robot_id") == robot and event.get("t") == "imu":
            tick_event.set()

    gateway.subscribe_events(_on_gateway_event)
    walk_seq: int | None = None
    history = PoseObservationHistory()
    sample_idx = 0
    init_deg, prev_action = manifold.project_angles_deg(usable_joint_angles_deg(obs), body=live_body)
    stand_ref_deg, _ = manifold.project_angles_deg(STAND_ANGLES_DEG, body=live_body)
    cmd_q_rad = torch.tensor(init_deg, dtype=torch.float64, device=live_body.device).reshape(1, 12) * (
        math.pi / 180.0
    )
    hold_goal_deg, hold_goal_foot = list(init_deg), list(prev_action)
    hold_support = manifold.infer_leg_support(hold_goal_deg)

    async def _wait_next_tick(tick_started_at: float) -> None:
        target_next = tick_started_at + 0.020
        wait_s = target_next - gateway.clock()
        if wait_s <= 0.001:
            await asyncio.sleep(0.001)
            return
        try:
            await asyncio.wait_for(tick_event.wait(), timeout=wait_s)
        except asyncio.TimeoutError:
            return
        rem = target_next - gateway.clock()
        if rem > 0.002:
            await asyncio.sleep(rem)
        else:
            await asyncio.sleep(0)

    async def _arm_via_stand(connection) -> None:
        stand_seq = await gateway.queue_intent("stand", {}, robot_id=robot, **sequence_options)
        sequence_options.clear()
        stand_res = await gateway.wait_terminal(stand_seq, robot_id=robot, epoch=connection.epoch, timeout=15.0)
        job["receipts"].append(stand_res)
        bridge.record(job, "command_receipt", stand_res, sequence=stand_seq)

    async def _ensure_host_stream():
        nonlocal walk_seq, sample_idx, prev_action, cmd_q_rad
        connection = gateway._connection(robot)
        if walk_seq is not None and connection._owns_walk(walk_seq) and walk_seq in connection.pending:
            return connection
        if "walk_nominal_v1" not in connection.features:
            raise ValueError(f"Robot {robot} does not advertise walk_nominal_v1 for 50 Hz neural pose control")
        status_dict = getattr(connection, "last_status", None) or {}
        if bool(status_dict.get("output_fault")):
            await _arm_via_stand(connection)
            connection = gateway._connection(robot)
        history.reset()
        sample_idx = 0

        for attempt in range(2):
            cur_obs = gateway.body_sensor_observation(robot)
            cur_deg, prev_action = manifold.project_angles_deg(usable_joint_angles_deg(cur_obs), body=live_body)
            cmd_q_rad = torch.tensor(cur_deg, dtype=torch.float64, device=live_body.device).reshape(1, 12) * (
                math.pi / 180.0
            )
            cmd_q_rad, _ = live_body.pwm(cmd_q_rad)
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
                    if attempt == 0 and ack.get("code") in ("limit", "busy", "reference", "state"):
                        await _arm_via_stand(connection)
                        connection = gateway._connection(robot)
                        continue
                    raise RuntimeError("Body rejected host pose stream: " + str(ack))
            walk_seq = seq
            break
        # Immediately seed sample 1 at the robot's current projected posture so the P4 does not
        # jump toward `reference_cd` (`feet_mm == 0`) before the first closed-loop tick arrives.
        pts0, _ = live_body.forward(cmd_q_rad.reshape(1, 4, 3))
        init_feet_mm = (pts0 - live_body.origin.unsqueeze(0)).reshape(12).cpu().tolist()
        sample_idx = 1
        await connection.send_command(
            {
                "t": "walk_target",
                "walk": walk_seq,
                "sample": sample_idx,
                "geometry": manifold.geometry_id,
                "feet_mm": init_feet_mm,
            },
            received_at=gateway.clock(),
        )
        return connection

    async def _step_50hz(
        connection,
        goal_deg: list[float],
        goal_foot_norm: list[float],
        leg_support: list[float],
        speed_scale: float,
        *,
        now: float,
    ) -> dict:
        nonlocal sample_idx, prev_action, cmd_q_rad
        if bridge.active.get(robot) != job["id"]:
            raise RuntimeError("Neural pose job was superseded")
        if walk_seq is None or not connection._owns_walk(walk_seq) or walk_seq not in connection.pending:
            raise RuntimeError("Host 50 Hz pose stream lost ownership")

        sensor = gateway.body_sensor_observation(robot)
        joints_map = sensor["joints"]
        imu = sensor["imu"]
        tracked_cmd_deg = (cmd_q_rad[0] * (180.0 / math.pi)).cpu().tolist()
        measured_deg = [joints_map[j].get("filtered_model_deg") for j in JOINTS]
        commanded_deg = [
            (
                float(joints_map[j]["commanded_model_deg"])
                if isinstance(joints_map[j].get("commanded_model_deg"), (int, float))
                else tracked_cmd_deg[i]
            )
            for i, j in enumerate(JOINTS)
        ]
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
        t_obs = float(dev_us) / 1e6 if isinstance(dev_us, (int, float)) and dev_us > 0 else now
        obs_vec = history.push_and_project(t_obs, feat)
        act_list, _ = actor.infer_feet_mm(obs_vec)
        cmd_q_rad, prev_action, feet_mm = manifold.step_host_command(
            act_list, cmd_q_rad, speed_scale=speed_scale, body=live_body
        )

        sample_idx += 1
        await connection.send_command(
            {
                "t": "walk_target",
                "walk": walk_seq,
                "sample": sample_idx,
                "geometry": manifold.geometry_id,
                "feet_mm": feet_mm,
            },
            received_at=now,
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
                had_stream = walk_seq is not None
                connection = await _ensure_host_stream()
                if not had_stream:
                    before_sensor = gateway.body_sensor_observation(robot)
                t_start = gateway.clock()

                if kind == "pose_goal":
                    orig_seg_goal_deg = list(seg["goal_deg"])
                    goal_deg = list(orig_seg_goal_deg)
                    goal_foot = list(seg["goal_foot_norm"])
                    support = list(seg["leg_support"])
                    spd = seg["speed_scale"]
                    duration_s = seg["duration_s"]
                    live_start_deg = usable_joint_angles_deg(before_sensor)
                    bridge.record(
                        job,
                        "motion_prepared",
                        {
                            "action_index": idx,
                            "start": {j: live_start_deg[i] for i, j in enumerate(JOINTS)},
                            "target": {j: goal_deg[i] for i, j in enumerate(JOINTS)},
                            "control": "neural_pose_50hz",
                            "duration_s": duration_s,
                        },
                    )
                    settled_frames = 0
                    prev_usable_deg: dict[int, float] = {}
                    prev_cmd_deg: list[float] | None = None
                    is_terminal_motion = not any(s["kind"] != "face" for s in segments[seg_pos + 1 :])
                    is_stand_op = bool(
                        seg.get("is_stand")
                        or action.get("name") == "stand"
                        or max(abs(goal_deg[i] - stand_ref_deg[i]) for i in range(12)) <= 1.5
                    )
                    tight_terminal_stance = is_stand_op or (
                        is_terminal_motion and all(s >= 0.5 for s in support)
                    )
                    active_set = {i for i in range(12) if abs(goal_deg[i] - live_start_deg[i]) > 2.0}
                    max_live_delta = max((abs(goal_deg[i] - live_start_deg[i]) for i in range(12)), default=0.0)
                    large_excursion = bool(seg.get("from_nonstanding") or max_live_delta > 45.0)
                    host_slew_deg_s = 545.4545454545455 * max(0.25, min(1.0, float(spd)))
                    min_settle_s = max(
                        (0.85 if is_stand_op else (0.50 if tight_terminal_stance else 0.45))
                        if large_excursion
                        else (0.35 if is_stand_op else (0.24 if tight_terminal_stance else 0.18)),
                        max_live_delta / host_slew_deg_s
                        + (0.24 if (is_stand_op and large_excursion) else 0.08),
                    )
                    max_stance_tol = 5.0 if is_stand_op else (6.0 if tight_terminal_stance else 13.0)
                    mean_tol = 2.5 if is_stand_op else (3.5 if tight_terminal_stance else 7.0)
                    max_step_tol = 0.6 if tight_terminal_stance else 1.2
                    req_settled_frames = 4 if is_stand_op else (3 if tight_terminal_stance else 2)
                    max_settle_budget_s = max(duration_s + 2.2, 4.4) if tight_terminal_stance else duration_s

                    while True:
                        now = gateway.clock()
                        elapsed = now - t_start
                        tick_event.clear()
                        sensor_now = await _step_50hz(connection, goal_deg, goal_foot, support, spd, now=now)
                        cmd_deg_now = (cmd_q_rad[0] * (180.0 / math.pi)).cpu().tolist()
                        cmd_step_max = (
                            max(abs(cmd_deg_now[i] - prev_cmd_deg[i]) for i in range(12))
                            if prev_cmd_deg is not None
                            else 0.0
                        )
                        prev_cmd_deg = cmd_deg_now
                        curr_usable_deg: dict[int, float] = {}
                        usable_errs: list[float] = []
                        free_errs: list[float] = []
                        stance_errs: list[float] = []
                        shoulder_errs: list[float] = []
                        active_errs: list[float] = []
                        active_steps: list[float] = []
                        all_usable_steps: list[float] = []
                        for i, j in enumerate(JOINTS):
                            jd = sensor_now["joints"][j]
                            if jd.get("feedback_usable") and isinstance(jd.get("filtered_model_deg"), (int, float)):
                                val = float(jd["filtered_model_deg"])
                                curr_usable_deg[i] = val
                                err_i = abs(val - goal_deg[i])
                                usable_errs.append(err_i)
                                if i in prev_usable_deg:
                                    all_usable_steps.append(abs(val - prev_usable_deg[i]))
                                if i % 3 == 0:
                                    shoulder_errs.append(err_i)
                                if support[i // 3] < 0.5:
                                    free_errs.append(err_i)
                                else:
                                    stance_errs.append(err_i)
                                if not active_set or i in active_set:
                                    active_errs.append(err_i)
                                    if i in prev_usable_deg:
                                        active_steps.append(abs(val - prev_usable_deg[i]))
                        had_prev = bool(prev_usable_deg)
                        prev_usable_deg = curr_usable_deg
                        max_cmd_meas_gap = max(
                            (abs(cmd_deg_now[i] - val) for i, val in curr_usable_deg.items()),
                            default=0.0,
                        )
                        step_rates = all_usable_steps if tight_terminal_stance else active_steps
                        if elapsed >= min_settle_s and had_prev and len(usable_errs) >= 6:
                            ang_rate = (sensor_now.get("imu") or {}).get("angular_rate_rad_s")
                            gyro_ok = True
                            if (
                                isinstance(ang_rate, (list, tuple))
                                and len(ang_rate) == 3
                                and all(isinstance(v, (int, float)) for v in ang_rate)
                            ):
                                gyro_ok = math.sqrt(sum(float(v) * float(v) for v in ang_rate)) <= 0.44
                            tracked_errs = active_errs if active_errs else usable_errs
                            mean_err = sum(tracked_errs) / len(tracked_errs)
                            stand_cmd_ok = True
                            if is_stand_op:
                                stand_cmd_ok = (
                                    max(abs(cmd_deg_now[i] - goal_deg[i]) for i in range(12)) <= 5.0
                                    and max(abs(cmd_deg_now[i] - goal_deg[i]) for i in (0, 3, 6, 9)) <= 3.5
                                    and (not shoulder_errs or max(shoulder_errs) <= 3.5)
                                )
                            cmd_steady_ok = (not tight_terminal_stance) or (
                                cmd_step_max <= max_step_tol and max_cmd_meas_gap <= 4.5
                            )
                            settled_now = (
                                (not free_errs or max(free_errs) <= 5.5)
                                and (not stance_errs or max(stance_errs) <= max_stance_tol)
                                and mean_err <= mean_tol
                                and (not step_rates or max(step_rates) <= max_step_tol)
                                and stand_cmd_ok
                                and cmd_steady_ok
                                and gyro_ok
                            )
                            if settled_now:
                                settled_frames += 1
                                if settled_frames >= req_settled_frames:
                                    break
                            else:
                                settled_frames = 0
                        else:
                            settled_frames = 0
                        if elapsed >= duration_s:
                            # On grounded terminal / stand segments, never sever the stream while
                            # `NeuralPose` itself is still commanding a lifted/in-transit foot
                            # (`max_cmd_goal_err > 5.5 deg`) or an active step is planting.
                            max_cmd_goal_err = max(abs(cmd_deg_now[i] - goal_deg[i]) for i in range(12))
                            mid_step_active = tight_terminal_stance and (
                                max_cmd_goal_err > 5.5
                                or (
                                    max_cmd_meas_gap > 4.5
                                    and (
                                        cmd_step_max > 0.35
                                        or (bool(all_usable_steps) and max(all_usable_steps) > 0.35)
                                    )
                                )
                            )
                            effective_budget_s = (
                                max_settle_budget_s + 2.6 if mid_step_active else max_settle_budget_s
                            )
                            if (
                                not tight_terminal_stance
                                or (
                                    (not stance_errs or max(stance_errs) <= 5.5)
                                    and max_cmd_meas_gap <= 4.5
                                    and max_cmd_goal_err <= 5.5
                                )
                                or elapsed >= effective_budget_s
                            ):
                                break
                        await _wait_next_tick(now)
                    hold_goal_deg, hold_goal_foot, hold_support = goal_deg, goal_foot, support

                elif kind == "oscillate_goal":
                    osc_dur = seg["cycles"] / seg["hz"]
                    total_dur = seg["duration_s"]
                    end_deg = list(seg["end_deg"])
                    _, end_foot = manifold.project_angles_deg(end_deg, body=live_body)
                    support = list(seg["leg_support"])
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
                        now = gateway.clock()
                        elapsed = now - t_start
                        tick_event.clear()
                        if elapsed < osc_dur:
                            cand = list(seg["base_deg"])
                            phase = 2.0 * math.pi * seg["hz"] * elapsed
                            for j_idx, c_deg, a_deg in zip(
                                seg["joint_indices"], seg["centers_deg"], seg["amplitudes_deg"]
                            ):
                                cand[j_idx] = c_deg + a_deg * math.sin(phase)
                            g_deg, g_foot = manifold.project_angles_deg(cand, body=live_body)
                        else:
                            g_deg, g_foot = end_deg, end_foot
                        sensor_now = await _step_50hz(connection, g_deg, g_foot, support, spd, now=now)
                        if elapsed >= total_dur:
                            break
                        await _wait_next_tick(now)
                    hold_goal_deg, hold_goal_foot, hold_support = end_deg, end_foot, support

                elif kind == "hold":
                    hold_dur = max(0.02, float(seg["seconds"]))
                    while True:
                        now = gateway.clock()
                        elapsed = now - t_start
                        tick_event.clear()
                        await _step_50hz(
                            connection, hold_goal_deg, hold_goal_foot, hold_support, 0.5, now=now
                        )
                        if elapsed >= hold_dur:
                            break
                        await _wait_next_tick(now)

            elif kind == "gait":
                from ..program import gait_intents

                walk_seq = None
                for intent in gait_intents(args):
                    seq = await gateway.queue_intent("walk", intent, robot_id=robot, **sequence_options)
                    sequence_options.clear()
                    await bridge._receipt(job, seq, obs["epoch"])
                hold_goal_deg, hold_goal_foot = manifold.project_angles_deg(
                    usable_joint_angles_deg(gateway.body_sensor_observation(robot)), body=live_body
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
                @asynccontextmanager
                async def _mark_err_hold(seq: int):
                    job["neural_pose_hold_seq"] = seq
                    yield

                try:
                    await gateway.estop(robot_id=robot, detach=False, on_sequence=_mark_err_hold)
                except Exception:
                    pass
        raise
    finally:
        gateway.unsubscribe_events(_on_gateway_event)
