from __future__ import annotations

import asyncio
import base64
import hmac
import json
import math
import struct
from collections.abc import Coroutine
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from time import monotonic
from typing import Any, AsyncContextManager, Callable, Mapping
from uuid import uuid4
from time import time

from gateway.plugins import (
    CameraAnalysis,
    AudioUtterance,
    AudioUtterancePlugin,
    robot_utterance_id,
)
from gateway.perception import RecognitionResult
from gateway.server.service import ActionExpiredError, GatewayError, GatewayService
from gateway.body_capabilities import body_commands, expression_library
from protocol.binary_helpers import CAMERA_JPEG_FRAME_TYPE, MIC_PCM_FRAME_TYPE
from protocol.control_v1 import COMMAND_DEADLINE_FEATURE, LOCOMOTION_FEATURE, WALK_STEERING_FEATURE, MAX_SEQUENCE, ProtocolValidationError, validate_walk_controls
from websockets.exceptions import ConnectionClosed

from .speech_transport import (
    SpeechAudioMessage,
    paced_speaker_frames,
    parse_speech_audio_message,
)
from .translation import (
    LEGACY_ROBOT_COMMANDS,
    ROBOT_COMMAND_DESCRIPTIONS,
    V2_COMMAND_DESCRIPTIONS,
    SUPPORTED_ROBOT_COMMANDS,
    BridgeAction,
    translate_environment_action,
)
from .action_receipts import ActionConflictError, ActionReceipts


ADAPTER_PROTOCOL_VERSION = 1
# A raw JPEG may be 256 KiB. Its base64 data URL needs roughly one third more
# room while remaining below the gateway's 512 KiB bridge-frame ceiling.
MAX_ADAPTER_JSON_MESSAGE_BYTES = 384 * 1024
MAX_AUDIO_UTTERANCE_MESSAGE_BYTES = 512 * 1024
AUDIO_UTTERANCE_MAGIC = b"AIKAUD01"
AUDIO_UTTERANCE_HEADER_BYTES = len(AUDIO_UTTERANCE_MAGIC) + 4
MICROPHONE_LEVEL_INTERVAL_SECONDS = 0.1
BRIDGE_SEND_TIMEOUT_SECONDS = 2.0
ACTION_VISUAL_WAIT_SECONDS = 2.0
CAMERA_DELIVERY_QUEUE_LENGTH = 1
MAX_PENDING_ACTION_VISUALS = 32
MAX_WALK_UPDATE_VALIDITY_MS = 2000
WALK_UPDATE_ACK_TIMEOUT_SECONDS = 2.0
CANCELLATION_TIMEOUT_SECONDS = 2.0


def _normalized_action_type(action: Mapping[str, object]) -> str:
    return str(action.get("type", "")).strip().lower().replace("_", "")


