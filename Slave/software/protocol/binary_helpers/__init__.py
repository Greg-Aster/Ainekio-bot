"""Host helpers for the Ainekio v1 binary WebSocket frame format."""

from .frame_v1 import (
    AUDIO_PAYLOAD_BYTES,
    CAMERA_JPEG_FRAME_TYPE,
    HEADER_BYTES,
    MAX_BINARY_COUNTER,
    MAX_JPEG_BYTES,
    MIC_PCM_FRAME_TYPE,
    SPEAKER_PCM_FRAME_TYPE,
    BinaryFrame,
    BinaryFrameError,
    decode_binary_frame,
    encode_binary_frame,
)

__all__ = [
    "AUDIO_PAYLOAD_BYTES",
    "CAMERA_JPEG_FRAME_TYPE",
    "HEADER_BYTES",
    "MAX_BINARY_COUNTER",
    "MAX_JPEG_BYTES",
    "MIC_PCM_FRAME_TYPE",
    "SPEAKER_PCM_FRAME_TYPE",
    "BinaryFrame",
    "BinaryFrameError",
    "decode_binary_frame",
    "encode_binary_frame",
]
