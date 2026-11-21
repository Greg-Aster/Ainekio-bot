"""50 Hz Neural-Pose Talking Presence controller for Ainekio V2.

Replaces the legacy System 3 Presence controller so `NeuralPose` is the sole
closed-loop posture/expression owner alongside walking locomotion:
- Dormant when idle and 100% motor-silent during microphone listening, never
  sending `stop` during `vad_open` (so ESP32-P4 firmware owns the `listening`
  OLED face, `listen_frame`, and active mic utterance uninterrupted).
- Activates ONLY when the robot is actively speaking (`gateway.speech_activity`),
  standing upright, armed, unstalled, and no external motion (Freestyle, emote,
  walking, manual command, or calibration) is active.
- Yields immediately (<1 ms) on any incoming walk, emote, Freestyle, Stop,
  listening, or stall event — never fighting or cancelling active motions.
- Modulates pure sagittal pitch/height nods (0.0 deg shoulder scrub) through
  the active `NeuralPoseActor` (`policy.onnx`), settling cleanly back to
  canonical Stand before locking `stop(detach=False)`.
"""
from __future__ import annotations

import asyncio
from contextvars import ContextVar
from dataclasses import dataclass, field
import math
from typing import Any, Callable
from uuid import uuid4

import torch

from .contract import JOINTS, PoseObservationHistory, assemble_pose_features
from .executor import NeuralPoseRuntime
from .goals import STAND_ANGLES_DEG, usable_joint_angles_deg

NEURAL_POSE_PRESENCE_OWNER: ContextVar[bool] = ContextVar("neural_pose_presence_owner", default=False)

PRESENCE_TICK_S = 0.020  # 50 Hz closed-loop matching NeuralPoseActor training cadence
SETTLE_AFTER_EXTERNAL_S = 0.65

PRESENCE_DEFAULTS: dict[str, Any] = {
    "enabled": True,
    "expressions_enabled": True,
}


def validate_presence_settings(raw: dict[str, Any] | None) -> dict[str, Any]:
    out = dict(PRESENCE_DEFAULTS)
    if not isinstance(raw, dict):
        return out
    for key in ("enabled", "expressions_enabled"):
        if key in raw:
            out[key] = bool(raw[key])
    return out


def _imu_upright_ok(imu: dict[str, Any] | None) -> bool:
    """True when IMU reports the chassis is upright (<= 28 deg roll/pitch), or IMU unavailable."""
    q = (imu or {}).get("orientation_wxyz")
    if not isinstance(q, (list, tuple)) or len(q) != 4:
        return True
    try:
        w, x, y, z = (float(v) for v in q)
    except (TypeError, ValueError):
        return True
    roll_deg = abs(math.degrees(math.atan2(2.0 * (w * x + y * z), 1.0 - 2.0 * (x * x + y * y))))
    pitch_deg = abs(math.degrees(math.asin(max(-1.0, min(1.0, 2.0 * (w * y - z * x))))))
    return roll_deg <= 28.0 and pitch_deg <= 28.0


def _standing_posture_ok(measured_deg: list[float], imu: dict[str, Any] | None = None) -> bool:
    """True when the robot is upright near Stand (never moves legs from Sit/Prone/Dead/Tipped)."""
    if not _imu_upright_ok(imu):
        return False
    max_stand_diff = max(abs(measured_deg[i] - STAND_ANGLES_DEG[i]) for i in range(12))
    prone_legs = sum(1 for leg in range(4) if measured_deg[3 * leg + 2] > 5.0)
    return max_stand_diff <= 26.0 and prone_legs == 0


