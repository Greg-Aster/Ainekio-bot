"""Exercise deployment checks without opening a listener or contacting a robot."""
from __future__ import annotations

import os
import json
import pty
import shlex
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
        for name in ("start-physical-gateway.sh", "stop-physical-gateway.sh", "gateway-env.sh", "ainekio-gateway.service"):
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

    def prepare_start(self):
        """Only the real gateway subprocess is replaced; no listener can start."""
        self.env.update({"AINEKIO_LOCAL_DISCOVERY": "0", "AINEKIO_HOTSPOT": "0"})
        self.gateway_args = self.root / "gateway-args"
        wrapper = self.root / ".venv/bin/python3"
        wrapper.write_text(
            '#!/bin/sh\nif [ "$1" = "-m" ] && [ "$2" = "gateway.server" ]; then\n'
            + 'printf "%s\\n" "$@" > ' + shlex.quote(str(self.gateway_args)) + '\nexit 0\nfi\n'
            + 'exec ' + shlex.quote(sys.executable) + ' "$@"\n')
        for name, body in [("ss", "exit 0"), ("hostname", "echo 192.0.2.20"),
                           ("ip", "echo '1.1.1.1 via 192.0.2.1 dev test src 192.0.2.20'")]:
            exe = self.bin / name
            exe.write_text('#!/bin/sh\n' + body + '\n')
            exe.chmod(0o755)
        return self.root / "build/gateway/physical/dashboard-connection.json"

    def interactive_start(self, answer=None):
        master, slave = pty.openpty()
        try:
            child = subprocess.Popen(["bash", str(self.root / "Master/start-physical-gateway.sh")],
                                     env=self.env, stdin=slave, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if answer is not None:
                os.write(master, answer.encode())
            try:
                stdout, stderr = child.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.communicate()
                raise
            self.assertFalse(self.marker.exists())
            return subprocess.CompletedProcess(child.args, child.returncode, stdout, stderr)
        finally:
            os.close(master)
            os.close(slave)

    def test_interactive_lan_choice_persists_and_reaches_gateway(self):
        setting = self.prepare_start()
        result = self.interactive_start("2\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("How will you open Body Control?", result.stderr)
        self.assertIn("http://192.0.2.20:8791/", result.stdout)
        self.assertEqual(json.loads(setting.read_text())["mode"], "lan")
        args = self.gateway_args.read_text().splitlines()
        self.assertEqual(args[args.index("--dashboard-host") + 1], "0.0.0.0")
        # Service launches must immediately reuse the same choice, with no prompt.
        result = self.run_launcher()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("Choose 1", result.stderr)
        self.assertIn("Dashboard access:   lan", result.stdout)

    def test_timeout_and_enter_reuse_saved_cloudflare_without_starting_a_tunnel(self):
        setting = self.prepare_start()
        self.env["AINEKIO_DASHBOARD_PUBLIC_URL"] = "https://another-machine.example/"
        result = self.interactive_start("3\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        del self.env["AINEKIO_DASHBOARD_PUBLIC_URL"]
        saved = setting.read_text()
        self.env["AINEKIO_DASHBOARD_CHOICE_TIMEOUT"] = "0.15"
        result = self.interactive_start()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Cloudflare [saved/default]", result.stderr)
        self.assertIn("https://another-machine.example/", result.stdout)
        self.assertEqual(setting.read_text(), saved)
        self.env["AINEKIO_DASHBOARD_CHOICE_TIMEOUT"] = "10"
        result = self.interactive_start("\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(setting.read_text(), saved)
        args = self.gateway_args.read_text().splitlines()
        self.assertEqual(args[args.index("--dashboard-host") + 1], "127.0.0.1")

    def test_explicit_choice_bypasses_prompt_and_preserves_host_override(self):
        setting = self.prepare_start()
        self.env.update({"AINEKIO_DASHBOARD_CONNECTION": "local", "AINEKIO_DASHBOARD_HOST": "192.0.2.20"})
        result = self.interactive_start()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("Choose 1", result.stderr)
        args = self.gateway_args.read_text().splitlines()
        self.assertEqual(args[args.index("--dashboard-host") + 1], "192.0.2.20")
        self.assertEqual(json.loads(setting.read_text())["mode"], "local")

    def test_missing_cloudflare_address_or_invalid_input_does_not_save_or_launch(self):
        setting = self.prepare_start()
        for answer in ("3\n", "wrong\n"):
            result = self.interactive_start(answer)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(setting.exists())
            self.assertFalse(self.gateway_args.exists())

    def test_check_does_not_prompt_or_rewrite_saved_connection(self):
        setting = self.prepare_start()
        setting.parent.mkdir(parents=True)
        setting.write_text('{"mode":"lan"}')
        result = self.run_launcher("--check")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("Choose 1", result.stderr)
        self.assertEqual(setting.read_text(), '{"mode":"lan"}')
        self.assertFalse(self.gateway_args.exists())

    def test_check_uses_repo_venv_without_starting_or_writing_runtime(self):
        result = self.run_launcher("--check")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Gateway prerequisites passed", result.stdout)
        self.assertFalse((self.root / "build").exists())

    def test_standalone_body_control_does_not_require_metahuman(self):
        del self.env["AINEKIO_ENVIRONMENT_ADAPTER_TOKEN"]
        result = self.run_launcher("--check")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("standalone Body Control", result.stdout)

    def test_recognition_still_requires_authenticated_bridge(self):
        del self.env["AINEKIO_ENVIRONMENT_ADAPTER_TOKEN"]
        self.env["AINEKIO_VISION_URL"] = "https://vision.example/v1/chat/completions"
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
        from gateway.security import RobotTokenStore
        RobotTokenStore(data / "robot-tokens.json").set("robot", "fixture-robot-secret")
        self.env["AINEKIO_GATEWAY_DATA_DIR"] = str(data)
        result = self.run_launcher("--check")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_existing_invalid_store_is_reported_before_start(self):
        data = self.root / "existing-runtime"
        data.mkdir()
        (data / "robot-tokens.json").write_text("{}")
        (data / "robot-tokens.json").chmod(0o600)
        self.env["AINEKIO_GATEWAY_DATA_DIR"] = str(data)
        result = self.run_launcher("--check")
        self.assertEqual(result.returncode, 2)
        self.assertIn("unsupported schema", result.stderr)

    def test_pairing_transfer_uses_saved_credentials_and_not_machine_paths(self):
        from gateway.security import DashboardPasswordStore, RobotTokenStore
        original = self.root / "original runtime"
        RobotTokenStore(original / "robot-tokens.json").set("robot", "fixture-robot-secret")
        DashboardPasswordStore(original / "dashboard-auth.json").set_password("fixture-dashboard-password")
        self.env["AINEKIO_GATEWAY_DATA_DIR"] = str(original)
        bundle = self.root / "portable pairing.json"
        result = self.run_launcher("--export-pairing", str(bundle))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("fixture-dashboard-password", result.stdout + result.stderr)
        self.assertNotIn(str(original), bundle.read_text())
        destination = self.root / "new computer runtime"
        self.env["AINEKIO_GATEWAY_DATA_DIR"] = str(destination)
        del self.env["AINEKIO_ROBOT_TOKEN"]
        del self.env["AINEKIO_ENVIRONMENT_ADAPTER_TOKEN"]
        result = self.run_launcher("--import-pairing", str(bundle))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(DashboardPasswordStore(destination / "dashboard-auth.json").verify("fixture-dashboard-password"))
        self.assertTrue(RobotTokenStore(destination / "robot-tokens.json").matches("robot", "fixture-robot-secret"))
        self.assertEqual(self.run_launcher("--check").returncode, 0)
        self.assertFalse((self.root / "build").exists())

    def test_pairing_filename_required_and_existing_export_preserved(self):
        self.assertEqual(self.run_launcher("--import-pairing").returncode, 2)
        self.assertEqual(self.run_launcher("--export-pairing", "one", "two").returncode, 2)

    def test_stop_reads_same_dotenv_runtime_as_start_without_touching_other_gateway(self):
        data = self.root / "custom runtime"
        data.mkdir()
        (data / "physical-gateway.pid").write_text("99999999\n")
        (self.root / ".env").write_text(f"AINEKIO_GATEWAY_DATA_DIR='{data}'\n")
        (self.bin / "systemctl").write_text("#!/bin/sh\nexit 1\n")
        result = subprocess.run(["bash", str(self.root / "Master/stop-physical-gateway.sh")],
                                env=self.env, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((data / "physical-gateway.pid").exists())
        self.assertFalse(self.marker.exists())

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
