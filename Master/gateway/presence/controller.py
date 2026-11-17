"""20 Hz Host Controller for System 3 (Conversational Speech Presence, Gaze & Hardware Rest/Self-Righting).

Arbitrates cleanly with System 1 (Locomotion) and System 2 (Freestyle / Motion Library):
- Drives subtle 20 Hz foot/posture accompaniment ONLY while the robot is speaking (`speech_activity`),
  staying completely silent while listening (so servo noise never holds P4's mic VAD gate open, letting
  P4's built-in quiet `listen_frame` shoulder perk & listening face run undisturbed) and dormant when idle.
- Yields on the immediate command callback (<1 ms) whenever any external motion or Stop arrives.
- Uses live TTS speech RMS envelope + optional YOLOE speaker gaze & 4th-wire compliance.
- Releases servos into rest pose after configurable quiet inactivity (`servo_release_s`), and optionally handles
  pickup/tip passive safety when `self_right_enabled` is enabled.
"""
from __future__ import annotations

import asyncio
from contextvars import ContextVar
from dataclasses import dataclass, field
import math
from typing import Any, Callable
from uuid import uuid4

import numpy as np
import torch

from .actor import PresenceRuntime, resolve_active_presence_policy
from .contract import (
    CALM_PASSIVE_DEG,
    DEFAULTS,
    JOINTS,
    PRESENCE_INTERVAL_S,
    REST_ANGLES_DEG,
    STAND_ANGLES_DEG,
    PresenceObservationHistory,
    SympatheticMotionMonitor,
    assemble_presence_features,
    presence_model_footprint,
    tilt_roll_pitch_deg_from_wxyz,
    update_compliance_trim_mm,
    validate_presence_settings,
)

PRESENCE_OWNER: ContextVar[bool] = ContextVar("presence_owner", default=False)
POSE_SCALE_VEC = np.array((95.0, 155.0, 180.0) * 4, dtype=np.float64)


@dataclass
class RobotPresenceState:
    robot_id: str = ""
    mode: str = "standby"  # standby | active | self_righting | passive | resting_released | yielded | disabled | stopped
    passive_reason: str | None = None
    walk_seq: int | None = None
    sample_idx: int = 0
    owned_sequences: set[int] = field(default_factory=set)
    history: PresenceObservationHistory = field(default_factory=PresenceObservationHistory)
    sympathy: SympatheticMotionMonitor = field(default_factory=SympatheticMotionMonitor)
    prev_foot_norm: list[float] = field(default_factory=lambda: [0.0] * 12)
    compliance_trim_mm: list[float] = field(default_factory=lambda: [0.0] * 12)
    chatter_deg: list[float] = field(default_factory=lambda: [0.0] * 12)
    prev_meas_deg: list[float] | None = None
    prev_cmd_deg: list[float] | None = None
    cmd_q_rad: torch.Tensor | None = None
    anchor_feet_mm: np.ndarray | None = None
    anchor_is_standing: bool = True
    settled_since: float | None = None
    last_tick_at: float = 0.0
    last_external_motion_at: float = 0.0
    last_interaction_at: float = 0.0
    last_release_reset_at: float = 0.0
    manual_stopped: bool = False
    pending_tip: bool = False
    tip_still_since: float | None = None
    tip_detected_at: float | None = None
    probe_until: float = 0.0
    vad_listening_until: float = 0.0
    prev_vision_obs_at: float | None = None
    prev_vision_centers: dict[str, tuple[float, float]] = field(default_factory=dict)
    prev_vision_motion_mag: float = 0.0
    last_sent_feet_mm: list[float] | None = None
    last_walk_target_at: float = 0.0
    walk_backoff_until: float = 0.0
    wake_yield_until: float = 0.0
    boot_stood: bool = False
    passive_entered_at: float = 0.0
    passive_entry_tilt_deg: float | None = None
    passive_saw_handling: bool = False
    upright_steady_since: float | None = None
    face_token: str = field(default_factory=lambda: "pr_" + uuid4().hex[:24])
    active_expression: str | None = None
    foreground_face_owned: bool = False
    last_expression_at: float = 0.0
    last_chatter_max_deg: float = 0.0
    last_tracking_err_max_deg: float = 0.0
    last_person_conf: float = 0.0
    last_speech_rms: float = 0.0
    last_error: str | None = None


