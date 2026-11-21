"""Full-parity Ainekio V2 MuJoCo simulator bridged to Body Control & Megameal.

Runs the real compiled ESP32-P4 firmware (`VirtualBody` / `libgait_native.so`)
against the real MuJoCo V2 four-bar CAD plant (`GaitEnvironment`) at 500 Hz,
connects to Body Control (`Master/gateway`) over authentic `protocol-v1`,
bridges 50 Hz pose/face/speaker/camera/mic/interactions with Megameal's 3D
world (`/__megameal-dev-bridge`), and records synchronized RL rollouts.
"""

from __future__ import annotations

import argparse
import asyncio
from collections import deque
import hashlib
import json
import logging
import math
from pathlib import Path
import struct
import time
from typing import Any

import mujoco
import numpy as np
from websockets.legacy.client import connect

from protocol.binary_helpers import (
    AUDIO_PAYLOAD_BYTES,
    CAMERA_JPEG_FRAME_TYPE,
    MIC_PCM_FRAME_TYPE,
    SPEAKER_PCM_FRAME_TYPE,
    decode_binary_frame,
    encode_binary_frame,
)

from .environment import EnvironmentConfig, GaitEnvironment
from .native import VirtualBody

LOGGER = logging.getLogger("ainekio.virtual_robot_bridge")

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_GATEWAY_URL = "ws://127.0.0.1:8790/robot"
DEFAULT_MEGAMEAL_URL = "ws://127.0.0.1:4321/__megameal-dev-bridge"
DEFAULT_MEGAMEAL_PORT_CANDIDATES = (4321, 4322, 4323, 4324, 4325)
DEFAULT_VIRTUAL_ROBOT_ID = "ainekio-v2-sim"
DEFAULT_TOKEN_FILE = REPO_ROOT / "build/gateway/physical/robot-tokens.json"
DEFAULT_RECORDINGS_DIR = REPO_ROOT / "build/neural-gait/virtual-recordings"
DEFAULT_ARENA_GEOMETRY = (
    REPO_ROOT.parent / "Merkin/apps/game.megameal/src/levels/v2-lab/arenaGeometry.json"
)

# Megameal binary bridge tags (robot-bridge-bin-v1)
BRIDGE_BIN_FACE_RGBA = 0x01
BRIDGE_BIN_CAMERA_JPEG = 0x02
BRIDGE_BIN_SPEAKER_PCM = 0x03
BRIDGE_BIN_MIC_PCM = 0x04

CAMERA_ORIGIN_STREAM = 0
CAMERA_ORIGIN_REQUEST = 1
CAMERA_ORIGIN_AUDIO = 2

RES_CODE_TO_NAME = {
    0: "QVGA",
    1: "VGA",
    2: "XGA",
    3: "960P",
    4: "FHD",
    5: "AUTO",
}
RES_NAME_TO_CODE = {v: k for k, v in RES_CODE_TO_NAME.items()}