@dataclass(frozen=True)
class EnvironmentAdapterConfig:
    token: str
    receipt_path: str
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
    if len(encoded) > MAX_AUDIO_UTTERANCE_MESSAGE_BYTES:
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
        self.receipts = ActionReceipts(config.receipt_path)
        self._websocket: Any | None = None
        self._send_lock = asyncio.Lock()
        self._cancelling_actions: set[str] = set()
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
        self._microphone_level_task: asyncio.Task[None] | None = None
        self._last_audio_result: dict[str, object] | None = None
        self._action_tasks: set[asyncio.Task[None]] = set()
        self._active_action_ids: set[str] = set()
        self._walk_update_task: asyncio.Task[None] | None = None
        self._bridge_ready = False
        self._settings_requests: dict[str, asyncio.Future[dict[str, object]]] = {}
        self._audio_utterances = AudioUtterancePlugin(
            gateway,
            self._handle_gateway_utterance,
            max_duration_ms=config.max_utterance_ms,
            utcnow=utcnow,
        )
        gateway.subscribe_events(self._handle_gateway_event)
        gateway.subscribe_frames(self._handle_gateway_frame)
        gateway.subscribe_transcripts(self._handle_gateway_transcript)

    async def _request_settings(self, kind: str, values: dict[str, object]) -> dict[str, object]:
        if not self._bridge_ready or self._websocket is None:
            raise GatewayError("MetaHuman Environment Bridge is disconnected")
        request_id = str(uuid4())
        future = asyncio.get_running_loop().create_future()
        self._settings_requests[request_id] = future
        try:
            if not await self._send({"type": kind, "version": ADAPTER_PROTOCOL_VERSION,
                    "requestId": request_id, **values}):
                raise GatewayError("MetaHuman Environment Bridge disconnected")
            try:
                result = await asyncio.wait_for(future, timeout=5.0)
            except asyncio.TimeoutError as exc:
                raise GatewayError("MetaHuman settings request unconfirmed; refresh its state before retrying") from exc
            if result.get("error"):
                raise GatewayError(str(result["error"]))
            if result.get("type") != kind + ".result":
                raise GatewayError("MetaHuman returned mismatched settings")
            return result
        finally:
            self._settings_requests.pop(request_id, None)
            if not future.done():
                future.cancel()

    async def speech_output_settings(self, output_target: str | None = None) -> dict[str, object]:
        if output_target is not None and output_target not in {"local", "robot"}:
            raise ValueError("outputTarget must be local or robot")
        result = await self._request_settings("speech.settings", {} if output_target is None else {"outputTarget": output_target})
        if result.get("outputTarget") not in {"local", "robot"}:
            raise GatewayError("MetaHuman returned invalid speech settings")
        return {key: result[key] for key in ("outputTarget", "username", "provider", "speechDisabled") if key in result}

    async def behavior_settings(self, enabled: bool | None = None) -> dict[str, object]:
        result = await self._request_settings("behavior.settings", {} if enabled is None else {"enabled": enabled})
        if type(result.get("enabled")) is not bool:
            raise GatewayError("MetaHuman returned invalid behavior settings")
        return {key: result[key] for key in ("enabled", "username", "executions", "unresolvedActions") if key in result}

    def _disconnect_settings(self) -> None:
        for future in self._settings_requests.values():
            if not future.done():
                future.set_result({"error": "MetaHuman Environment Bridge disconnected"})
        self._settings_requests.clear()

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
        self._disconnect_settings()
        previous_camera_task = self._camera_delivery_task
        previous_microphone_level_task = self._microphone_level_task
        self._websocket = websocket
        self._bridge_ready = False
        self._camera_delivery_queue = asyncio.Queue(
            maxsize=CAMERA_DELIVERY_QUEUE_LENGTH
        )
        self._camera_delivery_task = asyncio.create_task(
            self._camera_delivery_worker(websocket)
        )
        self._microphone_level_task = None
        if previous_camera_task is not None:
            previous_camera_task.cancel()
            await asyncio.gather(previous_camera_task, return_exceptions=True)
        if previous_microphone_level_task is not None:
            previous_microphone_level_task.cancel()
            await asyncio.gather(
                previous_microphone_level_task,
                return_exceptions=True,
            )
        if previous is not None and previous is not websocket:
            await previous.close(code=4000, reason="new authenticated environment connection")

        ready_sent = await self._send(
            {
                "type": "bridge.ready",
                "version": ADAPTER_PROTOCOL_VERSION,
                "sessionId": self.config.session_id,
                "observation": self._observation(),
            }
        )
        self._bridge_ready = ready_sent
        if ready_sent:
            await self._recover_action_receipts()
            await self._replay_pending_feedback()
        try:
            async for raw in websocket:
                if isinstance(raw, bytes):
                    try:
                        speech = parse_speech_audio_message(
                            raw,
                            expected_session_id=self.config.session_id,
                        )
                    except ValueError:
                        await websocket.close(
                            code=1002,
                            reason="malformed environment speech frame",
                        )
                        return
                    accepted = self._feedback(
                        speech.action_id,
                        "accepted",
                        "accepted",
                        command="speak",
                    )
                    try:
                        accepted = await asyncio.to_thread(self.receipts.receive, {"id": speech.action_id, "type": "speechAudio", "sessionId": speech.session_id,
                            "speechId": speech.speech_id, "durationMs": speech.duration_ms, "pcm": base64.b64encode(speech.pcm).decode("ascii")}, accepted)
                    except ActionConflictError as error:
                        await self._send({"type": "environment.protocol_error", "version": ADAPTER_PROTOCOL_VERSION,
                            "actionId": speech.action_id, "message": str(error)})
                        continue
                    await self._send_feedback(accepted)
                    continue
                message = self._decode_message(raw)
                if message.get("type") in {"speech.settings.result", "behavior.settings.result"}:
                    request_id = message.get("requestId")
                    future = self._settings_requests.get(request_id) if isinstance(request_id, str) else None
                    if self._websocket is websocket and future is not None and not future.done():
                        future.set_result(message)
                    continue
                if message.get("type") == "environment.feedback.ack":
                    feedback_id = message.get("feedbackId")
                    if isinstance(feedback_id, str):
                        await self._acknowledge_feedback(
                            feedback_id,
                            admitted=message.get("admitted") is True,
                        )
                    continue
                if message.get("type") == "audio.utterance.result":
                    self._last_audio_result = {
                        key: value
                        for key, value in message.items()
                        if key in {"utteranceId", "status", "message", "timestamp"}
                    }
                    continue
                if message.get("type") == "environment.observation.ack":
                    if message.get("admitted") is True and isinstance(message.get("observationId"), str):
                        await asyncio.to_thread(self.receipts.acknowledge, message["observationId"])
                    continue
                if message.get("type") == "environment.cancel":
                    task = asyncio.create_task(self._cancel_action(message))
                    self._action_tasks.add(task)
                    task.add_done_callback(self._action_finished)
                    continue
                if message.get("type") == "environment.action.update":
                    await self._schedule_walk_update(message, websocket)
                    continue
                if message.get("type") != "environment.action":
                    continue
                action = message.get("action")
                if not isinstance(action, dict):
                    continue
                action_id = action.get("id")
                if isinstance(action_id, str) and action_id:
                    accepted = self._feedback(
                        action_id,
                        "accepted",
                        "accepted",
                        command=str(action.get("type", "environment.action")),
                    )
                    try:
                        accepted = await asyncio.to_thread(self.receipts.receive, action, accepted)
                    except ActionConflictError as error:
                        await self._send({"type": "environment.protocol_error", "version": ADAPTER_PROTOCOL_VERSION,
                            "actionId": action_id, "message": str(error)})
                        continue
                    except GatewayError as error:
                        # Rejection is a delivery response, not a replacement for
                        # an existing action's immutable terminal receipt.
                        await self._send({"type": "environment.feedback", "version": ADAPTER_PROTOCOL_VERSION,
                            "sessionId": self.config.session_id, "feedback": self._feedback(action_id, "rejected", str(error))})
                        continue
                    await self._send_feedback(accepted)
        except ConnectionClosed:
            pass
        finally:
            if self._websocket is websocket:
                self._bridge_ready = False
                self._disconnect_settings()
                self._websocket = None
                if self._camera_delivery_task is not None:
                    self._camera_delivery_task.cancel()
                    await asyncio.gather(
                        self._camera_delivery_task,
                        return_exceptions=True,
                    )
                self._camera_delivery_task = None
                self._camera_delivery_queue = None
                if self._microphone_level_task is not None:
                    self._microphone_level_task.cancel()
                    await asyncio.gather(
                        self._microphone_level_task,
                        return_exceptions=True,
                    )
                self._microphone_level_task = None

    async def _schedule_walk_update(self, request: dict[str, Any], websocket: Any) -> None:
        # Backpressure is explicit: one in-flight update, no update task queue.
        # A sender must await its result before supplying the next revision.
        if self._walk_update_task is not None and not self._walk_update_task.done():
            await self._send_walk_update_result(websocket, request, "rejected", "a walk update is already in flight")
            return
        task = asyncio.create_task(self._update_walk(request, websocket, self.clock()))
        self._walk_update_task = task
        self._action_tasks.add(task)
        task.add_done_callback(self._action_finished)

    def _walk_update_robot(self, request: Mapping[str, object]) -> Mapping[str, object]:
        robot_id, robot = self._selected_robot()
        if (request.get("gatewayInstance") != self.gateway.instance_id
            or robot is None or robot_id != request.get("robotId") or robot.get("epoch") != request.get("epoch")):
            raise GatewayError("walk update belongs to an ended control session")
        if (robot.get("model") != "v2-12servo"
            or not {LOCOMOTION_FEATURE, COMMAND_DEADLINE_FEATURE}.issubset(robot.get("features", []))
            or robot.get("connection_state") != "online"
            or not isinstance(robot.get("capabilities"), Mapping) or robot["capabilities"].get("motion") is not True):
            raise GatewayError("body is not ready for active walk updates")
        return robot

    async def _update_walk(self, request: dict[str, Any], websocket: Any, received_at: float) -> None:
        sequence: int | None = None
        dispatched = False
        try:
            if request.get("version") != ADAPTER_PROTOCOL_VERSION or type(request.get("version")) is not int:
                raise GatewayError("walk update requires adapter protocol version 1")
            if request.get("sessionId") != self.config.session_id:
                raise GatewayError("walk update identifies a different environment session")
            action_id, revision, validity_ms = request.get("actionId"), request.get("revision"), request.get("validForMs")
            if not isinstance(action_id, str) or not 1 <= len(action_id) <= 256:
                raise GatewayError("walk update requires bounded action identity")
            if type(revision) is not int or not 1 <= revision <= MAX_SEQUENCE:
                raise GatewayError("walk update requires a positive revision")
            if type(validity_ms) is not int or not 1 <= validity_ms <= MAX_WALK_UPDATE_VALIDITY_MS:
                raise GatewayError("walk update validity must be between 1 and 2000 ms")
            if type(request.get("epoch")) is not int:
                raise GatewayError("walk update requires the robot epoch")
            controls = request.get("controls")
            if not isinstance(controls, dict) or set(controls) - {"forward", "turn"} not in ({"speed"}, {"stride", "rate"}):
                raise GatewayError("walk update controls require speed OR stride and rate, optionally forward and turn")
            robot = self._walk_update_robot(request)
            row = await asyncio.to_thread(self.receipts.action, action_id)
            if row is None or row["state"] != "started" or row["wire"] is None:
                raise GatewayError("walk action is not active")
            payload, wire = json.loads(row["payload"]), json.loads(row["wire"])
            if payload.get("bodyLease") != request.get("bodyLease"):
                raise GatewayError("walk update identifies a different body owner")
            original_sequence = wire.get("sequence")
            active = robot.get("active_walk")
            if (wire.get("gatewayInstance") != self.gateway.instance_id or wire.get("robotId") != request["robotId"]
                or wire.get("epoch") != request["epoch"] or wire.get("kind") != "intent"
                or robot.get("body_command_sequence") != original_sequence
                or robot.get("active_walk_sequence") != original_sequence
                or not isinstance(active, Mapping) or active.get("steps") != 0):
                raise GatewayError("update does not identify this action's ongoing walk")
            if revision <= wire.get("walkUpdate", {}).get("revision", 0):
                raise GatewayError("walk update revision was already consumed")
            previous = wire.get("walkUpdate", {})
            if previous.get("dispatched") is True:
                try:
                    await self.gateway.wait_terminal(previous["sequence"], robot_id=request["robotId"],
                        epoch=request["epoch"], timeout=0)
                except (GatewayError, TimeoutError) as error:
                    raise GatewayError("previous walk update has no terminal acknowledgement") from error
            params = {"dir": active["dir"], "steps": 0, "update": original_sequence,
                "gait": active.get("gait", "walk"), **controls}
            validate_walk_controls(params)
            context = {key: wire[key] for key in ("gatewayInstance", "robotId", "epoch", "sequence", "kind")}

            def before_send() -> None:
                nonlocal dispatched
                age_ms = (self.clock() - received_at) * 1000
                if not math.isfinite(age_ms) or not 0 <= age_ms <= validity_ms:
                    raise ActionExpiredError("walk update expired before dispatch")
                if self._websocket is not websocket or websocket.closed:
                    raise GatewayError("walk update bridge session ended before dispatch")
                current = self._walk_update_robot(request)
                if current.get("active_walk_sequence") != original_sequence or current.get("body_command_sequence") != original_sequence:
                    raise GatewayError("walk action ended before update dispatch")
                dispatched = True

            def guard(assigned: int):
                nonlocal sequence
                sequence = assigned
                return self.receipts.walk_update_dispatch(action_id, request.get("bodyLease"), context,
                    revision, assigned, before_send)

            await self.gateway.queue_intent("walk", params, robot_id=request["robotId"],
                received_at=received_at, on_sequence=guard, valid_for_ms=validity_ms)
            terminal = await self.gateway.wait_terminal(sequence, robot_id=request["robotId"],
                epoch=request["epoch"], timeout=WALK_UPDATE_ACK_TIMEOUT_SECONDS)
            status = "acknowledged" if terminal.get("t") == "ack" else "rejected"
            message = str(terminal.get("code", terminal.get("t")))
        except (GatewayError, ProtocolValidationError, TimeoutError, ConnectionClosed, OSError) as error:
            status, message = ("outcome_unknown" if dispatched else "rejected"), str(error)
        await self._send_walk_update_result(websocket, request, status, message, sequence=sequence)

    async def _send_walk_update_result(self, websocket: Any, request: Mapping[str, object],
        status: str, message: str, *, sequence: int | None = None) -> None:
        if self._websocket is not websocket or websocket.closed:
            return
        # This is a control update receipt, not the parent action's completion.
        # It is never admitted as cognitive work or replayed after reconnection.
        result = {"type": "environment.action.update.result", "version": ADAPTER_PROTOCOL_VERSION,
            "sessionId": self.config.session_id,
            "actionId": request["actionId"] if isinstance(request.get("actionId"), str) and len(request["actionId"]) <= 256 else None,
            "revision": request["revision"] if type(request.get("revision")) is int and 1 <= request["revision"] <= MAX_SEQUENCE else None,
            "status": status, "message": message,
            "sequence": sequence, "timestamp": self.utcnow().isoformat()}
        await self._send_payload(websocket, json.dumps(result, separators=(",", ":")))

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
                epoch = robot["epoch"]
                sequence = await self.gateway.tts_speak(
                    paced_speaker_frames(speech.pcm),
                    robot_id=robot_id,
                    received_at=self.clock(),
                    on_sequence=lambda assigned: self.receipts.dispatch(speech.action_id,
                        {"robotId": robot_id, "epoch": epoch, "sequence": assigned,
                         "gatewayInstance": self.gateway.instance_id, "kind": "speech"}),
                )
                terminal = await self.gateway.wait_terminal(
                    sequence,
                    robot_id=robot_id,
                    epoch=epoch,
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
                    epoch=epoch,
                )
            except (GatewayError, TimeoutError, ConnectionClosed, OSError) as error:
                feedback = self._feedback(
                    speech.action_id,
                    "outcome_unknown",
                    str(error),
                    command="speak",
                    robot_id=robot_id,
                )
        feedback = await self._send_feedback(feedback)
        await self._send_observation(feedback=[feedback])

    async def _process_environment_action(self, action: dict[str, Any], *, resume: dict[str, Any] | None = None) -> None:
        action_id = action.get("id")
        visual_future: asyncio.Future[dict[str, object] | None] | None = None
        translated = translate_environment_action(action, model=(self._selected_robot()[1] or {}).get("model"))
        if (
            isinstance(action_id, str)
            and translated is not None
            and translated.kind in {"intent", "motion_plan", "snapshot"}
            and translated.name != "face"
        ):
            visual_future = asyncio.get_running_loop().create_future()
            self._remember_action_visual(action_id, visual_future)
        recovered_context_key: tuple[str, int, int] | None = None
        recovered_snapshot = False
        try:
            if resume is not None:
                wire = json.loads(resume["wire"])
                context = self._snapshot_context(action)
                if (wire.get("gatewayInstance") == self.gateway.instance_id and context is not None
                    and isinstance(wire.get("robotId"), str) and type(wire.get("epoch")) is int
                    and type(wire.get("sequence")) is int):
                    recovered_context_key = (wire["robotId"], wire["epoch"], wire["sequence"])
                    self._remember_bounded(self._robot_action_contexts, recovered_context_key, context)
                    if wire.get("kind") == "snapshot":
                        await self._snapshot_lock.acquire()
                        recovered_snapshot = self._snapshot_in_flight = True
                        self._pending_snapshot_context = context
                        self._pending_snapshot_key = None
                feedback = await self._resume_action_receipt(resume)
            else:
                feedback = await self.handle_action(action)
            row = await asyncio.to_thread(self.receipts.action, action_id) if isinstance(action_id, str) else None
            if row is not None and row["state"] == "terminal" and row["result"]:
                feedback = json.loads(row["result"])
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
            feedback = await self._send_feedback(feedback)
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
            if recovered_snapshot:
                self._pending_snapshot_context = self._pending_snapshot_key = None
                self._snapshot_in_flight = False
                self._snapshot_lock.release()
            if recovered_context_key is not None:
                self._robot_action_contexts.pop(recovered_context_key, None)
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
        translated = translate_environment_action(action, model=(self._selected_robot()[1] or {}).get("model"))
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
        recorded_sequence: int | None = None
        receipt = await asyncio.to_thread(self.receipts.action, action_id) if isinstance(action_id, str) else None
        def check_interpretation_owner():
            metadata = action.get("metadata")
            fence = metadata.get("interpretationBody") if isinstance(metadata, Mapping) else None
            if fence is None or translated.kind in {"snapshot", "speech"} or translated.name == "face":
                return
            current = self.gateway.status().get("robots", {}).get(robot_id, {})
            expected = [self.config.session_id, self.gateway.instance_id, robot_id,
                current.get("epoch"), current.get("body_command_sequence")]
            if fence != expected:
                raise GatewayError("instruction interpretation belongs to an ended body owner or session")

        def remember_sequence(assigned_sequence: int):
            nonlocal action_context_key, recorded_sequence
            if recorded_sequence == assigned_sequence:
                return
            recorded_sequence = assigned_sequence
            if (
                snapshot_context is None
                or not isinstance(robot_id, str)
                or type(robot_epoch) is not int
            ):
                pass
            else:
                action_context_key = (robot_id, robot_epoch, assigned_sequence)
                self._remember_bounded(self._robot_action_contexts, action_context_key, snapshot_context)
            if receipt is not None:
                return self.receipts.dispatch(action_id, {"sequence": assigned_sequence, "robotId": robot_id,
                    "epoch": robot_epoch, "kind": translated.kind, "gatewayInstance": self.gateway.instance_id},
                    check_interpretation_owner, body_command=(translated.kind in {"stop", "motion_plan"}
                        or translated.kind == "intent" and translated.name not in {"face", "say"}))

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
                robot_id=robot_id,
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
                robot_id=robot_id,
                epoch=robot_epoch,
                timeout=None,
            )
        except (GatewayError, TimeoutError, ConnectionClosed, OSError) as exc:
            if translated.kind == "motion_plan":
                await self._send_motion_plan_status(
                    action_id,
                    "rejected",
                    frame_count=len(frame_durations),
                    duration_ms=sum(frame_durations),
                    message=str(exc),
                )
            receipt = await asyncio.to_thread(self.receipts.action, action_id) if isinstance(action_id, str) else None
            status = "outcome_unknown" if receipt is not None and receipt["wire"] is not None else "rejected"
            return self._feedback(action_id, status, str(exc) or type(exc).__name__, command=translated.name,
                robot_id=robot_id, epoch=robot_epoch, sequence=sequence)
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
        feedback = self._terminal_feedback(action_id, terminal, command=translated.name or translated.kind,
            sequence=sequence, robot_id=robot_id, epoch=robot_epoch)
        if translated.kind == "motion_plan":
            await self._send_motion_plan_status(
                action_id,
                feedback["type"],
                sequence=sequence,
                frame_count=len(frame_durations),
                duration_ms=sum(frame_durations),
                active_frame=len(frame_durations) if feedback["type"] == "completed" else None,
                message=feedback["message"],
            )
        return feedback

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
        robot_id: str | None = None,
        on_sequence: Callable[[int], AsyncContextManager[None] | None] | None = None,
    ) -> int:
        if action.kind == "stop":
            return await self.gateway.estop(
                robot_id=robot_id,
                received_at=received_at,
                on_sequence=on_sequence,
            )
        if action.kind == "intent" and action.name is not None:
            return await self.gateway.queue_intent(
                action.name,
                action.params,
                robot_id=robot_id,
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
                robot_id=robot_id,
                received_at=received_at,
                on_sequence=on_sequence,
            )
        if action.kind == "snapshot":
            return await self.gateway.request_snap(
                robot_id=robot_id,
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
                type(counter) is int
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
                type(counter) is int
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
        if event.get("t") == "connection":
            await self._recover_action_receipts()

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
                self._schedule_microphone_level(
                    {
                        "robot_id": frame.get("robot_id"),
                        "epoch": frame.get("epoch"),
                        "counter": frame.get("counter"),
                        "level": round(level, 4),
                    }
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
            "id": f"ainekio-camera-{self.gateway.instance_id}-{frame.get('robot_id')}-{frame.get('epoch')}-{frame.get('counter')}",
            "timestamp": self.utcnow().isoformat(),
            "mimeType": "image/jpeg",
            "dataUrl": f"data:image/jpeg;base64,{base64.b64encode(payload).decode('ascii')}",
            "source": "robot-camera",
            "metadata": {
                "robotId": frame.get("robot_id"),
                "gatewayInstance": self.gateway.instance_id,
                "epoch": frame.get("epoch"),
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

    def _schedule_microphone_level(self, data: dict[str, object]) -> None:
        task = self._microphone_level_task
        if task is not None and not task.done():
            return
        task = asyncio.create_task(self._send_telemetry("audio.level", data))
        self._microphone_level_task = task
        task.add_done_callback(self._microphone_level_finished)

    def _microphone_level_finished(self, task: asyncio.Task[None]) -> None:
        if self._microphone_level_task is task:
            self._microphone_level_task = None
        if not task.cancelled():
            task.exception()

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

    async def publish_camera_analysis(self, analysis: CameraAnalysis, *, max_frame_age_s: float) -> None:
        """Send compact current recognition on the existing local bridge, without pixels or replay."""
        robot_id, robot = self._selected_robot()
        age = self.gateway.clock() - analysis.received_at
        if (not self._bridge_ready or robot is None or robot_id != analysis.robot_id
            or robot.get("epoch") != analysis.epoch or robot.get("connection_state") != "online"):
            return
        if analysis.error is not None:
            # Use the existing observation route so MetaHuman receives an
            # explicit failure without fabricating perception or body feedback.
            await self._send_observation(metadata={"recognitionFailure": {
                "robotId": robot_id, "epoch": analysis.epoch, "frameCounter": analysis.counter,
                "gatewayInstance": self.gateway.instance_id, "reason": analysis.error,
                **({"processing": analysis.processing} if analysis.processing is not None else {}),
            }})
            return
        if not 0 <= age < max_frame_age_s:
            return
        if not isinstance(analysis.result, RecognitionResult):
            raise ValueError("camera recognition backend must return RecognitionResult")
        # These wall times describe host receipt, not sensor acquisition.
        now = self.utcnow()
        perception = {"version": 1, "robotId": robot_id, "epoch": analysis.epoch,
            "gatewayInstance": self.gateway.instance_id, "frameCounter": analysis.counter,
            "timeBasis": "gateway_receipt", "observedAt": (now - timedelta(seconds=age)).isoformat(),
            "expiresAt": (now + timedelta(seconds=max_frame_age_s - age)).isoformat(),
            **analysis.result.message()}
        await self._send_telemetry("vision.recognition", {"perception": perception,
            **({"processing": analysis.processing} if analysis.processing is not None else {})})

    async def _send_observation(
        self,
        *,
        text: list[dict[str, object]] | None = None,
        visual: dict[str, object] | None = None,
        body_event: dict[str, object] | None = None,
        metadata: dict[str, object] | None = None,
        feedback: list[dict[str, object]] | None = None,
    ) -> None:
        observation = self._observation(text=text, visual=visual, body_event=body_event, metadata=metadata, feedback=feedback)
        observation["id"] = str(uuid4())
        envelope = {
                "type": "environment.observation",
                "version": ADAPTER_PROTOCOL_VERSION,
                "sessionId": self.config.session_id,
                "observation": observation,
        }
        action_id = str(feedback[0]["actionId"]) if feedback and feedback[0].get("actionId") else None
        if action_id or text or visual:
            envelope = await asyncio.to_thread(self.receipts.queue, str(observation["id"]), action_id, envelope)
        await self._send(envelope)

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
        declared = robot.get("capabilities") if robot is not None else None
        supported = body_commands(
            str(robot.get("model", "v1-8servo")), robot.get("features", []),
            declared if isinstance(declared, Mapping) else None,
        ) if robot is not None else ()
        motion_ready = body_authenticated and (supported is None or any(name in SUPPORTED_ROBOT_COMMANDS and name != "stop" for name in supported))
        updates_available = bool(motion_ready and robot and robot.get("model") == "v2-12servo"
            and {LOCOMOTION_FEATURE, COMMAND_DEADLINE_FEATURE}.issubset(robot.get("features", []))
            and robot.get("connection_state") == "online")
        speaker_ready = body_authenticated and (not isinstance(declared, Mapping) or declared.get("speaker") is True)
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
                "motionAvailable": motion_ready,
                "cameraReady": camera_ready,
                "microphoneReady": declared.get("microphone") if isinstance(declared, Mapping) else None,
                "speakerReady": speaker_ready,
            },
            "gateway": gateway_status,
            "freestyleMovement": self._motion_plan_support_status(gateway_status),
            "activeMovementUpdates": {
                "version": 1,
                "available": updates_available,
                "gatewayInstance": self.gateway.instance_id,
                "maxValidityMs": MAX_WALK_UPDATE_VALIDITY_MS,
                "controls": (["speed", "stride", "rate"] + (["forward", "turn"]
                    if WALK_STEERING_FEATURE in robot.get("features", []) else [])) if updates_available else [],
                "robotId": robot_id, "epoch": robot.get("epoch") if robot else None,
                "maxInFlight": 1,
            },
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
        expressions = expression_library(robot) if body_authenticated else []
        expression_feedback = bool(expressions and robot and "face_feedback_v1" in robot.get("features", []))
        if expression_feedback:
            actions.append("faceExpression")
        robot_commands: list[str] = []
        if motion_ready:
            actions.extend(["robotCommand", "move", "stop"])
            robot_commands = list(LEGACY_ROBOT_COMMANDS) if supported is None else [
                name for name in SUPPORTED_ROBOT_COMMANDS if name in supported
            ]
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
                "expressionLibrary": expressions,
                "expressionFeedback": expression_feedback,
                "robotCommands": robot_commands,
                "robotCommandDescriptions": {
                    command: (V2_COMMAND_DESCRIPTIONS.get(command, ROBOT_COMMAND_DESCRIPTIONS[command]) if robot and robot.get("model") == "v2-12servo" else ROBOT_COMMAND_DESCRIPTIONS[command])
                    for command in robot_commands
                },
                "text": True,
                "movement": motion_ready,
                "visual": camera_ready,
                "map": False,
            },
            "state": state,
        }
        if text:
            observation["text"] = text
        if visual:
            observation["visual"] = visual
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
        connected = [(robot_id, robot) for robot_id, robot in robots.items()
                     if isinstance(robot_id, str) and isinstance(robot, Mapping) and robot.get("connected") is True]
        if len(connected) != 1:
            return None, None
        return connected[0]

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

    async def _send_feedback(self, feedback: Mapping[str, object]) -> dict[str, Any]:
        feedback_id = feedback.get("id")
        if not isinstance(feedback_id, str) or not feedback_id:
            raise GatewayError("environment feedback requires an id")
        envelope = await asyncio.to_thread(self.receipts.queue_feedback, {
            "type": "environment.feedback", "version": ADAPTER_PROTOCOL_VERSION,
            "sessionId": self.config.session_id, "feedback": dict(feedback),
        })
        if self._bridge_ready:
            await self._replay_pending_feedback()
        return envelope["feedback"]

    async def _recover_action_receipts(self) -> None:
        for row in await asyncio.to_thread(self.receipts.recoverable):
            if row["id"] in self._active_action_ids:
                continue
            if row["state"] == "received":
                await self._send_feedback(json.loads(row["accepted"]))
            elif row["state"] != "terminal" and row["wire"]:
                self._track_action(row["id"], self._process_environment_action(json.loads(row["payload"]), resume=dict(row)))
            else:
                feedback = json.loads(row["result"]) if row["result"] else self._feedback(row["id"], "outcome_unknown", "adapter restarted before terminal acknowledgement")
                feedback = await self._send_feedback(feedback)
                await self._send_observation(feedback=[feedback], metadata={"actionId": row["id"]})
        await asyncio.to_thread(self.receipts.prune, time() - 30 * 86400)

    async def _resume_action_receipt(self, row: dict[str, Any]) -> dict[str, object]:
        """Follow the recorded wire command, never dispatch its payload again."""
        wire = json.loads(row["wire"])
        robot_id, epoch, sequence = wire.get("robotId"), wire.get("epoch"), wire.get("sequence")
        action_id = row["id"]
        command = json.loads(row["payload"])
        try:
            if not isinstance(robot_id, str) or type(epoch) is not int or type(sequence) is not int:
                raise GatewayError("saved action lacks its robot/session/sequence identity")
            # Legacy receipts also belong to a previous host session: no new
            # dispatch omits this ID. Remote timestamps cannot identify a host
            # process, and a new process can reuse an old epoch and sequence.
            same_instance = wire.get("gatewayInstance") == self.gateway.instance_id
            if not same_instance:
                robot = self.gateway.status().get("robots", {}).get(robot_id)
                if not isinstance(robot, Mapping) or robot.get("connected") is not True:
                    raise GatewayError("previous gateway session ended; awaiting authenticated robot reconnection")
                # Reauthentication establishes a new body session. The previous
                # control session is over; this does not claim its motion succeeded.
                feedback = self._feedback(action_id, "outcome_unknown",
                    "Previous gateway session ended; earlier physical effect remains unverified",
                    command=command.get("command", command.get("type")), robot_id=robot_id, epoch=epoch, sequence=sequence)
                feedback["data"]["earlierEffectUnknown"] = True
                feedback["data"]["priorOutcome"] = json.loads(row["result"]) if row["result"] else None
            else:
                terminal = await self.gateway.wait_terminal(sequence, robot_id=robot_id, epoch=epoch, timeout=None)
                feedback = self._terminal_feedback(action_id, terminal,
                    command=command.get("command", command.get("type")), robot_id=robot_id, epoch=epoch, sequence=sequence)
        except (GatewayError, TimeoutError, ConnectionClosed, OSError, KeyError, ValueError) as error:
            feedback = self._feedback(action_id, "outcome_unknown", str(error) or type(error).__name__,
                command=command.get("command", command.get("type")), robot_id=robot_id, epoch=epoch, sequence=sequence)
        return feedback

    async def _replay_pending_feedback(self) -> None:
        for envelope in await asyncio.to_thread(self.receipts.pending):
            sent = await self._send(envelope)
            if not sent:
                return

    async def _cancel_action(self, request: dict[str, Any]) -> None:
        action_id = request.get("actionId")
        if not isinstance(action_id, str) or not isinstance(request.get("cancellationId"), str):
            raise GatewayError("cancellation requires action and request identity")
        if action_id in self._cancelling_actions:
            return
        self._cancelling_actions.add(action_id)
        try:
            try:
                row = await asyncio.to_thread(self.receipts.request_cancel, action_id, request.get("bodyLease"),
                    self._feedback(action_id, "cancelled", str(request.get("reason") or "cancelled by Coordinator")))
            except GatewayError as error:
                await self._send({"type": "environment.protocol_error", "version": ADAPTER_PROTOCOL_VERSION,
                    "actionId": action_id, "message": str(error)})
                return
            if row["state"] == "terminal":
                feedback = json.loads(row["result"])
            else:
                try:
                    if row["wire"] is not None:
                        wire = json.loads(row["wire"])
                        robot_id, epoch, original = wire.get("robotId"), wire.get("epoch"), wire.get("sequence")
                        if not isinstance(robot_id, str) or type(epoch) is not int or type(original) is not int:
                            raise GatewayError("Saved cancellation lacks its original wire identity")
                        if wire.get("gatewayInstance") != self.gateway.instance_id:
                            raise GatewayError("Cancellation belongs to a previous gateway instance; outcome unknown")
                        speech = json.loads(row["payload"]).get("type") == "speechAudio"
                        # Natural termination may have won the race while its
                        # feedback was in transit. Reuse that receipt, not Stop.
                        try:
                            terminal = await self.gateway.wait_terminal(original, robot_id=robot_id, epoch=epoch, timeout=0)
                        except (GatewayError, TimeoutError):
                            terminal = None
                        if terminal is not None:
                            feedback = self._terminal_feedback(action_id, terminal, command=wire.get("kind"),
                                robot_id=robot_id, epoch=epoch, sequence=original)
                            if feedback["type"] != "outcome_unknown":
                                feedback = await self._send_feedback(feedback)
                                await self._send_observation(feedback=[feedback])
                                return

                        def before_send() -> None:
                            robot = self.gateway.status().get("robots", {}).get(robot_id, {})
                            if (wire.get("gatewayInstance") != self.gateway.instance_id
                                or robot.get("epoch") != epoch or not robot.get("connected")):
                                raise GatewayError("Cancellation belongs to an ended body session; outcome unknown")
                            if not speech and robot.get("body_command_sequence") != original:
                                raise GatewayError("Body control was replaced; old cleanup cannot stop the current owner")
                            if speech and robot.get("active_speech_sequence") != original:
                                raise GatewayError("Speech control was replaced; old cleanup cannot cancel the current speaker")

                        async with asyncio.timeout(CANCELLATION_TIMEOUT_SECONDS):
                            # The receipt owner and the wire fence are checked while
                            # holding the same send lock as dashboard/manual commands.
                            guard = lambda sequence: self.receipts.cancellation_dispatch(action_id, before_send,
                                sequence=None if speech else sequence)
                            if speech:
                                await self.gateway.cancel_speech(robot_id=robot_id, on_sequence=guard)
                            elif wire.get("kind") != "snapshot" and json.loads(row["payload"]).get("type") != "faceExpression":
                                await self.gateway.estop(robot_id=robot_id, received_at=self.clock(), on_sequence=guard)
                            terminal = await self.gateway.wait_terminal(original, robot_id=robot_id, epoch=epoch, timeout=None)
                            feedback = self._terminal_feedback(action_id, terminal,
                                command=wire.get("kind"), robot_id=robot_id, epoch=epoch, sequence=original)
                        if feedback["type"] not in {"completed", "cancelled", "rejected"}:
                            raise GatewayError("Original command termination remains unconfirmed")
                    else:
                        # Cancellation overtook dispatch: no physical command was sent.
                        feedback = self._feedback(action_id, "cancelled", str(request.get("reason") or "cancelled by Coordinator"))
                except (GatewayError, TimeoutError, ConnectionClosed, OSError) as error:
                    feedback = self._feedback(action_id, "outcome_unknown", str(error) or "Original command termination was not confirmed within the cancellation deadline")
            feedback = await self._send_feedback(feedback)
            await self._send_observation(feedback=[feedback])
        finally:
            self._cancelling_actions.discard(action_id)

    async def _acknowledge_feedback(self, feedback_id: str, *, admitted: bool) -> None:
        await asyncio.to_thread(self.receipts.acknowledge, feedback_id)
        pending = next((row for row in await asyncio.to_thread(self.receipts.recoverable) if json.loads(row["accepted"])["id"] == feedback_id
            and row["state"] == "received" and row["id"] not in self._active_action_ids), None)
        if pending is None:
            return
        payload = json.loads(pending["payload"])
        if not admitted:
            feedback = self._feedback(payload["id"], "cancelled", "Coordinator declined admission")
            feedback = await self._send_feedback(feedback)
            await self._send_observation(feedback=[feedback])
            return
        if payload["type"] == "speechAudio":
            speech = SpeechAudioMessage(payload["sessionId"], payload["id"], payload["speechId"], payload["durationMs"], base64.b64decode(payload["pcm"]))
            processing = self._process_speech_audio(speech)
        else:
            processing = self._process_environment_action(payload)
        self._track_action(str(payload["id"]), processing)

    def _track_action(self, action_id: str, processing: Coroutine[Any, Any, None]) -> None:
        self._active_action_ids.add(action_id)
        task = asyncio.create_task(processing)
        task.add_done_callback(lambda _: self._active_action_ids.discard(action_id))
        self._action_tasks.add(task)
        task.add_done_callback(self._action_finished)

    def _action_finished(self, task: asyncio.Task[None]) -> None:
        self._action_tasks.discard(task)
        if not task.cancelled():
            error = task.exception()
            if error is not None:
                task.get_loop().call_exception_handler({
                    "message": "Environment action processing failed; its durable receipt remains available for recovery",
                    "exception": error,
                    "task": task,
                })

    async def _send(self, message: Mapping[str, object]) -> bool:
        websocket = self._websocket
        if websocket is None or websocket.closed:
            return False
        # Older durable receipts duplicated a single image in both fields.
        # Preserve every distinct frame, but send that image only once on replay.
        observation = message.get("observation")
        if isinstance(observation, dict) and observation.get("visual") and observation.get("visuals") == [observation["visual"]]:
            message = {**message, "observation": {
                key: value for key, value in observation.items() if key != "visuals"
            }}
        encoded = json.dumps(message, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > MAX_ADAPTER_JSON_MESSAGE_BYTES:
            raise GatewayError("environment adapter message exceeds its size limit")
        return await self._send_payload(websocket, encoded)

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

    def _terminal_feedback(self, action_id: str | None, terminal: Mapping[str, object], *,
        command: str | None, sequence: int, robot_id: str, epoch: int) -> dict[str, object]:
        terminal_type = str(terminal.get("t"))
        status = {"ack": "completed", "done": "completed", "cancelled": "cancelled"}.get(terminal_type, "rejected")
        if terminal.get("seq") != sequence or terminal.get("outcome_unknown") or terminal.get("code") in {"disconnect", "superseded"}:
            status = "outcome_unknown"
        return self._feedback(action_id, status, str(terminal.get("code", terminal_type)),
            command=command, sequence=sequence, robot_id=robot_id, epoch=epoch)

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
            "id": f"ainekio-result-{action_id or int(self.clock() * 1000)}-{status}",
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
