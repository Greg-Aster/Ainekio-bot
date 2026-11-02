"""Control the installed host hotspot through its existing .env setting."""
from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
import threading
from time import monotonic

from gateway.server.service import GatewayError

UNITS = ("ainekio-hotspot-interface.service", "ainekio-hotspot.service", "ainekio-hotspot-dhcp.service")
TARGET = "ainekio-hotspot.target"


class RobotHotspot:
    def __init__(self, env_file: Path = Path(".env"), *, enabled: bool | None = None) -> None:
        self.env_file = env_file.resolve()
        self.enabled = os.environ.get("AINEKIO_HOTSPOT", "0") == "1" if enabled is None else enabled
        self._lock = asyncio.Lock()
        self._network_lock = threading.Lock()
        self._network_cache: dict[str, str] = {}
        self._network_cache_until = 0.0
        self._hotspot_error: str | None = "Robot hotspot has not been inspected."

    def snapshot(self) -> dict[str, object]:
        error = self._availability() if self.enabled else None
        return {"hotspot": self.enabled, "available": self.enabled and error is None, "error": error}

    def _availability(self, *, force: bool = False) -> str | None:
        self.connection_networks(force=force)
        with self._network_lock:
            return self._hotspot_error

    def connection_networks(self, *, force: bool = False) -> dict[str, str]:
        """Read active Wi-Fi names by local socket address; never change networking."""
        with self._network_lock:
            if not force and monotonic() < self._network_cache_until:
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
                devices = json.loads(addresses.stdout)
                for device in devices:
                    ssid = ssids.get(device.get("ifname"))
                    if not ssid:
                        continue
                    for address in device.get("addr_info", []):
                        local = address.get("local")
                        if isinstance(local, str):
                            networks[local] = ssid
                ap = next((device for device in devices if device.get("ifname") == "aineap0"), None)
                if ap is None:
                    self._hotspot_error = "Robot hotspot interface is missing."
                elif "UP" not in ap.get("flags", []) or ap.get("operstate") != "UP" or not ssids.get("aineap0"):
                    self._hotspot_error = "Robot hotspot is not broadcasting; its Wi-Fi interface is down."
                elif not any(address.get("local") == "10.42.77.1" and address.get("prefixlen") == 24
                             for address in ap.get("addr_info", [])):
                    self._hotspot_error = "Robot hotspot is missing its 10.42.77.1/24 address."
                else:
                    services = subprocess.run(
                        ["systemctl", "is-active", *UNITS], capture_output=True, text=True, timeout=1, check=False,
                    )
                    states = services.stdout.splitlines()
                    failed = [unit for index, unit in enumerate(UNITS)
                              if index >= len(states) or states[index] != "active"]
                    self._hotspot_error = ("Robot hotspot services are unavailable: " + ", ".join(failed)) if failed else None
            except (OSError, subprocess.SubprocessError, ValueError, TypeError, AttributeError) as exc:
                # Status still works on hosts without these Linux tools or when
                # an interface disappears while it is being inspected.
                networks = {}
                self._hotspot_error = f"Could not inspect the robot hotspot: {exc}"
            self._network_cache = networks
            self._network_cache_until = monotonic() + 5
            return dict(networks)

    async def start(self) -> None:
        async with self._lock:
            if self.enabled:
                try:
                    await self._service(True)
                except GatewayError:
                    # Keep Body Control reachable so its status can explain a
                    # broken network instead of taking its diagnostic UI down.
                    logging.getLogger(__name__).exception("Robot hotspot startup failed")

    async def set_enabled(self, enabled: bool) -> dict[str, object]:
        async with self._lock:
            if enabled != self.enabled or enabled:
                try:
                    await self._service(enabled)
                except GatewayError as exc:
                    if enabled and not self.enabled:
                        try:
                            await self._service(False)
                        except GatewayError as rollback:
                            raise GatewayError(f"{exc}; could not restore the previous Off mode: {rollback}") from exc
                    raise
                self.enabled = enabled
            try:
                self._save_setting()
            except OSError as exc:
                raise GatewayError(f"Network mode applied, but .env could not be saved: {exc}") from exc
            return await asyncio.to_thread(self.snapshot)

    async def _service(self, enabled: bool) -> None:
        error = await asyncio.to_thread(self._availability, force=True) if enabled else None
        action = ("restart" if error else "start") if enabled else "stop"
        units = (TARGET, *UNITS) if enabled and error else (TARGET, UNITS[-1]) if enabled else (TARGET,)
        try:
            process = await asyncio.create_subprocess_exec(
                "systemctl", "--no-ask-password", action, *units,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
        except OSError as exc:
            raise GatewayError(f"Could not {action} the robot hotspot: {exc}") from exc
        _, error = await process.communicate()
        if process.returncode:
            detail = error.decode(errors="replace").strip()
            raise GatewayError(f"Could not {action} the robot hotspot: {detail or ', '.join(units)}")
        with self._network_lock:
            self._network_cache_until = 0
        if enabled:
            error = await asyncio.to_thread(self._availability, force=True)
            if error:
                raise GatewayError(f"Robot hotspot activation did not restore the network: {error}")

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
