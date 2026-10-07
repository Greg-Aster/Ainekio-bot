from __future__ import annotations

import asyncio
import hmac
import inspect
import json
import math
import struct
import threading
import time
from collections.abc import AsyncIterable, Awaitable, Callable, Iterable, Mapping
from contextlib import nullcontext
from dataclasses import dataclass, field
from time import monotonic
from typing import Any, AsyncContextManager
from uuid import uuid4

from gateway.security import RobotTokenStore

from protocol.binary_helpers import (
    MAX_JPEG_BYTES,
    MIC_PCM_FRAME_TYPE,
    SPEAKER_PCM_FRAME_TYPE,
    encode_binary_frame,
)
from protocol.control_v1 import (
    BODY_CAPABILITIES_FEATURE,
    WALK_CONTROLS_FEATURE,
    LOCOMOTION_FEATURE,
    WALK_STEERING_FEATURE,
    RUN_GAIT_FEATURE,
    CRAB_GAIT_FEATURE,
    COMMAND_DEADLINE_FEATURE,
    CAMERA_PROFILES_FEATURE,
    CAMERA_ADAPTIVE_FEATURE,
    AUDIO_INPUT_FEATURE,
    BODY_CALIBRATION_FEATURE,
    STORAGE_CONTROL_FEATURE,
    ROBOT_SETTINGS_FEATURE,
    GATEWAY_SWITCHING_FEATURE,
    MOTION_SPEED_FEATURE,
    JOINT_SPEED_LIMIT_FEATURE,
    MAX_SEQUENCE,
    MOTION_PLAN_FEATURE,
    MOTION_PLAN_JOINT_MAP,
    PROTOCOL_VERSION,
    ProtocolValidationError,
    validate_binary_frame,
    validate_control_message,
)
from protocol.joints_v1 import joint_contract
from gateway.body_capabilities import body_command_available, body_commands, movement_command, CRAB_DIRECTIONS
from websockets.exceptions import ConnectionClosed


MAX_WEBSOCKET_MESSAGE_BYTES = MAX_JPEG_BYTES + 5
DEFAULT_PING_INTERVAL_SECONDS = 1.0
CONTROL_STALE_SECONDS = 4.0
BODY_CLOCK_FRESHNESS_SECONDS = 1.0
TTS_START_ACK_TIMEOUT_SECONDS = 2.0
SPEAKER_FRAME_SECONDS = 0.020
SPEAKER_PREBUFFER_FRAMES = 5

GatewayCallback = Callable[[dict[str, object]], Awaitable[None] | None]


class GatewayError(RuntimeError):
    pass


class RobotOfflineError(GatewayError):
    pass


class ActionExpiredError(GatewayError):
    pass


class GatewayClock:
    def __init__(
        self,
        *,
        monotonic_clock: Callable[[], float] = monotonic,
        wall_clock: Callable[[], float] = time.time,
    ) -> None:
        self._monotonic = monotonic_clock
        self._wall = wall_clock
        self._wall_offset = 0.0
        self._lock = threading.Lock()

    def monotonic(self) -> float:
        return self._monotonic()

    def wall_time(self) -> float:
        with self._lock:
            return self._wall() + self._wall_offset

    def jump_wall_clock(self, seconds: float) -> None:
        if not math.isfinite(seconds) or abs(seconds) > 10 * 365 * 86400:
            raise ValueError("wall clock jump is out of range")
        with self._lock:
            self._wall_offset += seconds

    @property
    def wall_offset(self) -> float:
        with self._lock:
            return self._wall_offset


@dataclass(frozen=True)
class GatewayServiceConfig:
    tokens: Mapping[str, str]
    profile: str = "home"
    max_action_age_ms: int = 2000
    ping_interval_s: float = DEFAULT_PING_INTERVAL_SECONDS

    def __post_init__(self) -> None:
        if self.profile not in {"home", "tether"}:
            raise ValueError("profile must be home or tether")
        if not 1 <= self.max_action_age_ms <= 60000:
            raise ValueError("max_action_age_ms must be between 1 and 60000")
        if not 0.01 <= self.ping_interval_s <= 60.0:
            raise ValueError("ping_interval_s must be between 0.01 and 60")


@dataclass
class PendingCommand:
    command: dict[str, object]
    needs_done: bool
    future: asyncio.Future[dict[str, object]]
    acknowledgement: asyncio.Future[dict[str, object]]
    acknowledged: bool = False


