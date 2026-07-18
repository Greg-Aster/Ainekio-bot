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
from dataclasses import dataclass, field
from time import monotonic
from typing import Any

from protocol.binary_helpers import (
    MIC_PCM_FRAME_TYPE,
    SPEAKER_PCM_FRAME_TYPE,
    encode_binary_frame,
)
from protocol.control_v1 import (
    MAX_SEQUENCE,
    MOTION_PLAN_FEATURE,
    MOTION_PLAN_JOINT_MAP,
    PROTOCOL_VERSION,
    ProtocolValidationError,
    validate_binary_frame,
    validate_control_message,
)
from protocol.joints_v1 import joint_contract
from websockets.exceptions import ConnectionClosed


MAX_WEBSOCKET_MESSAGE_BYTES = (120 * 1024) + 5
PING_AFTER_SECONDS = 2.0
OFFLINE_AFTER_SECONDS = 3.0

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

    def __post_init__(self) -> None:
        if self.profile not in {"home", "tether"}:
            raise ValueError("profile must be home or tether")
        if not 1 <= self.max_action_age_ms <= 60000:
            raise ValueError("max_action_age_ms must be between 1 and 60000")


@dataclass
class PendingCommand:
    command: dict[str, object]
    needs_done: bool
    future: asyncio.Future[dict[str, object]]
    acknowledged: bool = False