def load_arena_scenario(geometry_path: Path | None) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Convert shared Megameal/MuJoCo arenaGeometry.json into a GaitEnvironment scenario."""
    if geometry_path is None or not geometry_path.exists():
        return None, None
    data = json.loads(geometry_path.read_text(encoding="utf-8"))
    geoms = []
    for item in data.get("geoms", []):
        raw_kind = item.get("kind", "block")
        kind = (
            raw_kind
            if raw_kind in {"rock", "block", "wall", "friction_patch"}
            else ("rock" if raw_kind == "ellipsoid" else "block")
        )
        entry = {
            "id": str(item.get("id", f"geom_{len(geoms)}")),
            "kind": kind,
            "position_m": [float(v) for v in item["position_m"]],
            "size_m": [float(v) for v in item["size_m"]],
            "rpy_deg": [float(v) for v in item.get("rpy_deg", [0.0, 0.0, 0.0])],
        }
        if "friction" in item:
            entry["friction"] = float(item["friction"])
        geoms.append(entry)
    scenario = {
        "id": str(data.get("id", "megameal_v2_lab")),
        "weight": 1.0,
        "geoms": geoms,
        "friction": float(data.get("friction", 0.85)),
    }
    return scenario, data


def resolve_robot_credentials(
    robot_id: str | None,
    token: str | None,
    token_file: Path,
) -> tuple[str, str]:
    """Resolve dedicated virtual robot credentials without colliding with physical robots."""
    target_id = robot_id or DEFAULT_VIRTUAL_ROBOT_ID
    if token:
        return target_id, token
    if token_file.exists():
        stored = json.loads(token_file.read_text(encoding="utf-8"))
        tokens = stored.get("tokens", stored) if isinstance(stored, dict) else {}
        if isinstance(tokens, dict) and target_id in tokens:
            entry = tokens[target_id]
            tok = entry.get("token") if isinstance(entry, dict) else entry
            if isinstance(tok, str) and tok:
                return target_id, tok
        # Provision a dedicated token for the virtual robot alongside existing physical robots
        # so physical and virtual robots can stay connected to Body Control simultaneously.
        from gateway.security import RobotTokenStore

        store = RobotTokenStore(token_file)
        generated = store.generate(target_id)
        LOGGER.info(
            "Provisioned dedicated virtual robot token for %s in %s",
            target_id,
            token_file,
        )
        return target_id, generated
    raise RuntimeError(
        f"No robot credentials found. Pass --robot-id and --token, or ensure {token_file} exists."
    )


def encode_bridge_face_rgba(width: int, height: int, seq: int, rgba_bytes: bytes) -> bytes:
    header = struct.pack("<BHHIB", BRIDGE_BIN_FACE_RGBA, width, height, seq & 0xFFFFFFFF, 0)
    return header + rgba_bytes


def encode_bridge_speaker_pcm(counter: int, volume_percent: int, pcm_bytes: bytes) -> bytes:
    header = struct.pack("<BIB", BRIDGE_BIN_SPEAKER_PCM, counter & 0xFFFFFFFF, volume_percent & 0xFF)
    return header + pcm_bytes


def decode_bridge_camera_jpeg(payload: bytes) -> dict[str, Any] | None:
    if len(payload) < 10 or payload[0] != BRIDGE_BIN_CAMERA_JPEG:
        return None
    _, origin_code, res_code, _reserved, origin_id = struct.unpack("<BBHHI", payload[:10])
    jpeg = payload[10:]
    if len(jpeg) < 4 or not jpeg.startswith(b"\xff\xd8") or not jpeg.endswith(b"\xff\xd9"):
        return None
    return {
        "origin_code": origin_code,
        "res": RES_CODE_TO_NAME.get(res_code, "QVGA"),
        "origin_id": origin_id,
        "jpeg": jpeg,
    }


def decode_bridge_mic_pcm(payload: bytes) -> tuple[int, int, bytes] | None:
    if len(payload) != 6 + AUDIO_PAYLOAD_BYTES or payload[0] != BRIDGE_BIN_MIC_PCM:
        return None
    _, counter, flags = struct.unpack("<BIB", payload[:6])
    return counter, flags, payload[6:]


class EpisodeRecorder:
    """Synchronized 50 Hz MuJoCo + sensor + camera rollout recorder for RL refinement."""

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.active = False
        self.episode_id: str | None = None
        self.episode_dir: Path | None = None
        self.frames_dir: Path | None = None
        self._fp = None
        self.step_count = 0
        self.camera_frame_count = 0
        self.started_at = 0.0
        self._start_xy: list[float] | None = None
        self._last_xy: list[float] | None = None
        self._stall_steps = 0

    def start(self, label: str, metadata: dict[str, Any]) -> dict[str, Any]:
        if self.active:
            self.stop()
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        safe_label = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in (label or "rollout"))[:40]
        self.episode_id = f"{stamp}_{safe_label}"
        self.episode_dir = self.base_dir / self.episode_id
        self.frames_dir = self.episode_dir / "frames"
        self.frames_dir.mkdir(parents=True, exist_ok=True)
        (self.episode_dir / "metadata.json").write_text(
            json.dumps({"episode_id": self.episode_id, **metadata}, indent=2) + "\n",
            encoding="utf-8",
        )
        self._fp = (self.episode_dir / "telemetry.jsonl").open("w", encoding="utf-8")
        self.step_count = 0
        self.camera_frame_count = 0
        self.started_at = time.monotonic()
        self._start_xy = None
        self._last_xy = None
        self._stall_steps = 0
        self.active = True
        LOGGER.info("Started rollout recording %s in %s", self.episode_id, self.episode_dir)
        return self.status()

    def record_camera(self, jpeg: bytes) -> str | None:
        if not self.active or self.frames_dir is None:
            return None
        filename = f"frame_{self.camera_frame_count:06d}.jpg"
        (self.frames_dir / filename).write_bytes(jpeg)
        self.camera_frame_count += 1
        return f"frames/{filename}"

    def record_step(self, row: dict[str, Any]) -> None:
        if not self.active or self._fp is None:
            return
        pos = row.get("root_pos_mj")
        if isinstance(pos, list) and len(pos) >= 2:
            if self._start_xy is None:
                self._start_xy = [float(pos[0]), float(pos[1])]
            self._last_xy = [float(pos[0]), float(pos[1])]
        if row.get("stalled_mask"):
            self._stall_steps += 1
        self._fp.write(json.dumps(row, separators=(",", ":")) + "\n")
        self.step_count += 1
        if self.step_count % 50 == 0:
            self._fp.flush()

    def stop(self) -> dict[str, Any]:
        if not self.active:
            return self.status()
        duration_s = max(0.0, time.monotonic() - self.started_at)
        distance_m = 0.0
        if self._start_xy is not None and self._last_xy is not None:
            distance_m = math.hypot(
                self._last_xy[0] - self._start_xy[0],
                self._last_xy[1] - self._start_xy[1],
            )
        if self._fp is not None:
            self._fp.flush()
            self._fp.close()
            self._fp = None
        summary = {
            "episode_id": self.episode_id,
            "steps": self.step_count,
            "camera_frames": self.camera_frame_count,
            "duration_s": round(duration_s, 3),
            "displacement_m": round(distance_m, 4),
            "stall_steps": self._stall_steps,
            "path": str(self.episode_dir),
        }
        if self.episode_dir is not None:
            (self.episode_dir / "summary.json").write_text(
                json.dumps(summary, indent=2) + "\n",
                encoding="utf-8",
            )
        self.active = False
        LOGGER.info("Stopped rollout recording %s (%d steps)", self.episode_id, self.step_count)
        return self.status()

    def status(self) -> dict[str, Any]:
        return {
            "active": self.active,
            "episodeId": self.episode_id or "",
            "steps": self.step_count,
            "cameraFrames": self.camera_frame_count,
            "path": str(self.episode_dir) if self.episode_dir else "",
        }


class VirtualRobotSimulatorBridge:
    """Full-parity MuJoCo V2 robot connected simultaneously to Body Control & Megameal."""

    def __init__(
        self,
        *,
        gateway_url: str | None,
        megameal_url: str | None,
        robot_id: str,
        token: str,
        arena_geometry_path: Path | None = DEFAULT_ARENA_GEOMETRY,
        recordings_dir: Path = DEFAULT_RECORDINGS_DIR,
        include_assembly: bool = True,
        collision_profile: str = "locomotion",
        real_time: bool = True,
    ) -> None:
        self.gateway_url = gateway_url
        self.megameal_url = megameal_url
        self.robot_id = robot_id
        self.token = token
        self.real_time = real_time

        scenario, self.arena_data = load_arena_scenario(arena_geometry_path)
        config = EnvironmentConfig(
            scenarios=[scenario] if scenario is not None else [],
            collision_profile=collision_profile,
            imu_prehistory_s=0.5,
        )
        self.env = GaitEnvironment(
            config,
            include_assembly=include_assembly,
            include_visuals=False,
        )
        self.env.reset(options={"scenario_id": scenario["id"]} if scenario else None)
        self.executor = VirtualBody(
            self.env.body_model,
            self.env.config.reference_joint_deg,
            joint_speed_deg_s=self.env.config.joint_speed_deg_s,
            balance=self.env.config.balance_enabled,
            heading_feedback=self.env.config.heading_feedback_enabled,
            balance_tuning=self.env.config.balance_tuning,
            oscillator_hz=self.env.config.pwm_oscillator_hz,
            frequency_hz=self.env.config.pwm_frequency_hz,
            now_us=self.now_us(),
            full_parity=True,
        )
        self.torso_body_id = int(self.env.model.body("torso").id)
        self.recorder = EpisodeRecorder(recordings_dir)

        # Connection state
        self.gateway_ws = None
        self.gateway_epoch: int | None = None
        self.gateway_connected = False
        self._last_gateway_rx_s = 0.0
        self.megameal_ws = None
        self.megameal_connected = False
        self._running = False

        # Peripheral / sensor runtime state (default live OV5647 preview on so
        # Body Control's camera view works immediately; Body Control can toggle/reconfigure anytime)
        self.camera_enabled = True
        self.camera_fps = 5
        self.camera_res = "QVGA"
        self.camera_snapshot_res = "VGA"
        self.camera_counter = 1
        self.last_camera_file: str | None = None

        self.mic_enabled = False
        self.mic_gate = "open"
        self.mic_capturing = False
        self.mic_utterance_id = 0
        self.mic_utterance_started_us = 0
        self.mic_utterance_wake = False
        self.mic_counter = 1
        self.mic_rms = 0.0
        self.mic_peak = 0.0

        self.speaker_volume_percent = 80
        self.speaker_active_seq: int | None = None
        self.speaker_ending = False
        self.speaker_queue: deque[tuple[int, bytes]] = deque()
        self.speaker_drain_until_s = 0.0
        self.speaker_rms = 0.0
        self.external_speech = False
        self.external_speech_until_s = 0.0

        # Face tracking
        self.face_name = "default"
        self.face_token = ""
        self.face_seq = 0
        self._last_face_digest = b""
        self._last_face_sent_s = 0.0

        # Interactive physics perturbations from Megameal player
        self.active_wrench = np.zeros(6, dtype=np.float64)
        self.wrench_until_s = 0.0
        self.pinned_joints: dict[int, float] = {}  # joint_index -> locked qpos rad
        self.battery_voltage = 8.15
        self._last_output: dict[str, Any] = {}
        self._last_metrics: dict[str, Any] = {}
        self._last_telemetry_packet: dict[str, Any] = {}
        self._last_status_s = 0.0
        self._last_heartbeat_s = 0.0
        self._step_index = 0

    def now_us(self) -> int:
        return round(self.env.device_time_us())

    def close(self) -> None:
        self._running = False
        if self.recorder.active:
            self.recorder.stop()
        if self.executor is not None and not self.executor.closed:
            self.executor.close()
        self.env.close()

    def _apply_external_interactions(self) -> None:
        now = time.monotonic()
        if now <= self.wrench_until_s:
            if self.env.scenario is None:
                self.env.data.xfrc_applied[self.torso_body_id, :] = self.active_wrench
            else:
                self.env.data.xfrc_applied[self.torso_body_id, :] += self.active_wrench
        elif self.env.scenario is None:
            self.env.data.xfrc_applied[self.torso_body_id, :] = 0.0

        # Enforce any player-pinned/jammed joints directly on MuJoCo qpos/qvel on every
        # 500 Hz substep so the real 4th-wire feedback path measures genuine shaft stall & I2t.
        for joint_idx, locked_rad in self.pinned_joints.items():
            qadr = int(self.env.qadr[joint_idx])
            vadr = int(self.env.vadr[joint_idx])
            self.env.data.qpos[qadr] = locked_rad
            self.env.data.qvel[vadr] = 0.0

    def step_once(self) -> dict[str, Any]:
        """Advance MuJoCo + real P4 firmware by one 50 Hz control frame (20 ms)."""
        now_wall = time.monotonic()
        if self.external_speech and now_wall >= self.external_speech_until_s:
            self.external_speech = False
        speaker_busy = (
            self.speaker_active_seq is not None
            or len(self.speaker_queue) > 0
            or now_wall < self.speaker_drain_until_s
        )
        if not speaker_busy:
            self.speaker_rms = 0.0

        self.executor.set_media_state(
            camera_ready=self.megameal_connected,
            microphone_ready=True,
            speaker_ready=True,
            wake_ready=True,
            display_ready=True,
            capturing=self.mic_capturing,
            speaker_busy=speaker_busy,
            external_speech=self.external_speech or speaker_busy,
            mic_rms=self.mic_rms,
            mic_peak=self.mic_peak,
            battery_voltage=self.battery_voltage,
        )

        # Apply active external wrenches / pinned joints inside every 500 Hz MuJoCo substep
        metrics, output = self.env.advance_body(
            self.executor,
            substep_hook=self._apply_external_interactions,
        )
        # Re-enforce pinned joints after MuJoCo step so they stay mechanically locked
        if self.pinned_joints:
            for joint_idx, locked_rad in self.pinned_joints.items():
                self.env.data.qpos[int(self.env.qadr[joint_idx])] = locked_rad
                self.env.data.qvel[int(self.env.vadr[joint_idx])] = 0.0
            mujoco.mj_forward(self.env.model, self.env.data)

        self._last_metrics = metrics
        self._last_output = output
        self._step_index += 1

        # Record synchronized 50 Hz rollout sample if active
        if self.recorder.active:
            foot = self.env.foot_measurements()
            self.recorder.record_step(
                {
                    "step": self._step_index,
                    "sim_time_s": round(float(self.env.data.time), 5),
                    "device_us": self.now_us(),
                    "root_pos_mj": [round(float(v), 5) for v in self.env.data.qpos[:3]],
                    "root_quat_wxyz": [round(float(v), 5) for v in self.env.data.qpos[3:7]],
                    "qpos_joints_deg": [round(float(math.degrees(v)), 3) for v in self.env.data.qpos[self.env.qadr]],
                    "qvel_joints_deg_s": [round(float(math.degrees(v)), 3) for v in self.env.data.qvel[self.env.vadr]],
                    "commanded_deg": [round(float(v), 3) for v in output["logical_angles"]],
                    "measured_deg": [round(float(v), 3) for v in self.env.feedback_angles],
                    "imu_orientation_wxyz": [round(float(v), 5) for v in self.env.imu_sample[:4]],
                    "imu_accel_m_s2": [round(float(v), 4) for v in self.env.imu_sample[4:7]],
                    "imu_gyro_rad_s": [round(float(v), 4) for v in self.env.imu_sample[7:10]],
                    "foot_contact": [bool(v) for v in foot["contact"]],
                    "foot_clearance_m": [round(float(v), 5) for v in foot["clearance_m"]],
                    "slip_speed_sq": round(float(metrics.get("contact_slip_speed_squared_m2_s2", 0.0)), 6),
                    "stalled_mask": int(self.env.jammed),
                    "armed": bool(output.get("armed", False)),
                    "pinned_joints": sorted(self.pinned_joints.keys()),
                    "face_name": self.face_name,
                    "camera_frame": self.last_camera_file,
                }
            )
            self.last_camera_file = None
        return output

    def build_megameal_state(self) -> dict[str, Any]:
        """Build the 50 Hz JSON state snapshot sent to Megameal's Three.js V2 actor."""
        pos_mj = self.env.data.qpos[:3]
        quat_mj = self.env.data.qpos[3:7]  # w, x, y, z
        joints_deg = np.rad2deg(self.env.data.qpos[self.env.qadr]).tolist()
        commanded_deg = (
            self._last_output["logical_angles"].tolist()
            if "logical_angles" in self._last_output
            else joints_deg
        )
        measured_deg = self.env.feedback_angles.tolist()
        foot = self.env.foot_measurements()

        # Convert MuJoCo (w, x, y, z) to Euler roll/pitch/yaw in degrees for HUD
        w, x, y, z = (float(quat_mj[0]), float(quat_mj[1]), float(quat_mj[2]), float(quat_mj[3]))
        roll = math.degrees(math.atan2(2.0 * (w * x + y * z), 1.0 - 2.0 * (x * x + y * y)))
        pitch = math.degrees(math.asin(max(-1.0, min(1.0, 2.0 * (w * y - z * x)))))
        yaw = math.degrees(math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z)))

        return {
            "type": "robot:state",
            "robotId": self.robot_id,
            "model": "v2-12servo",
            "timestampMs": int(time.time() * 1000),
            "simTimeS": round(float(self.env.data.time), 4),
            "gatewayConnected": self.gateway_connected,
            "armed": bool(self._last_output.get("armed", False)),
            "enabledMask": int(self._last_output.get("enabled_mask", 0)),
            "stalledMask": int(self.env.jammed),
            "pinnedJoints": sorted(self.pinned_joints.keys()),
            # Canonical MuJoCo coordinates (+X fwd, +Y left, +Z up)
            "rootPosMj": [round(float(pos_mj[0]), 5), round(float(pos_mj[1]), 5), round(float(pos_mj[2]), 5)],
            "rootQuatMjWxyz": [round(w, 5), round(x, 5), round(y, 5), round(z, 5)],
            # 12 joints in canonical joints_v2 order: RL(0..2), RR(3..5), FL(6..8), FR(9..11)
            "jointsDeg": [round(float(v), 3) for v in joints_deg],
            "commandedDeg": [round(float(v), 3) for v in commanded_deg],
            "measuredDeg": [round(float(v), 3) for v in measured_deg],
            "footContacts": [bool(v) for v in foot["contact"]],
            "imu": {
                "rollDeg": round(roll, 2),
                "pitchDeg": round(pitch, 2),
                "yawDeg": round(yaw, 2),
                "accel": [round(float(v), 3) for v in self.env.imu_sample[4:7]],
                "gyro": [round(float(v), 3) for v in self.env.imu_sample[7:10]],
            },
            "face": {
                "name": self.face_name,
                "token": self.face_token,
                "talking": bool(self.speaker_active_seq is not None or len(self.speaker_queue) > 0),
                "listening": self.mic_capturing,
            },
            "camera": {
                "enabled": self.camera_enabled,
                "fps": self.camera_fps,
                "res": self.camera_res,
                "snapshotRes": self.camera_snapshot_res,
            },
            "microphone": {
                "enabled": self.mic_enabled,
                "gate": self.mic_gate,
                "capturing": self.mic_capturing,
                "externalSpeech": self.external_speech,
            },
            "speaker": {
                "volumePercent": self.speaker_volume_percent,
                "busy": bool(self.speaker_active_seq is not None or len(self.speaker_queue) > 0),
                "rms": round(self.speaker_rms, 4),
            },
            "batteryVoltage": round(self.battery_voltage, 2),
            "recording": self.recorder.status(),
        }

    async def _send_gateway_json(self, messages: list[Any]) -> None:
        ws = self.gateway_ws
        if ws is None or not self.gateway_connected:
            return
        try:
            for msg in messages:
                if msg is None:
                    continue
                await ws.send(msg if isinstance(msg, str) else json.dumps(msg))
        except Exception as exc:
            LOGGER.warning("Gateway JSON send failed; triggering reconnect: %s", exc)
            self.gateway_connected = False
            try:
                await ws.close()
            except Exception:
                pass

    async def _send_megameal_json(self, payload: dict[str, Any]) -> None:
        ws = self.megameal_ws
        if ws is None or not self.megameal_connected:
            return
        try:
            await ws.send(json.dumps(payload))
        except Exception:
            self.megameal_connected = False

    async def _send_megameal_binary(self, data: bytes) -> None:
        ws = self.megameal_ws
        if ws is None or not self.megameal_connected:
            return
        try:
            await ws.send(data)
        except Exception:
            self.megameal_connected = False

    async def _handle_media_actions(self, actions: list[dict[str, Any]]) -> None:
        for action in actions:
            kind = action.get("kind")
            if kind == "camera":
                self.camera_enabled = bool(action.get("enabled", False))
                self.camera_fps = int(action.get("fps", 0)) if self.camera_enabled else 0
                self.camera_res = str(action.get("res", self.camera_res))
                if "snapshot_res" in action:
                    self.camera_snapshot_res = str(action["snapshot_res"])
            elif kind == "snapshot":
                seq = int(action.get("seq", 0))
                await self._send_megameal_json(
                    {
                        "type": "robot:camera-request",
                        "origin": "request",
                        "originCode": CAMERA_ORIGIN_REQUEST,
                        "originId": seq,
                        "res": self.camera_snapshot_res,
                    }
                )
            elif kind == "microphone":
                self.mic_enabled = bool(action.get("on", False))
                self.mic_gate = str(action.get("gate", "open"))
                if not self.mic_enabled and self.mic_capturing:
                    await self._close_mic_utterance()
            elif kind == "speaker":
                self.speaker_volume_percent = int(action.get("volume_percent", 80))
            elif kind == "tts":
                op = action.get("op")
                seq = int(action.get("seq", 0))
                if op == "start":
                    if self.speaker_active_seq is not None:
                        await self._send_gateway_json(
                            [{"t": "cancelled", "seq": self.speaker_active_seq, "code": "stop"}]
                        )
                    self.speaker_active_seq = seq
                    self.speaker_ending = False
                    self.speaker_queue.clear()
                elif op == "end":
                    self.speaker_ending = True
                elif op == "cancel":
                    await self._cancel_speaker("stop")
            elif kind == "say":
                seq = int(action.get("seq", 0))
                await self._send_gateway_json([{"t": "done", "seq": seq}])
            elif kind == "external_speech":
                active = bool(action.get("active", False))
                duration_ms = int(action.get("ms", 800))
                self.external_speech = active
                self.external_speech_until_s = time.monotonic() + max(0.0, duration_ms / 1000.0)
            elif kind == "stop_media":
                await self._cancel_speaker("stop")
                await self._send_megameal_json({"type": "robot:audio-stop"})

    async def _cancel_speaker(self, code: str) -> None:
        self.speaker_queue.clear()
        self.speaker_ending = False
        self.speaker_drain_until_s = 0.0
        self.speaker_rms = 0.0
        if self.speaker_active_seq is not None:
            seq = self.speaker_active_seq
            self.speaker_active_seq = None
            await self._send_gateway_json([{"t": "cancelled", "seq": seq, "code": code}])

    async def _finish_speaker_if_drained(self) -> None:
        if (
            self.speaker_active_seq is not None
            and self.speaker_ending
            and not self.speaker_queue
            and time.monotonic() >= self.speaker_drain_until_s
        ):
            seq = self.speaker_active_seq
            self.speaker_active_seq = None
            self.speaker_ending = False
            self.external_speech = True
            self.external_speech_until_s = time.monotonic() + 0.8
            await self._send_gateway_json([{"t": "done", "seq": seq}])

    async def _open_mic_utterance(self, wake_word: bool = False) -> None:
        if self.mic_capturing or self.external_speech or self.speaker_active_seq is not None:
            return
        self.mic_capturing = True
        self.mic_utterance_id = self.mic_counter
        self.mic_utterance_started_us = self.now_us()
        self.mic_utterance_wake = wake_word
        events = [{"t": "event", "name": "vad_open", "origin_id": self.mic_utterance_id}]
        if wake_word:
            events.append({"t": "event", "name": "wake_word"})
        await self._send_gateway_json(events)

    async def _close_mic_utterance(self) -> None:
        if not self.mic_capturing:
            return
        utterance_id = self.mic_utterance_id
        duration_us = self.now_us() - self.mic_utterance_started_us
        self.mic_capturing = False
        await self._send_gateway_json(
            [{"t": "event", "name": "vad_close", "origin_id": utterance_id}]
        )
        if duration_us >= 300_000 and self.megameal_connected:
            await self._send_megameal_json(
                {
                    "type": "robot:camera-request",
                    "origin": "audio",
                    "originCode": CAMERA_ORIGIN_AUDIO,
                    "originId": utterance_id,
                    "res": self.camera_snapshot_res,
                }
            )

    async def _handle_megameal_message(self, raw: Any) -> None:
        if isinstance(raw, (bytes, bytearray)):
            data = bytes(raw)
            if not data:
                return
            tag = data[0]
            if tag == BRIDGE_BIN_CAMERA_JPEG:
                cam = decode_bridge_camera_jpeg(data)
                if cam is not None:
                    await self._forward_camera_jpeg(cam)
            elif tag == BRIDGE_BIN_MIC_PCM:
                decoded = decode_bridge_mic_pcm(data)
                if decoded is not None:
                    _counter, flags, pcm = decoded
                    await self._forward_mic_pcm(pcm, flags)
            return

        try:
            message = json.loads(raw)
        except Exception:
            return
        if not isinstance(message, dict):
            return
        msg_type = message.get("type")

        if msg_type == "robot:interact:wrench":
            force = message.get("forceMj", [0.0, 0.0, 0.0])
            torque = message.get("torqueMj", [0.0, 0.0, 0.0])
            duration_ms = max(20.0, min(5000.0, float(message.get("durationMs", 250.0))))
            self.active_wrench = np.array(
                [float(force[0]), float(force[1]), float(force[2]),
                 float(torque[0]), float(torque[1]), float(torque[2])],
                dtype=np.float64,
            )
            self.wrench_until_s = time.monotonic() + duration_ms / 1000.0
        elif msg_type == "robot:interact:pin-joint":
            joint_idx = int(message.get("jointIndex", -1))
            pinned = bool(message.get("pinned", False))
            if 0 <= joint_idx < 12:
                if pinned:
                    if "angleDeg" in message and message["angleDeg"] is not None:
                        rad = math.radians(float(message["angleDeg"]))
                    else:
                        rad = float(self.env.data.qpos[int(self.env.qadr[joint_idx])])
                    self.pinned_joints[joint_idx] = rad
                else:
                    self.pinned_joints.pop(joint_idx, None)
        elif msg_type == "robot:interact:clear-pins":
            self.pinned_joints.clear()
        elif msg_type == "robot:interact:reset-pose":
            self.pinned_joints.clear()
            self.active_wrench[:] = 0.0
            self.wrench_until_s = 0.0
            pos = message.get("positionMj")
            yaw = float(message.get("yawRad", 0.0))
            self.env.data.qvel[:] = 0.0
            if isinstance(pos, list) and len(pos) == 3:
                self.env.data.qpos[0] = float(pos[0])
                self.env.data.qpos[1] = float(pos[1])
                self.env.data.qpos[2] = float(pos[2])
            else:
                self.env.data.qpos[0] = 0.0
                self.env.data.qpos[1] = 0.0
                self.env.data.qpos[2] = 0.095
            self.env.data.qpos[3:7] = [math.cos(yaw * 0.5), 0.0, 0.0, math.sin(yaw * 0.5)]
            self.env.set_pose(self.env.config.reference_joint_deg)
            mujoco.mj_forward(self.env.model, self.env.data)
        elif msg_type == "robot:interact:mic-gate":
            capturing = bool(message.get("capturing", False))
            wake = bool(message.get("wakeWord", False))
            if capturing:
                await self._open_mic_utterance(wake_word=wake)
            else:
                await self._close_mic_utterance()
        elif msg_type == "robot:record:start":
            label = str(message.get("label", "megameal_v2"))
            self.recorder.start(
                label,
                {
                    "robot_id": self.robot_id,
                    "model": "v2-12servo",
                    "arena": self.arena_data.get("id") if self.arena_data else "flat",
                    "physics_hz": self.env.config.physics_hz,
                    "control_hz": self.env.config.control_hz,
                },
            )
        elif msg_type == "robot:record:stop":
            self.recorder.stop()

    async def _forward_camera_jpeg(self, cam: dict[str, Any]) -> None:
        jpeg = cam["jpeg"]
        if self.recorder.active:
            self.last_camera_file = self.recorder.record_camera(jpeg)
        if self.gateway_ws is None or not self.gateway_connected:
            return
        counter = self.camera_counter
        self.camera_counter = (self.camera_counter + 1) & 0xFFFFFFFF
        origin_code = cam["origin_code"]
        origin_id = int(cam["origin_id"])
        meta: dict[str, Any] = {
            "t": "cam_meta",
            "res": cam["res"],
            "fps": max(1, self.camera_fps) if origin_code == CAMERA_ORIGIN_STREAM else self.camera_fps,
            "counter_base": counter,
            "frame_completed_us": self.now_us(),
            "boot_id": 1,
        }
        if origin_code == CAMERA_ORIGIN_REQUEST:
            meta["origin"] = "request"
            meta["origin_id"] = origin_id
        elif origin_code == CAMERA_ORIGIN_AUDIO:
            meta["origin"] = "audio"
            meta["origin_id"] = origin_id
        try:
            await self.gateway_ws.send(json.dumps(meta))
            await self.gateway_ws.send(encode_binary_frame(CAMERA_JPEG_FRAME_TYPE, counter, jpeg))
            if origin_code == CAMERA_ORIGIN_REQUEST and origin_id > 0:
                await self.gateway_ws.send(json.dumps({"t": "done", "seq": origin_id}))
        except Exception as exc:
            LOGGER.warning("Camera JPEG forward to gateway failed: %s", exc)

    async def _forward_mic_pcm(self, pcm: bytes, flags: int) -> None:
        samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
        self.mic_rms = float(np.sqrt(np.mean(samples * samples)))
        self.mic_peak = float(np.max(np.abs(samples)))
        if self.external_speech or self.speaker_active_seq is not None:
            return
        if not self.mic_capturing:
            if flags & 0x01:
                await self._open_mic_utterance(wake_word=bool(flags & 0x02))
            else:
                return
        if self.gateway_ws is None or not self.gateway_connected:
            return
        counter = self.mic_counter
        self.mic_counter = (self.mic_counter + 1) & 0xFFFFFFFF
        try:
            await self.gateway_ws.send(encode_binary_frame(MIC_PCM_FRAME_TYPE, counter, pcm))
        except Exception as exc:
            LOGGER.warning("Mic PCM forward to gateway failed: %s", exc)

    async def _gateway_loop(self) -> None:
        if not self.gateway_url:
            return
        while self._running:
            try:
                LOGGER.info("Connecting virtual V2 body %s to Body Control at %s", self.robot_id, self.gateway_url)
                async with connect(self.gateway_url, ping_interval=None, max_size=2 * 1024 * 1024) as ws:
                    self.gateway_ws = ws
                    self.gateway_connected = False
                    hello = self.executor.hello(self.robot_id, self.token, self.now_us())
                    await ws.send(json.dumps(hello))
                    raw_welcome = await ws.recv()
                    welcome = json.loads(raw_welcome)
                    if welcome.get("t") != "welcome":
                        raise RuntimeError(f"Body Control rejected virtual V2 hello: {welcome}")
                    self.gateway_epoch = int(welcome["epoch"])
                    self.executor.reset(self.now_us(), self.gateway_epoch)
                    replies = self.executor.receive(raw_welcome, self.gateway_epoch, self.now_us())
                    self._last_gateway_rx_s = time.monotonic()
                    self.gateway_connected = True
                    LOGGER.info(
                        "Virtual V2 body authenticated with Body Control (epoch=%d)",
                        self.gateway_epoch,
                    )
                    if replies:
                        await self._send_gateway_json(replies)
                    await self._handle_media_actions(self.executor.media_actions())
                    await self._send_gateway_json([self.executor.status(self.now_us())])

                    async for raw in ws:
                        self._last_gateway_rx_s = time.monotonic()
                        if isinstance(raw, (bytes, bytearray)):
                            frame = decode_binary_frame(bytes(raw))
                            if frame.frame_type == SPEAKER_PCM_FRAME_TYPE:
                                pcm = bytes(raw)[5:]
                                samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
                                self.speaker_rms = float(np.sqrt(np.mean(samples * samples)))
                                self.speaker_queue.append((frame.counter, pcm))
                                now_w = time.monotonic()
                                self.speaker_drain_until_s = max(self.speaker_drain_until_s, now_w) + 0.02
                                await self._send_megameal_binary(
                                    encode_bridge_speaker_pcm(
                                        frame.counter, self.speaker_volume_percent, pcm
                                    )
                                )
                            continue
                        replies = self.executor.receive(raw, self.gateway_epoch, self.now_us())
                        if replies:
                            await self._send_gateway_json(replies)
                            # Mirror controller.c::control_current() — if admission went stale,
                            # tear down the socket so Body Control issues a fresh welcome/epoch.
                            if any(
                                isinstance(r, dict) and r.get("t") == "nak" and r.get("code") == "stale"
                                for r in replies
                            ):
                                LOGGER.warning("Virtual V2 admission went stale; reconnecting to Body Control")
                                await ws.close()
                                break
                        await self._handle_media_actions(self.executor.media_actions())
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                LOGGER.warning("Body Control connection closed: %s", exc)
            finally:
                if self.gateway_epoch is not None and not self.executor.closed:
                    self.executor.connection_lost(self.gateway_epoch)
                self.gateway_connected = False
                self.gateway_ws = None
            if self._running:
                await asyncio.sleep(1.5)

    async def _megameal_loop(self) -> None:
        if not self.megameal_url:
            return
        candidate_urls = (
            [
                f"ws://127.0.0.1:{port}/__megameal-dev-bridge"
                for port in DEFAULT_MEGAMEAL_PORT_CANDIDATES
            ]
            if self.megameal_url == DEFAULT_MEGAMEAL_URL
            else [self.megameal_url]
        )
        candidate_index = 0
        while self._running:
            target_url = candidate_urls[candidate_index % len(candidate_urls)]
            try:
                LOGGER.info("Connecting virtual V2 bridge to Megameal at %s", target_url)
                async with connect(target_url, ping_interval=None, max_size=4 * 1024 * 1024) as ws:
                    self.megameal_ws = ws
                    await ws.send(
                        json.dumps(
                            {
                                "type": "bridge:hello",
                                "role": "robot-sim",
                                "sessionId": self.robot_id,
                            }
                        )
                    )
                    self.megameal_connected = True
                    self._last_face_digest = b""  # Force fresh face upload on connect
                    LOGGER.info("Connected to Megameal relay at %s", target_url)
                    if self.arena_data is not None:
                        await self._send_megameal_json(
                            {"type": "robot:arena-meta", "arena": self.arena_data}
                        )
                    async for raw in ws:
                        await self._handle_megameal_message(raw)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                LOGGER.warning("Megameal bridge connection closed (%s): %s", target_url, exc)
                if len(candidate_urls) > 1:
                    candidate_index = (candidate_index + 1) % len(candidate_urls)
            finally:
                self.megameal_connected = False
                self.megameal_ws = None
            if self._running:
                await asyncio.sleep(0.35 if len(candidate_urls) > 1 and candidate_index != 0 else 1.5)

    async def _simulation_loop(self) -> None:
        period_s = 1.0 / float(self.env.config.control_hz)
        next_tick = time.monotonic()
        while self._running:
            output = self.step_once()
            now_us = self.now_us()
            now_wall = time.monotonic()

            # Drain speaker chunks (paced roughly at real-time 20ms playback)
            if self.speaker_queue:
                self.speaker_queue.popleft()
            await self._finish_speaker_if_drained()

            # Render exact P4 ST7789 face at up to 20 Hz, transmit only when pixels change
            talking = self.speaker_active_seq is not None or len(self.speaker_queue) > 0
            should_render_face = (now_wall - self._last_face_sent_s) >= 0.05
            face_rgba: bytes | None = None
            if should_render_face:
                frame = self.executor.face_frame(
                    now_us // 1000,
                    talking=talking,
                    capturing=self.mic_capturing,
                    render_rgba=self.megameal_connected,
                )
                self.face_name = frame["name"]
                self.face_token = frame["token"]
                if frame["rgba"] is not None:
                    raw_rgba = frame["rgba"].tobytes()
                    digest = hashlib.blake2b(raw_rgba, digest_size=12).digest()
                    if digest != self._last_face_digest:
                        self._last_face_digest = digest
                        self.face_seq += 1
                        face_rgba = raw_rgba
                self._last_face_sent_s = now_wall

            # Mirror controller.c::ainekio_p4_controller_supervise(): if Body Control
            # heartbeat stops arriving (>3.8s), tear down and reconnect for a fresh epoch.
            if (
                self.gateway_connected
                and self._last_gateway_rx_s > 0.0
                and (now_wall - self._last_gateway_rx_s) >= 3.8
            ):
                LOGGER.warning("Control heartbeat lost (>3.8s); reconnecting to Body Control")
                ws = self.gateway_ws
                self.gateway_connected = False
                if ws is not None:
                    try:
                        await ws.close()
                    except Exception:
                        pass

            # Publish authentic P4 telemetry & events to Body Control
            if self.gateway_connected:
                messages = list(output.get("messages", []))
                telemetry = self.executor.telemetry(now_us)
                self._last_telemetry_packet = telemetry
                messages.append(telemetry)
                if (now_wall - self._last_status_s) >= 1.0:
                    self._last_status_s = now_wall
                    messages.append(self.executor.status(now_us))
                    health = self.executor.feedback_health(now_us)
                    if health is not None:
                        messages.append(health)
                if (now_wall - self._last_heartbeat_s) >= 1.0:
                    self._last_heartbeat_s = now_wall
                    messages.append(self.executor.heartbeat(now_us, pong=False))
                await self._send_gateway_json(messages)

            # Publish live V2 state + face frame to Megameal
            if self.megameal_connected:
                await self._send_megameal_json(self.build_megameal_state())
                if face_rgba is not None:
                    await self._send_megameal_binary(
                        encode_bridge_face_rgba(320, 170, self.face_seq, face_rgba)
                    )

            if self.real_time:
                next_tick += period_s
                delay = next_tick - time.monotonic()
                if delay > 0:
                    await asyncio.sleep(delay)
                else:
                    next_tick = time.monotonic()
                    await asyncio.sleep(0)
            else:
                await asyncio.sleep(0)

    async def run(self) -> None:
        self._running = True
        tasks = [
            asyncio.create_task(self._simulation_loop(), name="mujoco-v2-sim"),
            asyncio.create_task(self._gateway_loop(), name="body-control-link"),
            asyncio.create_task(self._megameal_loop(), name="megameal-bridge-link"),
        ]
        try:
            await asyncio.gather(*tasks)
        finally:
            self._running = False
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the full-parity MuJoCo Ainekio V2 simulator bridged to Body Control and Megameal."
    )
    parser.add_argument("--gateway-url", default=DEFAULT_GATEWAY_URL, help="Body Control /robot WebSocket URL")
    parser.add_argument("--megameal-url", default=DEFAULT_MEGAMEAL_URL, help="Megameal dev-bridge WebSocket URL")
    parser.add_argument("--robot-id", default=None, help="Robot ID registered in Body Control")
    parser.add_argument("--token", default=None, help="Robot auth token for Body Control")
    parser.add_argument("--token-file", type=Path, default=DEFAULT_TOKEN_FILE)
    parser.add_argument("--arena-geometry", type=Path, default=DEFAULT_ARENA_GEOMETRY)
    parser.add_argument("--recordings-dir", type=Path, default=DEFAULT_RECORDINGS_DIR)
    parser.add_argument(
        "--collision-profile",
        choices=("locomotion", "assembly"),
        default="locomotion",
        help="MuJoCo collision profile (locomotion keeps exact CAD mass/inertia at 50 Hz real time)",
    )
    parser.add_argument("--no-assembly", action="store_true", help="Skip CAD assembly inertia/meshes")
    parser.add_argument("--no-gateway", action="store_true", help="Run connected to Megameal only without Body Control")
    parser.add_argument("--log-level", default="INFO")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    if args.no_gateway:
        robot_id = args.robot_id or "ainekio-v2-virtual"
        token = args.token or "local-offline-sim-token"
        gateway_url = None
    else:
        robot_id, token = resolve_robot_credentials(args.robot_id, args.token, args.token_file)
        gateway_url = args.gateway_url

    bridge = VirtualRobotSimulatorBridge(
        gateway_url=gateway_url,
        megameal_url=args.megameal_url,
        robot_id=robot_id,
        token=token,
        arena_geometry_path=args.arena_geometry if args.arena_geometry.exists() else None,
        recordings_dir=args.recordings_dir,
        include_assembly=not args.no_assembly,
        collision_profile=args.collision_profile,
    )
    try:
        asyncio.run(bridge.run())
    except KeyboardInterrupt:
        LOGGER.info("Virtual V2 robot simulator interrupted; shutting down.")
    finally:
        bridge.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
