from __future__ import annotations

import inspect
import io
import wave
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4

from protocol.binary_helpers import CAMERA_JPEG_FRAME_TYPE, MIC_PCM_FRAME_TYPE

from .server.service import GatewayService


AUDIO_FRAME_BYTES = 640
AUDIO_FRAME_DURATION_MS = 20
AUDIO_SAMPLE_RATE_HZ = 16000
AUDIO_CHANNELS = 1
AUDIO_SAMPLE_WIDTH_BYTES = 2
DEFAULT_MAX_UTTERANCE_MS = 15000
MAX_BINARY_COUNTER = (1 << 32) - 1

TranscriptFunction = Callable[[bytes], str | None | Awaitable[str | None]]
CameraFunction = Callable[[bytes], object | Awaitable[object]]


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
            self._pending[key] = _PendingUtterance(
                utterance_id=self.id_factory(),
                robot_id=key[0],
                epoch=key[1],
                started_at=self.utcnow().isoformat(),
                wake_triggered=key in self._pending_wake,
            )
            self._pending_wake.discard(key)
            return
        if name == "vad_close":
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


class CameraFramePlugin:
    def __init__(self, gateway: GatewayService, consume: CameraFunction) -> None:
        self.consume = consume
        gateway.subscribe_frames(self._handle_frame)

    async def _handle_frame(self, frame: dict[str, object]) -> None:
        if frame.get("frame_type") != CAMERA_JPEG_FRAME_TYPE:
            return
        payload = frame.get("payload")
        if not isinstance(payload, bytes):
            return
        result = self.consume(payload)
        if inspect.isawaitable(result):
            await result
