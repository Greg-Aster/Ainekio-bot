"""Gateway ownership of the installed host hotspot and its existing .env setting."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
import re
import stat
import tempfile

from gateway.server.service import GatewayError


class RobotHotspot:
    def __init__(self, env_file: Path = Path(".env"), *, enabled: bool | None = None) -> None:
        self.env_file = env_file.resolve()
        self.enabled = os.environ.get("AINEKIO_HOTSPOT", "0") == "1" if enabled is None else enabled
        self._managed = False
        self._lock = asyncio.Lock()

    def snapshot(self) -> dict[str, bool]:
        return {"hotspot": self.enabled}

    async def start(self) -> None:
        async with self._lock:
            if self.enabled:
                self._managed = True
                await self._service(True)

    async def close(self) -> None:
        async with self._lock:
            if self._managed:
                await self._service(False)
                self._managed = False

    async def set_enabled(self, enabled: bool) -> dict[str, bool]:
        async with self._lock:
            if enabled != self.enabled or (not enabled and self._managed):
                if enabled:
                    self._managed = True
                await self._service(enabled)
                self.enabled = enabled
                self._managed = enabled
            try:
                self._save_setting()
            except OSError as exc:
                raise GatewayError(f"Network mode applied, but .env could not be saved: {exc}") from exc
            return self.snapshot()

    async def _service(self, enabled: bool) -> None:
        action = "start" if enabled else "stop"
        unit = "ainekio-hotspot-dhcp.service" if enabled else "ainekio-hotspot-interface.service"
        try:
            process = await asyncio.create_subprocess_exec(
                "systemctl", "--no-ask-password", action, unit,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
        except OSError as exc:
            raise GatewayError(f"Could not {action} the robot hotspot: {exc}") from exc
        _, error = await process.communicate()
        if process.returncode:
            detail = error.decode(errors="replace").strip()
            raise GatewayError(f"Could not {action} the robot hotspot: {detail or unit}")

    def _save_setting(self) -> None:
        content = self.env_file.read_text() if self.env_file.exists() else ""
        mode = stat.S_IMODE(self.env_file.stat().st_mode) if self.env_file.exists() else 0o600
        assignment = re.compile(
            r"^([ \t]*(?:export[ \t]+)?AINEKIO_HOTSPOT=)[^\r\n]*?([ \t]+#[^\r\n]*)?$", re.MULTILINE,
        )
        value = "1" if self.enabled else "0"
        updated, count = assignment.subn(lambda match: match[1] + value + (match[2] or ""), content)
        if not count:
            updated = content + ("\n" if content and not content.endswith("\n") else "") + f"AINEKIO_HOTSPOT={value}\n"
        with tempfile.NamedTemporaryFile(mode="w", dir=self.env_file.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(updated)
        try:
            temporary.chmod(mode)
            temporary.replace(self.env_file)
        finally:
            temporary.unlink(missing_ok=True)