class GatewayConnection:
    def __init__(
        self,
        service: "GatewayService",
        websocket: Any,
        robot_id: str,
        epoch: int,
        features: tuple[str, ...] = (),
    ) -> None:
        self.service = service
        self.websocket = websocket
        self.robot_id = robot_id
        self.epoch = epoch
        self.features = features
        self.next_sequence = 1
        self.pending: dict[int, PendingCommand] = {}
        self.completed: dict[int, dict[str, object]] = {}
        self.last_status: dict[str, object] | None = None
        self.last_command: dict[str, object] | None = None
        self.profile = service.config.profile
        self.microphone_level = 0.0
        self.connected_at = service.clock()
        self.last_control_at = self.connected_at
        self.last_sent_at = self.connected_at
        self._send_lock = asyncio.Lock()
        self._speaker_lock = asyncio.Lock()
        self._cancel_code = "disconnect"

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
    ) -> int:
        async with self._send_lock:
            age_ms = (self.service.clock() - received_at) * 1000.0
            if age_ms > self.service.config.max_action_age_ms:
                raise ActionExpiredError("action expired before sequence assignment")
            if self.websocket.closed:
                raise RobotOfflineError(f"robot {self.robot_id} is offline")
            if self.next_sequence > MAX_SEQUENCE:
                await self.websocket.close(code=1002, reason="sequence exhausted")
                raise GatewayError("session sequence space exhausted")

            sequence = self.next_sequence
            self.next_sequence += 1
            message = dict(command)
            message["seq"] = sequence
            validate_control_message(message)
            future: asyncio.Future[dict[str, object]] = (
                asyncio.get_running_loop().create_future()
            )
            self.pending[sequence] = PendingCommand(
                command=message,
                needs_done=_command_needs_done(message),
                future=future,
            )
            try:
                await self.websocket.send(json.dumps(message, separators=(",", ":")))
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
    ) -> int:
        async with self._speaker_lock:
            start_sequence = await self.send_command(
                {"t": "tts", "op": "start"},
                received_at=received_at,
            )
            counter = 0
            if isinstance(pcm_stream, AsyncIterable):
                async for payload in pcm_stream:
                    await self._send_speaker_frame(counter, payload)
                    counter = (counter + 1) & 0xFFFFFFFF
            else:
                for payload in pcm_stream:
                    await self._send_speaker_frame(counter, payload)
                    counter = (counter + 1) & 0xFFFFFFFF
            await self.send_command(
                {"t": "tts", "op": "end"},
                received_at=self.service.clock(),
            )
            return start_sequence

    async def _send_speaker_frame(self, counter: int, payload: bytes) -> None:
        frame = encode_binary_frame(SPEAKER_PCM_FRAME_TYPE, counter, payload)
        async with self._send_lock:
            await self.websocket.send(frame)
            self.last_sent_at = self.service.clock()

    async def run(self) -> None:
        while True:
            now = self.service.clock()
            if now - self.last_control_at >= OFFLINE_AFTER_SECONDS:
                await self.close(1011, "control timeout", cancel_code="disconnect")
                return
            if now - self.last_sent_at >= PING_AFTER_SECONDS:
                await self.send_control({"t": "ping"})

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
            await self._handle_control(message)

    async def _handle_binary(self, raw: bytes) -> None:
        try:
            frame = validate_binary_frame(raw)
        except ProtocolValidationError:
            return
        if not frame.known_type:
            return
        if frame.frame_type == MIC_PCM_FRAME_TYPE:
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
            }
        )

    async def _handle_control(self, message: dict[str, object]) -> None:
        message_type = message.get("t")
        if message_type == "ping":
            await self.send_control({"t": "pong"})
            return
        if message_type == "status":
            self.last_status = dict(message)
            await self.service._publish_event(
                {"robot_id": self.robot_id, "epoch": self.epoch, **message}
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
        if message_type == "ack":
            pending.acknowledged = True
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
        if pending is None or pending.future.done():
            return
        if (
            result.get("t") == "ack"
            and pending.command.get("t") == "profile"
        ):
            self.profile = str(pending.command["name"])
        pending.future.set_result(dict(result))
        self.completed[sequence] = dict(result)
        while len(self.completed) > 256:
            del self.completed[next(iter(self.completed))]
        self.service._record_terminal(self, sequence, result)

    async def wait_terminal(
        self,
        sequence: int,
        *,
        timeout: float,
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
    ) -> None:
        if clock is not None and clock_source is not None:
            raise ValueError("provide clock or clock_source, not both")
        self.config = config
        self.clock_source = clock_source or GatewayClock(
            monotonic_clock=clock or monotonic
        )
        self.clock = self.clock_source.monotonic
        self._tokens = dict(config.tokens)
        self._connections: dict[str, GatewayConnection] = {}
        self._epochs: dict[str, int] = {}
        self._lock = asyncio.Lock()
        self._event_callbacks: list[GatewayCallback] = []
        self._frame_callbacks: list[GatewayCallback] = []
        self._transcript_callbacks: list[GatewayCallback] = []
        self._command_callbacks: list[GatewayCallback] = []
        self.terminals: list[dict[str, object]] = []

    async def handler(self, websocket: Any, path: str) -> None:
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
        if expected_token is None or not hmac.compare_digest(expected_token, supplied_token):
            await _send_control(websocket, {"t": "err", "code": "auth"})
            await websocket.close(code=4001, reason="authentication failed")
            return

        async with self._lock:
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
            )
            self._connections[robot_id] = connection
        if previous is not None:
            await previous.close(4000, "new authenticated connection", cancel_code="reconnect")

        await connection.send_control(
            {
                "t": "welcome",
                "ver": PROTOCOL_VERSION,
                "epoch": epoch,
                "profile": self.config.profile,
            }
        )
        await self._publish_event(
            {
                "t": "connection",
                "status": "connected",
                "robot_id": robot_id,
                "epoch": epoch,
                "features": list(connection.features),
            }
        )
        try:
            await connection.run()
        except ConnectionClosed:
            pass
        finally:
            connection.cancel_pending()
            async with self._lock:
                if self._connections.get(robot_id) is connection:
                    del self._connections[robot_id]
            await self._publish_event(
                {"t": "connection", "status": "disconnected", "robot_id": robot_id, "epoch": epoch}
            )

    async def wait_connected(self, robot_id: str, *, timeout: float = 3.0) -> None:
        deadline = self.clock() + timeout
        while self.clock() < deadline:
            if robot_id in self._connections:
                return
            await asyncio.sleep(0.01)
        raise TimeoutError(f"robot {robot_id} did not connect")

    async def queue_intent(
        self,
        name: str,
        params: Mapping[str, object] | None = None,
        *,
        robot_id: str | None = None,
        received_at: float | None = None,
    ) -> int:
        command: dict[str, object] = {"t": "intent", "name": name}
        if params:
            command.update(params)
        return await self._send(command, robot_id=robot_id, received_at=received_at)

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
        )

    async def estop(
        self,
        *,
        robot_id: str | None = None,
        received_at: float | None = None,
    ) -> int:
        return await self._send(
            {"t": "stop"},
            robot_id=robot_id,
            received_at=received_at,
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

    async def request_snap(self, *, robot_id: str | None = None) -> int:
        return await self._send({"t": "snap"}, robot_id=robot_id)

    async def set_camera(
        self,
        *,
        on: bool,
        fps: int,
        resolution: str,
        robot_id: str | None = None,
    ) -> int:
        connection = self._connection(robot_id)
        if connection.profile == "home" and fps > 10:
            raise GatewayError("home profile camera limit is 10 fps")
        if connection.profile == "tether" and fps != 0:
            raise GatewayError("tether profile permits snapshots only")
        return await self._send(
            {"t": "cam", "on": on, "fps": fps, "res": resolution},
            robot_id=robot_id,
        )

    async def set_microphone(
        self,
        *,
        on: bool,
        gate: str,
        robot_id: str | None = None,
    ) -> int:
        connection = self._connection(robot_id)
        if connection.profile == "tether" and gate == "open":
            raise GatewayError("tether profile requires vad or wake microphone gate")
        return await self._send(
            {"t": "mic", "on": on, "gate": gate},
            robot_id=robot_id,
        )

    async def set_wake_configuration(
        self,
        *,
        enabled: bool,
        model: str,
        robot_id: str | None = None,
    ) -> int:
        return await self._send(
            {"t": "wake", "enabled": enabled, "model": model},
            robot_id=robot_id,
        )

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
    ) -> int:
        connection = self._connection(robot_id)
        return await connection.send_tts(
            pcm_stream,
            received_at=self.clock() if received_at is None else received_at,
        )

    async def wait_terminal(
        self,
        sequence: int,
        *,
        robot_id: str | None = None,
        timeout: float = 5.0,
    ) -> dict[str, object]:
        return await self._connection(robot_id).wait_terminal(sequence, timeout=timeout)

    async def revoke_token(self, robot_id: str) -> None:
        self._tokens.pop(robot_id, None)
        connection = self._connections.get(robot_id)
        if connection is not None:
            await connection.close(4001, "token revoked", cancel_code="disconnect")

    def set_token(self, robot_id: str, token: str) -> None:
        if not robot_id or not token or len(token) > 128:
            raise ValueError("robot_id and bounded token are required")
        self._tokens[robot_id] = token

    def subscribe_events(self, callback: GatewayCallback) -> None:
        self._event_callbacks.append(callback)

    def subscribe_frames(self, callback: GatewayCallback) -> None:
        self._frame_callbacks.append(callback)

    def subscribe_transcripts(self, callback: GatewayCallback) -> None:
        self._transcript_callbacks.append(callback)

    def subscribe_commands(self, callback: GatewayCallback) -> None:
        self._command_callbacks.append(callback)

    async def publish_transcript(self, transcript: dict[str, object]) -> None:
        await _publish(self._transcript_callbacks, transcript)

    def status(self) -> dict[str, object]:
        return {
            "profile": self.config.profile,
            "effective_caps": _profile_caps(self.config.profile),
            "joint_contract": joint_contract(),
            "faults": {"wall_clock_offset_s": self.clock_source.wall_offset},
            "robots": {
                robot_id: {
                    "connected": True,
                    "epoch": connection.epoch,
                    "next_sequence": connection.next_sequence,
                    "profile": connection.profile,
                    "features": list(connection.features),
                    "effective_caps": _profile_caps(connection.profile),
                    "pending": sum(
                        not command.future.done() for command in connection.pending.values()
                    ),
                    "pending_sequences": sorted(connection.pending),
                    "heartbeat_age_ms": int(
                        max(0.0, self.clock() - connection.last_control_at) * 1000
                    ),
                    "last_terminal": (
                        next(reversed(connection.completed.values()))
                        if connection.completed
                        else None
                    ),
                    "last_command": connection.last_command,
                    "microphone_level": round(connection.microphone_level, 4),
                    "status": connection.last_status,
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
    ) -> int:
        connection = self._connection(robot_id)
        return await connection.send_command(
            command,
            received_at=self.clock() if received_at is None else received_at,
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
    ) -> None:
        self.terminals.append(
            {
                "robot_id": connection.robot_id,
                "epoch": connection.epoch,
                "seq": sequence,
                "result": dict(result),
            }
        )

    async def _publish_event(self, event: dict[str, object]) -> None:
        await _publish(self._event_callbacks, event)

    async def _publish_frame(self, frame: dict[str, object]) -> None:
        await _publish(self._frame_callbacks, frame)

    async def _publish_command(self, command: dict[str, object]) -> None:
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
    return (
        message_type in {"intent", "motion_plan", "snap"}
        or (message_type == "tts" and command.get("op") == "start")
        or (message_type == "state" and command.get("name") == "sleep")
    )


async def _publish(callbacks: list[GatewayCallback], payload: dict[str, object]) -> None:
    for callback in tuple(callbacks):
        result = callback(dict(payload))
        if inspect.isawaitable(result):
            await result


def _profile_caps(profile: str) -> dict[str, object]:
    if profile == "tether":
        return {
            "camera_max_fps": 0,
            "camera_default_resolution": "QVGA",
            "microphone_gates": ["vad", "wake"],
            "status_interval_s": 30,
        }
    return {
        "camera_max_fps": 10,
        "camera_default_resolution": "VGA",
        "microphone_gates": ["open", "vad", "wake"],
        "status_interval_s": 5,
    }
