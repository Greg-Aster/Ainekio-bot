"""Direct Kokoro stream client for robot speaker playback."""

from __future__ import annotations

import asyncio
import base64
import binascii
import io
import json
import sys
import wave
from array import array
from collections.abc import AsyncIterator, Callable
from typing import Any
from urllib.parse import urlparse, urlunparse
from urllib.request import Request, urlopen


PCM_SAMPLE_RATE = 16000
PCM_FRAME_SAMPLES = 320
PCM_FRAME_BYTES = PCM_FRAME_SAMPLES * 2
MAX_TEXT_CHARS = 4096
MAX_WAV_CHUNK_BYTES = 8 * 1024 * 1024
MAX_SSE_LINE_BYTES = 12 * 1024 * 1024
MAX_AUDIO_SECONDS = 300


class TTSClientError(RuntimeError):
    pass


class KokoroTTSClient:
    """Read Kokoro's SSE WAV chunks and expose protocol-v1 PCM frames."""

    def __init__(
        self,
        endpoint: str,
        *,
        timeout_seconds: float = 30.0,
        opener: Callable[..., Any] = urlopen,
    ) -> None:
        self.endpoint = _stream_endpoint(endpoint)
        if not 1.0 <= timeout_seconds <= 120.0:
            raise ValueError("TTS timeout must be between 1 and 120 seconds")
        self.timeout_seconds = timeout_seconds
        self._opener = opener

    async def stream_pcm_frames(self, text: str) -> AsyncIterator[bytes]:
        spoken_text = text.strip()
        if not spoken_text:
            raise TTSClientError("TTS text is empty")
        if len(spoken_text) > MAX_TEXT_CHARS:
            raise TTSClientError("TTS text exceeds the 4096 character limit")

        pending = bytearray()
        total_samples = 0
        frame_count = 0
        async for wav_bytes in self._stream_wav_chunks(spoken_text):
            pcm = _wav_to_pcm16_mono(wav_bytes)
            total_samples += len(pcm) // 2
            if total_samples > PCM_SAMPLE_RATE * MAX_AUDIO_SECONDS:
                raise TTSClientError("TTS audio exceeds the five minute limit")

            pending.extend(pcm)
            complete_bytes = len(pending) - (len(pending) % PCM_FRAME_BYTES)
            for offset in range(0, complete_bytes, PCM_FRAME_BYTES):
                frame_count += 1
                yield bytes(pending[offset : offset + PCM_FRAME_BYTES])
            if complete_bytes:
                del pending[:complete_bytes]

        if pending:
            pending.extend(bytes(PCM_FRAME_BYTES - len(pending)))
            frame_count += 1
            yield bytes(pending)
        if frame_count == 0:
            raise TTSClientError("Kokoro produced no playable audio")

    async def _stream_wav_chunks(self, text: str) -> AsyncIterator[bytes]:
        request = Request(
            self.endpoint,
            data=json.dumps({"text": text}, separators=(",", ":")).encode("utf-8"),
            headers={
                "Accept": "text/event-stream",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            response = await asyncio.to_thread(
                self._opener,
                request,
                timeout=self.timeout_seconds,
            )
        except Exception as exc:
            raise TTSClientError(f"Kokoro stream connection failed: {exc}") from exc

        completed = False
        data_lines: list[str] = []
        try:
            content_type = str(response.headers.get("Content-Type", "")).lower()
            if "text/event-stream" not in content_type:
                raise TTSClientError(
                    f"Kokoro returned unexpected content type: {content_type or 'missing'}"
                )

            while True:
                raw_line = await asyncio.to_thread(
                    response.readline,
                    MAX_SSE_LINE_BYTES + 1,
                )
                if len(raw_line) > MAX_SSE_LINE_BYTES:
                    raise TTSClientError("Kokoro stream event exceeds its size limit")
                if not raw_line:
                    if data_lines:
                        wav_bytes, completed = _decode_sse_event(data_lines)
                        data_lines.clear()
                        if wav_bytes is not None:
                            yield wav_bytes
                    break

                try:
                    line = raw_line.decode("utf-8").rstrip("\r\n")
                except UnicodeDecodeError as exc:
                    raise TTSClientError("Kokoro stream is not valid UTF-8") from exc
                if not line:
                    if not data_lines:
                        continue
                    wav_bytes, event_complete = _decode_sse_event(data_lines)
                    data_lines.clear()
                    if wav_bytes is not None:
                        yield wav_bytes
                    if event_complete:
                        completed = True
                        break
                    continue
                if line.startswith("data:"):
                    data_lines.append(line[5:].lstrip())
        finally:
            await asyncio.to_thread(response.close)

        if not completed:
            raise TTSClientError("Kokoro stream ended before its completion event")


def _stream_endpoint(value: str) -> str:
    parsed = urlparse(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("TTS URL must be an http or https address")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("TTS URL must not contain credentials")
    path = parsed.path
    if path in {"", "/"}:
        path = "/synthesize-stream-default"
    return urlunparse(parsed._replace(path=path))


def _decode_sse_event(data_lines: list[str]) -> tuple[bytes | None, bool]:
    try:
        event = json.loads("\n".join(data_lines))
    except json.JSONDecodeError as exc:
        raise TTSClientError("Kokoro stream returned malformed event data") from exc
    if not isinstance(event, dict):
        raise TTSClientError("Kokoro stream event must be an object")
    if event.get("event") == "complete":
        return None, True
    if event.get("event") == "error":
        message = str(event.get("error", "synthesis failed"))[:512]
        raise TTSClientError(f"Kokoro synthesis failed: {message}")

    encoded = event.get("audio_base64")
    if not isinstance(encoded, str) or not encoded:
        raise TTSClientError("Kokoro audio event is missing audio_base64")
    if len(encoded) > ((MAX_WAV_CHUNK_BYTES + 2) // 3) * 4:
        raise TTSClientError("Kokoro WAV chunk exceeds its size limit")
    try:
        wav_bytes = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise TTSClientError("Kokoro audio event contains invalid base64") from exc
    if not wav_bytes or len(wav_bytes) > MAX_WAV_CHUNK_BYTES:
        raise TTSClientError("Kokoro WAV chunk exceeds its size limit")
    declared_size = event.get("audio_size")
    if type(declared_size) is int and declared_size != len(wav_bytes):
        raise TTSClientError("Kokoro WAV chunk size does not match its event metadata")
    return wav_bytes, False


def _wav_to_pcm16_mono(wav_bytes: bytes) -> bytes:
    try:
        with wave.open(io.BytesIO(wav_bytes), "rb") as reader:
            channels = reader.getnchannels()
            sample_width = reader.getsampwidth()
            sample_rate = reader.getframerate()
            frame_count = reader.getnframes()
            compression = reader.getcomptype()
            raw = reader.readframes(frame_count)
    except (EOFError, wave.Error) as exc:
        raise TTSClientError("Kokoro returned an invalid WAV chunk") from exc

    if compression != "NONE" or sample_width != 2 or channels not in {1, 2}:
        raise TTSClientError("Kokoro WAV must be uncompressed mono or stereo s16 PCM")
    if not 8000 <= sample_rate <= 48000:
        raise TTSClientError("Kokoro WAV sample rate is outside the supported range")
    if len(raw) != frame_count * channels * sample_width:
        raise TTSClientError("Kokoro WAV chunk is truncated")

    samples = array("h")
    samples.frombytes(raw)
    if sys.byteorder == "big":
        samples.byteswap()
    if channels == 2:
        samples = array(
            "h",
            (
                int(samples[index] + samples[index + 1]) // 2
                for index in range(0, len(samples), 2)
            ),
        )
    if sample_rate != PCM_SAMPLE_RATE:
        samples = _resample_linear(samples, sample_rate, PCM_SAMPLE_RATE)
    if sys.byteorder == "big":
        samples.byteswap()
    return samples.tobytes()


def _resample_linear(samples: array[int], source_rate: int, target_rate: int) -> array[int]:
    if not samples:
        return array("h")
    output_count = max(1, round(len(samples) * target_rate / source_rate))
    output = array("h")
    for output_index in range(output_count):
        position = output_index * source_rate
        left = position // target_rate
        remainder = position % target_rate
        if left >= len(samples) - 1:
            value = samples[-1]
        else:
            value = (
                samples[left] * (target_rate - remainder)
                + samples[left + 1] * remainder
            ) // target_rate
        output.append(value)
    return output
