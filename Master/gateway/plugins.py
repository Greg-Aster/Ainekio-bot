from __future__ import annotations

import asyncio
import inspect
import io
import logging
import math
import wave
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from protocol.binary_helpers import CAMERA_JPEG_FRAME_TYPE, MAX_JPEG_BYTES, MIC_PCM_FRAME_TYPE

from .server.service import GatewayService
from .depth_motion import DepthMotion, settings as depth_settings


AUDIO_FRAME_BYTES = 640
AUDIO_FRAME_DURATION_MS = 20
AUDIO_SAMPLE_RATE_HZ = 16000
AUDIO_CHANNELS = 1
AUDIO_SAMPLE_WIDTH_BYTES = 2
DEFAULT_MAX_UTTERANCE_MS = 15000
MAX_BINARY_COUNTER = (1 << 32) - 1

TranscriptFunction = Callable[[bytes], str | None | Awaitable[str | None]]
CameraFunction = Callable[[bytes], object | Awaitable[object]]

def robot_utterance_id(robot_id: str, epoch: int, origin_id: int) -> str:
    """Return the stable bridge identifier for one firmware-owned utterance."""
    return f"audio:{robot_id}:{epoch}:{origin_id}"


@dataclass(frozen=True)
class AudioUtterance:
    utterance_id: str
    robot_id: str
    epoch: int
    started_at: str
    ended_at: str
    first_counter: int
    last_counter: int
    frame_count: int
    missing_frames: int
    duration_ms: int
    wake_triggered: bool
    truncated: bool
    pcm: bytes

    def wav_bytes(self) -> bytes:
        output = io.BytesIO()
        with wave.open(output, "wb") as wav:
            wav.setnchannels(AUDIO_CHANNELS)
            wav.setsampwidth(AUDIO_SAMPLE_WIDTH_BYTES)
            wav.setframerate(AUDIO_SAMPLE_RATE_HZ)
            wav.writeframes(self.pcm)
        return output.getvalue()

    def metadata(self, *, session_id: str) -> dict[str, object]:
        return {
            "type": "audio.utterance",
            "version": 1,
            "sessionId": session_id,
            "utteranceId": self.utterance_id,
            "robotId": self.robot_id,
            "epoch": self.epoch,
            "startedAt": self.started_at,
            "endedAt": self.ended_at,
            "firstCounter": self.first_counter,
            "lastCounter": self.last_counter,
            "frameCount": self.frame_count,
            "missingFrames": self.missing_frames,
            "durationMs": self.duration_ms,
            "wakeTriggered": self.wake_triggered,
            "truncated": self.truncated,
            "format": "wav",
            "sampleRateHz": AUDIO_SAMPLE_RATE_HZ,
            "channels": AUDIO_CHANNELS,
            "bitsPerSample": AUDIO_SAMPLE_WIDTH_BYTES * 8,
        }


UtteranceFunction = Callable[
    [AudioUtterance], object | Awaitable[object]
]


@dataclass
class _PendingUtterance:
    utterance_id: str
    origin_id: int | None
    robot_id: str
    epoch: int
    started_at: str
    wake_triggered: bool
    pcm: bytearray = field(default_factory=bytearray)
    first_counter: int | None = None
    last_counter: int | None = None
    frame_count: int = 0
    missing_frames: int = 0


