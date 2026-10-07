"""Gateway ownership of the installed host hotspot and its existing .env setting."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
import threading
from time import monotonic

from gateway.server.service import GatewayError


class RobotHotspot:
    def __init__(self, env_file: Path = Path(".env"), *, enabled: bool | None = None) -> None:
        self.env_file = env_file.resolve()
        self.enabled = os.environ.get("AINEKIO_HOTSPOT", "0") == "1" if enabled is None else enabled
        self._managed = False
        self._lock = asyncio.Lock()
        self._network_lock = threading.Lock()
        self._network_cache: dict[str, str] = {}
        self._network_cache_until = 0.0

    def snapshot(self) -> dict[str, bool]:
        return {"hotspot": self.enabled}

    def connection_networks(self) -> dict[str, str]:
        """Read active Wi-Fi names by local socket address; never change networking."""
        with self._network_lock:
            if monotonic() < self._network_cache_until:
                return dict(self._network_cache)
            networks: dict[str, str] = {}
            try:
                addresses = subprocess.run(
                    ["ip", "-json", "address", "show"], capture_output=True,
                    text=True, timeout=1, check=True,
                )
                wireless = subprocess.run(
                    ["iw", "dev"], capture_output=True, text=True, timeout=1, check=True,
                )
                ssids: dict[str, str] = {}
                interface = None
                for raw_line in wireless.stdout.splitlines():
                    line = raw_line.lstrip()
                    if line.startswith("Interface "):
                        interface = line[len("Interface "):].strip()
                    elif line.startswith("Unnamed/"):
                        interface = None
                    elif interface and line.startswith("ssid "):
                        ssids[interface] = line[len("ssid "):]
                for device in json.loads(addresses.stdout):
                    ssid = ssids.get(device.get("ifname"))
                    if not ssid:
                        continue
                    for address in device.get("addr_info", []):
                        local = address.get("local")
                        if isinstance(local, str):
                            networks[local] = ssid
            except (OSError, subprocess.SubprocessError, ValueError, TypeError, AttributeError):
                # Status still works on hosts without these Linux tools or when
                # an interface disappears while it is being inspected.
                networks = {}
            self._network_cache = networks
            self._network_cache_until = monotonic() + 5
            return dict(networks)

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
