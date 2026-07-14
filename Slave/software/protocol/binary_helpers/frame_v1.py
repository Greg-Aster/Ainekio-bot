"""Encode and decode the compact Ainekio v1 media-frame envelope."""

from __future__ import annotations

from dataclasses import dataclass


HEADER_BYTES = 5
MAX_BINARY_COUNTER = (1 << 32) - 1
MIC_PCM_FRAME_TYPE = 0x01
CAMERA_JPEG_FRAME_TYPE = 0x02
SPEAKER_PCM_FRAME_TYPE = 0x10
AUDIO_PAYLOAD_BYTES = 640
MAX_JPEG_BYTES = 120 * 1024
KNOWN_FRAME_TYPES = frozenset(
    {MIC_PCM_FRAME_TYPE, CAMERA_JPEG_FRAME_TYPE, SPEAKER_PCM_FRAME_TYPE}
)


class BinaryFrameError(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class BinaryFrame:
    frame_type: int
    counter: int
    payload_size: int
    known_type: bool


def _fail(reason: str) -> None:
    raise BinaryFrameError(reason)


def _validate_payload(frame_type: int, payload: bytes) -> None:
    if frame_type in {MIC_PCM_FRAME_TYPE, SPEAKER_PCM_FRAME_TYPE}:
        if len(payload) != AUDIO_PAYLOAD_BYTES:
            _fail("length:audio")
        return

    if frame_type == CAMERA_JPEG_FRAME_TYPE:
        if len(payload) > MAX_JPEG_BYTES:
            _fail("length:jpeg")
        if len(payload) < 4 or not payload.startswith(b"\xff\xd8") or not payload.endswith(b"\xff\xd9"):
            _fail("format:jpeg")


def encode_binary_frame(frame_type: int, counter: int, payload: bytes) -> bytes:
    if type(frame_type) is not int:
        _fail("type:frame_type")
    if not 0 <= frame_type <= 0xFF:
        _fail("range:frame_type")
    if type(counter) is not int:
        _fail("type:counter")
    if not 0 <= counter <= MAX_BINARY_COUNTER:
        _fail("range:counter")
    if not isinstance(payload, bytes):
        _fail("type:payload")

    _validate_payload(frame_type, payload)
    return bytes([frame_type]) + counter.to_bytes(4, "little", signed=False) + payload


def decode_binary_frame(frame: bytes) -> BinaryFrame:
    if not isinstance(frame, bytes):
        _fail("type:frame")
    if len(frame) < HEADER_BYTES:
        _fail("truncated:header")

    frame_type = frame[0]
    counter = int.from_bytes(frame[1:HEADER_BYTES], "little", signed=False)
    payload = frame[HEADER_BYTES:]
    known_type = frame_type in KNOWN_FRAME_TYPES
    if known_type:
        _validate_payload(frame_type, payload)

    return BinaryFrame(frame_type, counter, len(payload), known_type)