class PresenceController:
    """Single authoritative host runtime owner for System 3 in Body Control."""

    def __init__(
        self,
        gateway,
        *,
        initial_settings: dict[str, dict[str, Any]] | None = None,
        stop_latched_fn: Callable[[], bool] | None = None,
        freestyle_active_fn: Callable[[str], bool] | None = None,
        camera_analysis_fn: Callable[[str], Any] | None = None,
    ):
        self.gateway = gateway
        self.runtime = PresenceRuntime()
        self.settings: dict[str, dict[str, Any]] = {
            robot_id: validate_presence_settings(cfg)
            for robot_id, cfg in (initial_settings or {}).items()
        }
        self.stop_latched_fn = stop_latched_fn or (lambda: False)
        self.freestyle_active_fn = freestyle_active_fn or (lambda _r: False)
        self.camera_analysis_fn = camera_analysis_fn or (lambda _r: None)
        self.states: dict[str, RobotPresenceState] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._wake_events: dict[str, asyncio.Event] = {}
        self._closed = False

        self.gateway.subscribe_commands(self._on_command)
        self.gateway.subscribe_events(self._on_event)

    def settings_for(self, robot_id: str) -> dict[str, Any]:
        return dict(self.settings.get(robot_id) or DEFAULTS)

    def configure(self, robot_id: str, raw: dict[str, Any] | None) -> dict[str, Any]:
        validated = validate_presence_settings(raw)
        self.settings[robot_id] = validated
        st = self._state(robot_id)
        now = self.gateway.clock()
        st.last_interaction_at = now
        st.last_release_reset_at = now
        if validated["enabled"]:
            st.manual_stopped = False
        if robot_id in self._wake_events:
            self._wake_events[robot_id].set()
        self._ensure_robot_loop(robot_id)
        return validated

    async def clear_passive(self, robot_id: str, stand_up: bool = True) -> dict[str, Any]:
        st = self._state(robot_id)
        now = self.gateway.clock()
        self._reset_stance_tracking(st)
        st.manual_stopped = False
        st.passive_reason = None
        st.passive_saw_handling = False
        st.pending_tip = False
        st.wake_yield_until = 0.0
        st.last_interaction_at = now
        st.last_release_reset_at = now
        st.mode = "standby"
        if robot_id in self.gateway._connections:
            if hasattr(self.gateway, "ensure_normal_mode"):
                await self.gateway.ensure_normal_mode(robot_id=robot_id)
            if stand_up:
                st.boot_stood = True
                st.last_external_motion_at = now
                await self._send_owned(
                    self.gateway.queue_intent("stand", {}, robot_id=robot_id),
                    st,
                    robot_id=robot_id,
                )
        if robot_id in self._wake_events:
            self._wake_events[robot_id].set()
        return self.robot_status(robot_id)

    def status(self) -> dict[str, Any]:
        policy_path = resolve_active_presence_policy()
        actor = self.runtime._actor
        footprint = (
            actor.footprint
            if actor is not None
            else {
                **presence_model_footprint(),
                **(
                    {"onnx_file_bytes": policy_path.stat().st_size, "policy_path": str(policy_path)}
                    if policy_path is not None
                    else {}
                ),
            }
        )
        robot_ids = set(self.settings) | set(self.gateway._connections) | set(self.states)
        return {
            "defaults": dict(DEFAULTS),
            "policy_loaded": policy_path is not None,
            "model_footprint": footprint,
            "robots": {rid: self.robot_status(rid) for rid in sorted(robot_ids)},
        }

    def robot_status(self, robot_id: str) -> dict[str, Any]:
        cfg = self.settings_for(robot_id)
        st = self._state(robot_id)
        now = self.gateway.clock()
        idle_s = max(0.0, now - st.last_interaction_at) if st.last_interaction_at > 0 else 0.0
        release_idle_s = max(0.0, now - st.last_release_reset_at) if st.last_release_reset_at > 0 else 0.0
        return {
            "settings": cfg,
            "mode": st.mode,
            "passive_reason": st.passive_reason,
            "active_expression": st.active_expression,
            "streaming_walk_seq": st.walk_seq,
            "idle_seconds": round(idle_s, 1),
            "release_idle_seconds": round(release_idle_s, 1),
            "sympathy_score": st.sympathy.last_score,
            "chatter_max_deg": round(st.last_chatter_max_deg, 2),
            "tracking_error_max_deg": round(st.last_tracking_err_max_deg, 2),
            "compliance_trim_max_mm": round(max((abs(v) for v in st.compliance_trim_mm), default=0.0), 2),
            "person_confidence": round(st.last_person_conf, 2),
            "speech_rms": round(st.last_speech_rms, 3),
            "imu_fed_to_policy": bool(cfg["self_right_enabled"]),
            "last_error": st.last_error,
        }

    def _reset_stance_tracking(self, st: RobotPresenceState) -> None:
        st.walk_seq = None
        st.last_sent_feet_mm = None
        st.anchor_feet_mm = None
        st.cmd_q_rad = None
        st.compliance_trim_mm = [0.0] * 12
        st.settled_since = None
        st.probe_until = 0.0
        st.sympathy.reset()

    def _reset_for_connection(self, st: RobotPresenceState, now: float) -> None:
        self._reset_stance_tracking(st)
        st.mode = "standby"
        st.passive_reason = None
        st.passive_saw_handling = False
        st.passive_entry_tilt_deg = None
        st.upright_steady_since = None
        st.manual_stopped = False
        st.pending_tip = False
        st.tip_detected_at = None
        st.tip_still_since = None
        st.owned_sequences.clear()
        st.history = PresenceObservationHistory()
        st.prev_foot_norm = [0.0] * 12
        st.chatter_deg = [0.0] * 12
        st.prev_meas_deg = None
        st.prev_cmd_deg = None
        st.vad_listening_until = 0.0
        st.walk_backoff_until = 0.0
        st.wake_yield_until = 0.0
        st.boot_stood = False
        st.foreground_face_owned = False
        st.active_expression = None
        st.last_external_motion_at = now
        st.last_interaction_at = now
        st.last_release_reset_at = now
        st.last_error = None

    def _state(self, robot_id: str) -> RobotPresenceState:
        st = self.states.get(robot_id)
        if st is None:
            now = self.gateway.clock()
            st = RobotPresenceState(
                robot_id=robot_id,
                last_external_motion_at=now,
                last_interaction_at=now,
                last_release_reset_at=now,
            )
            self.states[robot_id] = st
        return st

    def _ensure_robot_loop(self, robot_id: str) -> None:
        if self._closed or robot_id not in self.gateway._connections:
            return
        existing = self._tasks.get(robot_id)
        if existing is None or existing.done():
            ev = self._wake_events.setdefault(robot_id, asyncio.Event())
            self._tasks[robot_id] = asyncio.create_task(
                self._robot_loop(robot_id, ev),
                name=f"presence-{robot_id}",
            )

    async def _send_owned(self, coro, st: RobotPresenceState, *, robot_id: str | None = None) -> int:
        token = PRESENCE_OWNER.set(True)
        try:
            seq = await coro
            if isinstance(seq, int):
                st.owned_sequences.add(seq)
                if len(st.owned_sequences) > 64:
                    target_id = robot_id or st.robot_id
                    conn = self.gateway._connections.get(target_id) if target_id else None
                    active_pending = {
                        p_seq
                        for p_seq, item in (conn.pending.items() if conn is not None else ())
                        if not item.future.done()
                    }
                    pinned = st.owned_sequences & active_pending
                    if st.walk_seq is not None:
                        pinned.add(st.walk_seq)
                    recent = sorted(st.owned_sequences - pinned)[-32:]
                    st.owned_sequences = pinned | set(recent)
            return seq
        finally:
            PRESENCE_OWNER.reset(token)

    async def _on_command(self, command: dict[str, Any]) -> None:
        robot_id = command.get("robot_id")
        if not isinstance(robot_id, str):
            return
        st = self._state(robot_id)
        seq = command.get("seq")
        cmd_t = command.get("t")
        cmd_name = command.get("name")

        if PRESENCE_OWNER.get() or (isinstance(seq, int) and seq in st.owned_sequences):
            return

        is_motion = (
            cmd_t in {"stop", "motion_plan", "servo", "mode", "state"}
            or (cmd_t == "calibration" and command.get("op") != "get")
            or (cmd_t == "intent" and cmd_name not in {"face", "say"})
        )
        if not is_motion:
            now = self.gateway.clock()
            if cmd_t == "tts" or (cmd_t == "intent" and cmd_name == "say"):
                st.last_interaction_at = now
                st.last_release_reset_at = now
                if robot_id in self._wake_events:
                    self._wake_events[robot_id].set()
            elif cmd_t == "intent" and cmd_name == "face":
                st.last_interaction_at = now
                st.last_release_reset_at = now
            return

        # External motion or Stop immediately preempts System 3
        now = self.gateway.clock()
        self._reset_stance_tracking(st)
        st.foreground_face_owned = False
        st.active_expression = None
        st.last_external_motion_at = now
        st.last_interaction_at = now
        st.last_release_reset_at = now

        if cmd_t == "stop" and bool(command.get("detach")):
            # Deliberate servo detach latches System 3 stopped until next Stand/motion or re-enable.
            st.manual_stopped = True
            st.wake_yield_until = 0.0
            st.mode = "stopped"
        else:
            # Normal Stop (detach=False, e.g. finishing a walk) yields cleanly and resumes living presence.
            st.manual_stopped = False
            if cmd_t != "stop":
                st.boot_stood = True
                st.wake_yield_until = 0.0
            if st.mode in ("passive", "resting_released", "stopped"):
                st.passive_reason = None
                st.passive_saw_handling = False
            st.mode = "yielded"

        if robot_id in self._wake_events:
            self._wake_events[robot_id].set()

    async def _on_event(self, event: dict[str, Any]) -> None:
        robot_id = event.get("robot_id")
        if not isinstance(robot_id, str):
            return
        ev_t = event.get("t")
        if ev_t == "connection":
            if event.get("status") == "connected":
                st = self._state(robot_id)
                self._reset_for_connection(st, self.gateway.clock())
                self._ensure_robot_loop(robot_id)
            else:
                task = self._tasks.pop(robot_id, None)
                if task is not None:
                    task.cancel()
            return

        if ev_t == "imu":
            self._ensure_robot_loop(robot_id)
            st = self._state(robot_id)
            if self.gateway.clock() >= st.last_tick_at + PRESENCE_INTERVAL_S:
                wake = self._wake_events.get(robot_id)
                if wake is not None:
                    wake.set()
            return

        ev_name = event.get("name")
        if ev_name in {"vad_open", "wake_word", "vad_close"}:
            st = self._state(robot_id)
            now = self.gateway.clock()
            st.last_interaction_at = now
            st.last_release_reset_at = now
            if ev_name in {"vad_open", "wake_word"}:
                st.vad_listening_until = now + 14.0
            else:
                st.vad_listening_until = 0.0
            wake = self._wake_events.get(robot_id)
            if wake is not None:
                wake.set()
            return

        if ev_name == "body_event":
            data = event.get("data") or {}
            kind = data.get("kind")
            st = self._state(robot_id)
            now = self.gateway.clock()
            if kind == "wake":
                # Boot/wake startup movement ("Perform a whole-body stretch.") is owned
                # by EnvironmentAdapter -> Freestyle. Reset timers and yield until Freestyle claims it.
                self._reset_stance_tracking(st)
                st.manual_stopped = False
                st.passive_reason = None
                st.passive_saw_handling = False
                st.boot_stood = True
                st.last_external_motion_at = now
                st.last_interaction_at = now
                st.last_release_reset_at = now
                st.wake_yield_until = max(st.wake_yield_until, now + 2.5)
                st.mode = "yielded"
                wake = self._wake_events.get(robot_id)
                if wake is not None:
                    wake.set()
                return
            cfg = self.settings_for(robot_id)
            if not cfg["enabled"]:
                return
            if kind == "tipped" and cfg["self_right_enabled"]:
                st.pending_tip = True
                st.tip_detected_at = now
                st.tip_still_since = None
            elif kind == "rapid_movement":
                # Arm a short grounded-sympathy verification probe if active & grounded
                if st.mode not in ("passive", "resting_released", "self_righting", "stopped"):
                    st.probe_until = max(st.probe_until, now + 1.15)
                st.last_interaction_at = now
            elif kind == "servo_stall" and st.mode == "self_righting":
                await self._enter_passive(robot_id, st, "righting_servo_stall")
            wake = self._wake_events.get(robot_id)
            if wake is not None:
                wake.set()

    def _external_motion_busy(self, robot_id: str, connection, st: RobotPresenceState, now: float | None = None) -> bool:
        t_now = self.gateway.clock() if now is None else now
        if t_now < st.wake_yield_until:
            return True
        if connection.mode != "normal":
            return True
        if connection.neural_walk is not None:
            return True
        if self.freestyle_active_fn(robot_id):
            return True
        for seq, pending in connection.pending.items():
            if seq == st.walk_seq or seq in st.owned_sequences or pending.future.done():
                continue
            cmd = pending.command
            ct = cmd.get("t")
            cn = cmd.get("name")
            if ct in {"motion_plan", "servo", "mode", "state", "calibration"} or (
                ct == "intent" and cn not in {"face", "say"}
            ):
                return True
        return False

    def _owned_posture_motion_pending(self, connection, st: RobotPresenceState) -> bool:
        for seq, pending in connection.pending.items():
            if seq == st.walk_seq or seq not in st.owned_sequences or pending.future.done():
                continue
            cmd = pending.command
            ct = cmd.get("t")
            cn = cmd.get("name")
            if ct == "motion_plan" or (ct == "intent" and cn == "stand"):
                return True
        return False

    def _extract_vision_context(self, robot_id: str, st: RobotPresenceState, now: float, enabled: bool) -> tuple[float, float, float, float, float]:
        if not enabled:
            st.prev_vision_obs_at = None
            st.prev_vision_centers.clear()
            st.prev_vision_motion_mag = 0.0
            return 0.0, 0.0, 0.0, 0.0, 0.0
        try:
            analysis = self.camera_analysis_fn(robot_id)
        except Exception:
            analysis = None
        if analysis is None:
            st.prev_vision_motion_mag = 0.0
            return 0.0, 0.0, 0.0, 0.0, 0.0
        observed_mono = getattr(analysis, "received_at", None)
        obs_t = float(observed_mono) if isinstance(observed_mono, (int, float)) else now
        if now - obs_t > 3.5:
            st.prev_vision_obs_at = None
            st.prev_vision_centers.clear()
            st.prev_vision_motion_mag = 0.0
            return 0.0, 0.0, 0.0, 0.0, 0.0
        recognition = getattr(analysis, "recognition", None)
        objects = getattr(recognition, "objects", None) or []
        best_person = None
        best_score = 0.0
        current_centers: dict[str, tuple[float, float]] = {}
        is_new_frame = st.prev_vision_obs_at is None or abs(obs_t - st.prev_vision_obs_at) > 1e-4
        dt_frame = max(0.05, obs_t - st.prev_vision_obs_at) if (is_new_frame and st.prev_vision_obs_at is not None) else None
        raw_motion = 0.0
        for idx, obj in enumerate(objects):
            if not isinstance(obj, dict):
                continue
            conf = float(obj.get("confidence") or 0.0)
            w = float(obj.get("width") or 0.0)
            h = float(obj.get("height") or 0.0)
            area = max(0.0, w * h)
            cx = float(obj.get("x") or 0.0) + 0.5 * w
            cy = float(obj.get("y") or 0.0) + 0.5 * h
            label = str(obj.get("label") or "").lower()
            ident = obj.get("identity") or {}
            track_key = str(ident.get("personId") or obj.get("trackId") or obj.get("id") or f"{label}:{idx}")
            current_centers[track_key] = (cx, cy)
            if dt_frame is not None and dt_frame <= 2.5 and track_key in st.prev_vision_centers:
                px, py = st.prev_vision_centers[track_key]
                disp = math.hypot(cx - px, cy - py)
                # Ignore tiny detector jitter (<1.2% of frame); scale real motion speed cleanly to [0, 1]
                if disp > 0.012:
                    raw_motion = max(raw_motion, min(1.0, (disp / max(0.12, dt_frame)) * 1.8))
            if label == "person" or ident.get("personId"):
                score = conf * (0.4 + area)
                if score > best_score:
                    best_score = score
                    best_person = obj
        if is_new_frame:
            st.prev_vision_obs_at = obs_t
            st.prev_vision_centers = current_centers
            st.prev_vision_motion_mag = raw_motion if dt_frame is not None else 0.0
        motion_mag = st.prev_vision_motion_mag * max(0.0, 1.0 - max(0.0, now - obs_t) / 1.5)
        if best_person is None:
            return 0.0, 0.0, 0.0, 0.0, motion_mag
        cx = float(best_person.get("x") or 0.0) + 0.5 * float(best_person.get("width") or 0.0)
        cy = float(best_person.get("y") or 0.0) + 0.5 * float(best_person.get("height") or 0.0)
        person_yaw = max(-1.0, min(1.0, (0.5 - cx) * 2.0))
        person_pitch = max(-1.0, min(1.0, (0.5 - cy) * 2.0))
        person_conf = max(0.0, min(1.0, float(best_person.get("confidence") or 0.6)))
        ident = best_person.get("identity") or {}
        known = 1.0 if ident.get("state") in ("face_match", "tracked") and ident.get("personId") else 0.0
        return person_yaw, person_pitch, person_conf, known, motion_mag

    async def _close_walk_stream(self, robot_id: str, connection, st: RobotPresenceState, *, detach: bool = False) -> None:
        seq = st.walk_seq
        st.walk_seq = None
        st.settled_since = None
        if detach or (seq is not None and connection._owns_walk(seq)):
            try:
                await self._send_owned(
                    self.gateway.estop(robot_id=robot_id, detach=detach),
                    st,
                )
            except Exception:
                pass
        if st.foreground_face_owned:
            st.foreground_face_owned = False
            st.active_expression = None
            if "face_feedback_v1" in connection.features:
                try:
                    await self._send_owned(
                        self.gateway.queue_intent(
                            "face",
                            {
                                "expr": "default",
                                "token": st.face_token,
                                "release": True,
                            },
                            robot_id=robot_id,
                        ),
                        st,
                    )
                except Exception:
                    pass

    async def _set_background_face(
        self,
        robot_id: str,
        connection,
        st: RobotPresenceState,
        expr: str,
        now: float,
        *,
        foreground: bool = False,
    ) -> None:
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
        # Never overwrite an active foreground body-event, MetaHuman, or Freestyle face token
        if fg_token and not fg_token.startswith("pr_"):
            return
        min_gap = 0.8 if expr in ("surprised", "listening", "talk_happy") else 1.8
        if expr == st.active_expression and st.foreground_face_owned == foreground and now - st.last_expression_at < 8.0:
            return
        if expr != st.active_expression and now - st.last_expression_at < min_gap:
            return
        try:
            await self._send_owned(
                self.gateway.queue_intent(
                    "face",
                    {
                        "expr": expr,
                        "token": st.face_token,
                        "background": not foreground,
                        "timeout_ms": 15000,
                    },
                    robot_id=robot_id,
                ),
                st,
            )
            st.active_expression = expr
            st.foreground_face_owned = foreground
            st.last_expression_at = now
        except Exception:
            pass

    async def _enter_passive(self, robot_id: str, st: RobotPresenceState, reason: str) -> None:
        connection = self.gateway._connections.get(robot_id)
        cfg = self.settings_for(robot_id)
        now = self.gateway.clock()
        st.mode = "passive"
        st.passive_reason = reason
        st.passive_saw_handling = False
        st.passive_entry_tilt_deg = None
        st.pending_tip = False
        st.passive_entered_at = now
        st.upright_steady_since = None
        self._reset_stance_tracking(st)
        if connection is None:
            return
        await self._close_walk_stream(robot_id, connection, st, detach=False)
        pmode = cfg["passive_mode"]
        servos_armed = (connection.last_status or {}).get("output_armed") is not False
        try:
            if servos_armed and pmode in ("calm_then_release", "calm_hold") and "motion_targets_v1" in connection.features:
                targets_cd = [round(v * 100) for v in CALM_PASSIVE_DEG]
                seq = await self._send_owned(
                    self.gateway.queue_motion_plan(
                        [[18000, targets_cd]],
                        end="hold",
                        control="targets",
                        robot_id=robot_id,
                    ),
                    st,
                    robot_id=robot_id,
                )
                try:
                    await self.gateway.wait_terminal(seq, robot_id=robot_id, epoch=connection.epoch, timeout=1.4)
                except Exception:
                    pass
            if servos_armed and pmode in ("calm_then_release", "release"):
                await self._send_owned(
                    self.gateway.estop(robot_id=robot_id, detach=True),
                    st,
                    robot_id=robot_id,
                )
            st.passive_entered_at = self.gateway.clock()
            st.passive_entry_tilt_deg = None
            await self._set_background_face(robot_id, connection, st, "rest", st.passive_entered_at)
        except Exception as err:
            st.last_error = str(err)

    async def _enter_resting_release(self, robot_id: str, connection, st: RobotPresenceState, now: float) -> None:
        await self._close_walk_stream(robot_id, connection, st, detach=False)
        st.mode = "resting_released"
        self._reset_stance_tracking(st)
        servos_armed = (connection.last_status or {}).get("output_armed") is not False
        try:
            if servos_armed:
                if "motion_targets_v1" in connection.features:
                    targets_cd = [round(v * 100) for v in REST_ANGLES_DEG]
                    seq = await self._send_owned(
                        self.gateway.queue_motion_plan(
                            [[12000, targets_cd]],
                            end="hold",
                            control="targets",
                            robot_id=robot_id,
                        ),
                        st,
                        robot_id=robot_id,
                    )
                    try:
                        await self.gateway.wait_terminal(seq, robot_id=robot_id, epoch=connection.epoch, timeout=2.2)
                    except Exception:
                        pass
                await self._send_owned(
                    self.gateway.estop(robot_id=robot_id, detach=True),
                    st,
                    robot_id=robot_id,
                )
            await self._set_background_face(robot_id, connection, st, "sleepy", now)
        except Exception as err:
            st.last_error = str(err)

    async def _ensure_walk_stream(self, robot_id: str, connection, st: RobotPresenceState, manifold, live_body, now: float) -> bool:
        if st.walk_seq is not None and connection._owns_walk(st.walk_seq) and st.walk_seq in connection.pending:
            return True
        if now < st.walk_backoff_until:
            return False
        if "walk_nominal_v1" not in connection.features:
            return False
        status_dict = connection.last_status or {}
        if "output_armed" in status_dict:
            if not status_dict.get("output_armed") or connection.last_calibration is None:
                return False
        st.sample_idx = 0
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
                    st.walk_backoff_until = now + 2.0
                    return False
            st.walk_seq = seq
            pts0, _ = live_body.forward(st.cmd_q_rad.reshape(1, 4, 3))
            init_feet_mm = (pts0 - live_body.origin.unsqueeze(0)).reshape(12).detach().cpu().tolist()
            st.sample_idx = 1
            await self._send_owned(
                connection.send_command(
                    {
                        "t": "walk_target",
                        "walk": seq,
                        "sample": st.sample_idx,
                        "geometry": manifold.geometry_id,
                        "feet_mm": init_feet_mm,
                    },
                    received_at=now,
                ),
                st,
            )
            st.last_sent_feet_mm = list(init_feet_mm)
            st.last_walk_target_at = now
            return True
        except Exception as err:
            st.last_error = str(err)
            st.walk_seq = None
            st.last_sent_feet_mm = None
            st.walk_backoff_until = now + 1.5
            return False

    async def _robot_loop(self, robot_id: str, wake_event: asyncio.Event) -> None:
        while not self._closed:
            t_tick = self.gateway.clock()
            wake_event.clear()
            connection = self.gateway._connections.get(robot_id)
            if connection is None or connection.websocket.closed:
                return

            st = self._state(robot_id)
            st.last_tick_at = t_tick
            cfg = self.settings_for(robot_id)

            if not cfg["enabled"]:
                if st.walk_seq is not None:
                    await self._close_walk_stream(robot_id, connection, st, detach=False)
                st.mode = "disabled"
                await self._sleep_next(t_tick, wake_event)
                continue

            if self.stop_latched_fn() or st.manual_stopped:
                if st.walk_seq is not None:
                    await self._close_walk_stream(robot_id, connection, st, detach=False)
                st.mode = "stopped"
                await self._sleep_next(t_tick, wake_event)
                continue

            if self._external_motion_busy(robot_id, connection, st, t_tick):
                if st.walk_seq is not None and connection.mode != "normal":
                    await self._close_walk_stream(robot_id, connection, st, detach=False)
                self._reset_stance_tracking(st)
                st.last_external_motion_at = t_tick
                st.last_interaction_at = t_tick
                st.last_release_reset_at = t_tick
                st.mode = "yielded"
                await self._sleep_next(t_tick, wake_event)
                continue

            try:
                sensor = self.gateway.body_sensor_observation(robot_id)
            except Exception:
                await self._sleep_next(t_tick, wake_event)
                continue

            imu = sensor["imu"]
            joints_map = sensor["joints"]
            be_cfg = self.gateway.body_events.config(robot_id)
            tip_degrees = float(be_cfg.get("tip_degrees", 60.0))
            tip_clear_degrees = float(be_cfg.get("tip_clear_degrees", 45.0))

            tilt_deg, _, _ = tilt_roll_pitch_deg_from_wxyz(imu["orientation_wxyz"])
            gyro_dps = math.degrees(math.hypot(*(float(v) for v in imu["angular_rate_rad_s"])))
            accel_g = math.hypot(*(float(v) for v in imu["acceleration_m_s2"])) / 9.80665

            # 1. Handle PASSIVE mode: stay completely calm until physically repositioned onto a steady level surface
            if st.mode == "passive":
                if t_tick - st.passive_entered_at >= 2.0:
                    if st.passive_entry_tilt_deg is None:
                        st.passive_entry_tilt_deg = tilt_deg
                    if (
                        gyro_dps >= 28.0
                        or abs(accel_g - 1.0) >= 0.18
                        or abs(tilt_deg - st.passive_entry_tilt_deg) >= 18.0
                    ):
                        st.passive_saw_handling = True
                        st.upright_steady_since = None

                    steady_level = (
                        tilt_deg < min(tip_clear_degrees, 28.0)
                        and gyro_dps < 12.0
                        and abs(accel_g - 1.0) < 0.09
                    )
                    if cfg["self_right_enabled"] and st.passive_saw_handling and steady_level:
                        if st.upright_steady_since is None:
                            st.upright_steady_since = t_tick
                        elif t_tick - st.upright_steady_since >= 1.5:
                            st.passive_reason = None
                            st.passive_saw_handling = False
                            st.passive_entry_tilt_deg = None
                            st.upright_steady_since = None
                            st.mode = "standby"
                            try:
                                seq = await self._send_owned(
                                    self.gateway.queue_intent("stand", {}, robot_id=robot_id),
                                    st,
                                )
                                await self.gateway.wait_terminal(seq, robot_id=robot_id, epoch=connection.epoch, timeout=8.0)
                            except Exception:
                                pass
                            now_after = self.gateway.clock()
                            st.boot_stood = True
                            st.last_external_motion_at = now_after
                            st.last_interaction_at = now_after
                            st.last_release_reset_at = now_after
                            st.anchor_feet_mm = None
                            st.cmd_q_rad = None
                            st.sympathy.reset()
                            st.probe_until = 0.0
                    else:
                        st.upright_steady_since = None
                await self._sleep_next(t_tick, wake_event)
                continue

            # 2. Handle SELF-RIGHTING mode: monitor sympathetic upright IMU progress
            if st.mode == "self_righting":
                stalled_mask = int((sensor.get("feedback") or {}).get("stalled_joints") or 0)
                status_str, reason = st.sympathy.evaluate_righting(
                    now=t_tick,
                    tilt_deg=tilt_deg,
                    tip_clear_degrees=tip_clear_degrees,
                    stalled=bool(stalled_mask),
                )
                if status_str == "recovered":
                    st.mode = "standby"
                    st.boot_stood = True
                    st.pending_tip = False
                    st.anchor_feet_mm = None
                    st.cmd_q_rad = None
                    st.compliance_trim_mm = [0.0] * 12
                    st.sympathy.reset()
                    st.last_external_motion_at = t_tick
                    st.last_interaction_at = t_tick
                    st.last_release_reset_at = t_tick
                elif status_str == "passive":
                    await self._enter_passive(robot_id, st, reason or "unrecoverable_tip")
                await self._sleep_next(t_tick, wake_event)
                continue

            # 3. Check if tipped over while idle (when self_right_enabled=True)
            if cfg["self_right_enabled"] and (st.pending_tip or tilt_deg >= tip_degrees):
                if st.tip_detected_at is None:
                    st.tip_detected_at = t_tick
                if gyro_dps < 48.0:
                    if st.tip_still_since is None:
                        st.tip_still_since = t_tick
                    elif t_tick - st.tip_still_since >= 0.45:
                        await self._close_walk_stream(robot_id, connection, st, detach=False)
                        st.mode = "self_righting"
                        st.pending_tip = False
                        st.tip_detected_at = None
                        st.tip_still_since = None
                        st.sympathy.start_righting(t_tick, tilt_deg)
                        try:
                            await self._send_owned(
                                self.gateway.queue_intent("stand", {}, robot_id=robot_id),
                                st,
                            )
                        except Exception as err:
                            st.last_error = str(err)
                            await self._enter_passive(robot_id, st, "righting_dispatch_failed")
                        await self._sleep_next(t_tick, wake_event)
                        continue
                else:
                    st.tip_still_since = None
                    if t_tick - st.tip_detected_at >= 3.0:
                        st.tip_detected_at = None
                        await self._enter_passive(robot_id, st, "continuous_handling")
                        await self._sleep_next(t_tick, wake_event)
                        continue
                await self._sleep_next(t_tick, wake_event)
                continue

            # Extract multimodal perception + real speech/listening context (no synthetic idle oscillators)
            speaking_fn = getattr(self.gateway, "speech_activity", None)
            if callable(speaking_fn):
                speaking_active_b, speech_rms = speaking_fn(robot_id)
            else:
                speaking_active_b = self.gateway.external_speech_active(robot_id)
                speech_rms = 0.55 if speaking_active_b else 0.0
            if speaking_active_b:
                st.vad_listening_until = 0.0
            speaking_active = 1.0 if speaking_active_b else 0.0

            audio_in = connection.audio_input or {}
            vad_open_b = t_tick < st.vad_listening_until
            listening_b = (
                not speaking_active_b
                and bool(
                    vad_open_b
                    or audio_in.get("utterance_open")
                    or (connection.last_status or {}).get("listening_feedback")
                )
            )
            listening_active = 1.0 if listening_b else 0.0
            raw_mic_rms = min(1.0, float(connection.microphone_level) * 6.0)
            mic_rms = (max(0.50, raw_mic_rms) if vad_open_b else raw_mic_rms) if listening_b else 0.0

            p_yaw, p_pitch, p_conf, p_known, motion_mag = self._extract_vision_context(
                robot_id, st, t_tick, cfg["social_gaze_enabled"] or cfg["presence_defers_release"]
            )
            if not cfg["social_gaze_enabled"]:
                p_yaw = 0.0
                p_pitch = 0.0

            st.last_person_conf = p_conf
            st.last_speech_rms = speech_rms

            # Update interaction & servo-release timers
            if speaking_active_b or listening_b:
                st.last_interaction_at = t_tick
                st.last_release_reset_at = t_tick
            if p_conf >= 0.35 and cfg["presence_defers_release"]:
                st.last_release_reset_at = t_tick

            # 4. Handle RESTING_RELEASED wake, owned posture guard, cold-boot disarmed guard, then idle release
            if st.mode == "resting_released":
                if speaking_active_b or listening_b:
                    st.mode = "standby"
                    try:
                        seq = await self._send_owned(
                            self.gateway.queue_intent("stand", {}, robot_id=robot_id),
                            st,
                            robot_id=robot_id,
                        )
                        await self.gateway.wait_terminal(seq, robot_id=robot_id, epoch=connection.epoch, timeout=8.0)
                    except Exception:
                        pass
                    now_after = self.gateway.clock()
                    st.boot_stood = True
                    st.last_external_motion_at = now_after
                    st.last_interaction_at = now_after
                    st.last_release_reset_at = now_after
                    self._reset_stance_tracking(st)
                await self._sleep_next(t_tick, wake_event)
                continue

            # Never interrupt an owned posture command (`stand` / `motion_plan`) mid-flight
            if self._owned_posture_motion_pending(connection, st):
                st.last_external_motion_at = t_tick
                st.mode = "standby"
                await self._sleep_next(t_tick, wake_event)
                continue

            # Cold-boot / disarmed guard on physical P4: never open `walk` or send idle release on disarmed servos
            status_dict = connection.last_status or {}
            if "output_armed" in status_dict:
                out_fault = status_dict.get("output_fault")
                if connection.last_calibration is None or (
                    status_dict.get("output_ready") is False and out_fault not in (0, 1, None)
                ):
                    st.mode = "standby"
                    await self._sleep_next(t_tick, wake_event)
                    continue
                if not status_dict.get("output_armed"):
                    if not st.boot_stood and cfg["self_right_enabled"]:
                        st.boot_stood = True
                        st.mode = "standby"
                        try:
                            seq = await self._send_owned(
                                self.gateway.queue_intent("stand", {}, robot_id=robot_id),
                                st,
                                robot_id=robot_id,
                            )
                            await self.gateway.wait_terminal(seq, robot_id=robot_id, epoch=connection.epoch, timeout=8.0)
                        except Exception:
                            pass
                        now_after = self.gateway.clock()
                        st.last_external_motion_at = now_after
                        st.last_interaction_at = now_after
                        st.last_release_reset_at = now_after
                        self._reset_stance_tracking(st)
                    else:
                        st.mode = "standby"
                    await self._sleep_next(t_tick, wake_event)
                    continue

            if cfg["servo_release_s"] > 0 and (t_tick - st.last_release_reset_at) >= cfg["servo_release_s"]:
                await self._enter_resting_release(robot_id, connection, st, t_tick)
                await self._sleep_next(t_tick, wake_event)
                continue

            # Wait a brief 0.65s settle after any external or posture motion completes before taking compliant ownership
            if t_tick - st.last_external_motion_at < 0.65:
                st.mode = "standby"
                await self._sleep_next(t_tick, wake_event)
                continue

            # 5. Measure 4th-wire angles, tracking error, and high-frequency servo chatter
            measured_deg = [joints_map[j].get("filtered_model_deg") for j in JOINTS]
            usable_flags = [bool(joints_map[j].get("feedback_usable", False)) for j in JOINTS]
            commanded_deg = [
                (
                    float(joints_map[j]["commanded_model_deg"])
                    if isinstance(joints_map[j].get("commanded_model_deg"), (int, float))
                    else float(STAND_ANGLES_DEG[i])
                )
                for i, j in enumerate(JOINTS)
            ]
            velocity_deg_s = [float(joints_map[j].get("velocity_deg_s") or 0.0) for j in JOINTS]

            safe_meas = [
                float(measured_deg[i]) if (usable_flags[i] and isinstance(measured_deg[i], (int, float))) else commanded_deg[i]
                for i in range(12)
            ]
            if st.prev_meas_deg is not None and st.prev_cmd_deg is not None:
                for i in range(12):
                    cmd_step = abs(commanded_deg[i] - st.prev_cmd_deg[i])
                    meas_step = abs(safe_meas[i] - st.prev_meas_deg[i])
                    # Chatter = joint oscillating/fighting while commanded target is nearly stationary
                    raw_chat = meas_step * 2.5 if cmd_step < 0.6 else 0.0
                    st.chatter_deg[i] = 0.82 * st.chatter_deg[i] + 0.18 * raw_chat
            st.prev_meas_deg = list(safe_meas)
            st.prev_cmd_deg = list(commanded_deg)

            st.last_chatter_max_deg = max(st.chatter_deg) if st.chatter_deg else 0.0
            st.last_tracking_err_max_deg = max(
                abs(commanded_deg[i] - safe_meas[i]) if usable_flags[i] else 0.0 for i in range(12)
            )

            loaded = (
                (self.runtime._actor, self.runtime._manifold)
                if self.runtime.is_fresh()
                else await asyncio.to_thread(self.runtime.load)
            )
            if loaded is None:
                st.mode = "standby"
                await self._sleep_next(t_tick, wake_event)
                continue
            actor, manifold = loaded
            cal_joints = (connection.last_calibration or {}).get("joints")
            live_body = manifold.body_for_calibration(cal_joints)

            # Initialize compliant anchor from the robot's actual current posture (preserves symmetric Sit/Crouch,
            # while smoothly re-centering twisted/stumbled postures back to symmetric STAND_ANGLES_DEG).
            if st.anchor_feet_mm is None or st.cmd_q_rad is None:
                proj_deg, _ = manifold.project_angles_deg(safe_meas, body=live_body)
                near_stand = max(abs(proj_deg[i] - STAND_ANGLES_DEG[i]) for i in range(12)) <= 26.0
                lr_asymmetry = max(
                    abs(abs(proj_deg[0]) - abs(proj_deg[3])),
                    abs(abs(proj_deg[6]) - abs(proj_deg[9])),
                    abs(proj_deg[1] - proj_deg[4]),
                    abs(proj_deg[2] - proj_deg[5]),
                    abs(proj_deg[7] - proj_deg[10]),
                    abs(proj_deg[8] - proj_deg[11]),
                )
                use_stand_anchor = bool(near_stand or lr_asymmetry > 18.0)
                base_deg = list(STAND_ANGLES_DEG) if use_stand_anchor else proj_deg
                st.anchor_is_standing = use_stand_anchor
                base_q = torch.tensor(base_deg, dtype=torch.float64, device=live_body.device).reshape(1, 4, 3) * (
                    math.pi / 180.0
                )
                pts_base, _ = live_body.forward(base_q)
                st.anchor_feet_mm = (pts_base - live_body.origin.unsqueeze(0)).reshape(12).detach().cpu().numpy()
                cur_q = torch.tensor(proj_deg, dtype=torch.float64, device=live_body.device).reshape(1, 12) * (
                    math.pi / 180.0
                )
                st.cmd_q_rad, _ = live_body.pwm(cur_q)

            # Sympathetic grounded motion check on measured leg z differentials
            meas_q_rad = torch.tensor(safe_meas, dtype=torch.float64, device=live_body.device).reshape(1, 4, 3) * (
                math.pi / 180.0
            )
            meas_pts, _ = live_body.forward(meas_q_rad)
            meas_feet_mm = (meas_pts - live_body.origin.unsqueeze(0)).reshape(4, 3).detach().cpu().numpy()
            unsympathetic, _, sym_reason = st.sympathy.observe_stance_motion(
                now=t_tick,
                measured_deg=safe_meas,
                measured_feet_z_mm=meas_feet_mm[:, 2].tolist(),
                orientation_wxyz=imu["orientation_wxyz"],
                angular_rate_rad_s=imu["angular_rate_rad_s"],
                acceleration_m_s2=imu["acceleration_m_s2"],
            )
            if unsympathetic and cfg["self_right_enabled"]:
                await self._enter_passive(robot_id, st, sym_reason or "legs_moved_without_ground_reaction")
                await self._sleep_next(t_tick, wake_event)
                continue

            # Keep servos completely silent while the microphone utterance/VAD gate is open so mechanical
            # servo noise never couples into the P4 microphone and holds `vad_open` open.
            if listening_b:
                if st.walk_seq is not None:
                    await self._close_walk_stream(robot_id, connection, st, detach=False)
                st.compliance_trim_mm = [0.0] * 12
                st.settled_since = None
                st.mode = "standby"
                await self._sleep_next(t_tick, wake_event)
                continue

            conversational_active = bool(cfg["social_gaze_enabled"] and speaking_active_b)
            probe_active = bool(cfg["self_right_enabled"] and t_tick < st.probe_until)

            # Stay completely dormant in standby when neither speaking nor finishing a stream return
            if not conversational_active and not probe_active and st.walk_seq is None:
                st.compliance_trim_mm = [0.0] * 12
                st.settled_since = None
                st.mode = "standby"
                await self._sleep_next(t_tick, wake_event)
                continue

            scale_factor = 1.0 if st.anchor_is_standing else 0.35
            expr_name = "idle"
            expr_conf = 0.0

            if conversational_active or probe_active:
                # 6. Run 20 Hz Neural Presence Actor only during active robot speech or pickup probe
                feat = assemble_presence_features(
                    measured_deg=safe_meas,
                    commanded_deg=commanded_deg,
                    velocity_deg_s=velocity_deg_s,
                    chatter_deg=st.chatter_deg,
                    usable_flags=usable_flags,
                    orientation_wxyz=imu["orientation_wxyz"],
                    angular_rate_rad_s=imu["angular_rate_rad_s"],
                    acceleration_m_s2=imu["acceleration_m_s2"],
                    imu_enabled=bool(cfg["self_right_enabled"]),
                    chatter_relief_enabled=bool(cfg["chatter_relief_enabled"]),
                    person_yaw=p_yaw if cfg["social_gaze_enabled"] else 0.0,
                    person_pitch=p_pitch if cfg["social_gaze_enabled"] else 0.0,
                    person_conf=p_conf if cfg["social_gaze_enabled"] else 0.0,
                    known_face=p_known if cfg["social_gaze_enabled"] else 0.0,
                    motion_mag=motion_mag if cfg["social_gaze_enabled"] else 0.0,
                    listening_active=0.0,
                    mic_rms=0.0,
                    speaking_active=speaking_active,
                    speech_rms=speech_rms,
                    boredom_level=0.0,
                    phase_rad=t_tick * 2.2,
                    previous_foot_action=st.prev_foot_norm,
                )
                dev_us = (sensor.get("feedback") or {}).get("device_us")
                t_obs = float(dev_us) / 1e6 if isinstance(dev_us, (int, float)) and dev_us > 0 else t_tick
                obs_vec = st.history.push_and_project(t_obs, feat)
                foot_norm, foot_delta_mm, comp_step_mm, expr_name, expr_conf = actor.infer(obs_vec)
                st.prev_foot_norm = foot_norm
                st.compliance_trim_mm = update_compliance_trim_mm(
                    st.compliance_trim_mm,
                    comp_step_mm,
                    enabled=bool(cfg["chatter_relief_enabled"]),
                )
                delta_arr = (
                    np.asarray(foot_delta_mm, dtype=np.float64)
                    + np.asarray(st.compliance_trim_mm, dtype=np.float64)
                ) * scale_factor
                if probe_active and st.anchor_is_standing:
                    probe_z = 8.0 * math.sin((st.probe_until - t_tick) * 3.0)
                    delta_arr[2] += probe_z
                    delta_arr[5] += probe_z
                    delta_arr[8] -= probe_z
                    delta_arr[11] -= probe_z
                desired_feet_mm = st.anchor_feet_mm + delta_arr
            else:
                # Conversation ended: decay compliance trim and return smoothly to anchor before closing hold
                st.compliance_trim_mm = [v * 0.5 if abs(v) > 0.2 else 0.0 for v in st.compliance_trim_mm]
                desired_feet_mm = (
                    st.anchor_feet_mm + np.asarray(st.compliance_trim_mm, dtype=np.float64) * scale_factor
                )

            pose_act = np.clip(desired_feet_mm / POSE_SCALE_VEC, -1.0, 1.0).tolist()
            next_q_rad, _, feet_mm = manifold.step_host_command(
                pose_act,
                st.cmd_q_rad,
                speed_scale=1.0,
                body=live_body,
            )
            step_deg = float(
                torch.amax(torch.abs(next_q_rad - st.cmd_q_rad)).item() * (180.0 / math.pi)
            )
            returning_to_anchor = st.walk_seq is not None and (
                max(abs(v) for v in st.compliance_trim_mm) > 0.2
                or max(abs(feet_mm[i] - float(st.anchor_feet_mm[i])) for i in range(12)) > 1.4
                or (
                    st.last_sent_feet_mm is not None
                    and max(abs(st.last_sent_feet_mm[i] - float(st.anchor_feet_mm[i])) for i in range(12)) > 1.4
                )
            )
            need_active_stream = (
                conversational_active
                or probe_active
                or returning_to_anchor
                or (st.walk_seq is not None and step_deg >= 0.65)
            )

            if need_active_stream:
                st.settled_since = None
                if await self._ensure_walk_stream(robot_id, connection, st, manifold, live_body, t_tick):
                    st.mode = "active"
                    st.cmd_q_rad = next_q_rad
                    foot_diff_mm = (
                        max(abs(feet_mm[i] - st.last_sent_feet_mm[i]) for i in range(12))
                        if st.last_sent_feet_mm is not None
                        else 999.0
                    )
                    dt_sent = t_tick - st.last_walk_target_at
                    if (foot_diff_mm >= 1.2 and dt_sent >= 0.065) or dt_sent >= 0.28:
                        st.sample_idx += 1
                        try:
                            await self._send_owned(
                                connection.send_command(
                                    {
                                        "t": "walk_target",
                                        "walk": st.walk_seq,
                                        "sample": st.sample_idx,
                                        "geometry": manifold.geometry_id,
                                        "feet_mm": feet_mm,
                                    },
                                    received_at=t_tick,
                                ),
                                st,
                                robot_id=robot_id,
                            )
                            st.last_sent_feet_mm = list(feet_mm)
                            st.last_walk_target_at = t_tick
                        except Exception as err:
                            st.last_error = str(err)
                            st.walk_seq = None
                            st.last_sent_feet_mm = None
                    if conversational_active:
                        await self._set_background_face(
                            robot_id, connection, st, "talk_happy", t_tick, foreground=True
                        )
            else:
                if st.walk_seq is not None:
                    if st.settled_since is None:
                        st.settled_since = t_tick
                    elif t_tick - st.settled_since >= 0.35:
                        # Lock symmetric anchor cleanly in hold and release conversational face token
                        await self._close_walk_stream(robot_id, connection, st, detach=False)
                        st.mode = "standby"
                else:
                    st.mode = "standby"

            await self._sleep_next(t_tick, wake_event)

    async def _sleep_next(self, started_at: float, wake_event: asyncio.Event) -> None:
        rem = (started_at + PRESENCE_INTERVAL_S) - self.gateway.clock()
        if rem <= 0.002:
            await asyncio.sleep(0.002)
            return
        try:
            await asyncio.wait_for(wake_event.wait(), timeout=rem)
        except asyncio.TimeoutError:
            return
        left = (started_at + PRESENCE_INTERVAL_S) - self.gateway.clock()
        if left > 0.002:
            await asyncio.sleep(left)

    async def close(self) -> None:
        self._closed = True
        self.gateway.unsubscribe_commands(self._on_command)
        self.gateway.unsubscribe_events(self._on_event)
        tasks = list(self._tasks.values())
        self._tasks.clear()
        for t in tasks:
            t.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
