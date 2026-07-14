from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable

from protocol.binary_helpers import CAMERA_JPEG_FRAME_TYPE, MIC_PCM_FRAME_TYPE

from .server.service import GatewayService


TranscriptFunction = Callable[[bytes], str | None | Awaitable[str | None]]
CameraFunction = Callable[[bytes], object | Awaitable[object]]


class AudioTranscriptPlugin:
    def __init__(self, gateway: GatewayService, transcribe: TranscriptFunction) -> None:
        self.gateway = gateway
        self.transcribe = transcribe
        gateway.subscribe_frames(self._handle_frame)

    async def _handle_frame(self, frame: dict[str, object]) -> None:
        if frame.get("frame_type") != MIC_PCM_FRAME_TYPE:
            return
        payload = frame.get("payload")
        if not isinstance(payload, bytes):
            return
        result = self.transcribe(payload)
        transcript = await result if inspect.isawaitable(result) else result
        if not transcript:
            return
        await self.gateway.publish_transcript(
            {
                "robot_id": frame.get("robot_id"),
                "epoch": frame.get("epoch"),
                "counter": frame.get("counter"),
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
