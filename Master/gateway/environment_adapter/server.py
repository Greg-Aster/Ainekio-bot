from __future__ import annotations

import asyncio
import base64
import hmac
import json
import math
import struct
from dataclasses import dataclass
from datetime import datetime, timezone
from time import monotonic
from typing import Any, Callable, Mapping

from gateway.plugins import AudioUtterance, AudioUtterancePlugin
from gateway.server.service import GatewayError, GatewayService
from protocol.binary_helpers import CAMERA_JPEG_FRAME_TYPE, MIC_PCM_FRAME_TYPE
from websockets.exceptions import ConnectionClosed

from .translation import (
    SUPPORTED_ROBOT_COMMANDS,
    BridgeAction,
    translate_environment_action,
)


ADAPTER_PROTOCOL_VERSION = 1
MAX_ADAPTER_JSON_MESSAGE_BYTES = 256 * 1024
MAX_ADAPTER_BINARY_MESSAGE_BYTES = 512 * 1024
AUDIO_UTTERANCE_MAGIC = b"AIKAUD01"
AUDIO_UTTERANCE_HEADER_BYTES = len(AUDIO_UTTERANCE_MAGIC) + 4
MAX_CONTROL_ACTION_AGE_SECONDS = 2.0
MAX_FUTURE_CLOCK_SKEW_SECONDS = 5.0
MICROPHONE_LEVEL_INTERVAL_SECONDS = 0.1
NON_REPLAYABLE_ACTION_TYPES = frozenset(
    {
        "move",
        "look",
        "jump",
        "interact",
        "stop",
        "captureimage",
        "robotcommand",
        "robotmotionplan",
    }
)


def _normalized_action_type(action: Mapping[str, object]) -> str:
    return str(action.get("type", "")).strip().lower().replace("_", "")


@dataclass(frozen=True)
class EnvironmentAdapterConfig:
    token: str
    session_id: str = "ainekio-sim-1"
    environment_id: str = "ainekio"
    adapter_id: str = "ainekio-gateway"
    robot_id: str | None = None
    snapshot_after_action: bool = True
    max_utterance_ms: int = 15000
    freestyle_enabled: bool = True

    def __post_init__(self) -> None:
        if not self.token.strip() or len(self.token) > 512:
            raise ValueError("a bounded environment adapter token is required")
        if not 20 <= self.max_utterance_ms <= 15000 or self.max_utterance_ms % 20:
            raise ValueError("max utterance duration must be a 20 ms multiple up to 15 seconds")


def encode_audio_utterance_message(
    utterance: AudioUtterance,
    *,
    session_id: str,
) -> bytes:
    metadata = json.dumps(
        utterance.metadata(session_id=session_id),
        separators=(",", ":"),
    ).encode("utf-8")
    wav = utterance.wav_bytes()
    encoded = (
        AUDIO_UTTERANCE_MAGIC
        + struct.pack("<I", len(metadata))
        + metadata
        + wav
    )
    if len(encoded) > MAX_ADAPTER_BINARY_MESSAGE_BYTES:
        raise GatewayError("audio utterance exceeds its bridge size limit")
    return encoded