def build_sagittal_nod_basis(manifold, live_body) -> tuple[list[float], list[float], list[float]]:
    """Precompute Stand and talking nod up/down poses (all 0 deg shoulders)."""
    stand_deg, _ = manifold.project_angles_deg(STAND_ANGLES_DEG, body=live_body)
    up_raw = manifold.resolve_spatial_deg(
        {"name": "body", "arguments": {"translation_mm": [0.0, 0.0, 2.5], "rotation_deg": [0.0, -4.5, 0.0]}},
        list(STAND_ANGLES_DEG),
    )
    down_raw = manifold.resolve_spatial_deg(
        {"name": "body", "arguments": {"translation_mm": [0.0, 0.0, -2.5], "rotation_deg": [0.0, 4.5, 0.0]}},
        list(STAND_ANGLES_DEG),
    )
    up_deg, _ = manifold.project_angles_deg(up_raw, body=live_body)
    down_deg, _ = manifold.project_angles_deg(down_raw, body=live_body)
    # Enforce exact 0.0 deg shoulders so talking nods never introduce lateral carpet scrub
    for pose in (up_deg, down_deg):
        for sh_idx in (0, 3, 6, 9):
            pose[sh_idx] = 0.0
    return stand_deg, up_deg, down_deg


def speech_presence_goal_deg(
    stand_deg: list[float],
    up_deg: list[float],
    down_deg: list[float],
    *,
    phase_rad: float,
    speech_rms: float,
) -> list[float]:
    """Compute a pure sagittal talking nod goal driven by live speech RMS."""
    amp = max(0.25, min(1.0, 0.25 + 0.95 * max(0.0, float(speech_rms))))
    wave = math.sin(phase_rad) * amp
    if wave >= 0.0:
        return [s + wave * (u - s) for s, u in zip(stand_deg, up_deg)]
    w = -wave
    return [s + w * (d - s) for s, d in zip(stand_deg, down_deg)]


@dataclass
class _RobotTalkingState:
    robot_id: str
    mode: str = "standby"  # standby | speaking | settling | yielded | disabled | stalled
    walk_seq: int | None = None
    sample_idx: int = 0
    owned_sequences: set[int] = field(default_factory=set)
    face_token: str = field(default_factory=lambda: "pr_" + uuid4().hex[:24])
    active_expression: str | None = None
    foreground_face_owned: bool = False
    last_expression_at: float = -1e9
    last_external_motion_at: float = -1e9
    manual_stopped: bool = False
    stalled_released: bool = False
    vad_listening_until: float = 0.0
    speech_phase_rad: float = 0.0
    last_speech_rms: float = 0.0
    last_error: str | None = None
    history: PoseObservationHistory = field(default_factory=PoseObservationHistory)
    cmd_q_rad: torch.Tensor | None = None
    prev_action: list[float] | None = None
    settling_since: float | None = None
    settled_frames: int = 0
    prev_usable_deg: dict[int, float] = field(default_factory=dict)
    prev_cmd_deg: list[float] | None = None
    basis_key: tuple[int, ...] | None = None
    basis_poses: tuple[list[float], list[float], list[float]] | None = None


