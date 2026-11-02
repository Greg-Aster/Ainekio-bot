"""Test hotspot provisioning without configuring radios or starting services."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


SOURCE = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("robot_hotspot_installer", SOURCE / "Master/install-robot-hotspot.py")
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class RobotHotspotInstallationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.credentials = self.root / "credentials"

    def credentials_file(self, content):
        self.credentials.write_text(content)
        self.credentials.chmod(0o600)
        return self.credentials

    def configuration(self):
        ssid, credential = installer.read_credentials(self.credentials_file(
            "ssid=Fixture robot\nwpa_passphrase=fixture secret\n"
            "interface=desktop0\nchannel=11\ninclude=/untrusted/config\n"))
        return installer.render_configuration("wlan0", "greggles", "ec:b5:0a:98:34:fb", ssid, credential, 1)

    def test_reuses_only_network_identity_and_preserves_uplink(self):
        files = self.configuration()
        hostapd = files["etc/ainekio-network/hostapd.conf"][0]
        self.assertIn("ssid=Fixture robot\n", hostapd)
        self.assertIn("wpa_passphrase=fixture secret\n", hostapd)
        self.assertNotIn("desktop0", hostapd)
        self.assertNotIn("include=", hostapd)
        unit = files["etc/systemd/system/ainekio-hotspot-interface.service"][0]
        self.assertIn("iw dev wlan0 interface add aineap0", unit)
        self.assertIn("ip address add 10.42.77.1/24 dev aineap0", unit)
        self.assertNotIn("connection up", unit)
        self.assertNotIn("connection down", unit)
        self.assertIn("addr ee:b5:0a:98:34:7b", unit)
        for relative, (content, _) in files.items():
            if relative.endswith((".service", ".target")):
                self.assertNotIn("WantedBy=", content)
        self.assertIn("match-device=interface-name:aineap0\nmanaged=0\n",
                      files["etc/NetworkManager/conf.d/80-ainekio-hotspot.conf"][0])
        self.assertIn("OriginalName=aineap0\n", files["etc/systemd/network/10-ainekio-hotspot.link"][0])
        self.assertIn("NamePolicy=\nName=aineap0\n", files["etc/systemd/network/10-ainekio-hotspot.link"][0])
        self.assertIn("ExecStopPost=-/usr/sbin/iw dev aineap0 del", unit)

    def test_wpa_key_and_invalid_credentials(self):
        key = "ab" * 32
        self.assertEqual(installer.read_credentials(self.credentials_file(
            f"ssid=Robot\nwpa_psk={key}\n")), ("Robot", "wpa_psk=" + key))
        for content in ("ssid=Robot\nwpa_passphrase=short\n",
                        "ssid=Robot\nwpa_psk=not-hex\n",
                        "ssid=Robot\nwpa_passphrase=long enough\nwpa_psk=" + key,
                        "ssid=Robot\nssid=Duplicate\nwpa_passphrase=long enough\n",
                        "ssid=" + "é" * 17 + "\nwpa_passphrase=long enough\n"):
            with self.subTest(content=content), self.assertRaises(ValueError):
                installer.read_credentials(self.credentials_file(content))
        self.credentials.chmod(0o644)
        with self.assertRaisesRegex(ValueError, "owner-only"):
            installer.read_credentials(self.credentials)

    def test_install_is_repeatable_and_credentials_remain_private(self):
        files = self.configuration()
        installer.install_files(self.root, files)
        installer.install_files(self.root, files)
        for relative, (content, mode) in files.items():
            path = self.root / relative
            self.assertEqual(path.read_text(), content)
            self.assertEqual(path.stat().st_mode & 0o777, mode)
        self.assertEqual((self.root / "etc/ainekio-network").stat().st_mode & 0o777, 0o700)

    def test_conflicting_owner_or_symlink_is_preserved_before_any_changes(self):
        files = self.configuration()
        destination = self.root / "etc/systemd/system/ainekio-hotspot.service"
        destination.parent.mkdir(parents=True)
        destination.write_text("Desktop owner's configuration\n")
        with self.assertRaisesRegex(ValueError, "unmanaged"):
            installer.install_files(self.root, files)
        self.assertEqual(destination.read_text(), "Desktop owner's configuration\n")
        self.assertFalse((self.root / "etc/ainekio-network").exists())
        destination.unlink()
        destination.symlink_to(self.root / "another owner's file")
        with self.assertRaisesRegex(ValueError, "unmanaged"):
            installer.install_files(self.root, files)
        self.assertTrue(destination.is_symlink())

    def test_only_named_operator_can_start_stop_restart_specific_hotspot_units(self):
        files = self.configuration()
        policy = files["etc/polkit-1/rules.d/49-ainekio-hotspot.rules"][0]
        self.assertIn('subject.user === "greggles"', policy)
        self.assertIn('["start", "stop", "restart"]', policy)
        for unit in installer.UNITS:
            self.assertIn('"' + unit + '"', policy)
        hostapd = files["etc/systemd/system/ainekio-hotspot.service"][0]
        dhcp = files["etc/systemd/system/ainekio-hotspot-dhcp.service"][0]
        for unit in (hostapd, dhcp):
            self.assertIn("PartOf=ainekio-hotspot-interface.service", unit)
        self.assertIn("interface=aineap0", files["etc/ainekio-network/dnsmasq.conf"][0])
        self.assertIn("port=0", files["etc/ainekio-network/dnsmasq.conf"][0])
        self.assertIn("--user=dnsmasq", dhcp)
        interface = files["etc/systemd/system/ainekio-hotspot-interface.service"][0]
        self.assertIn("Wants=ainekio-hotspot.service ainekio-hotspot-dhcp.service", interface)
        self.assertIn("PartOf=ainekio-hotspot.target", interface)
        self.assertIn("Wants=ainekio-hotspot-interface.service", files["etc/systemd/system/ainekio-hotspot.target"][0])
        self.assertIn("Type=forking", hostapd)
        self.assertIn("hostapd -B -P /run/ainekio-hotspot/hostapd.pid", hostapd)

    def test_recovery_hooks_route_only_resume_and_selected_uplink_events_to_existing_owner(self):
        files = self.configuration()
        recorder = self.root / "systemctl"
        calls = self.root / "calls"
        recorder.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "' + str(calls) + '"\n')
        recorder.chmod(0o755)
        hooks = {
            "usr/lib/systemd/system-sleep/ainekio-hotspot": [
                ("pre", "suspend"), ("post", "suspend"), ("post", "hibernate"),
            ],
            "etc/NetworkManager/dispatcher.d/80-ainekio-hotspot": [
                ("aineap0", "up"), ("wlan0", "down"), ("wlan1", "up"), ("wlan0", "up"),
            ],
        }
        expected = 0
        for relative, events in hooks.items():
            content, mode = files[relative]
            self.assertEqual(mode, 0o755)
            hook = self.root / Path(relative).name
            hook.write_text(content.replace("/usr/bin/systemctl", str(recorder)))
            for event in events:
                subprocess.run(["sh", str(hook), *event], check=True)
                expected += int(event[0] == "post" or event == ("wlan0", "up"))
                actual = calls.read_text().splitlines() if calls.exists() else []
                self.assertEqual(actual, ["--no-block try-restart ainekio-hotspot.target"] * expected)
        # Off is preserved by try-restart rather than an unconditional start.
        self.assertEqual(expected, 3)

    def test_unmanaged_executable_hook_is_not_adopted_by_its_shebang(self):
        files = self.configuration()
        destination = self.root / "usr/lib/systemd/system-sleep/ainekio-hotspot"
        destination.parent.mkdir(parents=True)
        destination.write_text("#!/bin/sh\necho existing owner\n")
        with self.assertRaisesRegex(ValueError, "unmanaged"):
            installer.install_files(self.root, files)

    def test_invalid_radio_arguments_reject_and_hyphenated_device_is_escaped(self):
        for interface, mac, channel in (("../wlan0", "00:11:22:33:44:55", 1),
                                        ("aineap0", "00:11:22:33:44:55", 1),
                                        ("wlan0", "invalid", 1),
                                        ("wlan0", "00:11:22:33:44:55", 36)):
            with self.subTest(interface=interface, mac=mac, channel=channel), self.assertRaises(ValueError):
                installer.render_configuration(interface, "greggles", mac, "Robot", "wpa_passphrase=fixture secret", channel)
        files = installer.render_configuration("wl-test", "greggles", "00:11:22:33:44:55",
                                               "Robot", "wpa_passphrase=fixture secret", 1)
        self.assertIn("devices-wl\\x2dtest.device", files["etc/systemd/system/ainekio-hotspot-interface.service"][0])

    @unittest.skipUnless(shutil.which("systemd-analyze") and shutil.which("hostapd"), "systemd/hostapd unavailable")
    def test_units_and_dhcp_config_pass_installed_parsers(self):
        files = self.configuration()
        paths = []
        for relative, (content, _) in files.items():
            if relative.endswith((".service", ".target")):
                path = self.root / Path(relative).name
                path.write_text(content)
                paths.append(str(path))
        result = subprocess.run(["systemd-analyze", "verify", *paths], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        config = self.root / "dnsmasq.conf"
        config.write_text(files["etc/ainekio-network/dnsmasq.conf"][0])
        result = subprocess.run(["dnsmasq", "--test", "--conf-file=" + str(config)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
