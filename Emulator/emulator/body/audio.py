from __future__ import annotations

import asyncio
from typing import Protocol


class SpeakerSink(Protocol):
    async def play_pcm(self, payload: bytes) -> None:
        ...

    async def stop(self) -> None:
        ...


class NullSpeakerSink:
    async def play_pcm(self, payload: bytes) -> None:
        await asyncio.sleep(0)

    async def stop(self) -> None:
        return None