class AudioUtteranceAssembler:
    """Assemble protocol PCM frames into one bounded VAD-delimited utterance."""

    def __init__(
        self,
        consume: UtteranceFunction,
        *,
        max_duration_ms: int = DEFAULT_MAX_UTTERANCE_MS,
        utcnow: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        id_factory: Callable[[], str] = lambda: str(uuid4()),
    ) -> None:
        if (
            max_duration_ms < AUDIO_FRAME_DURATION_MS
            or max_duration_ms % AUDIO_FRAME_DURATION_MS != 0
        ):
            raise ValueError("max utterance duration must be a positive 20 ms multiple")
        self.consume = consume
        self.max_frames = max_duration_ms // AUDIO_FRAME_DURATION_MS
        self.utcnow = utcnow
        self.id_factory = id_factory
        self._pending: dict[tuple[str, int], _PendingUtterance] = {}
        self._blocked: set[tuple[str, int]] = set()
        self._pending_wake: set[tuple[str, int]] = set()

    async def handle_event(self, event: dict[str, object]) -> None:
        key = self._key(event)
        if key is None:
            return
        if event.get("t") == "connection" and event.get("status") == "disconnected":
            self._pending.pop(key, None)
            self._blocked.discard(key)
            self._pending_wake.discard(key)
            return
        if event.get("t") != "event":
            return

        name = event.get("name")
        if name == "wake_word":
            pending = self._pending.get(key)
            if pending is not None:
                pending.wake_triggered = True
            else:
                self._pending_wake.add(key)
            return
        if name == "vad_open":
            if key in self._pending:
                await self._finish(key, truncated=True)
            self._blocked.discard(key)
            origin_id = self._event_origin_id(event)
            self._pending[key] = _PendingUtterance(
                utterance_id=(
                    robot_utterance_id(key[0], key[1], origin_id)
                    if origin_id is not None
                    else self.id_factory()
                ),
                origin_id=origin_id,
                robot_id=key[0],
                epoch=key[1],
                started_at=self.utcnow().isoformat(),
                wake_triggered=key in self._pending_wake,
            )
            self._pending_wake.discard(key)
            return
        if name == "vad_close":
            pending = self._pending.get(key)
            origin_id = self._event_origin_id(event)
            if (
                pending is not None
                and pending.origin_id is not None
                and origin_id != pending.origin_id
            ):
                return
            self._blocked.discard(key)
            self._pending_wake.discard(key)
            await self._finish(key, truncated=False)

    async def handle_frame(self, frame: dict[str, object]) -> None:
        if frame.get("frame_type") != MIC_PCM_FRAME_TYPE:
            return
        key = self._key(frame)
        if key is None or key in self._blocked:
            return
        pending = self._pending.get(key)
        payload = frame.get("payload")
        counter = frame.get("counter")
        if (
            pending is None
            or not isinstance(payload, bytes)
            or len(payload) != AUDIO_FRAME_BYTES
            or type(counter) is not int
            or not 0 <= counter <= MAX_BINARY_COUNTER
        ):
            return

        if pending.last_counter is not None:
            expected = (pending.last_counter + 1) & MAX_BINARY_COUNTER
            gap = (counter - expected) & MAX_BINARY_COUNTER
            if gap >= (1 << 31):
                return
            if gap:
                remaining = self.max_frames - self._total_frames(pending)
                inserted = min(gap, remaining)
                pending.pcm.extend(bytes(AUDIO_FRAME_BYTES * inserted))
                pending.missing_frames += inserted
                if inserted < gap or self._total_frames(pending) >= self.max_frames:
                    await self._finish(key, truncated=True)
                    self._blocked.add(key)
                    return

        if pending.first_counter is None:
            pending.first_counter = counter
        pending.last_counter = counter
        pending.frame_count += 1
        pending.pcm.extend(payload)
        if self._total_frames(pending) >= self.max_frames:
            await self._finish(key, truncated=True)
            self._blocked.add(key)

    @staticmethod
    def _key(value: dict[str, object]) -> tuple[str, int] | None:
        robot_id = value.get("robot_id")
        epoch = value.get("epoch")
        if not isinstance(robot_id, str) or not robot_id or type(epoch) is not int:
            return None
        return robot_id, epoch

    @staticmethod
    def _event_origin_id(value: dict[str, object]) -> int | None:
        origin_id = value.get("origin_id")
        return (
            origin_id
            if type(origin_id) is int and 0 <= origin_id <= MAX_BINARY_COUNTER
            else None
        )

    @staticmethod
    def _total_frames(pending: _PendingUtterance) -> int:
        return len(pending.pcm) // AUDIO_FRAME_BYTES

    async def _finish(self, key: tuple[str, int], *, truncated: bool) -> None:
        pending = self._pending.pop(key, None)
        if (
            pending is None
            or pending.frame_count == 0
            or pending.first_counter is None
            or pending.last_counter is None
        ):
            return
        utterance = AudioUtterance(
            utterance_id=pending.utterance_id,
            robot_id=pending.robot_id,
            epoch=pending.epoch,
            started_at=pending.started_at,
            ended_at=self.utcnow().isoformat(),
            first_counter=pending.first_counter,
            last_counter=pending.last_counter,
            frame_count=pending.frame_count,
            missing_frames=pending.missing_frames,
            duration_ms=self._total_frames(pending) * AUDIO_FRAME_DURATION_MS,
            wake_triggered=pending.wake_triggered,
            truncated=truncated,
            pcm=bytes(pending.pcm),
        )
        result = self.consume(utterance)
        if inspect.isawaitable(result):
            await result


