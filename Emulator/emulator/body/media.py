from __future__ import annotations

import math
import struct
from collections import deque
from time import monotonic
from typing import Callable
from typing import Protocol


AUDIO_FRAME_BYTES = 640
MAX_JPEG_BYTES = 120 * 1024
DEFAULT_MEDIA_BYTES_PER_SECOND = 512 * 1024


class CameraSource(Protocol):
    async def capture_jpeg(self, resolution: str) -> bytes:
        ...


class MicrophoneSource(Protocol):
    async def read_pcm(self) -> bytes | None:
        ...


class FixtureCameraSource:
    def __init__(self, jpeg: bytes = b"\xff\xd8\xff\xd9") -> None:
        self.jpeg = jpeg
        self.captures: list[str] = []

    async def capture_jpeg(self, resolution: str) -> bytes:
        self.captures.append(resolution)
        return self.jpeg


class QueueMicrophoneSource:
    def __init__(self, frames: list[bytes] | None = None) -> None:
        self.frames: deque[bytes] = deque(frames or [])

    async def read_pcm(self) -> bytes | None:
        return self.frames.popleft() if self.frames else None

    def append(self, payload: bytes) -> None:
        self.frames.append(payload)


class MediaBudget:
    """Token budget where audio may borrow and camera frames may not."""

    def __init__(
        self,
        bytes_per_second: int = DEFAULT_MEDIA_BYTES_PER_SECOND,
        *,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if not 1024 <= bytes_per_second <= 100 * 1024 * 1024:
            raise ValueError("media budget must be between 1 KiB/s and 100 MiB/s")
        self.bytes_per_second = bytes_per_second
        self._clock = clock
        self._tokens = float(bytes_per_second)
        self._last = clock()

    def consume_audio(self, byte_count: int) -> None:
        self._refill()
        self._tokens = max(-float(self.bytes_per_second), self._tokens - byte_count)

    def allow_camera(self, byte_count: int) -> bool:
        self._refill()
        if byte_count > self._tokens:
            return False
        self._tokens -= byte_count
        return True

    def _refill(self) -> None:
        now = self._clock()
        elapsed = max(0.0, now - self._last)
        self._last = now
        self._tokens = min(
            float(self.bytes_per_second),
            self._tokens + elapsed * self.bytes_per_second,
        )


class EnergyVad:
    def __init__(self, *, threshold: float = 500.0, hangover_frames: int = 5) -> None:
        if threshold <= 0 or not 0 <= hangover_frames <= 100:
            raise ValueError("VAD settings are out of range")
        self.threshold = threshold
        self.hangover_frames = hangover_frames
        self.is_open = False
        self._hangover = 0

    def process(self, payload: bytes) -> str | None:
        if len(payload) != AUDIO_FRAME_BYTES:
            raise ValueError("microphone frame must contain exactly 640 bytes")
        samples = struct.unpack("<320h", payload)
        rms = math.sqrt(sum(sample * sample for sample in samples) / len(samples))
        if rms >= self.threshold:
            self._hangover = self.hangover_frames
            if not self.is_open:
                self.is_open = True
                return "vad_open"
            return None
        if self._hangover > 0:
            self._hangover -= 1
            return None
        if self.is_open:
            self.is_open = False
            return "vad_close"
        return None
