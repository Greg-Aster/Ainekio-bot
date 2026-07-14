from __future__ import annotations

import asyncio

from .media import AUDIO_FRAME_BYTES, MAX_JPEG_BYTES


_RESOLUTIONS = {"QVGA": "320x240", "VGA": "640x480"}


class WebcamCameraSource:
    def __init__(self, device: str = "/dev/video0", *, timeout: float = 3.0) -> None:
        if not device or not 0.1 <= timeout <= 10.0:
            raise ValueError("webcam device and bounded timeout are required")
        self.device = device
        self.timeout = timeout

    async def capture_jpeg(self, resolution: str) -> bytes:
        try:
            size = _RESOLUTIONS[resolution]
        except KeyError as exc:
            raise ValueError("unsupported webcam resolution") from exc
        process = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-loglevel",
            "error",
            "-f",
            "v4l2",
            "-video_size",
            size,
            "-i",
            self.device,
            "-frames:v",
            "1",
            "-f",
            "image2pipe",
            "-vcodec",
            "mjpeg",
            "pipe:1",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            payload, error = await asyncio.wait_for(
                process.communicate(), timeout=self.timeout
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            raise RuntimeError("webcam capture timed out") from None
        if process.returncode != 0:
            reason = error.decode("utf-8", errors="replace").strip()[:160]
            raise RuntimeError(f"webcam capture failed: {reason}")
        if not 1 <= len(payload) <= MAX_JPEG_BYTES:
            raise RuntimeError("webcam JPEG is empty or oversized")
        return payload


class AlsaMicrophoneSource:
    def __init__(self, device: str = "default") -> None:
        if not device:
            raise ValueError("ALSA capture device is required")
        self.device = device
        self._process: asyncio.subprocess.Process | None = None
        self._lock = asyncio.Lock()

    async def read_pcm(self) -> bytes | None:
        async with self._lock:
            process = await self._ensure_process()
            assert process.stdout is not None
            try:
                return await asyncio.wait_for(
                    process.stdout.readexactly(AUDIO_FRAME_BYTES), timeout=0.25
                )
            except (asyncio.IncompleteReadError, asyncio.TimeoutError):
                await self.close()
                return None

    async def close(self) -> None:
        process = self._process
        self._process = None
        if process is None or process.returncode is not None:
            return
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=1.0)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()

    async def _ensure_process(self) -> asyncio.subprocess.Process:
        if self._process is None or self._process.returncode is not None:
            self._process = await asyncio.create_subprocess_exec(
                "arecord",
                "-q",
                "-D",
                self.device,
                "-t",
                "raw",
                "-f",
                "S16_LE",
                "-r",
                "16000",
                "-c",
                "1",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
        return self._process


class AlsaSpeakerSink:
    def __init__(self, device: str = "default") -> None:
        if not device:
            raise ValueError("ALSA playback device is required")
        self.device = device
        self._process: asyncio.subprocess.Process | None = None
        self._lock = asyncio.Lock()

    async def play_pcm(self, payload: bytes) -> None:
        if not payload or len(payload) % 2:
            raise ValueError("speaker PCM must contain complete s16le samples")
        async with self._lock:
            process = await self._ensure_process()
            if process.stdin is None:
                raise RuntimeError("ALSA playback stdin is unavailable")
            process.stdin.write(payload)
            await process.stdin.drain()

    async def stop(self) -> None:
        async with self._lock:
            process = self._process
            self._process = None
            if process is None or process.returncode is not None:
                return
            if process.stdin is not None:
                process.stdin.close()
            try:
                await asyncio.wait_for(process.wait(), timeout=1.0)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()

    async def _ensure_process(self) -> asyncio.subprocess.Process:
        if self._process is None or self._process.returncode is not None:
            self._process = await asyncio.create_subprocess_exec(
                "aplay",
                "-q",
                "-D",
                self.device,
                "-t",
                "raw",
                "-f",
                "S16_LE",
                "-r",
                "16000",
                "-c",
                "1",
                stdin=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
        return self._process
