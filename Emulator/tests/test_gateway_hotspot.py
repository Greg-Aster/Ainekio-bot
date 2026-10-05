"""Exercise the existing hotspot service contract without changing host networking."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
import tempfile
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from gateway.hotspot import RobotHotspot
from gateway.server.service import GatewayError


class RobotHotspotTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.env_file = Path(temporary.name) / ".env"
        self.env_file.write_text("# Keep operator settings\nSECRET='unchanged'\nexport AINEKIO_HOTSPOT='0' # robot network\n")
        self.env_file.chmod(0o640)
        self.hotspot = RobotHotspot(self.env_file, enabled=False)
        self.process = SimpleNamespace(returncode=0, communicate=AsyncMock(return_value=(b"", b"")))
        self.execute = AsyncMock(return_value=self.process)
        patcher = patch("gateway.hotspot.asyncio.create_subprocess_exec", self.execute)
        patcher.start()
        self.addCleanup(patcher.stop)

    def operations(self):
        return [call.args for call in self.execute.await_args_list]

    async def test_live_switch_persists_and_shutdown_uses_same_owner(self):
        await self.hotspot.start()
        self.execute.assert_not_awaited()
        self.assertEqual(await self.hotspot.set_enabled(True), {"hotspot": True})
        self.assertEqual(self.env_file.read_text(), "# Keep operator settings\nSECRET='unchanged'\nexport AINEKIO_HOTSPOT=1 # robot network\n")
        self.assertEqual(self.env_file.stat().st_mode & 0o777, 0o640)
        await self.hotspot.close()
        self.assertEqual(self.operations(), [
            ("systemctl", "--no-ask-password", "start", "ainekio-hotspot-dhcp.service"),
            ("systemctl", "--no-ask-password", "stop", "ainekio-hotspot-interface.service"),
        ])

    async def test_startup_and_switch_to_wifi_leave_no_second_shutdown_stop(self):
        self.hotspot = RobotHotspot(self.env_file, enabled=True)
        await self.hotspot.start()
        self.assertEqual(await self.hotspot.set_enabled(False), {"hotspot": False})
        await self.hotspot.close()
        self.assertEqual(len(self.operations()), 2)
        self.assertIn("AINEKIO_HOTSPOT=0 # robot network", self.env_file.read_text())

    async def test_failed_service_reports_error_without_saving_success(self):
        original = self.env_file.read_bytes()
        self.process.returncode = 1
        self.process.communicate.return_value = (b"", b"Unit not installed")
        with self.assertRaisesRegex(GatewayError, "Unit not installed"):
            await self.hotspot.set_enabled(True)
        self.assertFalse(self.hotspot.enabled)
        self.assertEqual(self.env_file.read_bytes(), original)

    async def test_save_failure_reports_applied_runtime_mode(self):
        with patch.object(self.hotspot, "_save_setting", side_effect=PermissionError("read-only .env")):
            with self.assertRaisesRegex(GatewayError, "mode applied, but .env could not be saved"):
                await self.hotspot.set_enabled(True)
        self.assertEqual(self.hotspot.snapshot(), {"hotspot": True})
        self.assertEqual(len(self.operations()), 1)

    async def test_overlapping_switches_preserve_requested_order_and_final_setting(self):
        entered = asyncio.Event()
        release = asyncio.Event()
        async def communicate():
            entered.set()
            await release.wait()
            return b"", b""
        self.process.communicate.side_effect = communicate
        first = asyncio.create_task(self.hotspot.set_enabled(True))
        await entered.wait()
        second = asyncio.create_task(self.hotspot.set_enabled(False))
        release.set()
        await asyncio.gather(first, second)
        self.assertEqual([operation[2] for operation in self.operations()], ["start", "stop"])
        self.assertFalse(self.hotspot.enabled)
        self.assertIn("AINEKIO_HOTSPOT=0 # robot network", self.env_file.read_text())

    async def test_new_setting_is_appended_without_touching_other_fields(self):
        self.env_file.write_text("SECRET='unchanged'")
        await self.hotspot.set_enabled(False)
        self.execute.assert_not_awaited()
        self.assertEqual(self.env_file.read_text(), "SECRET='unchanged'\nAINEKIO_HOTSPOT=0\n")

    def test_active_network_names_distinguish_hotspot_and_uplink_and_are_cached(self):
        addresses = json.dumps([
            {"ifname": "aineap0", "addr_info": [{"local": "10.42.77.1"}]},
            {"ifname": "wlan0", "addr_info": [{"local": "192.168.0.88"}, {"local": "fe80::1234"}]},
            {"ifname": "lo", "addr_info": [{"local": "127.0.0.1"}]},
        ])
        wireless = "phy#0\n\tInterface aineap0\n\t\tssid Ainekio-Robot\n\tInterface wlan0\n\t\tssid Home: Wi-Fi\n"
        results = [subprocess.CompletedProcess([], 0, addresses), subprocess.CompletedProcess([], 0, wireless)]
        with patch("gateway.hotspot.subprocess.run", side_effect=results) as execute:
            names = self.hotspot.connection_networks()
            self.assertEqual(names, {
                "10.42.77.1": "Ainekio-Robot", "192.168.0.88": "Home: Wi-Fi", "fe80::1234": "Home: Wi-Fi",
            })
            self.assertEqual(self.hotspot.connection_networks(), names)
            self.assertEqual(execute.call_count, 2)
        self.execute.assert_not_awaited()

    def test_network_inspection_failure_does_not_reuse_an_old_name(self):
        self.hotspot._network_cache = {"10.42.77.1": "Old network"}
        for failure in (FileNotFoundError(), subprocess.TimeoutExpired("ip", 1)):
            self.hotspot._network_cache_until = 0
            with patch("gateway.hotspot.subprocess.run", side_effect=failure):
                self.assertEqual(self.hotspot.connection_networks(), {})


if __name__ == "__main__":
    unittest.main()