class AudioUtterancePlugin:
    def __init__(
        self,
        gateway: GatewayService,
        consume: UtteranceFunction,
        *,
        max_duration_ms: int = DEFAULT_MAX_UTTERANCE_MS,
        utcnow: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        id_factory: Callable[[], str] = lambda: str(uuid4()),
    ) -> None:
        self.assembler = AudioUtteranceAssembler(
            consume,
            max_duration_ms=max_duration_ms,
            utcnow=utcnow,
            id_factory=id_factory,
        )
        gateway.subscribe_events(self.assembler.handle_event)
        gateway.subscribe_frames(self.assembler.handle_frame)


class AudioTranscriptPlugin:
    """Optional gateway-local transcription, invoked once per complete utterance."""

    def __init__(
        self,
        gateway: GatewayService,
        transcribe: TranscriptFunction,
        *,
        max_duration_ms: int = DEFAULT_MAX_UTTERANCE_MS,
    ) -> None:
        self.gateway = gateway
        self.transcribe = transcribe
        self.utterances = AudioUtterancePlugin(
            gateway,
            self._handle_utterance,
            max_duration_ms=max_duration_ms,
        )

    async def _handle_utterance(self, utterance: AudioUtterance) -> None:
        result = self.transcribe(utterance.wav_bytes())
        transcript = await result if inspect.isawaitable(result) else result
        if not transcript:
            return
        await self.gateway.publish_transcript(
            {
                "source": "gateway_transcriber",
                "robot_id": utterance.robot_id,
                "epoch": utterance.epoch,
                "utterance_id": utterance.utterance_id,
                "first_counter": utterance.first_counter,
                "last_counter": utterance.last_counter,
                "duration_ms": utterance.duration_ms,
                "wake_triggered": utterance.wake_triggered,
                "text": transcript,
            }
        )


@dataclass(frozen=True)
class CameraAnalysis:
    """Backend output tied to its source frame and local monotonic times.

    received_at is gateway receipt time, not sensor capture time. result remains
    backend-owned: a detector and a vision LLM need not return the same format.
    """

    robot_id: str
    epoch: int
    counter: int
    received_at: float
    completed_at: float
    result: object
    error: str | None = None
    processing: dict[str, object] | None = None
    jpeg: bytes | None = None


@dataclass(frozen=True)
class _CameraInput:
    robot_id: str
    epoch: int
    counter: int
    received_at: float
    payload: bytes


CameraObserver = Callable[[CameraAnalysis], object | Awaitable[object]]