class GatewayConnection:
    def __init__(
        self,
        service: "GatewayService",
        websocket: Any,
        robot_id: str,
        epoch: int,
        features: tuple[str, ...] = (),
        transport: str = "lan",
        model: str = "v1-8servo",
        capabilities: Mapping[str, object] | None = None,
    ) -> None:
        self.service = service
        self.websocket = websocket
        self.robot_id = robot_id
        self.epoch = epoch
        self.features = features
        self.transport = transport
        self.model = model
        self.capabilities = dict(capabilities) if capabilities is not None else None
        self.body_clock_ms: int | None = None
        self.body_clock_received_at = 0.0
        self.body_clock_samples = 0
        self.body_clock_max_gap_ms = 0
        self.next_sequence = 1
        self.pending: dict[int, PendingCommand] = {}
        self.completed: dict[int, dict[str, object]] = {}
        self.last_status: dict[str, object] | None = None
        self.last_calibration: dict[str, object] | None = None
        self.last_storage: dict[str, object] | None = None
        self.last_motion_speed: dict[str, object] | None = None
        self.last_robot_settings: dict[str, object] | None = None
        self.mode = "normal"
        self.last_command: dict[str, object] | None = None
        self.profile = service.config.profile
        self.microphone_level = 0.0
        self.audio_input: dict[str, object] | None = None
        self.audio_input_received_at = 0.0
        self.connected_at = service.clock()
        self.last_control_at = self.connected_at
        self.last_sent_at = self.connected_at
        self.control_frames_received = 0
        self.json_pings_sent = 0
        self.last_control_type: str | None = None
        self.close_code: int | None = None
        self.close_reason: str | None = None
        self._send_lock = asyncio.Lock()
        self._speaker_lock = asyncio.Lock()
        self._cancel_code = "disconnect"

    def observe_body_clock(self, message: Mapping[str, object]) -> None:
        if COMMAND_DEADLINE_FEATURE not in self.features:
            return
        value = message.get("clock_ms")
        if type(value) is int and (self.body_clock_ms is None or value >= self.body_clock_ms):
            now = self.service.clock()
            if self.body_clock_ms is not None:
                gap_ms = round((now - self.body_clock_received_at) * 1000)
                self.body_clock_max_gap_ms = max(self.body_clock_max_gap_ms, gap_ms)
                if gap_ms >= BODY_CLOCK_FRESHNESS_SECONDS * 1000:
                    self.service._record_diagnostic({
                        "event": "body_clock_gap", "robot_id": self.robot_id,
                        "epoch": self.epoch, "clock_gap_ms": gap_ms,
                        "clock_advance_ms": value - self.body_clock_ms,
                        "body_clock_ms": value,
                    })
            self.body_clock_ms = value
            self.body_clock_received_at = now
            self.body_clock_samples += 1

    def clock_diagnostics(self) -> dict[str, object]:
        return {
            "body_clock_ms": self.body_clock_ms,
            "clock_age_ms": (round((self.service.clock() - self.body_clock_received_at) * 1000)
                             if self.body_clock_ms is not None else None),
            "clock_samples": self.body_clock_samples,
            "clock_max_gap_ms": self.body_clock_max_gap_ms,
        }

    def _deadline(self, received_at: float, validity_ms: int) -> int:
        now = self.service.clock()
        if self.body_clock_ms is None or now - self.body_clock_received_at >= BODY_CLOCK_FRESHNESS_SECONDS:
            raise ActionExpiredError("fresh body clock required before dispatch")
        age_ms = (now - received_at) * 1000.0
        remaining = min(1000, math.floor(validity_ms - age_ms)) - 5
        if remaining <= 0:
            raise ActionExpiredError("action validity exhausted before dispatch")
        # Both monotonic clocks advance while a sample is cached. Add only the
        # measured time since its receipt, leaving unknown network delay
        # uncompensated. Remaining upstream validity uses this same host instant.
        elapsed_ms = math.floor((now - self.body_clock_received_at) * 1000.0)
        return self.body_clock_ms + elapsed_ms + remaining

    async def send_control(self, message: Mapping[str, object]) -> None:
        validate_control_message(message)
        encoded = json.dumps(message, separators=(",", ":"))
        async with self._send_lock:
            await self.websocket.send(encoded)
            self.last_sent_at = self.service.clock()
            self.last_command = dict(message)

    async def send_command(
        self,
        command: Mapping[str, object],
        *,
        received_at: float,
        on_sequence: Callable[[int], AsyncContextManager[None] | None] | None = None,
        valid_for_ms: int | None = None,
    ) -> int:
        async with self._send_lock:
            validity_ms = self.service.config.max_action_age_ms
            if valid_for_ms is not None:
                if type(valid_for_ms) is not int or not 1 <= valid_for_ms <= 60000:
                    raise GatewayError("command validity must be between 1 and 60000 ms")
                validity_ms = min(validity_ms, valid_for_ms)
            age_ms = (self.service.clock() - received_at) * 1000.0
            if not math.isfinite(age_ms) or age_ms < 0 or age_ms > validity_ms:
                raise ActionExpiredError("action expired before sequence assignment")
            if self.websocket.closed:
                raise RobotOfflineError(f"robot {self.robot_id} is offline")
            if self.next_sequence > MAX_SEQUENCE:
                await self.websocket.close(code=1002, reason="sequence exhausted")
                raise GatewayError("session sequence space exhausted")

            message = dict(command)
            if message.get("t") == "speaker" and "speaker_volume_percent" not in (self.audio_input or {}):
                raise GatewayError("body firmware does not report saved speaker volume; update the robot firmware")
            if message.get("t") == "intent" and ("forward" in message or "turn" in message):
                if message.get("name") != "walk":
                    raise GatewayError("steering requires a walk command")
                if self.model != "v2-12servo" or not {LOCOMOTION_FEATURE, WALK_STEERING_FEATURE}.issubset(self.features):
                    raise GatewayError("body does not support composed steering (walk_steering_v1 required)")
            if ((message.get("t") == "mic" and "gain_db" in message) or
                (message.get("t") == "wake" and "threshold" in message)):
                if AUDIO_INPUT_FEATURE not in self.features:
                    raise GatewayError("body firmware does not support audio input adjustments")
                validate_control_message({**message, "seq": 1})
            if message.get("t") == "cam" and "snapshot_res" in message:
                if CAMERA_PROFILES_FEATURE not in self.features:
                    raise GatewayError("body does not support independent snapshot settings")
                if message["snapshot_res"] in {"AUTO", "960P", "FHD"} and CAMERA_ADAPTIVE_FEATURE not in self.features:
                    raise GatewayError("body does not support adaptive/high-resolution camera settings")
            if message.get("t") == "motion_speed" or "playback_rate" in message:
                if self.model != "v2-12servo" or MOTION_SPEED_FEATURE not in self.features:
                    raise GatewayError("body does not support saved motion speed")
                if "joint_speed_limit_deg_s" in message and JOINT_SPEED_LIMIT_FEATURE not in self.features:
                    raise GatewayError("body firmware does not support a configurable joint speed limit")
                validate_control_message({**message, "seq": 1})
                if "playback_rate" in message and (message.get("t") != "intent" or
                    message.get("name") not in {"sit", "stand", "emote"} or
                    message.get("asset") in {"run", *CRAB_DIRECTIONS}):
                    raise GatewayError("use walking controls for ongoing gaits")
            # V1 keeps its preprogrammed Run asset. V2 Run is the same ongoing
            # walking command with Speed above 100; feature admission follows.
            if self.model == "v2-12servo" and message.get("t") == "intent" and message.get("name") == "emote" and message.get("asset") == "run":
                message = {"t":"intent", "name":"walk", "dir":"fwd", "steps":0, "gait":"walk", "speed":150}
            if self.model == "v2-12servo" and CRAB_GAIT_FEATURE in self.features and message.get("t") == "intent" and message.get("name") == "emote" and message.get("asset") in CRAB_DIRECTIONS:
                message = {"t":"intent", "name":"walk", "dir":CRAB_DIRECTIONS[message["asset"]], "steps":0, "gait":"crab", "speed":50}
            if message.get("t") == "intent" and message.get("name") == "walk" and (
                message.get("steps") == 0 or any(key in message for key in
                    ("speed", "stride", "rate", "forward", "turn", "update", "gait", "speed_percent", "stride_percent", "motion_rate"))
            ):
                if self.model != "v2-12servo" or not {WALK_CONTROLS_FEATURE, LOCOMOTION_FEATURE}.intersection(self.features):
                    raise GatewayError("body does not support variable walking controls")
                if (message.get("steps") == 0 or "gait" in message or message.get("dir") != "fwd") and LOCOMOTION_FEATURE not in self.features:
                    raise GatewayError("body does not support ongoing directional locomotion")
                # Validate before allocating a sequence or creating pending work.
                validate_control_message({**message, "seq": 1})
                if "update" in message:
                    active = self.pending.get(message["update"])
                    if active is None or active.future.done() or active.command.get("name") != "walk" or "update" in active.command:
                        raise GatewayError("walk update does not identify an active walk")
                    if message.get("dir") != active.command.get("dir") or message.get("gait", "walk") != active.command.get("gait", "walk"):
                        raise GatewayError("finish the active walk before changing direction or gait")
            supported = body_commands(self.model, self.features, self.capabilities)
            if message.get("name") == "walk" and message.get("gait") == "crawl" and not body_command_available("crawl", supported):
                raise GatewayError("crawl is unavailable on this body")
            if message.get("name") == "walk" and (message.get("gait") == "run" or message.get("speed", 0) > 100):
                if RUN_GAIT_FEATURE not in self.features or not body_command_available("run", supported):
                    raise GatewayError("body does not support the bounding Run gait")
            if message.get("name") == "walk" and message.get("gait") == "crab":
                if CRAB_GAIT_FEATURE not in self.features or not body_command_available("crab", supported):
                    raise GatewayError("body does not support ongoing Crab")
            movement = movement_command(message)
            if movement is not None and not body_command_available(movement, supported):
                raise GatewayError(f"{movement} is unavailable on body {self.robot_id} ({self.model})")
            if self.model != "v1-8servo" and message.get("t") in {"servo", "limits", "pose_save", "cal_save"}:
                raise GatewayError("this body does not support the eight-servo calibration contract")
            if message.get("t") == "calibration" and (
                self.model != "v2-12servo" or BODY_CALIBRATION_FEATURE not in self.features
            ):
                raise GatewayError("body does not support twelve-joint calibration")
            if message.get("t") == "robot_settings" and (self.model != "v2-12servo" or ROBOT_SETTINGS_FEATURE not in self.features):
                raise GatewayError("Update the P4 firmware to manage robot settings here")
            if message.get("t") == "robot_settings" and message.get("op") == "network" and GATEWAY_SWITCHING_FEATURE not in self.features:
                saved = self.last_robot_settings
                if saved is None or saved["revision"] != message.get("revision"):
                    raise GatewayError("Read robot settings before editing this firmware's network profiles")
                if any(p["ssid"] == message.get("ssid") and p["index"] != message.get("index")
                       for p in saved["networks"]):
                    raise GatewayError("This firmware cannot switch computers on the same Wi-Fi; update the P4 firmware")
            if message.get("t") == "storage" and (
                self.model != "v2-12servo" or STORAGE_CONTROL_FEATURE not in self.features
            ):
                raise GatewayError("body does not support storage control")
            # Feature checks and validation precede sequence allocation: a
            # rejected operator request never creates pending device work.
            capability = {
                "cam": "camera", "snap": "camera", "mic": "microphone",
                "wake": "wake", "tts": "speaker", "speaker": "speaker", "profile": "profile", "state": "power", "storage": "storage",
            }.get(message.get("t"))
            if message.get("t") == "intent":
                capability = {"face": "display", "say": "speaker"}.get(message.get("name"))
            if self.model != "v1-8servo" and capability and (
                self.capabilities is None or self.capabilities.get(capability) is not True
            ):
                reasons = (self.capabilities or {}).get("reasons", {})
                reason = reasons.get(capability) if isinstance(reasons, dict) else None
                raise GatewayError(str(reason or f"{capability} is unavailable on this body"))
            validate_control_message({**message, "seq": 1})
            if COMMAND_DEADLINE_FEATURE in self.features:
                message["epoch"] = self.epoch
                if message.get("t") != "stop":
                    try:
                        message["deadline_ms"] = self._deadline(received_at, validity_ms)
                    except ActionExpiredError as error:
                        self.service._record_diagnostic({
                            **message, **self.clock_diagnostics(),
                            "event": "dispatch_rejected", "robot_id": self.robot_id,
                            "epoch": self.epoch, "error": str(error),
                            "action_age_ms": round(age_ms),
                        })
                        raise
            sequence = self.next_sequence
            self.next_sequence += 1
            message["seq"] = sequence
            validate_control_message(message)
            future: asyncio.Future[dict[str, object]] = (
                asyncio.get_running_loop().create_future()
            )
            acknowledgement: asyncio.Future[dict[str, object]] = (
                asyncio.get_running_loop().create_future()
            )
            self.pending[sequence] = PendingCommand(
                command=message,
                needs_done=_command_needs_done(message),
                future=future,
                acknowledgement=acknowledgement,
            )
            try:
                guard = on_sequence(sequence) if on_sequence is not None else None
                async with guard if guard is not None else nullcontext():
                    await asyncio.wait_for(self.websocket.send(json.dumps(message, separators=(",", ":"))), timeout=5.0)
            except Exception:
                self.pending.pop(sequence, None)
                raise
            self.last_sent_at = self.service.clock()
            await self.service._publish_command(
                {
                    "robot_id": self.robot_id,
                    "epoch": self.epoch,
                    **message,
                }
            )
            return sequence

    async def send_tts(
        self,
        pcm_stream: Iterable[bytes] | AsyncIterable[bytes],
        *,
        received_at: float,
        on_sequence: Callable[[int], AsyncContextManager[None] | None] | None = None,
    ) -> int:
        async with self._speaker_lock:
            start_sequence = await self.send_command(
                {"t": "tts", "op": "start"},
                received_at=received_at,
                on_sequence=on_sequence,
            )
            try:
                await self.wait_acknowledged(
                    start_sequence,
                    timeout=TTS_START_ACK_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError as error:
                try:
                    await self.send_command(
                        {"t": "tts", "op": "cancel"},
                        received_at=self.service.clock(),
                    )
                except Exception:
                    pass
                raise GatewayError(
                    f"robot {self.robot_id} did not acknowledge TTS start"
                ) from error
            counter = 0
            loop = asyncio.get_running_loop()
            lead = (SPEAKER_PREBUFFER_FRAMES - 1) * SPEAKER_FRAME_SECONDS
            next_frame_at = loop.time() - lead

            async def send_frame(payload: bytes) -> None:
                nonlocal counter, next_frame_at
                # Bound both initial prebuffer and catch-up after a slow source.
                # The scheduler clock is independent of host wall-clock tests.
                next_frame_at = max(next_frame_at, loop.time() - lead)
                await asyncio.sleep(max(0.0, next_frame_at - loop.time()))
                await self._send_speaker_frame(counter, payload, start_sequence=start_sequence)
                next_frame_at += SPEAKER_FRAME_SECONDS
                counter = (counter + 1) & 0xFFFFFFFF

            try:
                if isinstance(pcm_stream, AsyncIterable):
                    async for payload in pcm_stream:
                        await send_frame(payload)
                else:
                    for payload in pcm_stream:
                        await send_frame(payload)
                self._check_speaker_session(start_sequence)
                await self.send_command(
                    {"t": "tts", "op": "end"},
                    received_at=self.service.clock(),
                )
            except (Exception, asyncio.CancelledError):
                # Producer failure or caller cancellation must not leave the
                # device waiting forever for the remainder of this utterance.
                if start_sequence in self.pending and not self.websocket.closed:
                    try:
                        await self.send_command({"t": "tts", "op": "cancel"}, received_at=self.service.clock())
                    except Exception:
                        pass
                raise
            return start_sequence

    def _check_speaker_session(self, start_sequence: int) -> None:
        pending = self.pending.get(start_sequence)
        if (self.websocket.closed or self.service._connections.get(self.robot_id) is not self or
                self.service.clock() - self.last_control_at >= CONTROL_STALE_SECONDS):
            raise RobotOfflineError("speaker body connection is offline, replaced or stale")
        if pending is None or pending.future.done() or not pending.acknowledged:
            raise GatewayError("speaker stream was cancelled or completed")

    async def _send_speaker_frame(self, counter: int, payload: bytes, *, start_sequence: int) -> None:
        self._check_speaker_session(start_sequence)
        frame = encode_binary_frame(SPEAKER_PCM_FRAME_TYPE, counter, payload)
        async with self._send_lock:
            self._check_speaker_session(start_sequence)
            await self.websocket.send(frame)
            self.last_sent_at = self.service.clock()

    async def run(self) -> None:
        while True:
            now = self.service.clock()
            if now - self.last_sent_at >= self.service.config.ping_interval_s:
                await self.send_control({"t": "ping"})
                self.json_pings_sent += 1

            try:
                raw = await asyncio.wait_for(self.websocket.recv(), timeout=0.1)
            except asyncio.TimeoutError:
                continue
            if isinstance(raw, bytes):
                await self._handle_binary(raw)
                continue

            try:
                message = json.loads(raw)
                validate_control_message(message)
            except (json.JSONDecodeError, ProtocolValidationError):
                await self.websocket.close(code=1002, reason="malformed control frame")
                return
            if not isinstance(message, dict):
                await self.websocket.close(code=1002, reason="control frame must be an object")
                return
            self.last_control_at = self.service.clock()
            self.control_frames_received += 1
            self.last_control_type = str(message.get("t"))
            if message.get("t") in {"ping", "pong"}:
                self.observe_body_clock(message)
            await self._handle_control(message)

    async def _handle_binary(self, raw: bytes) -> None:
        try:
            frame = validate_binary_frame(raw)
        except ProtocolValidationError:
            return
        if not frame.known_type:
            return
        if frame.frame_type == MIC_PCM_FRAME_TYPE and AUDIO_INPUT_FEATURE not in self.features:
            samples = struct.unpack("<320h", raw[5:])
            self.microphone_level = math.sqrt(
                sum(sample * sample for sample in samples) / len(samples)
            ) / 32768.0
        await self.service._publish_frame(
            {
                "robot_id": self.robot_id,
                "epoch": self.epoch,
                "frame_type": frame.frame_type,
                "counter": frame.counter,
                "payload": raw[5:],
                "received_at": self.service.clock(),
            }
        )

    async def _handle_control(self, message: dict[str, object]) -> None:
        message_type = message.get("t")
        if message_type in {"ping", "pong"} and "audio" in message and AUDIO_INPUT_FEATURE in self.features:
            self.audio_input = dict(message["audio"])
            self.audio_input_received_at = self.service.clock()
            self.microphone_level = float(self.audio_input["rms"]) if self.audio_input["listening"] else 0.0
        if message_type == "ping":
            await self.send_control({"t": "pong"})
            return
        if message_type == "status":
            validate_control_message(message)
            self.last_status = dict(message)
            if BODY_CAPABILITIES_FEATURE in self.features and "capabilities" in message:
                self.capabilities = dict(message["capabilities"])
            if message.get("mode") in {"normal", "calibrate"}:
                self.mode = str(message["mode"])
            await self.service._publish_event(
                {"robot_id": self.robot_id, "epoch": self.epoch, **message,
                 **self.clock_diagnostics()}
            )
            return
        if message_type in {"event", "cam_meta"}:
            await self.service._publish_event(
                {"robot_id": self.robot_id, "epoch": self.epoch, **message}
            )
            return
        if message_type in {"pong"}:
            return

        sequence = message.get("seq")
        if type(sequence) is not int:
            return
        pending = self.pending.get(sequence)
        if pending is None:
            return
        if message_type == "calibration_status":
            if pending.command.get("t") != "calibration" or not pending.acknowledged:
                return
            validate_control_message(message)
            self.last_calibration = dict(message)
            self._finish_pending(sequence, message)
            return
        if message_type == "motion_speed_status":
            if pending.command.get("t") != "motion_speed" or not pending.acknowledged:
                return
            validate_control_message(message)
            self.last_motion_speed = dict(message)
            self._finish_pending(sequence, message)
            return
        if message_type == "robot_settings_status":
            if pending.command.get("t") != "robot_settings" or not pending.acknowledged:
                return
            validate_control_message(message)
            self.last_robot_settings = dict(message)
            self._finish_pending(sequence, message)
            return
        if message_type == "storage_status":
            if pending.command.get("t") != "storage" or not pending.acknowledged:
                return
            validate_control_message(message)
            self.last_storage = dict(message)
            self._finish_pending(sequence, message)
            return
        if message_type == "ack":
            pending.acknowledged = True
            if not pending.acknowledgement.done():
                pending.acknowledgement.set_result(dict(message))
            if not pending.needs_done:
                self._finish_pending(sequence, message)
            return
        if message_type == "nak":
            self._finish_pending(sequence, message)
            return
        if message_type in {"done", "cancelled"} and pending.acknowledged:
            self._finish_pending(sequence, message)

    def _finish_pending(self, sequence: int, result: dict[str, object]) -> None:
        pending = self.pending.pop(sequence, None)
        if pending is None:
            return
        if not pending.acknowledgement.done():
            pending.acknowledgement.set_result(dict(result))
        if pending.future.done():
            return
        if (
            result.get("t") == "ack"
            and pending.command.get("t") == "profile"
        ):
            self.profile = str(pending.command["name"])
        if result.get("t") == "ack" and pending.command.get("t") == "mode":
            self.mode = str(pending.command["name"])
        pending.future.set_result(dict(result))
        self.completed[sequence] = dict(result)
        while len(self.completed) > 256:
            del self.completed[next(iter(self.completed))]
        self.service._record_terminal(self, sequence, result, pending.command)
        if pending.command.get("t") == "stop" and result.get("t") in {"ack", "done"}:
            # A confirmed stop ends earlier asynchronous commands even when
            # their individual cancellation acknowledgements were lost. Keep
            # commands admitted after the stop and ACK-only controls intact.
            for earlier, command in tuple(self.pending.items()):
                if earlier < sequence and command.needs_done and command.command.get("t") not in {"storage", "motion_speed", "robot_settings"}:
                    self._finish_pending(earlier, {"t": "cancelled", "seq": earlier, "code": "stop"})

    async def wait_acknowledged(
        self,
        sequence: int,
        *,
        timeout: float,
    ) -> dict[str, object]:
        completed = self.completed.get(sequence)
        if completed is not None:
            if completed.get("t") != "ack":
                raise GatewayError(
                    f"sequence {sequence} ended before acknowledgement"
                )
            return dict(completed)
        pending = self.pending.get(sequence)
        if pending is None:
            raise GatewayError(
                f"sequence {sequence} is not pending in epoch {self.epoch}"
            )
        result = await asyncio.wait_for(
            asyncio.shield(pending.acknowledgement),
            timeout=timeout,
        )
        if result.get("t") != "ack":
            raise GatewayError(
                f"sequence {sequence} ended before acknowledgement"
            )
        return dict(result)

    async def wait_terminal(
        self,
        sequence: int,
        *,
        timeout: float | None,
    ) -> dict[str, object]:
        completed = self.completed.get(sequence)
        if completed is not None:
            return dict(completed)
        pending = self.pending.get(sequence)
        if pending is None:
            raise GatewayError(f"sequence {sequence} is not pending in epoch {self.epoch}")
        return await asyncio.wait_for(asyncio.shield(pending.future), timeout=timeout)

    async def close(self, code: int, reason: str, *, cancel_code: str) -> None:
        self._cancel_code = cancel_code
        self.close_code = code
        self.close_reason = reason
        self.cancel_pending(cancel_code)
        if not self.websocket.closed:
            await self.websocket.close(code=code, reason=reason)

    def cancel_pending(self, code: str | None = None) -> None:
        cancellation_code = code or self._cancel_code
        for sequence, pending in tuple(self.pending.items()):
            if pending.future.done():
                continue
            result = {"t": "cancelled", "seq": sequence, "code": cancellation_code}
            self._finish_pending(sequence, result)


class GatewayService:
    def __init__(
        self,
        config: GatewayServiceConfig,
        *,
        clock: Callable[[], float] | None = None,
        clock_source: GatewayClock | None = None,
        token_store: RobotTokenStore | None = None,
    ) -> None:
        if clock is not None and clock_source is not None:
            raise ValueError("provide clock or clock_source, not both")
        self.config = config
        self.clock_source = clock_source or GatewayClock(
            monotonic_clock=clock or monotonic
        )
        self.clock = self.clock_source.monotonic
        self.instance_id = uuid4().hex
        self._tokens = dict(config.tokens)
        self.token_store = token_store
        self._connections: dict[str, GatewayConnection] = {}
        self._epochs: dict[str, int] = {}
        self._lock = asyncio.Lock()
        self._closing = False
        self._event_callbacks: list[GatewayCallback] = []
        self._frame_callbacks: list[GatewayCallback] = []
        self._transcript_callbacks: list[GatewayCallback] = []
        self._command_callbacks: list[GatewayCallback] = []
        self._diagnostic_callbacks: list[Callable[[dict[str, object]], None]] = []
        self.terminals: list[dict[str, object]] = []

    async def handler(
        self,
        websocket: Any,
        path: str,
        *,
        transport: str = "lan",
    ) -> None:
        if path != "/robot":
            await websocket.close(code=1008, reason="wrong endpoint")
            return
        try:
            hello = await _receive_hello(websocket)
        except Exception:
            await websocket.close(code=1002, reason="malformed hello")
            return

        if hello.get("ver") != PROTOCOL_VERSION:
            await _send_control(websocket, {"t": "err", "code": "ver"})
            await websocket.close(code=4002, reason="unsupported protocol version")
            return
        robot_id = str(hello["id"])
        expected_token = self._tokens.get(robot_id)
        supplied_token = str(hello["auth"])
        valid_token = self.token_store.matches(robot_id, supplied_token) if self.token_store else (
            expected_token is not None and hmac.compare_digest(expected_token.encode(), supplied_token.encode()))
        if not valid_token:
            await _send_control(websocket, {"t": "err", "code": "auth"})
            await websocket.close(code=4001, reason="authentication failed")
            return

        async with self._lock:
            if self._closing:
                await websocket.close(code=1001, reason="gateway stopped")
                return
            previous = self._connections.get(robot_id)
            epoch = self._epochs.get(robot_id, 0) + 1
            self._epochs[robot_id] = epoch
            features = tuple(str(feature) for feature in hello.get("features", []))
            connection = GatewayConnection(
                self,
                websocket,
                robot_id,
                epoch,
                features,
                transport,
                str(hello["model"]) if BODY_CAPABILITIES_FEATURE in features else "v1-8servo",
                hello.get("capabilities") if BODY_CAPABILITIES_FEATURE in features else None,
            )
            connection.observe_body_clock(hello)
            self._connections[robot_id] = connection
        if previous is not None:
            await previous.close(4000, "new authenticated connection", cancel_code="reconnect")

        await connection.send_control(
            {
                "t": "welcome",
                "ver": PROTOCOL_VERSION,
                "epoch": epoch,
                "profile": self.config.profile,
                **({COMMAND_DEADLINE_FEATURE: True} if COMMAND_DEADLINE_FEATURE in features else {}),
            }
        )
        await self._publish_event(
            {
                "t": "connection",
                "status": "connected",
                "robot_id": robot_id,
                "epoch": epoch,
                "features": list(connection.features),
                "transport": connection.transport,
            }
        )
        try:
            await connection.run()
        except ConnectionClosed as error:
            if connection.close_code is None:
                connection.close_code = error.code
                connection.close_reason = error.reason
        finally:
            connection.cancel_pending()
            async with self._lock:
                if self._connections.get(robot_id) is connection:
                    del self._connections[robot_id]
            disconnected: dict[str, object] = {
                "t": "connection",
                "status": "disconnected",
                "robot_id": robot_id,
                "epoch": epoch,
                "transport": connection.transport,
            }
            if connection.close_code is not None:
                disconnected["close_code"] = connection.close_code
            if connection.close_reason:
                disconnected["close_reason"] = connection.close_reason
            await self._publish_event(disconnected)

    async def wait_connected(self, robot_id: str, *, timeout: float = 3.0) -> None:
        deadline = self.clock() + timeout
        while self.clock() < deadline:
            if robot_id in self._connections:
                return
            await asyncio.sleep(0.01)
        raise TimeoutError(f"robot {robot_id} did not connect")

    async def close(self) -> None:
        """Release body sessions before the server waits for its sockets to close."""
        async with self._lock:
            self._closing = True
            connections = tuple(self._connections.values())
        await asyncio.gather(*(connection.close(1001, "gateway stopped", cancel_code="disconnect")
                               for connection in connections))

    async def queue_intent(
        self,
        name: str,
        params: Mapping[str, object] | None = None,
        *,
        robot_id: str | None = None,
        received_at: float | None = None,
        on_sequence: Callable[[int], AsyncContextManager[None] | None] | None = None,
        valid_for_ms: int | None = None,
    ) -> int:
        command: dict[str, object] = {"t": "intent", "name": name}
        if params:
            command.update(params)
        return await self._send(
            command,
            robot_id=robot_id,
            received_at=received_at,
            on_sequence=on_sequence,
            valid_for_ms=valid_for_ms,
        )

    async def emote(
        self,
        asset: str,
        *,
        robot_id: str | None = None,
        received_at: float | None = None,
    ) -> int:
        return await self.queue_intent(
            "emote",
            {"asset": asset},
            robot_id=robot_id,
            received_at=received_at,
        )

    async def queue_motion_plan(
        self,
        frames: list[object],
        *,
        end: str,
        robot_id: str | None = None,
        received_at: float | None = None,
        on_sequence: Callable[[int], AsyncContextManager[None] | None] | None = None,
    ) -> int:
        connection = self._connection(robot_id)
        if MOTION_PLAN_FEATURE not in connection.features:
            raise GatewayError(
                f"robot {connection.robot_id} does not advertise {MOTION_PLAN_FEATURE}"
            )
        return await connection.send_command(
            {
                "t": "motion_plan",
                "map": MOTION_PLAN_JOINT_MAP,
                "frames": frames,
                "end": end,
            },
            received_at=self.clock() if received_at is None else received_at,
            on_sequence=on_sequence,
        )

    async def estop(
        self,
        *,
        robot_id: str | None = None,
        received_at: float | None = None,
        detach: bool = False,
        on_sequence: Callable[[int], AsyncContextManager[None] | None] | None = None,
    ) -> int:
        command: dict[str, object] = {"t": "stop"}
        if detach:
            command["detach"] = True
        return await self._send(
            command,
            robot_id=robot_id,
            received_at=received_at,
            on_sequence=on_sequence,
        )

    async def set_profile(self, profile: str, *, robot_id: str | None = None) -> int:
        return await self._send(
            {"t": "profile", "name": profile},
            robot_id=robot_id,
        )

    async def set_state(
        self,
        name: str,
        sleep_s: int | None = None,
        *,
        robot_id: str | None = None,
    ) -> int:
        command: dict[str, object] = {"t": "state", "name": name}
        if sleep_s is not None:
            command["sleep_s"] = sleep_s
        return await self._send(command, robot_id=robot_id)

    async def request_snap(
        self,
        *,
        robot_id: str | None = None,
        on_sequence: Callable[[int], AsyncContextManager[None] | None] | None = None,
    ) -> int:
        return await self._send(
            {"t": "snap"},
            robot_id=robot_id,
            on_sequence=on_sequence,
        )

    async def set_camera(
        self,
        *,
        on: bool,
        fps: int,
        resolution: str,
        robot_id: str | None = None,
        snapshot_resolution: str | None = None,
    ) -> int:
        command: dict[str, object] = {"t": "cam", "on": on, "fps": fps, "res": resolution}
        if snapshot_resolution is not None:
            command["snapshot_res"] = snapshot_resolution
        return await self._send(
            command,
            robot_id=robot_id,
        )

    async def set_microphone(
        self,
        *,
        on: bool,
        gate: str,
        robot_id: str | None = None,
        gain_db: int | None = None,
    ) -> int:
        command = {"t": "mic", "on": on, "gate": gate}
        if gain_db is not None:
            command["gain_db"] = gain_db
        return await self._send(command, robot_id=robot_id)

    async def set_speaker_volume(self, *, volume_percent: int, robot_id: str | None = None) -> int:
        return await self._send({"t": "speaker", "volume_percent": volume_percent}, robot_id=robot_id)

    async def set_wake_configuration(
        self,
        *,
        enabled: bool,
        model: str,
        robot_id: str | None = None,
        threshold: float | None = None,
    ) -> int:
        command = {"t": "wake", "enabled": enabled, "model": model}
        if threshold is not None:
            command["threshold"] = threshold
        return await self._send(command, robot_id=robot_id)

    async def set_calibration_mode(
        self,
        mode: str,
        *,
        robot_id: str | None = None,
    ) -> int:
        return await self._send(
            {"t": "mode", "name": mode},
            robot_id=robot_id,
        )

    async def set_servo(
        self,
        servo_id: int,
        degrees: float,
        duration_ms: int,
        *,
        robot_id: str | None = None,
    ) -> int:
        return await self._send(
            {
                "t": "servo",
                "id": servo_id,
                "deg": degrees,
                "ms": duration_ms,
            },
            robot_id=robot_id,
        )

    async def body_calibration(
        self, operation: str, values: Mapping[str, object] | None = None,
        *, robot_id: str | None = None,
    ) -> dict[str, object]:
        """Operator service only; return correlated device readback, never a host echo."""
        connection = self._connection(robot_id)
        fields = dict(values or {})
        if set(fields) - {"id", "channel", "home_us", "invert", "pulse_us", "home_cd", "us_per_degree"}:
            raise GatewayError("unknown calibration fields")
        sequence = await connection.send_command(
            {**fields, "t": "calibration", "op": operation}, received_at=self.clock(),
        )
        try:
            result = await connection.wait_terminal(sequence, timeout=5.0)
        except TimeoutError as error:
            connection.last_calibration = None
            connection._finish_pending(sequence, {"t": "cancelled", "seq": sequence, "code": "disconnect"})
            raise GatewayError("calibration readback timed out; refresh from the body before continuing") from error
        if result.get("t") != "calibration_status":
            raise GatewayError(str(result.get("msg") or result.get("code") or "calibration did not complete"))
        return result

    async def body_motion_speed(self, operation: str, values: Mapping[str, object] | None = None,
                                *, robot_id: str | None = None) -> dict[str, object]:
        connection = self._connection(robot_id)
        fields = dict(values or {})
        if set(fields) - {"rate", "joint_speed_limit_deg_s"}:
            raise GatewayError("unknown motion speed fields")
        sequence = await connection.send_command(
            {**fields, "t": "motion_speed", "op": operation}, received_at=self.clock())
        try:
            result = await connection.wait_terminal(sequence, timeout=5.0)
        except TimeoutError as error:
            connection.last_motion_speed = None
            connection._finish_pending(sequence, {"t": "cancelled", "seq": sequence, "code": "disconnect"})
            raise GatewayError("motion speed readback timed out; read from robot again") from error
        if result.get("t") != "motion_speed_status":
            raise GatewayError(str(result.get("msg") or result.get("code") or "motion speed did not complete"))
        return result

    async def body_robot_settings(self, operation: str, values: Mapping[str, object] | None = None,
                                  *, robot_id: str | None = None) -> dict[str, object]:
        connection = self._connection(robot_id)
        if connection.model != "v2-12servo" or ROBOT_SETTINGS_FEATURE not in connection.features:
            raise GatewayError("Update the P4 firmware to manage robot settings here")
        message = {**dict(values or {}), "t": "robot_settings", "op": operation}
        validate_control_message({**message, "seq": 1})
        if operation == "network" and GATEWAY_SWITCHING_FEATURE not in connection.features:
            await self.body_robot_settings("get", robot_id=connection.robot_id)
            if self._connection(connection.robot_id) is not connection:
                raise GatewayError("Body session changed before saving the network; read its settings again")
        token = message.get("robot_token")
        if token is not None:
            if self.token_store is None:
                raise GatewayError("Persistent pairing storage is required to change the robot token")
            # Persist both credentials before sending. Even an ambiguous timeout
            # or host restart must not strand a body which saved the new token.
            self.token_store.stage(connection.robot_id, str(token))
        sequence = await connection.send_command(message, received_at=self.clock())
        try:
            result = await connection.wait_terminal(sequence, timeout=8.0)
        except TimeoutError as error:
            connection._finish_pending(sequence, {"t": "cancelled", "seq": sequence, "code": "disconnect"})
            raise GatewayError("Settings result is unknown; reconnect and read from the robot before retrying") from error
        if result.get("t") != "robot_settings_status":
            raise GatewayError(str(result.get("msg") or result.get("code") or "robot settings did not complete"))
        return result

    async def body_storage(self, operation: str, *, robot_id: str | None = None) -> dict[str, object]:
        """Storage operations are operator-owned and settle only on device readback."""
        connection = self._connection(robot_id)
        if operation == "clear":
            # Read current readiness before starting a destructive operation;
            # a stale dashboard snapshot cannot establish mount/busy state.
            status = await self.body_storage("get", robot_id=connection.robot_id)
            if self._connection(connection.robot_id) is not connection:
                raise GatewayError("body session changed before storage clear; read its status again")
            if not status["available"] or not status["mounted"] or status["busy"]:
                raise GatewayError("storage must be mounted and idle before clearing logs and captures")
        sequence = await connection.send_command(
            {"t": "storage", "op": operation}, received_at=self.clock(),
        )
        try:
            result = await connection.wait_terminal(sequence, timeout=5.0)
        except TimeoutError as error:
            connection.last_storage = None
            connection._finish_pending(sequence, {"t": "cancelled", "seq": sequence, "code": "disconnect"})
            raise GatewayError("storage result timed out; read status from the body before continuing") from error
        if result.get("t") != "storage_status":
            raise GatewayError(str(result.get("msg") or result.get("code") or "storage operation did not complete"))
        return result

    async def set_servo_limits(
        self,
        servo_id: int,
        minimum: float,
        maximum: float,
        center: float,
        invert: bool,
        *,
        robot_id: str | None = None,
    ) -> int:
        return await self._send(
            {
                "t": "limits",
                "id": servo_id,
                "min": minimum,
                "max": maximum,
                "center": center,
                "invert": invert,
            },
            robot_id=robot_id,
        )

    async def save_calibration(self, *, robot_id: str | None = None) -> int:
        return await self._send({"t": "cal_save"}, robot_id=robot_id)

    async def save_pose(
        self,
        name: str,
        servos: list[list[object]],
        *,
        robot_id: str | None = None,
    ) -> int:
        return await self._send(
            {"t": "pose_save", "name": name, "servos": servos},
            robot_id=robot_id,
        )

    async def tts_speak(
        self,
        pcm_stream: Iterable[bytes] | AsyncIterable[bytes],
        *,
        robot_id: str | None = None,
        received_at: float | None = None,
        on_sequence: Callable[[int], AsyncContextManager[None] | None] | None = None,
    ) -> int:
        connection = self._connection(robot_id)
        return await connection.send_tts(
            pcm_stream,
            received_at=self.clock() if received_at is None else received_at,
            on_sequence=on_sequence,
        )

    async def cancel_speech(
        self,
        *,
        robot_id: str,
        on_sequence: Callable[[int], AsyncContextManager[None] | None] | None = None,
    ) -> int:
        return await self._send({"t": "tts", "op": "cancel"},
            robot_id=robot_id, on_sequence=on_sequence)

    async def wait_terminal(
        self,
        sequence: int,
        *,
        robot_id: str | None = None,
        epoch: int | None = None,
        timeout: float | None = 5.0,
    ) -> dict[str, object]:
        if epoch is not None:
            for receipt in reversed(self.terminals):
                if receipt["robot_id"] == robot_id and receipt["epoch"] == epoch and receipt["seq"] == sequence:
                    return dict(receipt["result"])
        connection = self._connection(robot_id)
        if epoch is not None and connection.epoch != epoch:
            raise GatewayError(f"command belongs to ended robot session {epoch}, not {connection.epoch}")
        return await connection.wait_terminal(sequence, timeout=timeout)

    async def revoke_token(self, robot_id: str) -> None:
        if self.token_store is not None:
            self.token_store.revoke(robot_id)
        self._tokens.pop(robot_id, None)
        connection = self._connections.get(robot_id)
        if connection is not None:
            await connection.close(4001, "token revoked", cancel_code="disconnect")

    def set_token(self, robot_id: str, token: str) -> None:
        if not robot_id or not token or len(token) > 128:
            raise ValueError("robot_id and bounded token are required")
        if self.token_store is not None:
            self.token_store.set(robot_id, token)
        self._tokens[robot_id] = token

    def subscribe_events(self, callback: GatewayCallback) -> None:
        self._event_callbacks.append(callback)

    def subscribe_frames(self, callback: GatewayCallback) -> None:
        self._frame_callbacks.append(callback)

    def unsubscribe_frames(self, callback: GatewayCallback) -> None:
        if callback in self._frame_callbacks:
            self._frame_callbacks.remove(callback)

    def subscribe_transcripts(self, callback: GatewayCallback) -> None:
        self._transcript_callbacks.append(callback)

    def subscribe_commands(self, callback: GatewayCallback) -> None:
        self._command_callbacks.append(callback)

    def subscribe_diagnostics(self, callback: Callable[[dict[str, object]], None]) -> None:
        self._diagnostic_callbacks.append(callback)

    def _record_diagnostic(self, diagnostic: dict[str, object]) -> None:
        for callback in tuple(self._diagnostic_callbacks):
            callback(dict(diagnostic))

    async def publish_transcript(self, transcript: dict[str, object]) -> None:
        await _publish(self._transcript_callbacks, transcript)

    def status(self) -> dict[str, object]:
        now = self.clock()
        return {
            "profile": self.config.profile,
            "effective_caps": _profile_caps(self.config.profile),
            "joint_contract": joint_contract(),
            "faults": {"wall_clock_offset_s": self.clock_source.wall_offset},
            "robots": {
                robot_id: {
                    "connected": True,
                    "connection_state": (
                        "stale"
                        if now - connection.last_control_at >= CONTROL_STALE_SECONDS
                        else "online"
                    ),
                    "epoch": connection.epoch,
                    "next_sequence": connection.next_sequence,
                    "profile": connection.profile,
                    "mode": connection.mode,
                    "transport": connection.transport,
                    "features": list(connection.features),
                    "model": connection.model,
                    "capabilities": connection.capabilities,
                    "robot_commands": body_commands(connection.model, connection.features, connection.capabilities),
                    "active_walk_sequence": next((seq for seq, item in connection.pending.items()
                        if not item.future.done() and item.command.get("name") == "walk" and "update" not in item.command), None),
                    "active_walk": next((dict(item.command) for item in connection.pending.values()
                        if not item.future.done() and item.command.get("name") == "walk" and "update" not in item.command), None),
                    "effective_caps": _profile_caps(connection.profile),
                    "pending": sum(
                        not command.future.done() for command in connection.pending.values()
                    ),
                    "pending_sequences": sorted(connection.pending),
                    "heartbeat_age_ms": int(
                        max(0.0, now - connection.last_control_at) * 1000
                    ),
                    "heartbeat": {
                        "ping_interval_s": self.config.ping_interval_s,
                        "control_frames_received": connection.control_frames_received,
                        "json_pings_sent": connection.json_pings_sent,
                        "last_control_type": connection.last_control_type,
                    },
                    "last_terminal": (
                        next(reversed(connection.completed.values()))
                        if connection.completed
                        else None
                    ),
                    "last_command": connection.last_command,
                    "body_clock": connection.clock_diagnostics(),
                    "microphone_level": round(connection.microphone_level, 6),
                    "audio_input": connection.audio_input,
                    "audio_input_age_ms": (round((self.clock() - connection.audio_input_received_at) * 1000)
                                           if connection.audio_input is not None else None),
                    "status": connection.last_status,
                    "calibration": connection.last_calibration,
                    "storage": connection.last_storage,
                    "motion_speed": connection.last_motion_speed,
                }
                for robot_id, connection in self._connections.items()
            }
        }

    def jump_wall_clock(self, seconds: float) -> None:
        self.clock_source.jump_wall_clock(seconds)

    async def status_snapshot(self) -> dict[str, object]:
        async with self._lock:
            return self.status()

    async def _send(
        self,
        command: Mapping[str, object],
        *,
        robot_id: str | None,
        received_at: float | None = None,
        on_sequence: Callable[[int], AsyncContextManager[None] | None] | None = None,
        valid_for_ms: int | None = None,
    ) -> int:
        connection = self._connection(robot_id)
        return await connection.send_command(
            command,
            received_at=self.clock() if received_at is None else received_at,
            on_sequence=on_sequence,
            valid_for_ms=valid_for_ms,
        )

    def _connection(self, robot_id: str | None) -> GatewayConnection:
        if robot_id is not None:
            connection = self._connections.get(robot_id)
        elif len(self._connections) == 1:
            connection = next(iter(self._connections.values()))
        else:
            connection = None
        if connection is None:
            raise RobotOfflineError("requested robot is not connected")
        return connection

    def _record_terminal(
        self,
        connection: GatewayConnection,
        sequence: int,
        result: Mapping[str, object],
        command: Mapping[str, object],
    ) -> None:
        self.terminals.append(
            {
                "robot_id": connection.robot_id,
                "epoch": connection.epoch,
                "seq": sequence,
                "result": dict(result),
            }
        )
        self._record_diagnostic({
            **command, **result, **connection.clock_diagnostics(),
            "event": "command_result", "robot_id": connection.robot_id,
            "epoch": connection.epoch, "seq": sequence,
            "command_type": command.get("t"),
        })

    async def _publish_event(self, event: dict[str, object]) -> None:
        await _publish(self._event_callbacks, event)

    async def _publish_frame(self, frame: dict[str, object]) -> None:
        await _publish(self._frame_callbacks, frame)

    async def _publish_command(self, command: dict[str, object]) -> None:
        if command.get("t") == "robot_settings":
            command = {key: value for key, value in command.items() if key not in {"wifi_password", "setup_password", "robot_token"}}
        await _publish(self._command_callbacks, command)


async def _receive_hello(websocket: Any) -> dict[str, object]:
    raw = await asyncio.wait_for(websocket.recv(), timeout=3.0)
    if not isinstance(raw, str):
        raise RuntimeError("hello must be a text frame")
    value = json.loads(raw)
    if not isinstance(value, dict) or value.get("t") != "hello":
        raise RuntimeError("first body message must be hello")
    try:
        validate_control_message(value)
    except ProtocolValidationError as error:
        if error.reason != "range:ver" or type(value.get("ver")) is not int:
            raise
    return value


async def _send_control(websocket: Any, message: Mapping[str, object]) -> None:
    validate_control_message(message)
    await websocket.send(json.dumps(message, separators=(",", ":")))


def _command_needs_done(command: Mapping[str, object]) -> bool:
    message_type = command.get("t")
    if message_type == "intent" and command.get("name") == "walk" and "update" in command:
        return False  # settings acknowledgement; original walk owns completion
    return (
        message_type in {"intent", "motion_plan", "snap", "calibration", "storage", "motion_speed", "robot_settings"}
        or (message_type == "tts" and command.get("op") == "start")
        or (message_type == "state" and command.get("name") == "sleep")
    )


async def _publish(callbacks: list[GatewayCallback], payload: dict[str, object]) -> None:
    for callback in tuple(callbacks):
        result = callback(dict(payload))
        if inspect.isawaitable(result):
            await result


def _profile_caps(profile: str) -> dict[str, object]:
    return {
        "camera_max_fps": 15,
        "camera_default_resolution": "QVGA" if profile == "tether" else "VGA",
        "microphone_gates": ["open", "vad", "wake"],
        "status_interval_s": 30 if profile == "tether" else 5,
    }
