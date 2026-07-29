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

from gateway.plugins import (
    AudioUtterance,
    AudioUtterancePlugin,
    robot_utterance_id,
)
from gateway.server.service import GatewayError, GatewayService
from protocol.binary_helpers import CAMERA_JPEG_FRAME_TYPE, MIC_PCM_FRAME_TYPE
from websockets.exceptions import ConnectionClosed

from .speech_transport import (
    SpeechAudioMessage,
    paced_speaker_frames,
    parse_speech_audio_message,
)
from .translation import (
    SUPPORTED_ROBOT_COMMANDS,
    BridgeAction,
    translate_environment_action,
)


ADAPTER_PROTOCOL_VERSION = 1
# A raw JPEG may be 256 KiB. Its base64 data URL needs roughly one third more
# room while remaining below the gateway's 512 KiB bridge-frame ceiling.
MAX_ADAPTER_JSON_MESSAGE_BYTES = 384 * 1024
MAX_ADAPTER_BINARY_MESSAGE_BYTES = 512 * 1024
AUDIO_UTTERANCE_MAGIC = b"AIKAUD01"
AUDIO_UTTERANCE_HEADER_BYTES = len(AUDIO_UTTERANCE_MAGIC) + 4
MAX_CONTROL_ACTION_AGE_SECONDS = 2.0
MAX_FUTURE_CLOCK_SKEW_SECONDS = 5.0
MICROPHONE_LEVEL_INTERVAL_SECONDS = 0.1
BRIDGE_SEND_TIMEOUT_SECONDS = 2.0
ACTION_VISUAL_WAIT_SECONDS = 2.0
CAMERA_DELIVERY_QUEUE_LENGTH = 1
MAX_PENDING_ACTION_VISUALS = 32
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
    session_id: str = "ainekio-01"
    environment_id: str = "ainekio"
    adapter_id: str = "ainekio-gateway"
    robot_id: str | None = None
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
        self._pending_snapshot_key: tuple[str, int, int] | None = None
        self._robot_action_contexts: dict[
            tuple[str, int, int],
            dict[str, object],
        ] = {}
        self._robot_snapshot_contexts: dict[
            tuple[str, int, int],
            dict[str, object],
        ] = {}
        self._pending_action_visuals: dict[
            str,
            asyncio.Future[dict[str, object] | None],
        ] = {}
        self._action_frames_received: set[str] = set()
        self._camera_delivery_queue: asyncio.Queue[
            tuple[dict[str, object], dict[str, object]]
        ] | None = None
        self._camera_delivery_task: asyncio.Task[None] | None = None
        self._snapshot_in_flight = False
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
        previous_camera_task = self._camera_delivery_task
        self._websocket = websocket
        self._camera_delivery_queue = asyncio.Queue(
            maxsize=CAMERA_DELIVERY_QUEUE_LENGTH
        )
        self._camera_delivery_task = asyncio.create_task(
            self._camera_delivery_worker(websocket)
        )
        if previous_camera_task is not None:
            previous_camera_task.cancel()
            await asyncio.gather(previous_camera_task, return_exceptions=True)
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
                if isinstance(raw, bytes):
                    try:
                        speech = parse_speech_audio_message(
                            raw,
                            expected_session_id=self.config.session_id,
                            max_message_bytes=MAX_ADAPTER_BINARY_MESSAGE_BYTES,
                        )
                    except ValueError:
                        await websocket.close(
                            code=1002,
                            reason="malformed environment speech frame",
                        )
                        return
                    await self._process_speech_audio(speech)
                    continue
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
                if self._camera_delivery_task is not None:
                    self._camera_delivery_task.cancel()
                    await asyncio.gather(
                        self._camera_delivery_task,
                        return_exceptions=True,
                    )
                self._camera_delivery_task = None
                self._camera_delivery_queue = None

    async def _process_speech_audio(self, speech: SpeechAudioMessage) -> None:
        robot_id, robot = self._selected_robot()
        if robot is None:
            feedback = self._feedback(
                speech.action_id,
                "rejected",
                "requested robot is not connected",
                command="speak",
            )
        else:
            try:
                sequence = await self.gateway.tts_speak(
                    paced_speaker_frames(speech.pcm),
                    robot_id=self.config.robot_id,
                    received_at=self.clock(),
                )
                terminal = await self.gateway.wait_terminal(
                    sequence,
                    robot_id=self.config.robot_id,
                    timeout=max(5.0, speech.duration_ms / 1_000 + 5.0),
                )
                terminal_type = str(terminal.get("t"))
                status = {
                    "done": "completed",
                    "cancelled": "cancelled",
                }.get(terminal_type, "rejected")
                feedback = self._feedback(
                    speech.action_id,
                    status,
                    "speech_played" if status == "completed"
                    else str(terminal.get("code", terminal_type)),
                    command="speak",
                    sequence=sequence,
                    robot_id=robot_id,
                )
            except (GatewayError, TimeoutError) as error:
                feedback = self._feedback(
                    speech.action_id,
                    "failed",
                    str(error),
                    command="speak",
                    robot_id=robot_id,
                )
        await self._send(
            {
                "type": "environment.feedback",
                "version": ADAPTER_PROTOCOL_VERSION,
                "sessionId": self.config.session_id,
                "feedback": feedback,
            }
        )

    async def _process_environment_action(self, action: dict[str, Any]) -> None:
        action_id = action.get("id")
        visual_future: asyncio.Future[dict[str, object] | None] | None = None
        translated = translate_environment_action(action)
        if (
            isinstance(action_id, str)
            and translated is not None
            and translated.kind in {"intent", "motion_plan", "snapshot"}
        ):
            visual_future = asyncio.get_running_loop().create_future()
            self._remember_action_visual(action_id, visual_future)
        try:
            feedback = await self.handle_action(action)
            visual: dict[str, object] | None = None
            if (
                visual_future is not None
                and feedback.get("type") == "completed"
                and (
                    visual_future.done()
                    or (
                        isinstance(action_id, str)
                        and action_id in self._action_frames_received
                    )
                )
            ):
                try:
                    visual = await asyncio.wait_for(
                        asyncio.shield(visual_future),
                        timeout=ACTION_VISUAL_WAIT_SECONDS,
                    )
                except asyncio.TimeoutError:
                    visual = None
            await self._send(
                {
                    "type": "environment.feedback",
                    "version": ADAPTER_PROTOCOL_VERSION,
                    "sessionId": self.config.session_id,
                    "feedback": feedback,
                }
            )
            if visual is not None:
                await self._send_observation(
                    visual=visual,
                    metadata=self._snapshot_context(action),
                    feedback=[feedback],
                )
                self._camera_observation_count += 1
            else:
                await self._send_observation(feedback=[feedback])
        finally:
            if isinstance(action_id, str):
                self._action_frames_received.discard(action_id)
                pending = self._pending_action_visuals.pop(action_id, None)
                if pending is not None and not pending.done():
                    pending.cancel()

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

        robot_id, robot = self._selected_robot()
        if robot is None:
            if translated.kind == "motion_plan":
                await self._send_motion_plan_status(
                    action_id,
                    "rejected",
                    message="requested robot is not connected",
                )
            return self._feedback(
                action_id,
                "rejected",
                "requested robot is not connected",
                command=translated.name or translated.kind,
            )
        if translated.kind == "snapshot" and not self._camera_ready():
            return self._feedback(
                action_id,
                "rejected",
                "camera is not ready",
                command=translated.name,
            )
        robot_epoch = robot.get("epoch")

        accepted_at = self.clock() if received_at is None else received_at
        progress_task: asyncio.Task[None] | None = None
        snapshot_lock_acquired = False
        snapshot_context = self._snapshot_context(action)
        frame_durations: list[int] = []
        sequence: int | None = None
        action_context_key: tuple[str, int, int] | None = None
        def remember_sequence(assigned_sequence: int) -> None:
            nonlocal action_context_key
            if (
                snapshot_context is None
                or not isinstance(robot_id, str)
                or type(robot_epoch) is not int
            ):
                return
            action_context_key = (
                robot_id,
                robot_epoch,
                assigned_sequence,
            )
            self._remember_bounded(
                self._robot_action_contexts,
                action_context_key,
                snapshot_context,
            )

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
                self._snapshot_in_flight = True
                self._pending_snapshot_context = snapshot_context
                self._pending_snapshot_key = None
            sequence = await self._dispatch(
                translated,
                accepted_at,
                on_sequence=remember_sequence,
            )
            if action_context_key is None:
                remember_sequence(sequence)
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
                self._pending_snapshot_key = None
                self._snapshot_in_flight = False
                self._snapshot_lock.release()
            if action_context_key is not None:
                self._robot_action_contexts.pop(action_context_key, None)

        assert sequence is not None
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
            robot_id=robot_id,
            epoch=robot_epoch if type(robot_epoch) is int else None,
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

    async def _dispatch(
        self,
        action: BridgeAction,
        received_at: float,
        *,
        on_sequence: Callable[[int], None] | None = None,
    ) -> int:
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
                on_sequence=on_sequence,
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
                on_sequence=on_sequence,
            )
        if action.kind == "snapshot":
            return await self.gateway.request_snap(
                robot_id=self.config.robot_id,
                on_sequence=on_sequence,
            )
        raise GatewayError("unsupported translated environment action")

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
        action_id = action.get("id")
        if not isinstance(robot_observer, Mapping) and not isinstance(
            correlation_id, str
        ):
            return None
        context: dict[str, object] = {}
        if isinstance(correlation_id, str) and correlation_id.strip():
            context["correlationId"] = correlation_id.strip()
        if isinstance(action_id, str) and action_id.strip():
            context["actionId"] = action_id.strip()
        if isinstance(robot_observer, Mapping):
            context["robotObserver"] = dict(robot_observer)
        return context or None

    @staticmethod
    def _snapshot_key(
        message: Mapping[str, object],
        counter: int,
    ) -> tuple[str, int, int] | None:
        robot_id = message.get("robot_id")
        epoch = message.get("epoch")
        if not isinstance(robot_id, str) or type(epoch) is not int:
            return None
        return (robot_id, epoch, counter)

    @staticmethod
    def _remember_bounded(
        values: dict[tuple[str, int, int], dict[str, object]],
        key: tuple[str, int, int],
        value: dict[str, object],
        *,
        maximum: int = 32,
    ) -> None:
        values[key] = value
        while len(values) > maximum:
            del values[next(iter(values))]

    def _remember_action_visual(
        self,
        action_id: str,
        future: asyncio.Future[dict[str, object] | None],
    ) -> None:
        previous = self._pending_action_visuals.pop(action_id, None)
        if previous is not None and not previous.done():
            previous.cancel()
        self._pending_action_visuals[action_id] = future
        while len(self._pending_action_visuals) > MAX_PENDING_ACTION_VISUALS:
            oldest = next(iter(self._pending_action_visuals))
            discarded = self._pending_action_visuals.pop(oldest)
            if not discarded.done():
                discarded.cancel()

    def _clear_robot_correlations(
        self,
        robot_id: str,
        epoch: int | None,
    ) -> None:
        for values in (
            self._robot_action_contexts,
            self._robot_snapshot_contexts,
        ):
            for key in tuple(values):
                if key[0] == robot_id and (epoch is None or key[1] != epoch):
                    values.pop(key, None)
        if (
            self._pending_snapshot_key is not None
            and self._pending_snapshot_key[0] == robot_id
            and (
                epoch is None
                or self._pending_snapshot_key[1] != epoch
            )
        ):
            self._pending_snapshot_key = None
            self._pending_snapshot_context = None

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
                        "camera_ready",
                        "spk_underruns",
                        "mic_drops",
                        "wake_enabled",
                        "wake_model",
                        "wake_ready",
                    }
                },
            )
            return
        if event.get("t") == "cam_meta":
            counter = event.get("counter_base")
            origin = event.get("origin")
            origin_id = event.get("origin_id")
            if (
                event.get("fps") == 0
                and type(counter) is int
                and origin in {"request", "action"}
                and type(origin_id) is int
            ):
                snapshot_key = self._snapshot_key(event, counter)
                robot_id = event.get("robot_id")
                epoch = event.get("epoch")
                action_key = (
                    (robot_id, epoch, origin_id)
                    if isinstance(robot_id, str) and type(epoch) is int
                    else None
                )
                context = (
                    self._robot_action_contexts.get(action_key)
                    if action_key is not None
                    else None
                )
                if context is not None and snapshot_key is not None:
                    self._remember_bounded(
                        self._robot_snapshot_contexts,
                        snapshot_key,
                        context,
                    )
                    return
            if (
                event.get("fps") == 0
                and type(counter) is int
                and origin == "audio"
                and type(origin_id) is int
                and isinstance(event.get("robot_id"), str)
                and type(event.get("epoch")) is int
            ):
                utterance_id = robot_utterance_id(
                    str(event["robot_id"]),
                    int(event["epoch"]),
                    origin_id,
                )
                snapshot_key = self._snapshot_key(event, counter)
                if snapshot_key is not None:
                    self._remember_bounded(
                        self._robot_snapshot_contexts,
                        snapshot_key,
                        {
                            "correlationId": utterance_id,
                            "audioUtteranceId": utterance_id,
                            "robotId": event["robot_id"],
                            "epoch": event["epoch"],
                            "perceptionEvent": "audio_utterance",
                        },
                    )
                return
            if (
                self._snapshot_in_flight
                and event.get("fps") == 0
                and type(counter) is int
            ):
                self._pending_snapshot_key = self._snapshot_key(event, counter)
            return
        if event.get("t") not in {"connection", "event"}:
            return
        if event.get("t") == "connection":
            robot_id = event.get("robot_id")
            epoch = event.get("epoch")
            if isinstance(robot_id, str):
                self._clear_robot_correlations(
                    robot_id,
                    epoch
                    if event.get("status") == "connected" and type(epoch) is int
                    else None,
                )
        if event.get("t") == "event" and event.get("name") in {
            "vad_open",
            "vad_close",
            "wake_word",
        }:
            if event.get("name") == "vad_close":
                await self._send_telemetry(
                    "audio.level",
                    {
                        "robot_id": event.get("robot_id"),
                        "epoch": event.get("epoch"),
                        "level": 0.0,
                    },
                )
            return
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
        await self._send_payload(websocket, encoded)

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
        counter = frame.get("counter")
        if type(counter) is not int:
            return
        snapshot_key = self._snapshot_key(frame, counter)
        snapshot_context = (
            self._robot_snapshot_contexts.pop(snapshot_key, None)
            if snapshot_key is not None
            else None
        )
        if (
            snapshot_context is None
            and self._snapshot_in_flight
            and snapshot_key == self._pending_snapshot_key
        ):
            snapshot_context = self._pending_snapshot_context
        if snapshot_context is None:
            return
        self._pending_snapshot_context = None
        self._pending_snapshot_key = None
        queue = self._camera_delivery_queue
        if queue is None:
            await self._deliver_camera_frame(frame, snapshot_context)
            return
        item = (dict(frame), snapshot_context)
        action_id = snapshot_context.get("actionId")
        if isinstance(action_id, str):
            self._action_frames_received.add(action_id)
        try:
            queue.put_nowait(item)
        except asyncio.QueueFull:
            discarded_frame, discarded_context = queue.get_nowait()
            del discarded_frame
            queue.task_done()
            self._resolve_action_visual(discarded_context, None)
            queue.put_nowait(item)

    def _resolve_action_visual(
        self,
        context: Mapping[str, object],
        visual: dict[str, object] | None,
    ) -> bool:
        action_id = context.get("actionId")
        if not isinstance(action_id, str):
            return False
        pending = self._pending_action_visuals.get(action_id)
        if pending is not None and not pending.done():
            pending.set_result(visual)
        return True

    async def _camera_delivery_worker(self, websocket: Any) -> None:
        while self._websocket is websocket:
            queue = self._camera_delivery_queue
            if queue is None:
                return
            frame, snapshot_context = await queue.get()
            try:
                await self._deliver_camera_frame(frame, snapshot_context)
            except Exception:
                self._resolve_action_visual(snapshot_context, None)
            finally:
                queue.task_done()

    async def _deliver_camera_frame(
        self,
        frame: Mapping[str, object],
        snapshot_context: dict[str, object],
    ) -> None:
        payload = frame.get("payload")
        if not isinstance(payload, bytes):
            self._resolve_action_visual(snapshot_context, None)
            return
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
                **{
                    key: snapshot_context[key]
                    for key in ("correlationId", "audioUtteranceId", "actionId")
                    if snapshot_context is not None
                    and isinstance(snapshot_context.get(key), str)
                },
            },
        }
        if self._resolve_action_visual(snapshot_context, visual):
            return
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
        feedback: list[dict[str, object]] | None = None,
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
                    feedback=feedback,
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
        feedback: list[dict[str, object]] | None = None,
    ) -> dict[str, object]:
        gateway_status = self.gateway.status()
        robot_id, robot = self._selected_robot(gateway_status)
        body_authenticated = robot is not None
        body_status = robot.get("status") if robot is not None else None
        camera_ready = (
            body_authenticated
            and isinstance(body_status, Mapping)
            and body_status.get("camera_ready") is True
        )
        heartbeat_age_ms = robot.get("heartbeat_age_ms") if robot is not None else None
        state: dict[str, object] = {
            "transport": "protocol-v1",
            "safety": "body-owned",
            "adapterConnected": True,
            "body": {
                "authenticated": body_authenticated,
                "robotId": robot_id,
                "heartbeatAgeMs": heartbeat_age_ms
                if type(heartbeat_age_ms) is int
                else None,
                "motionAvailable": body_authenticated,
                "cameraReady": camera_ready,
                "microphoneReady": None,
                "speakerReady": body_authenticated,
            },
            "gateway": gateway_status,
            "freestyleMovement": self._motion_plan_support_status(gateway_status),
        }
        if body_event is not None:
            state["bodyEvent"] = {
                key: value
                for key, value in body_event.items()
                if key in {"t", "name", "status", "robot_id", "epoch"}
            }
        if self._last_audio_result is not None:
            state["lastAudioResult"] = dict(self._last_audio_result)
        actions = ["sendText"]
        robot_commands: list[str] = []
        if body_authenticated:
            actions.extend(["robotCommand", "move", "stop"])
            robot_commands = list(SUPPORTED_ROBOT_COMMANDS)
        if camera_ready:
            actions.append("captureImage")
        if self._motion_plan_available(gateway_status):
            actions.append("robotMotionPlan")
        observation: dict[str, object] = {
            "environmentId": self.config.environment_id,
            "adapter": self.config.adapter_id,
            "sessionId": self.config.session_id,
            "timestamp": self.utcnow().isoformat(),
            "capabilities": {
                "actions": actions,
                "robotCommands": robot_commands,
                "text": True,
                "movement": body_authenticated,
                "visual": camera_ready,
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
        if feedback:
            observation["feedback"] = feedback
        return observation

    def _selected_robot(
        self,
        gateway_status: Mapping[str, object] | None = None,
    ) -> tuple[str | None, Mapping[str, object] | None]:
        status = gateway_status if gateway_status is not None else self.gateway.status()
        robots = status.get("robots")
        if not isinstance(robots, Mapping):
            return None, None
        if self.config.robot_id is not None:
            robot = robots.get(self.config.robot_id)
            return (
                self.config.robot_id,
                robot if isinstance(robot, Mapping) and robot.get("connected") is True else None,
            )
        if len(robots) != 1:
            return None, None
        robot_id, robot = next(iter(robots.items()))
        if not isinstance(robot_id, str) or not isinstance(robot, Mapping):
            return None, None
        return (
            robot_id,
            robot if robot.get("connected") is True else None,
        )

    def _camera_ready(self) -> bool:
        _, robot = self._selected_robot()
        status = robot.get("status") if robot is not None else None
        return isinstance(status, Mapping) and status.get("camera_ready") is True

    def _motion_plan_available(
        self,
        gateway_status: Mapping[str, object] | None = None,
    ) -> bool:
        return self._motion_plan_support_status(gateway_status)["available"] is True

    def _motion_plan_support_status(
        self,
        gateway_status: Mapping[str, object] | None = None,
    ) -> dict[str, bool]:
        _, robot = self._selected_robot(gateway_status)
        if robot is None:
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
        await self._send_payload(websocket, encoded)

    async def _send_payload(self, websocket: Any, payload: str | bytes) -> bool:
        async with self._send_lock:
            try:
                await asyncio.wait_for(
                    websocket.send(payload),
                    timeout=BRIDGE_SEND_TIMEOUT_SECONDS,
                )
                return True
            except (asyncio.TimeoutError, ConnectionClosed, OSError, RuntimeError):
                if self._websocket is websocket:
                    try:
                        await asyncio.wait_for(
                            websocket.close(
                                code=1011,
                                reason="environment bridge send timeout",
                            ),
                            timeout=0.25,
                        )
                    except (
                        asyncio.TimeoutError,
                        ConnectionClosed,
                        OSError,
                        RuntimeError,
                    ):
                        pass
                return False

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
        robot_id: str | None = None,
        epoch: int | None = None,
    ) -> dict[str, object]:
        return {
            "id": f"ainekio-result-{action_id or int(self.clock() * 1000)}",
            "timestamp": self.utcnow().isoformat(),
            "type": status,
            "message": message,
            "actionId": action_id,
            "data": {
                "command": command,
                "sequence": sequence,
                "robotId": robot_id,
                "epoch": epoch,
            },
        }