class CameraFramePlugin:
    """Process one image at a time without awaiting inference in robot receive.

    There is one waiting image; newer images replace it. Synchronous callbacks
    run on one private worker thread, while async callbacks must yield normally.
    This plugin observes images and has no movement or task authority.
    Owners must await aclose() when removing the plugin or shutting down.
    """

    def __init__(
        self,
        gateway: GatewayService,
        consume: CameraFunction | None,
        *,
        observe: CameraObserver | None = None,
        robot_id: str | None = None,
        max_frame_age_s: float = 1.0,
    ) -> None:
        if not math.isfinite(max_frame_age_s) or max_frame_age_s <= 0:
            raise ValueError("max_frame_age_s must be finite and positive")
        self.gateway = gateway
        self.consume = consume
        self.observe = observe
        self.robot_id = robot_id
        self.max_frame_age_s = max_frame_age_s
        self.dropped_frames = 0
        self.stale_frames = 0
        self.errors = 0
        self.received_frames = 0
        self.processed_frames = 0
        self.fresh_results = 0
        self._started_at: float | None = None
        self._last_received_at: float | None = None
        self._last_queue_wait_ms: float | None = None
        self._last_inference_ms: float | None = None
        self._queue: asyncio.Queue[_CameraInput] = asyncio.Queue(maxsize=1)
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ainekio-camera")
        self._worker: asyncio.Task[None] | None = None
        self._close_task: asyncio.Task[None] | None = None
        self._closed = False
        self.enabled = consume is not None
        self._generation = 0
        self._latest_analysis: CameraAnalysis | None = None
        self._metric_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ainekio-ground-plane")
        self._metric_queue = asyncio.Queue(maxsize=1)
        self._metric_worker = None
        self._ground_plane = None
        self._depth_motion = None
        self._depth_settings = {}
        self._metric_generation = {}
        self._metric_latest = {}
        self._camera_latest = {}
        gateway.subscribe_frames(self._handle_frame)

    def set_enabled(self, enabled: bool) -> None:
        if enabled and self.consume is None:
            raise ValueError("Camera recognition is not configured")
        if self.enabled == enabled:
            return
        self.enabled = enabled
        self._generation += 1
        self._last_received_at = None
        self._latest_analysis = None
        while not self._queue.empty():
            self._queue.get_nowait()
            self._queue.task_done()

    async def _handle_frame(self, frame: dict[str, object]) -> None:
        if self._closed or frame.get("frame_type") != CAMERA_JPEG_FRAME_TYPE:
            return
        payload = frame.get("payload")
        robot_id, epoch, counter = frame.get("robot_id"), frame.get("epoch"), frame.get("counter")
        received_at = frame.get("received_at", self.gateway.clock())
        if (
            not isinstance(payload, bytes) or not 0 < len(payload) <= MAX_JPEG_BYTES
            or not isinstance(robot_id, str) or not robot_id
            or (self.robot_id is not None and robot_id != self.robot_id)
            or type(epoch) is not int or epoch < 1
            or type(counter) is not int or not 0 <= counter <= MAX_BINARY_COUNTER
            or type(received_at) not in {int, float} or not math.isfinite(received_at)
        ):
            return
        item = _CameraInput(robot_id, epoch, counter, received_at, payload)
        received_iso = (datetime.now(timezone.utc) - timedelta(seconds=self.gateway.clock() - received_at)).isoformat()
        if self._body_current(item):
            self._camera_latest[robot_id] = {"available": True, "source": "gateway-camera",
                "robotId": robot_id, "epoch": epoch, "gatewayInstance": self.gateway.instance_id,
                "referenceId": f"{self.gateway.instance_id}:{robot_id}:{epoch}",
                "frameId": f"ainekio-camera-{self.gateway.instance_id}-{robot_id}-{epoch}-{counter}",
                "frameCounter": counter, "observedAt": received_iso, "clock": "gateway-receipt",
                "receivedAtMonotonic": received_at,
                "expiresAt": (datetime.fromisoformat(received_iso) + timedelta(seconds=self.max_frame_age_s)).isoformat()}
            await self.gateway._publish_event({"t": "locomotion_measurement", "robot_id": robot_id,
                "epoch": epoch, "measurement": {"camera": self.camera_measurement(robot_id)}})
        if self._metric_queue.full():
            self._metric_queue.get_nowait()
            self._metric_queue.task_done()
        self._metric_queue.put_nowait((item, received_iso))
        if self._metric_worker is None:
            self._metric_worker = asyncio.create_task(self._run_metrics())
        if not self.enabled:
            return
        self.received_frames += 1
        if self._started_at is None:
            self._started_at = self.gateway.clock()
        if self._queue.full():
            self._queue.get_nowait()
            self._queue.task_done()
            self.dropped_frames += 1
        self._queue.put_nowait(item)
        if self._worker is None:
            self._worker = asyncio.create_task(self._consume_frames())

    def _body_current(self, frame: _CameraInput) -> bool:
        robot = self.gateway.status()["robots"].get(frame.robot_id)
        return (
            not self._closed and robot is not None
            and robot.get("epoch") == frame.epoch
            and robot.get("connection_state") == "online"
        )

    def _current(self, frame: _CameraInput) -> bool:
        return self.enabled and self._body_current(frame)

    def _fresh(self, frame: _CameraInput) -> bool:
        age = self.gateway.clock() - frame.received_at
        return self._current(frame) and 0 <= age <= self.max_frame_age_s

    async def _call(self, callback: Callable, argument: object) -> object:
        if inspect.iscoroutinefunction(callback):
            result = callback(argument)
        else:
            result = await asyncio.get_running_loop().run_in_executor(self._executor, callback, argument)
        return await result if inspect.isawaitable(result) else result

    def metrics(self) -> dict[str, object]:
        """Host-receipt age and throughput since the first frame, not capture latency."""
        now = self.gateway.clock()
        elapsed = now - self._started_at if self._started_at is not None else 0
        return {"enabled": self.enabled, "maxFrameAgeMs": self.max_frame_age_s * 1000,
            "visionOperations": getattr(self.consume, "vision_operations", lambda: [])(),
            "visionTarget": getattr(self.consume, "vision_target", lambda: None)(),
            "receivedFrames": self.received_frames, "processedFrames": self.processed_frames,
            "freshResults": self.fresh_results, "droppedFrames": self.dropped_frames,
            "staleFrames": self.stale_frames, "errors": self.errors,
            "queueDepth": self._queue.qsize(), "queueWaitMs": self._last_queue_wait_ms,
            "inferenceMs": self._last_inference_ms,
            "observationAgeMs": (now - self._last_received_at) * 1000 if self._last_received_at is not None else None,
            "processedFps": self.processed_frames / elapsed if elapsed > 0 else 0,
            "freshFps": self.fresh_results / elapsed if elapsed > 0 else 0}

    def identity_status(self) -> dict[str, object]:
        status = getattr(self.consume, "status", None)
        return status() if status else {"configured": False}

    def current_analysis(self, robot_id: str | None = None) -> CameraAnalysis | None:
        analysis = self._latest_analysis
        if analysis is not None and (robot_id is None or analysis.robot_id == robot_id):
            robot = self.gateway.status()["robots"].get(analysis.robot_id, {})
            if (self.enabled and robot.get("epoch") == analysis.epoch and robot.get("connection_state") == "online"
                    and 0 <= self.gateway.clock() - analysis.received_at <= self.max_frame_age_s):
                return analysis
        return None

    def recognition_status(self) -> dict[str, object]:
        analysis = self.current_analysis()
        return {"configured": self.consume is not None, "maxAgeMs": self.max_frame_age_s * 1000,
            **self.metrics(), "observation": self.analysis_observation(analysis) if analysis else None}

    def analysis_observation(self, analysis: CameraAnalysis) -> dict[str, object]:
        return {
            **analysis.result.message(), "robotId": analysis.robot_id, "epoch": analysis.epoch,
            "gatewayInstance": self.gateway.instance_id, "frameCounter": analysis.counter,
            "ageMs": (self.gateway.clock() - analysis.received_at) * 1000,
        }

    def _metric_owner(self):
        if self._ground_plane is None:
            from .ground_plane import GroundPlane
            self._ground_plane = GroundPlane(self.gateway.instance_id)
        return self._ground_plane

    async def _metric_call(self, operation, *args):
        return await asyncio.get_running_loop().run_in_executor(
            self._metric_executor, lambda: getattr(self._metric_owner(), operation)(*args))

    async def configure_ground_plane(self, robot_id, request):
        result = await self._metric_call("calibration", robot_id, request)
        if result.get("measurement") and request.get("operation") != "status":
            measurement = result["measurement"]
            timestamp = measurement.get("observedAt")
            if timestamp:
                measurement["expiresAt"] = (datetime.fromisoformat(timestamp) + timedelta(seconds=self.max_frame_age_s)).isoformat()
            self._metric_latest[robot_id] = measurement
            await self.gateway._publish_event({"t": "locomotion_measurement", "robot_id": robot_id,
                                               "epoch": measurement.get("epoch"), "measurement": measurement})
        return result

    async def restore_ground_plane(self, calibrations):
        await self._metric_call("restore", calibrations)

    async def configure_depth(self, robot_id, request):
        config = depth_settings(request)
        self._metric_generation[robot_id] = self._metric_generation.get(robot_id, 0)+1
        # Serialized with camera inference, while the gateway remains async.
        def update():
            self._depth_settings[robot_id] = config
            if self._depth_motion is not None:
                if any(c["mode"] == "moge-open3d" for c in self._depth_settings.values()):
                    self._depth_motion.reset(robot_id)
                else:
                    self._depth_motion.close()
                    self._depth_motion = None
            self._metric_latest.pop(robot_id, None)
        await asyncio.get_running_loop().run_in_executor(self._metric_executor, update)
        return config

    async def restore_depth(self, configurations):
        self._depth_settings = {robot: depth_settings(config) for robot, config in configurations.items()}

    def _process_metric(self, frame, received_iso):
        config = self._depth_settings.get(frame.robot_id, {})
        if config.get("mode") == "moge-open3d":
            if self._depth_motion is None:
                self._depth_motion = DepthMotion(self.gateway.instance_id)
            return self._depth_motion.process(frame.robot_id, frame.epoch, frame.counter,
                frame.received_at, frame.payload, received_iso, config)
        return self._metric_owner().process(frame.robot_id, frame.epoch, frame.counter,
                                             frame.received_at, frame.payload, received_iso)

    def camera_measurement(self, robot_id):
        camera = self._camera_latest.get(robot_id)
        if camera is None:
            return {"available": False, "source": "gateway-camera", "robotId": robot_id,
                "reason": "No camera observation"}
        robot = self.gateway.status().get("robots", {}).get(robot_id, {})
        if self._closed or robot.get("epoch") != camera["epoch"] or robot.get("connection_state") != "online":
            return {**camera, "available": False, "reason": "Camera observation belongs to disconnected body epoch"}
        if not 0 <= self.gateway.clock() - camera["receivedAtMonotonic"] <= self.max_frame_age_s:
            return {**camera, "available": False, "reason": "Camera observation exceeds configured camera freshness"}
        return dict(camera)

    def locomotion_measurement(self, robot_id=None):
        selected = robot_id or self.robot_id
        candidates = self._camera_latest.keys() | self._metric_latest.keys()
        if selected is None and len(candidates) == 1:
            selected = next(iter(candidates))
        camera = self.camera_measurement(selected)
        measurement = self._metric_latest.get(selected)
        if measurement is None:
            return {"available": False, "reason": "No metric camera observation", "robotId": selected, "camera": camera}
        measurement = {**measurement, "camera": camera}
        robot = self.gateway.status().get("robots", {}).get(selected, {})
        if robot.get("epoch") != measurement.get("epoch") or robot.get("connection_state") != "online":
            return {**measurement, "available": False, "reason": "Metric observation belongs to disconnected body epoch"}
        if self.gateway.clock() - measurement.get("receivedAtMonotonic", 0) > self.max_frame_age_s:
            return {**measurement, "available": False, "reason": "Camera observation exceeds configured camera freshness"}
        return measurement

    async def selected_ground_range(self, frame_id, point, source_frame=None):
        result = await self._metric_call("range", frame_id, point, source_frame)
        if not result.get("available"):
            return result
        measurement = self.locomotion_measurement(result.get("robotId"))
        if not measurement.get("available"):
            return {**result, "available": False, "reason": measurement.get("reason")}
        return {**result, "expiresAt": measurement.get("expiresAt")}

    async def _run_metrics(self):
        while True:
            frame, received_iso = await self._metric_queue.get()
            generation = self._metric_generation.get(frame.robot_id, 0)
            try:
                result = await asyncio.get_running_loop().run_in_executor(
                    self._metric_executor, self._process_metric, frame, received_iso)
                if self._body_current(frame) and generation == self._metric_generation.get(frame.robot_id, 0):
                    result["expiresAt"] = (datetime.fromisoformat(received_iso) + timedelta(seconds=self.max_frame_age_s)).isoformat()
                    self._metric_latest[frame.robot_id] = result
                    await self.gateway._publish_event({"t": "locomotion_measurement", "robot_id": frame.robot_id,
                        "epoch": frame.epoch, "measurement": {k: v for k, v in result.items() if k != "depthPreview"}})
            except Exception as error:
                failed = {"available": False, "robotId": frame.robot_id, "epoch": frame.epoch,
                    "observedAt": received_iso, "frameTimestamp": received_iso, "reason": str(error),
                    "receivedAtMonotonic": frame.received_at, "frameCounter": frame.counter,
                    "frameId": f"ainekio-camera-{self.gateway.instance_id}-{frame.robot_id}-{frame.epoch}-{frame.counter}"}
                logging.getLogger(__name__).warning("Camera motion measurement failed: %s", error)
                if self._body_current(frame) and generation == self._metric_generation.get(frame.robot_id, 0):
                    self._metric_latest[frame.robot_id] = failed
                    await self.gateway._publish_event({"t": "locomotion_measurement", "robot_id": frame.robot_id,
                                                       "epoch": frame.epoch, "measurement": failed})
            finally:
                self._metric_queue.task_done()

    async def enroll_person(self, payload: dict[str, object]) -> object:
        enroll = getattr(self.consume, "enroll", None)
        if enroll is None:
            raise ValueError("Named-person recognition is not configured")
        return await self._call(enroll, payload)

    async def configure_vision(self, request: dict[str, object]) -> object:
        configure = getattr(self.consume, "configure_vision", None)
        if configure is None:
            raise ValueError("The configured recognition backend does not support target configuration")
        self._generation += 1
        self._latest_analysis = None
        # Same executor as inference: no concurrent mutation of model prompts.
        try:
            return await self._call(configure, request)
        finally:
            self._generation += 1
            self._latest_analysis = None

    async def forget_person(self, person_id: str) -> dict[str, object]:
        gallery = getattr(self.consume, "gallery", None)
        if gallery is None:
            raise ValueError("Named-person recognition is not configured")
        await self._call(gallery.forget, person_id)
        self._latest_analysis = None
        return {"ok": True, "people": gallery.list()}

    async def _consume_frames(self) -> None:
        while True:
            frame = await self._queue.get()
            generation = self._generation
            try:
                if not self._fresh(frame):
                    self.stale_frames += 1
                    continue
                started_at = self.gateway.clock()
                self._last_queue_wait_ms = (started_at - frame.received_at) * 1000
                try:
                    result = await self._call(self.consume, frame.payload)
                except Exception as error:
                    self.errors += 1
                    self.processed_frames += 1
                    self._last_inference_ms = (self.gateway.clock() - started_at) * 1000
                    reason = f"{type(error).__name__}: {error}"[:240]
                    logging.getLogger(__name__).warning("Camera processing failed (%s)", reason)
                    # A timed-out frame is not a fresh observation, but its
                    # failure still belongs to the current connected body.
                    if generation == self._generation and self._current(frame) and self.observe is not None:
                        await self._call(self.observe, CameraAnalysis(
                            frame.robot_id, frame.epoch, frame.counter, frame.received_at,
                            self.gateway.clock(), None, error=reason, processing=self.metrics(),
                        ))
                    continue
                self.processed_frames += 1
                self._last_inference_ms = (self.gateway.clock() - started_at) * 1000
                if generation != self._generation or not self._fresh(frame):
                    self.stale_frames += 1
                    continue
                finalize = getattr(self.consume, "finalize_frame", None)
                if finalize is not None:
                    result = finalize(result, (frame.robot_id, frame.epoch, generation), frame.counter, frame.received_at)
                self.fresh_results += 1
                self._last_received_at = frame.received_at
                self._latest_analysis = CameraAnalysis(frame.robot_id, frame.epoch, frame.counter,
                    frame.received_at, self.gateway.clock(), result, jpeg=frame.payload)
                if self.observe is not None:
                    await self._call(self.observe, CameraAnalysis(
                        frame.robot_id, frame.epoch, frame.counter, frame.received_at,
                        self.gateway.clock(), result, processing=self.metrics(),
                    ))
            except Exception as error:
                self.errors += 1
                logging.getLogger(__name__).warning("Camera processing failed (%s)", type(error).__name__)
            finally:
                self._queue.task_done()

    async def aclose(self) -> None:
        if self._close_task is None:
            self._closed = True
            self.gateway.unsubscribe_frames(self._handle_frame)
            self._close_task = asyncio.create_task(self._finish_close())
        await asyncio.shield(self._close_task)

    async def _finish_close(self) -> None:
        if self._metric_worker is not None:
            self._metric_worker.cancel()
            await asyncio.gather(self._metric_worker, return_exceptions=True)
        def close_depth():
            if self._depth_motion is not None:
                self._depth_motion.close()
        await asyncio.get_running_loop().run_in_executor(self._metric_executor, close_depth)
        await asyncio.to_thread(self._metric_executor.shutdown, wait=True, cancel_futures=True)
        if self._worker is not None:
            self._worker.cancel()
            await asyncio.gather(self._worker, return_exceptions=True)
        while not self._queue.empty():
            self._queue.get_nowait()
            self._queue.task_done()
        # Cancellation cannot interrupt native inference already on the thread.
        # Wait for it without blocking the event loop; its result is discarded.
        await asyncio.to_thread(self._executor.shutdown, wait=True, cancel_futures=True)
