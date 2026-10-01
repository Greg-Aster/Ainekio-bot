"""Exercise deployment checks without opening a listener or contacting a robot."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


SOURCE = Path(__file__).resolve().parents[2]


class PhysicalGatewayLauncherTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "checkout with spaces 100%"
        (self.root / "Master").mkdir(parents=True)
        (self.root / "Slave").mkdir()
        for name in ("start-physical-gateway.sh", "ainekio-gateway.service"):
            shutil.copy2(SOURCE / "Master" / name, self.root / "Master" / name)
        (self.root / "Master/gateway").symlink_to(SOURCE / "Master/gateway", target_is_directory=True)
        (self.root / "Slave/software").symlink_to(SOURCE / "Slave/software", target_is_directory=True)
        (self.root / ".venv/bin").mkdir(parents=True)
        # Preserve the real venv interpreter path instead of resolving its symlink.
        interpreter = SOURCE / ".venv/bin/python3"
        if not interpreter.exists():
            interpreter = Path(sys.executable)
        wrapper = self.root / ".venv/bin/python3"
        wrapper.write_text(f'#!/bin/sh\nexec "{interpreter}" "$@"\n')
        wrapper.chmod(0o755)
        self.bin = self.root / "test-bin"
        self.bin.mkdir()
        self.marker = self.root / "unexpected-service-start"
        for name in ("avahi-publish-service", "python3", "systemctl"):
            executable = self.bin / name
            executable.write_text(f'#!/bin/sh\ntouch "{self.marker}"\nexit 99\n')
            executable.chmod(0o755)
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("AINEKIO_")}
        self.env.update({
            "PATH": str(self.bin) + os.pathsep + os.environ["PATH"],
            "XDG_CONFIG_HOME": str(self.root / "user-config"),
            "AINEKIO_ENVIRONMENT_ADAPTER_TOKEN": "fixture-environment-secret",
            "AINEKIO_ROBOT_TOKEN": "fixture-robot-secret",
        })

    def run_launcher(self, *args):
        result = subprocess.run(
            ["bash", str(self.root / "Master/start-physical-gateway.sh"), *args],
            env=self.env, capture_output=True, text=True, timeout=15,
        )
        self.assertFalse(self.marker.exists(), result.stdout + result.stderr)
        for secret in ("fixture-environment-secret", "fixture-robot-secret"):
            self.assertNotIn(secret, result.stdout + result.stderr)
        return result

    def test_check_uses_repo_venv_without_starting_or_writing_runtime(self):
        result = self.run_launcher("--check")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Gateway prerequisites passed", result.stdout)
        self.assertFalse((self.root / "build").exists())

    def test_missing_adapter_token_is_actionable(self):
        del self.env["AINEKIO_ENVIRONMENT_ADAPTER_TOKEN"]
        result = self.run_launcher("--check")
        self.assertEqual(result.returncode, 2)
        self.assertIn("AINEKIO_ENVIRONMENT_ADAPTER_TOKEN is required", result.stderr)

    def test_first_launch_needs_robot_pairing(self):
        del self.env["AINEKIO_ROBOT_TOKEN"]
        result = self.run_launcher("--check")
        self.assertEqual(result.returncode, 2)
        self.assertIn("First launch requires AINEKIO_ROBOT_TOKEN", result.stderr)

    def test_existing_robot_store_does_not_require_reseeding(self):
        del self.env["AINEKIO_ROBOT_TOKEN"]
        data = self.root / "existing-runtime"
        data.mkdir()
        (data / "robot-tokens.json").write_text("{}")
        self.env["AINEKIO_GATEWAY_DATA_DIR"] = str(data)
        result = self.run_launcher("--check")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_explicit_environment_retains_precedence_over_dotenv(self):
        (self.root / ".env").write_text("AINEKIO_ENVIRONMENT_ADAPTER_TOKEN=''\n")
        self.assertEqual(self.run_launcher("--check").returncode, 0)

    def test_missing_interpreter_has_no_startup_side_effect(self):
        self.env["AINEKIO_PYTHON"] = str(self.root / "missing-python")
        result = self.run_launcher("--check")
        self.assertEqual(result.returncode, 2)
        self.assertIn("Gateway Python is not executable", result.stderr)

    def test_check_rejects_runtime_arguments(self):
        result = self.run_launcher("--check", "--port", "9000")
        self.assertEqual(result.returncode, 2)

    def test_installer_uses_checkout_path_and_does_not_activate_service(self):
        del self.env["AINEKIO_ROBOT_TOKEN"]
        del self.env["AINEKIO_ENVIRONMENT_ADAPTER_TOKEN"]
        result = self.run_launcher("--install-service")
        self.assertEqual(result.returncode, 0, result.stderr)
        unit = self.root / "user-config/systemd/user/ainekio-gateway.service"
        content = unit.read_text()
        escaped = str(self.root).replace("%", "%%")
        self.assertIn(f'WorkingDirectory={escaped}\n', content)
        self.assertIn(f'ExecStart="{escaped}/Master/start-physical-gateway.sh"', content)
        self.assertNotIn("%h/Ainekio", content)
        self.assertFalse((unit.parent / "default.target.wants").exists())
        self.assertEqual(self.run_launcher("--install-service").returncode, 0)
        self.assertEqual(unit.read_text(), content)

    @unittest.skipUnless(shutil.which("systemd-analyze"), "systemd unit validator unavailable")
    def test_generated_unit_passes_systemd_parser(self):
        result = self.run_launcher("--install-service")
        self.assertEqual(result.returncode, 0, result.stderr)
        unit = self.root / "user-config/systemd/user/ainekio-gateway.service"
        result = subprocess.run(
            ["systemd-analyze", "--user", "verify", str(unit)],
            env=self.env, capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_installer_preserves_unmanaged_service(self):
        unit = self.root / "user-config/systemd/user/ainekio-gateway.service"
        unit.parent.mkdir(parents=True)
        unit.write_text("existing owner configuration\n")
        result = self.run_launcher("--install-service")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(unit.read_text(), "existing owner configuration\n")


if __name__ == "__main__":
    unittest.main()
