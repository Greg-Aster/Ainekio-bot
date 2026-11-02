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
        self.radio_up = True
        self.services_active = True
        network_patcher = patch("gateway.hotspot.subprocess.run", side_effect=self.inspect_network)
        network_patcher.start()
        self.addCleanup(network_patcher.stop)

    def inspect_network(self, command, **kwargs):
        if command[0] == "ip":
            output = json.dumps([{"ifname": "aineap0", "flags": ["UP"],
                                  "operstate": "UP" if self.radio_up else "DOWN",
                                  "addr_info": [{"local": "10.42.77.1", "prefixlen": 24}]}])
        elif command[0] == "iw":
            output = "phy#0\n\tInterface aineap0\n\t\ttype AP\n"
            if self.radio_up:
                output += "\t\tssid Fixture robot\n"
        else:
            self.assertEqual(command[:2], ["systemctl", "is-active"])
            output = "active\nactive\n" + ("active\n" if self.services_active else "failed\n")
        return subprocess.CompletedProcess(command, 0, output)

    def operations(self):
        return [call.args for call in self.execute.await_args_list]

    async def test_live_switch_persists_without_stopping_hotspot_on_shutdown(self):
        await self.hotspot.start()
        self.execute.assert_not_awaited()
        self.assertEqual(await self.hotspot.set_enabled(True), {"hotspot": True, "available": True, "error": None})
        self.assertEqual(self.env_file.read_text(), "# Keep operator settings\nSECRET='unchanged'\nexport AINEKIO_HOTSPOT=1 # robot network\n")
        self.assertEqual(self.env_file.stat().st_mode & 0o777, 0o640)
        self.assertEqual(self.operations(), [
            ("systemctl", "--no-ask-password", "start", "ainekio-hotspot.target", "ainekio-hotspot-dhcp.service"),
        ])

    async def test_startup_and_switch_to_wifi_leave_no_second_shutdown_stop(self):
        self.hotspot = RobotHotspot(self.env_file, enabled=True)
        await self.hotspot.start()
        self.assertEqual(await self.hotspot.set_enabled(False), {"hotspot": False, "available": False, "error": None})
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
        self.assertEqual(self.hotspot.snapshot(), {"hotspot": True, "available": True, "error": None})
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

    async def test_start_repairs_sleep_stale_active_services_and_repeated_on_repairs_again(self):
        self.hotspot.enabled = True
        for _ in range(2):
            self.radio_up = False
            self.assertIn("not broadcasting", self.hotspot.snapshot()["error"])
            async def restored():
                self.radio_up = True
                return b"", b""
            self.process.communicate.side_effect = restored
            if not self.execute.await_count:
                await self.hotspot.start()
            else:
                await self.hotspot.set_enabled(True)
            self.assertTrue(self.hotspot.snapshot()["available"])
            self.assertEqual(self.operations()[-1], (
                "systemctl", "--no-ask-password", "restart", "ainekio-hotspot.target", "ainekio-hotspot-interface.service",
                "ainekio-hotspot.service", "ainekio-hotspot-dhcp.service",
            ))
            self.hotspot._network_cache_until = 0

    async def test_successful_systemctl_with_dead_radio_is_not_reported_or_saved_as_success(self):
        self.radio_up = False
        original = self.env_file.read_bytes()
        with self.assertRaisesRegex(GatewayError, "not broadcasting"):
            await self.hotspot.set_enabled(True)
        self.assertEqual(self.env_file.read_bytes(), original)
        self.assertFalse(self.hotspot.enabled)
        self.assertEqual(self.operations()[-1], ("systemctl", "--no-ask-password", "stop", "ainekio-hotspot.target"))

    async def test_failed_start_keeps_diagnostic_dashboard_available_and_logs_error(self):
        self.hotspot.enabled = True
        self.radio_up = False
        self.process.returncode = 1
        self.process.communicate.return_value = (b"", b"Radio unavailable")
        with self.assertLogs("gateway.hotspot", level="ERROR") as logs:
            await self.hotspot.start()
        self.assertIn("Radio unavailable", "\n".join(logs.output))
        self.assertFalse(self.hotspot.snapshot()["available"])
        self.assertIn("not broadcasting", self.hotspot.snapshot()["error"])

    def test_running_radio_with_failed_dhcp_is_unavailable(self):
        self.hotspot.enabled = True
        self.services_active = False
        status = self.hotspot.snapshot()
        self.assertFalse(status["available"])
        self.assertIn("ainekio-hotspot-dhcp.service", status["error"])


if __name__ == "__main__":
    unittest.main()