class NeuralPosePresence:
    """50 Hz Neural-Pose talking presence with strict external-motion mutual exclusion."""

    def __init__(
        self,
        gateway,
        *,
        runtime: NeuralPoseRuntime | None = None,
        initial_settings: dict[str, dict[str, Any]] | None = None,
        freestyle_active_fn: Callable[[str], bool] | None = None,
        stop_latched_fn: Callable[[], bool] | None = None,
    ):
        self.gateway = gateway
        self.runtime = runtime if runtime is not None else NeuralPoseRuntime()
        self.freestyle_active_fn = freestyle_active_fn or (lambda _r: False)
        self.stop_latched_fn = stop_latched_fn or (lambda: False)
        self._settings: dict[str, dict[str, Any]] = {
            rid: validate_presence_settings(cfg)
            for rid, cfg in (initial_settings or {}).items()
            if isinstance(rid, str)
        }
        self._states: dict[str, _RobotTalkingState] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._wake_events: dict[str, asyncio.Event] = {}
        self._closed = False
        self.gateway.subscribe_commands(self._on_command)
        self.gateway.subscribe_events(self._on_event)
        try:
            asyncio.get_running_loop()
            for rid in tuple(getattr(self.gateway, "_connections", {})):
                self._ensure_robot_task(rid)
        except RuntimeError:
            pass

    def settings_for(self, robot_id: str) -> dict[str, Any]:
        return dict(self._settings.get(robot_id, PRESENCE_DEFAULTS))

    def configure(self, robot_id: str, raw: dict[str, Any] | None) -> dict[str, Any]:
        validated = validate_presence_settings(raw)
        self._settings[robot_id] = validated
        st = self._states.get(robot_id)
        if st is not None and not validated["enabled"]:
            st.mode = "disabled"
        wake = self._wake_events.get(robot_id)
        if wake is not None:
            wake.set()
        return dict(validated)

    def _state(self, robot_id: str) -> _RobotTalkingState:
        st = self._states.get(robot_id)
        if st is None:
            st = _RobotTalkingState(robot_id=robot_id)
            self._states[robot_id] = st
        return st

    def _reset_stream_state(self, st: _RobotTalkingState) -> None:
        st.walk_seq = None
        st.sample_idx = 0
        st.history.reset()
        st.cmd_q_rad = None
        st.prev_action = None
        st.settling_since = None
        st.settled_frames = 0
        st.prev_usable_deg.clear()
        st.prev_cmd_deg = None

    def _ensure_robot_task(self, robot_id: str) -> None:
        if self._closed:
            return
        task = self._tasks.get(robot_id)
        if task is not None and not task.done():
            return
        wake = self._wake_events.setdefault(robot_id, asyncio.Event())
        self._tasks[robot_id] = asyncio.create_task(
            self._robot_loop(robot_id, wake),
            name=f"neural-pose-presence-{robot_id}",
        )

    def status(self) -> dict[str, Any]:
        robot_ids = sorted(
            set(self._settings) | set(self._states) | set(getattr(self.gateway, "_connections", {}))
        )
        policy_path = self.runtime._cached_key[0] if self.runtime._cached_key else None
        robots: dict[str, Any] = {}
        for rid in robot_ids:
            st = self._states.get(rid)
            robots[rid] = {
                "settings": self.settings_for(rid),
                "mode": st.mode if st is not None else "standby",
                "active_expression": st.active_expression if st is not None else None,
                "speech_rms": round(st.last_speech_rms, 3) if st is not None else 0.0,
                "stalled_released": bool(st.stalled_released) if st is not None else False,
                "last_error": st.last_error if st is not None else None,
            }
        return {
            "defaults": dict(PRESENCE_DEFAULTS),
            "policy_loaded": self.runtime._actor is not None,
            "policy_path": policy_path,
            "robots": robots,
        }

    async def _send_owned(self, coro, st: _RobotTalkingState):
        token = NEURAL_POSE_PRESENCE_OWNER.set(True)
        try:
            res = await coro
        finally:
            NEURAL_POSE_PRESENCE_OWNER.reset(token)
        if isinstance(res, int):
            st.owned_sequences.add(res)
            if len(st.owned_sequences) > 96:
                st.owned_sequences = set(sorted(st.owned_sequences)[-64:])
        return res

    async def _on_command(self, message: dict[str, Any]) -> None:
        if NEURAL_POSE_PRESENCE_OWNER.get():
            return
        robot_id = message.get("robot_id")
        if not isinstance(robot_id, str) or not robot_id:
            return
        st = self._state(robot_id)
        seq = message.get("seq")
        if isinstance(seq, int) and seq in st.owned_sequences:
            return
        cmd_t = message.get("t")
        cmd_name = message.get("name")
        is_stop = cmd_t == "stop"
        is_external_motion = (
            cmd_t in {"motion_plan", "servo", "mode", "state"}
            or (cmd_t == "calibration" and message.get("op") != "get")
            or (cmd_t == "intent" and cmd_name not in {"face", "say"})
        )
        if not (is_stop or is_external_motion):
            if cmd_t == "tts" or (cmd_t == "intent" and cmd_name == "say"):
                wake = self._wake_events.get(robot_id)
                if wake is not None:
                    wake.set()
            return
        now = self.gateway.clock()
        st.last_external_motion_at = now
        if is_stop:
            if message.get("detach"):
                st.manual_stopped = True
            else:
                st.manual_stopped = False
        else:
            # Explicit new external motion/stand clears prior manual stop or stall latch
            st.manual_stopped = False
            st.stalled_released = False
        # Drop our walk_seq immediately WITHOUT sending a conflicting `stop` so the incoming
        # walk/emote/Freestyle command keeps clean ownership on ESP32-P4.
        self._reset_stream_state(st)
        st.mode = "yielded"
        connection = self.gateway._connections.get(robot_id)
        if connection is not None and st.foreground_face_owned:
            await self._release_foreground_face(robot_id, connection, st)
        wake = self._wake_events.get(robot_id)
        if wake is not None:
            wake.set()

    async def _on_event(self, event: dict[str, Any]) -> None:
        robot_id = event.get("robot_id")
        if not isinstance(robot_id, str) or not robot_id:
            return
        ev_t = event.get("t")
        if ev_t == "connection":
            status = event.get("status")
            if status == "connected":
                st = self._state(robot_id)
                self._reset_stream_state(st)
                st.manual_stopped = False
                st.stalled_released = False
                st.vad_listening_until = 0.0
                st.mode = "standby"
                self._ensure_robot_task(robot_id)
            elif status == "disconnected":
                task = self._tasks.pop(robot_id, None)
                if task is not None:
                    task.cancel()
                st = self._states.get(robot_id)
                if st is not None:
                    self._reset_stream_state(st)
                    st.mode = "standby"
            return

        if ev_t == "imu":
            # Wake our 50 Hz tick loop on fresh IMU frames while speaking or settling
            st = self._states.get(robot_id)
            if st is not None and st.mode in ("speaking", "settling"):
                wake = self._wake_events.get(robot_id)
                if wake is not None:
                    wake.set()
            return

        if ev_t == "event":
            ev_name = event.get("name")
            data = event.get("data") or {}
            kind = data.get("kind") if ev_name == "body_event" else ev_name
            st = self._state(robot_id)
            now = self.gateway.clock()
            if kind in ("wake_word", "vad_open"):
                st.vad_listening_until = max(st.vad_listening_until, now + 15.0)
            elif kind == "vad_close":
                st.vad_listening_until = 0.0
            elif kind == "servo_stall":
                if data.get("outputs_released"):
                    st.stalled_released = True
                    connection = self.gateway._connections.get(robot_id)
                    if connection is not None and st.walk_seq is not None:
                        await self._close_walk_stream(robot_id, connection, st)
                    self._reset_stream_state(st)
                    st.mode = "stalled"
            wake = self._wake_events.get(robot_id)
            if wake is not None:
                wake.set()

    def _motion_conflict(self, robot_id: str, connection, st: _RobotTalkingState, now: float) -> bool:
        """Return True if ANY walk, emote, Freestyle job, manual command, or fault owns the body."""
        if self.stop_latched_fn() or st.manual_stopped or st.stalled_released:
            return True
        if connection.mode != "normal":
            return True
        if connection.neural_walk is not None:
            return True
        if self.freestyle_active_fn(robot_id):
            return True
        if now - st.last_external_motion_at < SETTLE_AFTER_EXTERNAL_S:
            return True
        for seq, pending in connection.pending.items():
            if seq == st.walk_seq or seq in st.owned_sequences or pending.future.done():
                continue
            cmd = pending.command
            ct = cmd.get("t")
            cn = cmd.get("name")
            if ct in {"motion_plan", "servo", "mode", "state"} or (
                ct == "calibration" and cmd.get("op") != "get"
            ) or (
                ct == "intent" and cn not in {"face", "say"}
            ):
                return True
        return False

    async def _set_face(self, robot_id: str, connection, st: _RobotTalkingState, expr: str, now: float) -> None:
        cfg = self.settings_for(robot_id)
        if not cfg["expressions_enabled"]:
            return
        if "face_feedback_v1" not in connection.features:
            return
        caps = connection.capabilities or {}
        if connection.model != "v1-8servo" and caps.get("display") is not True:
            return
        imu = (connection.last_status or {}).get("imu") or {}
        fg_token = str(imu.get("face_token") or "")
        # Never overwrite an active Freestyle, body-event, or MetaHuman foreground face
        if fg_token and not fg_token.startswith("pr_"):
            return
        if expr == st.active_expression and st.foreground_face_owned and now - st.last_expression_at < 8.0:
            return
        if expr != st.active_expression and now - st.last_expression_at < 0.8:
            return
        try:
            await self._send_owned(
                self.gateway.queue_intent(
                    "face",
                    {
                        "expr": expr,
                        "token": st.face_token,
                        "background": False,
                        "timeout_ms": 15000,
                    },
                    robot_id=robot_id,
                ),
                st,
            )
            st.active_expression = expr
            st.foreground_face_owned = True
            st.last_expression_at = now
        except Exception:
            pass

    async def _release_foreground_face(self, robot_id: str, connection, st: _RobotTalkingState) -> None:
        if not st.foreground_face_owned:
            return
        st.foreground_face_owned = False
        st.active_expression = None
        if "face_feedback_v1" not in connection.features:
            return
        try:
            await self._send_owned(
                self.gateway.queue_intent(
                    "face",
                    {"expr": "default", "token": st.face_token, "release": True},
                    robot_id=robot_id,
                ),
                st,
            )
        except Exception:
            pass

    async def _close_walk_stream(self, robot_id: str, connection, st: _RobotTalkingState, *, release_face: bool = True) -> None:
        seq = st.walk_seq
        self._reset_stream_state(st)
        if seq is not None and connection._owns_walk(seq):
            try:
                await self._send_owned(
                    self.gateway.estop(robot_id=robot_id, detach=False),
                    st,
                )
            except Exception:
                pass
        if release_face:
            await self._release_foreground_face(robot_id, connection, st)

    async def _ensure_walk_stream(
        self,
        robot_id: str,
        connection,
        st: _RobotTalkingState,
        manifold,
        live_body,
        now: float,
    ) -> bool:
        if st.walk_seq is not None and connection._owns_walk(st.walk_seq) and st.walk_seq in connection.pending:
            return True
        if "walk_nominal_v1" not in connection.features:
            return False
        status_dict = connection.last_status or {}
        if "output_armed" in status_dict:
            if not status_dict.get("output_armed") or connection.last_calibration is None:
                return False
        try:
            seq = await self._send_owned(
                self.gateway.queue_intent(
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
                    robot_id=robot_id,
                ),
                st,
            )
            pending = connection.pending.get(seq)
            if pending is not None:
                ack = await asyncio.wait_for(asyncio.shield(pending.acknowledgement), timeout=1.0)
                if ack.get("t") != "ack":
                    return False
            st.walk_seq = seq
            st.sample_idx = 0
            return True
        except Exception as err:
            st.last_error = str(err)
            self._reset_stream_state(st)
            return False

    def _get_basis(self, st: _RobotTalkingState, manifold, live_body, cal_joints):
        key = tuple(int(j.get("home_us", 0)) for j in (cal_joints or ()))
        if st.basis_key != key or st.basis_poses is None:
            st.basis_poses = build_sagittal_nod_basis(manifold, live_body)
            st.basis_key = key
        return st.basis_poses

    async def _step_neural_pose(
        self,
        connection,
        st: _RobotTalkingState,
        actor,
        manifold,
        live_body,
        sensor: dict[str, Any],
        goal_deg: list[float],
        now: float,
        *,
        speed_scale: float = 0.55,
    ) -> list[float]:
        """Run one 50 Hz closed-loop NeuralPoseActor inference and stream `walk_target`."""
        imu = sensor.get("imu") or {}
        joints_map = sensor.get("joints") or {}
        usable_flags = [bool(joints_map[j].get("feedback_usable", False)) for j in JOINTS]
        measured_deg = usable_joint_angles_deg(sensor)
        if st.cmd_q_rad is None or st.prev_action is None:
            init_deg, init_act = manifold.project_angles_deg(measured_deg, body=live_body)
            st.cmd_q_rad = torch.tensor(init_deg, dtype=torch.float64, device=live_body.device).reshape(1, 12) * (
                math.pi / 180.0
            )
            st.prev_action = list(init_act)
        cmd_deg_list = (st.cmd_q_rad[0] * (180.0 / math.pi)).detach().cpu().tolist()
        commanded_deg = [
            float(joints_map[j]["commanded_model_deg"])
            if isinstance(joints_map[j].get("commanded_model_deg"), (int, float))
            else float(cmd_deg_list[i])
            for i, j in enumerate(JOINTS)
        ]
        velocity_deg_s = [float(joints_map[j].get("velocity_deg_s") or 0.0) for j in JOINTS]
        _, goal_foot_norm = manifold.project_angles_deg(goal_deg, body=live_body)

        feat = assemble_pose_features(
            measured_deg=measured_deg,
            commanded_deg=commanded_deg,
            velocity_deg_s=velocity_deg_s,
            usable_flags=usable_flags,
            orientation_wxyz=imu.get("orientation_wxyz") or [1.0, 0.0, 0.0, 0.0],
            angular_rate_rad_s=imu.get("angular_rate_rad_s") or [0.0, 0.0, 0.0],
            acceleration_m_s2=imu.get("acceleration_m_s2") or [0.0, 0.0, 9.81],
            goal_joint_deg=goal_deg,
            goal_foot_norm=goal_foot_norm,
            leg_support=[1.0, 1.0, 1.0, 1.0],
            speed_scale=speed_scale,
            previous_action=st.prev_action,
        )
        dev_us = (sensor.get("feedback") or {}).get("device_us")
        t_obs = float(dev_us) / 1e6 if isinstance(dev_us, (int, float)) and dev_us > 0 else now
        obs_vec = st.history.push_and_project(t_obs, feat)
        act_list, _ = actor.infer_feet_mm(obs_vec)
        st.cmd_q_rad, st.prev_action, feet_mm = manifold.step_host_command(
            act_list,
            st.cmd_q_rad,
            speed_scale=speed_scale,
            body=live_body,
        )
        st.sample_idx += 1
        await self._send_owned(
            connection.send_command(
                {
                    "t": "walk_target",
                    "walk": st.walk_seq,
                    "sample": st.sample_idx,
                    "geometry": manifold.geometry_id,
                    "feet_mm": feet_mm,
                },
                received_at=now,
            ),
            st,
        )
        return (st.cmd_q_rad[0] * (180.0 / math.pi)).detach().cpu().tolist()

    def _stand_settled(self, sensor: dict[str, Any], st: _RobotTalkingState, stand_deg: list[float], cmd_deg: list[float], elapsed_s: float) -> bool:
        """Verify physical arrival at canonical Stand (never stop mid-step or with a bound shoulder)."""
        joints_map = sensor.get("joints") or {}
        cmd_step_max = (
            max(abs(cmd_deg[i] - st.prev_cmd_deg[i]) for i in range(12))
            if st.prev_cmd_deg is not None
            else 0.0
        )
        st.prev_cmd_deg = list(cmd_deg)
        usable_errs: list[float] = []
        shoulder_errs: list[float] = []
        all_steps: list[float] = []
        cmd_meas_gaps: list[float] = []
        for i, j in enumerate(JOINTS):
            jd = joints_map.get(j) or {}
            if jd.get("feedback_usable") and isinstance(jd.get("filtered_model_deg"), (int, float)):
                val = float(jd["filtered_model_deg"])
                err = abs(val - stand_deg[i])
                usable_errs.append(err)
                cmd_meas_gaps.append(abs(cmd_deg[i] - val))
                if i % 3 == 0:
                    shoulder_errs.append(err)
                if i in st.prev_usable_deg:
                    all_steps.append(abs(val - st.prev_usable_deg[i]))
                st.prev_usable_deg[i] = val

        max_gap = max(cmd_meas_gaps) if cmd_meas_gaps else 0.0
        max_step = max(all_steps) if all_steps else 0.0
        max_sh_err = max(shoulder_errs) if shoulder_errs else 0.0
        mean_err = (sum(usable_errs) / len(usable_errs)) if usable_errs else 0.0
        max_err = max(usable_errs) if usable_errs else 0.0

        if elapsed_s >= 0.30 and max_err <= 5.0 and mean_err <= 2.5 and max_sh_err <= 5.0 and max_step <= 0.6 and max_gap <= 4.5:
            st.settled_frames += 1
        else:
            st.settled_frames = 0
        if st.settled_frames >= 4:
            return True
        mid_step_active = max_gap > 4.5 and (max_step > 0.35 or cmd_step_max > 0.35)
        budget_s = 6.6 if mid_step_active else 4.4
        return elapsed_s >= budget_s

    async def _robot_loop(self, robot_id: str, wake_event: asyncio.Event) -> None:
        while not self._closed:
            t_tick = self.gateway.clock()
            wake_event.clear()
            connection = self.gateway._connections.get(robot_id)
            if connection is None or connection.websocket.closed:
                return

            st = self._state(robot_id)
            cfg = self.settings_for(robot_id)

            if not cfg["enabled"]:
                if st.walk_seq is not None or st.foreground_face_owned:
                    await self._close_walk_stream(robot_id, connection, st)
                st.mode = "disabled"
                await self._sleep_next(t_tick, wake_event, idle=True)
                continue

            # 1. Strict mutual exclusion: never conflict with Freestyle, emotes, walking, manual cmds, or stalls
            if self._motion_conflict(robot_id, connection, st, t_tick):
                if st.walk_seq is not None:
                    # Only send `stop` if Freestyle is queued (no competing command on P4 yet);
                    # if another walk/emote already took over, `_on_command` already dropped `walk_seq`.
                    await self._close_walk_stream(robot_id, connection, st)
                elif st.foreground_face_owned:
                    await self._release_foreground_face(robot_id, connection, st)
                st.mode = "stalled" if st.stalled_released else "yielded"
                await self._sleep_next(t_tick, wake_event, idle=True)
                continue

            # 2. Check speaking vs listening (robot is never listening while speaking)
            speaking_fn = getattr(self.gateway, "speech_activity", None)
            if callable(speaking_fn):
                speaking_active, speech_rms = speaking_fn(robot_id)
            else:
                speaking_active = self.gateway.external_speech_active(robot_id)
                speech_rms = 0.55 if speaking_active else 0.0
            st.last_speech_rms = float(speech_rms) if speaking_active else 0.0
            if speaking_active:
                st.vad_listening_until = 0.0

            audio_in = connection.audio_input or {}
            vad_open = t_tick < st.vad_listening_until
            listening_active = (
                not speaking_active
                and bool(
                    vad_open
                    or audio_in.get("utterance_open")
                    or (connection.last_status or {}).get("listening_feedback")
                )
            )

            # 3. During listening: stay completely motor-silent and NEVER send `stop`
            # (ESP32-P4 `AINEKIO_COMMAND_STOP` cancels audio and forces `vad_close`).
            # Firmware owns the `listening` OLED face (`display.c`) and `listen_frame` (`body.c`).
            if listening_active:
                if st.walk_seq is not None:
                    # Drop any lingering post-speech walk stream without sending `stop`
                    self._reset_stream_state(st)
                if st.foreground_face_owned:
                    await self._release_foreground_face(robot_id, connection, st)
                st.mode = "listening"
                await self._sleep_next(t_tick, wake_event, idle=True)
                continue

            # 4. Stay completely dormant when idle (not speaking and not returning to Stand)
            if not speaking_active and st.walk_seq is None:
                if st.foreground_face_owned:
                    await self._release_foreground_face(robot_id, connection, st)
                st.mode = "standby"
                await self._sleep_next(t_tick, wake_event, idle=True)
                continue

            # 5. Read live sensors & verify armed/unstalled hardware
            sensor = self.gateway.body_sensor_observation(robot_id)
            if sensor is None:
                st.mode = "standby"
                await self._sleep_next(t_tick, wake_event, idle=True)
                continue
            fb_meta = sensor.get("feedback") or {}
            cmd_mask = fb_meta.get("commanded_mask")
            stalled_mask = int(fb_meta.get("stalled_joints") or 0)
            if stalled_mask != 0 or (isinstance(cmd_mask, int) and 0 < cmd_mask < 4095):
                st.stalled_released = True
                if st.walk_seq is not None:
                    await self._close_walk_stream(robot_id, connection, st)
                st.mode = "stalled"
                await self._sleep_next(t_tick, wake_event, idle=True)
                continue

            # Never move legs from Sit/Prone/Dead/Tipped; show face only
            measured_deg = usable_joint_angles_deg(sensor)
            if st.walk_seq is None and not _standing_posture_ok(measured_deg, sensor.get("imu")):
                if speaking_active:
                    await self._set_face(robot_id, connection, st, "talk_happy", t_tick)
                st.mode = "standby"
                await self._sleep_next(t_tick, wake_event, idle=True)
                continue

            loaded = (
                (self.runtime._actor, self.runtime._manifold)
                if (self.runtime._actor is not None and self.runtime._manifold is not None)
                else await asyncio.to_thread(self.runtime.load)
            )
            if loaded is None:
                if speaking_active:
                    await self._set_face(robot_id, connection, st, "talk_happy", t_tick)
                st.mode = "standby"
                await self._sleep_next(t_tick, wake_event, idle=True)
                continue
            actor, manifold = loaded
            cal_joints = (connection.last_calibration or {}).get("joints")
            live_body = manifold.body_for_calibration(cal_joints)
            stand_deg, up_deg, down_deg = self._get_basis(st, manifold, live_body, cal_joints)

            if not await self._ensure_walk_stream(robot_id, connection, st, manifold, live_body, t_tick):
                st.mode = "standby"
                await self._sleep_next(t_tick, wake_event, idle=True)
                continue

            # 6. Stream 50 Hz NeuralPose: talking nods while speaking, or clean return to canonical Stand
            if speaking_active:
                st.mode = "speaking"
                st.settling_since = None
                st.settled_frames = 0
                st.speech_phase_rad += PRESENCE_TICK_S * 3.8
                goal_deg = speech_presence_goal_deg(
                    stand_deg,
                    up_deg,
                    down_deg,
                    phase_rad=st.speech_phase_rad,
                    speech_rms=speech_rms,
                )
                try:
                    await self._step_neural_pose(
                        connection, st, actor, manifold, live_body, sensor, goal_deg, t_tick
                    )
                except Exception as err:
                    st.last_error = str(err)
                    await self._close_walk_stream(robot_id, connection, st)
                    st.mode = "standby"
                    await self._sleep_next(t_tick, wake_event, idle=True)
                    continue
                await self._set_face(robot_id, connection, st, "talk_happy", t_tick)
            else:
                st.mode = "settling"
                if st.settling_since is None:
                    st.settling_since = t_tick
                try:
                    cmd_deg = await self._step_neural_pose(
                        connection, st, actor, manifold, live_body, sensor, stand_deg, t_tick
                    )
                except Exception as err:
                    st.last_error = str(err)
                    await self._close_walk_stream(robot_id, connection, st)
                    st.mode = "standby"
                    await self._sleep_next(t_tick, wake_event, idle=True)
                    continue
                elapsed = t_tick - st.settling_since
                if self._stand_settled(sensor, st, stand_deg, cmd_deg, elapsed):
                    await self._close_walk_stream(robot_id, connection, st, release_face=True)
                    st.mode = "standby"

            await self._sleep_next(t_tick, wake_event, idle=False)

    async def _sleep_next(self, started_at: float, wake_event: asyncio.Event, *, idle: bool) -> None:
        interval = 0.050 if idle else PRESENCE_TICK_S
        rem = (started_at + interval) - self.gateway.clock()
        if rem <= 0.002:
            await asyncio.sleep(0.002)
            return
        try:
            await asyncio.wait_for(wake_event.wait(), timeout=rem)
        except asyncio.TimeoutError:
            return
        left = (started_at + interval) - self.gateway.clock()
        if left > 0.002:
            await asyncio.sleep(left)

    async def close(self) -> None:
        self._closed = True
        self.gateway.unsubscribe_commands(self._on_command)
        self.gateway.unsubscribe_events(self._on_event)
        tasks = list(self._tasks.values())
        self._tasks.clear()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
