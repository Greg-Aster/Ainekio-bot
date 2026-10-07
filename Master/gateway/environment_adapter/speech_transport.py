from __future__ import annotations

import asyncio
import json
import re
import struct
from collections.abc import AsyncIterator
from dataclasses import dataclass


SPEECH_AUDIO_MAGIC = b"AIKSPK01"
SPEECH_AUDIO_HEADER_BYTES = len(SPEECH_AUDIO_MAGIC) + 4
MAX_METADATA_BYTES = 4 * 1024
PCM_FRAME_BYTES = 640
PCM_FRAME_SECONDS = 0.020
_IDENTIFIER = re.compile(r"^[a-zA-Z0-9_-]{1,160}$")


@dataclass(frozen=True)
class SpeechAudioMessage:
    session_id: str
    action_id: str
    speech_id: str
    duration_ms: int
    pcm: bytes


def parse_speech_audio_message(
    raw: bytes,
    *,
    expected_session_id: str,
) -> SpeechAudioMessage:
    if (
        len(raw) < SPEECH_AUDIO_HEADER_BYTES
        or not raw.startswith(SPEECH_AUDIO_MAGIC)
    ):
        raise ValueError("invalid robot speech frame")
    metadata_bytes = struct.unpack_from("<I", raw, len(SPEECH_AUDIO_MAGIC))[0]
    if metadata_bytes < 2 or metadata_bytes > MAX_METADATA_BYTES:
        raise ValueError("invalid robot speech metadata size")
    metadata_end = SPEECH_AUDIO_HEADER_BYTES + metadata_bytes
    if metadata_end > len(raw):
        raise ValueError("truncated robot speech metadata")
    try:
        metadata = json.loads(raw[SPEECH_AUDIO_HEADER_BYTES:metadata_end])
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("invalid robot speech metadata") from error
    if not isinstance(metadata, dict):
        raise ValueError("robot speech metadata must be an object")

    session_id = metadata.get("sessionId")
    action_id = metadata.get("actionId")
    speech_id = metadata.get("speechId")
    duration_ms = metadata.get("durationMs")
    pcm = raw[metadata_end:]
    if (
        metadata.get("type") != "audio.speech"
        or metadata.get("version") != 1
        or session_id != expected_session_id
        or not isinstance(action_id, str)
        or not _IDENTIFIER.fullmatch(action_id)
        or not isinstance(speech_id, str)
        or not _IDENTIFIER.fullmatch(speech_id)
        or metadata.get("format") != "pcm_s16le"
        or metadata.get("sampleRateHz") != 16_000
        or metadata.get("channels") != 1
        or metadata.get("frameBytes") != PCM_FRAME_BYTES
        or type(duration_ms) is not int
        or duration_ms <= 0
        or metadata.get("pcmBytes") != len(pcm)
        or len(pcm) == 0
        or len(pcm) % PCM_FRAME_BYTES
    ):
        raise ValueError("unsupported robot speech payload")
    return SpeechAudioMessage(
        session_id=session_id,
        action_id=action_id,
        speech_id=speech_id,
        duration_ms=duration_ms,
        pcm=pcm,
    )


async def paced_speaker_frames(pcm: bytes) -> AsyncIterator[bytes]:
    loop = asyncio.get_running_loop()
    started = loop.time()
    for index, offset in enumerate(range(0, len(pcm), PCM_FRAME_BYTES)):
        delay = started + index * PCM_FRAME_SECONDS - loop.time()
        if delay > 0:
            await asyncio.sleep(delay)
        yield pcm[offset:offset + PCM_FRAME_BYTES]
