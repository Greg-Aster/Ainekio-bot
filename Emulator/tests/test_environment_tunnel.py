"""Cloudflare launch configuration and real gateway sockets over raw TCP.

Cloudflare account authentication and physical devices are not exercised.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest

import websockets


ROOT = Path(__file__).resolve().parents[2]


class EnvironmentRelayLauncherTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        base = Path(temporary.name)
        self.root = base / "checkout"
        (self.root / "Master").mkdir(parents=True)
        for name in ("start-physical-relay.sh", "gateway-env.sh"):
            shutil.copy2(ROOT / "Master" / name, self.root / "Master" / name)
        credentials = base / "credentials.json"
        credentials.write_text("{}")
        executable = base / "cloudflared"
        executable.write_text(
            "#!" + sys.executable + "\n"
            "import pathlib, sys\n"
            "args = sys.argv[1:]\n"
            "if 'rule' in args:\n"
            "    text = pathlib.Path(args[args.index('--config') + 1]).read_text()\n"
            "    if args[-1].endswith('/robot'):\n"
            "        print(next(line.strip() for line in text.splitlines() if 'service: http://' in line))\n"
            "    else:\n"
            "        print('service: http_status:404')\n"
            "elif 'run' in args:\n"
            "    print('RUN ' + ' '.join(args))\n"
        )
        executable.chmod(0o755)
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("AINEKIO_")}
        self.env.update({
            "PATH": str(base) + os.pathsep + os.environ["PATH"],
            "AINEKIO_CLOUDFLARE_TUNNEL_ID": "12345678-1234-1234-1234-123456789abc",
            "AINEKIO_CLOUDFLARE_CREDENTIALS_FILE": str(credentials),
        })

    def launch(self, *args):
        return subprocess.run(
            ["bash", str(self.root / "Master/start-physical-relay.sh"), *args],
            env=self.env, text=True, capture_output=True, timeout=10,
        )

    def configuration(self):
        return (self.root / "build/gateway/cloudflare/ainekio-robot.yml").read_text()

    def test_legacy_robot_route_retains_path_filter_and_no_tcp_route(self):
        result = self.launch("--check")
        self.assertEqual(result.returncode, 0, result.stderr)
        text = self.configuration()
        self.assertIn("hostname: robot-gateway.ainek.io\n    path: ^/robot$", text)
        self.assertIn("service: http://127.0.0.1:8790", text)
        self.assertNotIn("tcp://", text)
        self.assertTrue(text.endswith("  - service: http_status:404\n"))
        self.assertNotIn("RUN ", result.stdout)

    def test_tcp_route_uses_configured_hostname_and_gateway_port_from_env_file(self):
        (self.root / ".env").write_text(
            "AINEKIO_CLOUDFLARE_ENVIRONMENT_HOSTNAME=bridge.ainek.io\n"
            "AINEKIO_GATEWAY_PORT=9123\n"
        )
        result = self.launch("--check")
        self.assertEqual(result.returncode, 0, result.stderr)
        text = self.configuration()
        self.assertIn("hostname: bridge.ainek.io\n    service: tcp://127.0.0.1:9123", text)
        self.assertIn("service: http://127.0.0.1:9123", text)
        self.assertNotIn("8791", text)
        self.assertEqual(text.count("hostname:"), 2)

    def test_start_executes_existing_named_tunnel_with_generated_configuration(self):
        self.env["AINEKIO_CLOUDFLARE_ENVIRONMENT_HOSTNAME"] = "bridge.ainek.io"
        result = self.launch()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--no-autoupdate run " + self.env["AINEKIO_CLOUDFLARE_TUNNEL_ID"], result.stdout)
        self.assertIn("--hostname bridge.ainek.io --url 127.0.0.1:18790", result.stdout)


class EnvironmentTCPForwardingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        with socket.socket() as gateway, socket.socket() as dashboard:
            gateway.bind(("127.0.0.1", 0))
            dashboard.bind(("127.0.0.1", 0))
            self.gateway_port = gateway.getsockname()[1]
            dashboard_port = dashboard.getsockname()[1]
        env = {k: v for k, v in os.environ.items() if not k.startswith("AINEKIO_")}
        env.update({
            "PYTHONPATH": os.pathsep.join(str(ROOT / p) for p in ("Master", "Slave/software")),
            "AINEKIO_ENVIRONMENT_ADAPTER_TOKEN": "fixture-bridge-token",
            "AINEKIO_DASHBOARD_PASSWORD": "fixture-dashboard-password",
        })
        self.process = await asyncio.create_subprocess_exec(
            sys.executable, "-u", "-m", "gateway.server",
            "--host", "127.0.0.1", "--port", str(self.gateway_port),
            "--dashboard-port", str(dashboard_port), "--data-dir", self.temporary.name,
            cwd=ROOT, env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        self.addAsyncCleanup(self.stop_gateway)
        line = await asyncio.wait_for(self.process.stdout.readline(), timeout=5)
        if not line:
            self.fail((await self.process.stderr.read()).decode())
        self.forwarding_tasks = set()
        self.forwarder = await asyncio.start_server(self.forward, "127.0.0.1", 0)
        self.addAsyncCleanup(self.stop_forwarder)
        port = self.forwarder.sockets[0].getsockname()[1]
        self.uri = f"ws://127.0.0.1:{port}/environment"

    async def stop_gateway(self):
        if self.process.returncode is None:
            self.process.terminate()
        await asyncio.wait_for(self.process.communicate(), timeout=5)

    async def stop_forwarder(self):
        self.forwarder.close()
        await self.forwarder.wait_closed()
        pending = list(self.forwarding_tasks)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)

    async def forward(self, reader, writer):
        task = asyncio.current_task()
        self.forwarding_tasks.add(task)
        upstream_writer = None
        pumps = []
        try:
            upstream_reader, upstream_writer = await asyncio.open_connection("127.0.0.1", self.gateway_port)

            async def copy(source, destination):
                while data := await source.read(16384):
                    destination.write(data)
                    await destination.drain()

            pumps = [asyncio.create_task(copy(reader, upstream_writer)),
                     asyncio.create_task(copy(upstream_reader, writer))]
            await asyncio.wait(pumps, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for pump in pumps:
                pump.cancel()
            await asyncio.gather(*pumps, return_exceptions=True)
            for stream in (writer, upstream_writer):
                if stream is not None:
                    stream.close()
                    await stream.wait_closed()
            self.forwarding_tasks.discard(task)

    async def test_forwarding_preserves_adapter_authentication_and_websocket_roundtrip(self):
        async with websockets.connect(self.uri, ping_interval=None) as bridge:
            await bridge.send(json.dumps({"type": "bridge.connect", "version": 1, "token": "fixture-bridge-token"}))
            ready = json.loads(await asyncio.wait_for(bridge.recv(), timeout=2))
            self.assertEqual(ready["type"], "bridge.ready")
            self.assertEqual(ready["observation"]["adapter"], "ainekio-gateway")
            pong = await bridge.ping(b"raw-tcp-roundtrip")
            await asyncio.wait_for(pong, timeout=2)
        async with websockets.connect(self.uri, ping_interval=None) as bridge:
            await bridge.send(json.dumps({"type": "bridge.connect", "version": 1, "token": "wrong"}))
            with self.assertRaises(websockets.ConnectionClosed) as closed:
                await asyncio.wait_for(bridge.recv(), timeout=2)
            self.assertEqual(closed.exception.code, 4001)

    async def test_http_relay_headers_remain_rejected_through_tcp_forwarder(self):
        async with websockets.connect(self.uri, extra_headers={"CF-Ray": "fixture"}, ping_interval=None) as bridge:
            with self.assertRaises(websockets.ConnectionClosed) as closed:
                await asyncio.wait_for(bridge.recv(), timeout=2)
            self.assertEqual(closed.exception.code, 1008)


if __name__ == "__main__":
    unittest.main()