class EnvironmentAdapter:
    def __init__(
        self,
        gateway: GatewayService,
        config: EnvironmentAdapterConfig,
        *,
        clock: Callable[[], float] = monotonic,
        utcnow: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self.gateway = gateway
        self.config = config
        self.clock = clock
        self.utcnow = utcnow
        self._websocket: Any | None = None
        self._send_lock = asyncio.Lock()
        self._camera_observation_count = 0
        self._pending_snapshot_context: dict[str, object] | None = None
        self._snapshot_lock = asyncio.Lock()
        self._last_microphone_level_at = float("-inf")
        self._last_audio_result: dict[str, object] | None = None
        self._action_tasks: set[asyncio.Task[None]] = set()
        self._audio_utterances = AudioUtterancePlugin(
            gateway,
            self._handle_gateway_utterance,
            max_duration_ms=config.max_utterance_ms,
            utcnow=utcnow,
        )
        gateway.subscribe_events(self._handle_gateway_event)
        gateway.subscribe_frames(self._handle_gateway_frame)
        gateway.subscribe_transcripts(self._handle_gateway_transcript)

    async def handler(self, websocket: Any) -> None:
        try:
            raw = await asyncio.wait_for(websocket.recv(), timeout=5.0)
            hello = self._decode_message(raw)
        except Exception:
            await websocket.close(code=4002, reason="malformed environment handshake")
            return

        supplied = hello.get("token")
        if (
            hello.get("type") != "bridge.connect"
            or hello.get("version") != ADAPTER_PROTOCOL_VERSION
            or not isinstance(supplied, str)
            or not hmac.compare_digest(self.config.token, supplied)
        ):
            await websocket.close(code=4001, reason="environment authentication failed")
            return

        previous = self._websocket
        self._websocket = websocket
        if previous is not None and previous is not websocket:
            await previous.close(code=4000, reason="new authenticated environment connection")

        await self._send(
            {
                "type": "bridge.ready",
                "version": ADAPTER_PROTOCOL_VERSION,
                "sessionId": self.config.session_id,
                "observation": self._observation(),
            }
        )
        try:
            async for raw in websocket:
                message = self._decode_message(raw)
                if message.get("type") == "audio.utterance.result":
                    self._last_audio_result = {
                        key: value
                        for key, value in message.items()
                        if key in {"utteranceId", "status", "message", "timestamp"}
                    }
                    continue
                if message.get("type") != "environment.action":
                    continue
                action = message.get("action")
                if not isinstance(action, dict):
                    continue
                task = asyncio.create_task(self._process_environment_action(action))
                self._action_tasks.add(task)
                task.add_done_callback(self._action_tasks.discard)
        except ConnectionClosed:
            pass
        finally:
            if self._websocket is websocket:
                self._websocket = None

    async def _process_environment_action(self, action: dict[str, Any]) -> None:
        capture_image = _normalized_action_type(action) == "captureimage"
        previous_camera_count = self._camera_observation_count
        feedback = await self.handle_action(action)
        await self._send(
            {
                "type": "environment.feedback",
                "version": ADAPTER_PROTOCOL_VERSION,
                "sessionId": self.config.session_id,
                "feedback": feedback,
            }
        )
        observation_sent = (
            capture_image
            and self._camera_observation_count > previous_camera_count
        )
        if (
            not capture_image
            and feedback["type"] == "completed"
            and self.config.snapshot_after_action
        ):
            previous_camera_count = self._camera_observation_count
            await self._request_post_action_snapshot(
                self._snapshot_context(action)
            )
            observation_sent = self._camera_observation_count > previous_camera_count
        if not observation_sent:
            await self._send_observation()

    async def handle_action(
        self,
        action: dict[str, Any],
        *,
        received_at: float | None = None,
    ) -> dict[str, object]:
        action_id = str(action["id"]) if action.get("id") else None
        if self._control_action_is_expired(action):
            if _normalized_action_type(action) == "robotmotionplan":
                await self._send_motion_plan_status(
                    action_id,
                    "rejected",
                    message="action_expired_before_dispatch",
                )
            return self._feedback(action_id, "expired", "action_expired_before_dispatch")
        translated = translate_environment_action(action)
        if translated is None:
            if _normalized_action_type(action) == "robotmotionplan":
                await self._send_motion_plan_status(
                    action_id,
                    "rejected",
                    message="invalid_or_unsupported_plan",
                )
            return self._feedback(
                action_id,
                "rejected",
                f"unsupported_action:{action.get('type')}",
            )
        if translated.kind == "text":
            await self.gateway.publish_transcript(
                {
                    "source": "environment_adapter",
                    "session_id": self.config.session_id,
                    **translated.params,
                }
            )
            return self._feedback(action_id, "completed", "text_received", command="sendText")

        accepted_at = self.clock() if received_at is None else received_at
        progress_task: asyncio.Task[None] | None = None
        snapshot_lock_acquired = False
        snapshot_context = (
            self._snapshot_context(action)
            if translated.kind == "snapshot"
            else None
        )
        frame_durations: list[int] = []
        if translated.kind == "motion_plan":
            frames = translated.params.get("frames")
            if isinstance(frames, list):
                frame_durations = [
                    int(frame[0])
                    for frame in frames
                    if isinstance(frame, list)
                    and len(frame) == 2
                    and type(frame[0]) is int
                ]
            await self._send_motion_plan_status(
                action_id,
                "validating",
                frame_count=len(frame_durations),
                duration_ms=sum(frame_durations),
            )
        elif translated.kind == "stop":
            await self._send_telemetry(
                "movement.stop",
                {"actionId": action_id, "status": "requested"},
            )
        try:
            if translated.kind == "snapshot":
                await self._snapshot_lock.acquire()
                snapshot_lock_acquired = True
                self._pending_snapshot_context = snapshot_context
            sequence = await self._dispatch(translated, accepted_at)
            if translated.kind == "motion_plan":
                await self._send_motion_plan_status(
                    action_id,
                    "active",
                    sequence=sequence,
                    frame_count=len(frame_durations),
                    duration_ms=sum(frame_durations),
                    active_frame=1,
                )
                progress_task = asyncio.create_task(
                    self._report_motion_plan_progress(
                        action_id,
                        sequence,
                        frame_durations,
                    )
                )
            terminal = await self.gateway.wait_terminal(
                sequence,
                robot_id=self.config.robot_id,
                timeout=30.0,
            )
        except (GatewayError, TimeoutError) as exc:
            if translated.kind == "motion_plan":
                await self._send_motion_plan_status(
                    action_id,
                    "rejected",
                    frame_count=len(frame_durations),
                    duration_ms=sum(frame_durations),
                    message=str(exc),
                )
            return self._feedback(action_id, "rejected", str(exc), command=translated.name)
        finally:
            if progress_task is not None:
                progress_task.cancel()
                await asyncio.gather(progress_task, return_exceptions=True)
            if snapshot_lock_acquired:
                if self._pending_snapshot_context is snapshot_context:
                    self._pending_snapshot_context = None
                self._snapshot_lock.release()

        terminal_type = str(terminal.get("t"))
        if terminal_type in {"ack", "done"}:
            status = "completed"
            message = terminal_type
        elif terminal_type == "cancelled":
            status = "cancelled"
            message = str(terminal.get("code", "cancelled"))
        else:
            status = "rejected"
            message = str(terminal.get("code", "rejected"))
        if translated.kind == "motion_plan":
            await self._send_motion_plan_status(
                action_id,
                status,
                sequence=sequence,
                frame_count=len(frame_durations),
                duration_ms=sum(frame_durations),
                active_frame=len(frame_durations) if status == "completed" else None,
                message=message,
            )
        return self._feedback(
            action_id,
            status,
            message,
            command=translated.name or translated.kind,
            sequence=sequence,
        )

    async def _report_motion_plan_progress(
        self,
        action_id: str | None,
        sequence: int,
        frame_durations: list[int],
    ) -> None:
        for frame_index, duration_ms in enumerate(frame_durations, start=1):
            await asyncio.sleep(duration_ms / 1000.0)
            next_frame = frame_index + 1
            if next_frame > len(frame_durations):
                return
            await self._send_motion_plan_status(
                action_id,
                "active",
                sequence=sequence,
                frame_count=len(frame_durations),
                duration_ms=sum(frame_durations),
                active_frame=next_frame,
            )

    async def _send_motion_plan_status(
        self,
        action_id: str | None,
        status: str,
        *,
        sequence: int | None = None,
        frame_count: int | None = None,
        duration_ms: int | None = None,
        active_frame: int | None = None,
        message: str | None = None,
    ) -> None:
        await self._send_telemetry(
            "movement.plan",
            {
                "actionId": action_id,
                "status": status,
                "sequence": sequence,
                "frameCount": frame_count,
                "durationMs": duration_ms,
                "activeFrame": active_frame,
                "message": message,
            },
        )

    async def _dispatch(self, action: BridgeAction, received_at: float) -> int:
        if action.kind == "stop":
            return await self.gateway.estop(
                robot_id=self.config.robot_id,
                received_at=received_at,
            )
        if action.kind == "intent" and action.name is not None:
            return await self.gateway.queue_intent(
                action.name,
                action.params,
                robot_id=self.config.robot_id,
                received_at=received_at,
            )
        if action.kind == "motion_plan":
            frames = action.params.get("frames")
            end = action.params.get("end")
            if not isinstance(frames, list) or not isinstance(end, str):
                raise GatewayError("invalid translated motion plan")
            if not self.config.freestyle_enabled:
                raise GatewayError("freestyle movement is disabled by owner policy")
            return await self.gateway.queue_motion_plan(
                frames,
                end=end,
                robot_id=self.config.robot_id,
                received_at=received_at,
            )
        if action.kind == "snapshot":
            return await self.gateway.request_snap(robot_id=self.config.robot_id)
        raise GatewayError("unsupported translated environment action")

    async def _request_post_action_snapshot(
        self,
        snapshot_context: dict[str, object] | None = None,
    ) -> None:
        async with self._snapshot_lock:
            self._pending_snapshot_context = snapshot_context
            try:
                sequence = await self.gateway.request_snap(robot_id=self.config.robot_id)
                await self.gateway.wait_terminal(
                    sequence,
                    robot_id=self.config.robot_id,
                    timeout=10.0,
                )
            except (GatewayError, TimeoutError):
                return
            finally:
                if self._pending_snapshot_context is snapshot_context:
                    self._pending_snapshot_context = None

    def _snapshot_context(
        self,
        action: Mapping[str, object],
    ) -> dict[str, object] | None:
        metadata = action.get("metadata")
        robot_observer = (
            metadata.get("robotObserver")
            if isinstance(metadata, Mapping)
            else None
        )
        correlation_id = action.get("correlationId") or action.get("id")
        if not isinstance(robot_observer, Mapping) and not isinstance(
            correlation_id, str
        ):
            return None
        context: dict[str, object] = {}
        if isinstance(correlation_id, str) and correlation_id.strip():
            context["correlationId"] = correlation_id.strip()
        if isinstance(robot_observer, Mapping):
            context["robotObserver"] = dict(robot_observer)
        return context or None

    async def _handle_gateway_event(self, event: dict[str, object]) -> None:
        if event.get("t") == "status":
            await self._send_telemetry(
                "robot.status",
                {
                    key: value
                    for key, value in event.items()
                    if key in {
                        "robot_id",
                        "epoch",
                        "vbat",
                        "rssi",
                        "state",
                        "uptime",
                        "heap",
                        "sd",
                        "cam_drops",
                        "spk_underruns",
                        "mic_drops",
                        "wake_enabled",
                        "wake_model",
                        "wake_ready",
                    }
                },
            )
            return
        if event.get("t") not in {"connection", "event"}:
            return
        if event.get("t") == "event" and event.get("name") == "vad_close":
            await self._send_telemetry(
                "audio.level",
                {
                    "robot_id": event.get("robot_id"),
                    "epoch": event.get("epoch"),
                    "level": 0.0,
                },
            )
        await self._send_observation(body_event=event)

    async def _handle_gateway_utterance(self, utterance: AudioUtterance) -> None:
        if self.config.robot_id is not None and utterance.robot_id != self.config.robot_id:
            return
        websocket = self._websocket
        if websocket is None or websocket.closed:
            return
        encoded = encode_audio_utterance_message(
            utterance,
            session_id=self.config.session_id,
        )
        async with self._send_lock:
            await websocket.send(encoded)

    async def _handle_gateway_transcript(self, transcript: dict[str, object]) -> None:
        if transcript.get("source") == "environment_adapter":
            return
        text = transcript.get("text")
        if not isinstance(text, str) or not text.strip():
            return
        text_event = {
            "id": f"ainekio-text-{int(self.clock() * 1000)}",
            "source": "environment",
            "text": text[:4096],
            "timestamp": self.utcnow().isoformat(),
        }
        await self._send_observation(text=[text_event])

    async def _handle_gateway_frame(self, frame: dict[str, object]) -> None:
        if frame.get("frame_type") == MIC_PCM_FRAME_TYPE:
            payload = frame.get("payload")
            now = self.clock()
            if (
                isinstance(payload, bytes)
                and len(payload) == 640
                and now - self._last_microphone_level_at
                >= MICROPHONE_LEVEL_INTERVAL_SECONDS
            ):
                samples = struct.unpack("<320h", payload)
                level = math.sqrt(
                    sum(sample * sample for sample in samples) / len(samples)
                ) / 32768.0
                self._last_microphone_level_at = now
                await self._send_telemetry(
                    "audio.level",
                    {
                        "robot_id": frame.get("robot_id"),
                        "epoch": frame.get("epoch"),
                        "counter": frame.get("counter"),
                        "level": round(level, 4),
                    },
                )
            return
        if frame.get("frame_type") != CAMERA_JPEG_FRAME_TYPE:
            return
        payload = frame.get("payload")
        if not isinstance(payload, bytes):
            return
        snapshot_context = self._pending_snapshot_context
        if snapshot_context is not None:
            self._pending_snapshot_context = None
        visual = {
            "id": f"ainekio-camera-{frame.get('counter', int(self.clock() * 1000))}",
            "timestamp": self.utcnow().isoformat(),
            "mimeType": "image/jpeg",
            "dataUrl": f"data:image/jpeg;base64,{base64.b64encode(payload).decode('ascii')}",
            "source": "robot-camera",
            "metadata": {
                "robotId": frame.get("robot_id"),
                "counter": frame.get("counter"),
                "bytes": len(payload),
                **(
                    {"correlationId": snapshot_context["correlationId"]}
                    if snapshot_context is not None
                    and "correlationId" in snapshot_context
                    else {}
                ),
            },
        }
        await self._send_observation(
            visual=visual,
            metadata=snapshot_context,
        )
        self._camera_observation_count += 1

    async def _send_telemetry(
        self,
        kind: str,
        data: Mapping[str, object],
    ) -> None:
        await self._send(
            {
                "type": "environment.telemetry",
                "version": ADAPTER_PROTOCOL_VERSION,
                "sessionId": self.config.session_id,
                "telemetry": {
                    "kind": kind,
                    "timestamp": self.utcnow().isoformat(),
                    **data,
                },
            }
        )

    async def _send_observation(
        self,
        *,
        text: list[dict[str, object]] | None = None,
        visual: dict[str, object] | None = None,
        body_event: dict[str, object] | None = None,
        metadata: dict[str, object] | None = None,
    ) -> None:
        await self._send(
            {
                "type": "environment.observation",
                "version": ADAPTER_PROTOCOL_VERSION,
                "sessionId": self.config.session_id,
                "observation": self._observation(
                    text=text,
                    visual=visual,
                    body_event=body_event,
                    metadata=metadata,
                ),
            }
        )

    def _observation(
        self,
        *,
        text: list[dict[str, object]] | None = None,
        visual: dict[str, object] | None = None,
        body_event: dict[str, object] | None = None,
        metadata: dict[str, object] | None = None,
    ) -> dict[str, object]:
        state: dict[str, object] = {
            "transport": "protocol-v1",
            "safety": "body-owned",
            "gateway": self.gateway.status(),
            "freestyleMovement": self._motion_plan_support_status(),
        }
        if body_event is not None:
            state["bodyEvent"] = {
                key: value
                for key, value in body_event.items()
                if key in {"t", "name", "status", "robot_id", "epoch"}
            }
        if self._last_audio_result is not None:
            state["lastAudioResult"] = dict(self._last_audio_result)
        actions = ["robotCommand", "move", "stop", "sendText"]
        if self._motion_plan_available():
            actions.append("robotMotionPlan")
        observation: dict[str, object] = {
            "environmentId": self.config.environment_id,
            "adapter": self.config.adapter_id,
            "sessionId": self.config.session_id,
            "timestamp": self.utcnow().isoformat(),
            "capabilities": {
                "actions": actions,
                "robotCommands": list(SUPPORTED_ROBOT_COMMANDS),
                "text": True,
                "movement": True,
                "visual": True,
                "map": False,
            },
            "state": state,
        }
        if text:
            observation["text"] = text
        if visual:
            observation["visual"] = visual
            observation["visuals"] = [visual]
        if metadata:
            observation["metadata"] = dict(metadata)
        return observation

    def _motion_plan_available(self) -> bool:
        return self._motion_plan_support_status()["available"] is True

    def _motion_plan_support_status(self) -> dict[str, bool]:
        robots = self.gateway.status().get("robots")
        if not isinstance(robots, Mapping):
            return {
                "supported": False,
                "enabled": self.config.freestyle_enabled,
                "available": False,
            }
        if self.config.robot_id is not None:
            robot = robots.get(self.config.robot_id)
        elif len(robots) == 1:
            robot = next(iter(robots.values()))
        else:
            return {
                "supported": False,
                "enabled": self.config.freestyle_enabled,
                "available": False,
            }
        if not isinstance(robot, Mapping):
            return {
                "supported": False,
                "enabled": self.config.freestyle_enabled,
                "available": False,
            }
        features = robot.get("features")
        supported = isinstance(features, list) and "motion_plan_v1" in features
        return {
            "supported": supported,
            "enabled": self.config.freestyle_enabled,
            "available": supported and self.config.freestyle_enabled,
        }

    async def _send(self, message: Mapping[str, object]) -> None:
        websocket = self._websocket
        if websocket is None or websocket.closed:
            return
        encoded = json.dumps(message, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > MAX_ADAPTER_JSON_MESSAGE_BYTES:
            raise GatewayError("environment adapter message exceeds its size limit")
        async with self._send_lock:
            await websocket.send(encoded)

    def _decode_message(self, raw: object) -> dict[str, Any]:
        if not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_ADAPTER_JSON_MESSAGE_BYTES:
            raise ValueError("invalid environment adapter message")
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError("environment adapter message must be an object")
        return value

    def _control_action_is_expired(self, action: Mapping[str, object]) -> bool:
        action_type = str(action.get("type", "")).strip().lower().replace("_", "")
        if action_type not in NON_REPLAYABLE_ACTION_TYPES:
            return False
        created_at = action.get("createdAt")
        if not isinstance(created_at, str):
            return True
        try:
            parsed = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        except ValueError:
            return True
        if parsed.tzinfo is None:
            return True
        age = (self.utcnow() - parsed.astimezone(timezone.utc)).total_seconds()
        return age > MAX_CONTROL_ACTION_AGE_SECONDS or age < -MAX_FUTURE_CLOCK_SKEW_SECONDS

    def _feedback(
        self,
        action_id: str | None,
        status: str,
        message: str,
        *,
        command: str | None = None,
        sequence: int | None = None,
    ) -> dict[str, object]:
        return {
            "id": f"ainekio-result-{action_id or int(self.clock() * 1000)}",
            "timestamp": self.utcnow().isoformat(),
            "type": status,
            "message": message,
            "actionId": action_id,
            "data": {"command": command, "sequence": sequence},
        }
