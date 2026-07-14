from __future__ import annotations

from typing import Protocol

from .assets import AssetStore, FaceAsset


class DisplaySink(Protocol):
    async def show_frame(self, name: str, payload: bytes) -> None:
        ...


class NullDisplaySink:
    async def show_frame(self, name: str, payload: bytes) -> None:
        return None


class DisplayController:
    def __init__(
        self,
        assets: AssetStore,
        sink: DisplaySink | None = None,
    ) -> None:
        self.assets = assets
        self.sink = sink or NullDisplaySink()
        self.current_name = "default"
        self.current_mode = "once"
        self.current_tick = 0
        self.previous_non_talk = "default"
        self.failure_count = 0
        self._next_frame_at: float | None = None

    async def set_face(
        self,
        name: str,
        mode: str | None = None,
        *,
        remember: bool = True,
    ) -> bool:
        asset = self.assets.face(name)
        if asset is None:
            return False
        self.current_name = name
        self.current_mode = mode or asset.mode
        self.current_tick = 0
        self._next_frame_at = None
        if remember and not name.startswith("talk_"):
            self.previous_non_talk = name
        await self._show(asset, 0)
        return True

    async def advance(self, ticks: int = 1) -> None:
        asset = self.assets.face(self.current_name)
        if asset is None:
            return
        self.current_tick += max(1, ticks)
        await self._show(asset, _frame_index(self.current_mode, len(asset.frame_paths), self.current_tick))

    async def service(self, now: float) -> None:
        asset = self.assets.face(self.current_name)
        if asset is None:
            return
        period = 1.0 / asset.fps
        if self._next_frame_at is None:
            self._next_frame_at = now + period
            return
        if now < self._next_frame_at:
            return
        ticks = int((now - self._next_frame_at) / period) + 1
        self._next_frame_at += ticks * period
        await self.advance(ticks)

    async def begin_tts(self) -> None:
        candidate = f"talk_{self.previous_non_talk}"
        if self.assets.face(candidate) is not None:
            await self.set_face(candidate)

    async def end_tts(self) -> None:
        await self.set_face(self.previous_non_talk)

    def face_duration_seconds(self, name: str) -> float | None:
        asset = self.assets.face(name)
        if asset is None:
            return None
        return len(asset.frame_paths) / asset.fps

    async def _show(self, asset: FaceAsset, index: int) -> None:
        try:
            await self.sink.show_frame(asset.name, self.assets.face_frame(asset, index))
        except Exception:
            self.failure_count += 1


def _frame_index(mode: str, count: int, tick: int) -> int:
    if count <= 1:
        return 0
    if mode == "once":
        return min(tick, count - 1)
    if mode == "loop":
        return tick % count
    period = (count * 2) - 2
    position = tick % period
    return position if position < count else period - position
