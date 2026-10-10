from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from gateway.environment_adapter import EnvironmentAdapter, EnvironmentAdapterConfig
from gateway.perception import VisionBackend, parse_recognition
from gateway.plugins import CameraFramePlugin
from gateway.server.service import GatewayConnection, GatewayService, GatewayServiceConfig
from protocol.binary_helpers import CAMERA_JPEG_FRAME_TYPE
from protocol.control_v1 import BODY_CAPABILITIES_FEATURE, BODY_COMMANDS_FEATURE, COMMAND_DEADLINE_FEATURE, LOCOMOTION_FEATURE, WALK_STEERING_FEATURE


JPEG = b"\xff\xd8\xff\xd9"
SCENE = {"summary": "Small metal objects on a table", "objects": [
    {"label": "keys", "box": {"x": 0.4, "y": 0.5, "width": 0.002, "height": 0.003}},
], "uncertainties": ["Identity of the keys is unverified"]}


class RecognitionBackendTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.certificates = tempfile.TemporaryDirectory()
        cls.certificate = Path(cls.certificates.name) / "vision.crt"
        cls.private_key = Path(cls.certificates.name) / "vision.key"
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
            "-days", "1", "-keyout", str(cls.private_key), "-out", str(cls.certificate),
            "-subj", "/CN=vision.test", "-addext", "subjectAltName=DNS:vision.test"],
            check=True, capture_output=True)
        cls.addClassCleanup(cls.certificates.cleanup)

    def setUp(self):
        self.requests = []
        self.result = {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(SCENE)}}]}
        self.status = 200
        self.delay = 0
        self.trickle = False
        self.length_extra = 0
        self.required_authorization = None
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                owner.requests.append((self.path, dict(self.headers), json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
                if owner.delay:
                    time.sleep(owner.delay)
                data = json.dumps(owner.result).encode()
                status = owner.status
                if owner.required_authorization and self.headers.get("Authorization") != owner.required_authorization:
                    status = 401
                self.send_response(status)
                if status == 302:
                    self.send_header("Location", "https://unconfigured.invalid/v1/chat/completions")
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data) + owner.length_extra))
                self.end_headers()
                try:
                    if owner.trickle:
                        for byte in data:
                            self.wfile.write(bytes([byte]))
                            self.wfile.flush()
                            time.sleep(0.01)
                    else:
                        self.wfile.write(data)
                except (BrokenPipeError, ConnectionResetError, ssl.SSLEOFError):
                    pass

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.endpoint = f"http://127.0.0.1:{self.server.server_port}/v1/chat/completions"

    async def remote_backend(self, *, api_key="fixture-key", timeout_s=2.0):
        """Real TLS transport to a simulated remote host, no external images."""
        await asyncio.to_thread(self.server.shutdown)
        self.server.server_close()
        self.thread.join(timeout=1)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self.server.RequestHandlerClass)
        self.server.daemon_threads = True
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(self.certificate, self.private_key)
        self.server.socket = context.wrap_socket(self.server.socket, server_side=True)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.enterContext(patch.dict(os.environ, {"SSL_CERT_FILE": str(self.certificate)}))
        resolve = socket.getaddrinfo

        def resolve_fixture(host, *args, **kwargs):
            return resolve("127.0.0.1" if host == "vision.test" else host, *args, **kwargs)

        self.enterContext(patch("socket.getaddrinfo", side_effect=resolve_fixture))
        self.required_authorization = "Bearer fixture-key"
        return VisionBackend(f"https://vision.test:{self.server.server_port}/v1/chat/completions",
                             "fixture-vision", api_key=api_key, timeout_s=timeout_s)

    async def asyncTearDown(self):
        await asyncio.to_thread(self.server.shutdown)
        self.server.server_close()
        self.thread.join(timeout=1)

    async def test_real_http_backend_preserves_image_and_uncertainty_without_inventing_scores(self):
        backend = VisionBackend(self.endpoint, "fixture-vision", api_key="fixture-key")
        result = await asyncio.to_thread(backend, JPEG)
        path, headers, request = self.requests[0]
        self.assertEqual(path, "/v1/chat/completions")
        self.assertEqual(headers["Authorization"], "Bearer fixture-key")
        self.assertEqual(request["model"], "fixture-vision")
        self.assertFalse(request["stream"])
        image = request["messages"][0]["content"][1]["image_url"]["url"]
        self.assertEqual(base64.b64decode(image.split(",")[1]), JPEG)
        self.assertEqual(result.objects[0].label, "keys")
        self.assertIsNone(result.objects[0].score)
        self.assertEqual(result.objects[0].box, (0.4, 0.5, 0.002, 0.003))
        self.assertEqual(list(result.uncertainties), SCENE["uncertainties"])

    def test_configured_remote_https_endpoint_uses_authenticated_transport(self):
        backend = VisionBackend("https://vision.example:8443/v1/chat/completions",
                                    "served-vision", api_key="fixture-key")
        self.assertEqual((backend.host, backend.port, backend.path),
                         ("vision.example", 8443, "/v1/chat/completions"))

    async def test_remote_https_success_preserves_authorization_and_image(self):
        backend = await self.remote_backend()
        result = await asyncio.to_thread(backend, JPEG)
        path, headers, request = self.requests[0]
        self.assertEqual(path, "/v1/chat/completions")
        self.assertEqual(headers["Authorization"], "Bearer fixture-key")
        self.assertEqual(request["model"], "fixture-vision")
        encoded = request["messages"][0]["content"][1]["image_url"]["url"]
        self.assertEqual(base64.b64decode(encoded.split(",")[1]), JPEG)
        self.assertEqual(result.objects[0].label, "keys")

    async def test_remote_certificate_must_be_trusted_before_images_are_sent(self):
        backend = await self.remote_backend()
        with patch.dict(os.environ, {"SSL_CERT_FILE": "/nonexistent/vision-ca.pem"}), self.assertRaises(ssl.SSLCertVerificationError):
            await asyncio.to_thread(backend, JPEG)
        self.assertEqual(self.requests, [])

    async def test_tls_hostname_must_match_before_images_are_sent(self):
        await self.remote_backend()
        wrong_host = VisionBackend(f"https://127.0.0.1:{self.server.server_port}/v1/chat/completions",
                                   "fixture", api_key="fixture-key")
        with self.assertRaises(ssl.SSLCertVerificationError):
            await asyncio.to_thread(wrong_host, JPEG)
        self.assertEqual(self.requests, [])

    async def test_remote_authentication_failure_is_explicit_without_leaking_key(self):
        backend = await self.remote_backend(api_key="wrong-secret")
        with self.assertRaisesRegex(ValueError, "HTTP 401") as caught:
            await asyncio.to_thread(backend, JPEG)
        self.assertNotIn("wrong-secret", str(caught.exception))
        self.status, self.required_authorization = 403, None
        with self.assertRaisesRegex(ValueError, "HTTP 403"):
            await asyncio.to_thread(backend, JPEG)

    async def test_remote_timeout_has_a_bounded_failure(self):
        backend = await self.remote_backend(timeout_s=0.1)
        self.delay = 0.2
        started = time.monotonic()
        with self.assertRaises(TimeoutError):
            await asyncio.to_thread(backend, JPEG)
        self.assertLess(time.monotonic() - started, 0.4)

    async def test_remote_invalid_responses_and_redirects_are_not_observations(self):
        backend = await self.remote_backend()
        for invalid in ({"choices": []}, {"choices": [{"finish_reason": "stop", "message": {"content": "not JSON"}}]},
                        {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps({**SCENE, "action": "walk"})}}]}):
            self.result = invalid
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                await asyncio.to_thread(backend, JPEG)
        before = len(self.requests)
        self.status = 302
        with self.assertRaisesRegex(ValueError, "HTTP 302"):
            await asyncio.to_thread(backend, JPEG)
        self.assertEqual(len(self.requests), before + 1)

    def test_remote_endpoint_validation_precedes_any_transport(self):
        for endpoint, key in (
            ("https://vision.example/v1/chat/completions", ""),
            ("http://10.0.0.2/v1/chat/completions", "fixture-key"),
            ("https://user:password@vision.example/v1/chat/completions", "fixture-key"),
            ("https://vision.example/v1/chat/completions?destination=other", "fixture-key"),
            ("https://vision.example/v1/chat/completions#other", "fixture-key"),
            ("https://vision.example/v1/chat/completions", "bad\r\nheader"),
            ("https://vision.example:0/v1/chat/completions", "fixture-key"),
            ("https://vision.example/v1/\nchat/completions", "fixture-key"),
        ):
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                VisionBackend(endpoint, "fixture", api_key=key)
        self.assertEqual(self.requests, [])

    async def test_remote_endpoint_and_redirect_are_rejected(self):
        for endpoint in ("http://example.com/v1/chat/completions", "http://10.0.0.2/v1/chat/completions",
                         "http://user:password@127.0.0.1/v1/chat/completions"):
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                VisionBackend(endpoint, "fixture")
        self.status = 302
        with self.assertRaisesRegex(ValueError, "HTTP 302"):
            await asyncio.to_thread(VisionBackend(self.endpoint, "fixture"), JPEG)
        self.assertEqual(len(self.requests), 1)

    async def test_timeout_and_slow_trickle_have_a_request_deadline(self):
        backend = VisionBackend(self.endpoint, "fixture", timeout_s=0.1)
        self.delay = 0.2
        with self.assertRaises(TimeoutError):
            await asyncio.to_thread(backend, JPEG)
        self.delay = 0
        self.trickle = True
        started = time.monotonic()
        with self.assertRaises(TimeoutError):
            await asyncio.to_thread(backend, JPEG)
        self.assertLess(time.monotonic() - started, 0.3)

    async def test_truncated_invalid_and_oversized_responses_do_not_become_observations(self):
        backend = VisionBackend(self.endpoint, "fixture")
        self.length_extra = 1
        with self.assertRaisesRegex(ValueError, "incomplete"):
            await asyncio.to_thread(backend, JPEG)
        self.length_extra = 0
        for result in (
            {"choices": [{"finish_reason": "length", "message": {"content": json.dumps(SCENE)}}]},
            {"choices": [None]},
            {"choices": [{"finish_reason": "stop", "message": {"content": "not JSON"}}]},
            {"choices": [{"finish_reason": "stop", "message": {"content": "x" * 70000}}]},
        ):
            self.result = result
            with self.subTest(result_kind=str(result)[:40]), self.assertRaises(ValueError):
                await asyncio.to_thread(backend, JPEG)

    async def test_worker_to_bridge_sends_only_fresh_recognition_metadata(self):
        class Socket:
            closed = False

            def __init__(self):
                self.sent = []

            async def send(self, raw):
                self.sent.append(json.loads(raw))

        now = 10.0
        service = GatewayService(GatewayServiceConfig(tokens={"robot": "fixture"}), clock=lambda: now)
        connection = GatewayConnection(service, Socket(), "robot", 1)
        connection.last_status = {"camera_ready": True}
        service._connections["robot"] = connection
        adapter = EnvironmentAdapter(service, EnvironmentAdapterConfig(token="fixture", receipt_path=":memory:"),
            utcnow=lambda: datetime(2026, 9, 30, tzinfo=timezone.utc))
        self.addCleanup(adapter.receipts.close)
        bridge = Socket()
        adapter._websocket, adapter._bridge_ready = bridge, True
        analyses = []

        async def observe(analysis):
            analyses.append(analysis)
            await adapter.publish_camera_analysis(analysis, max_frame_age_s=1)

        plugin = CameraFramePlugin(service, VisionBackend(self.endpoint, "fixture-vision"), observe=observe)
        self.addAsyncCleanup(plugin.aclose)
        adapter.recognition_status = plugin.metrics
        health = adapter._observation()["state"]["recognition"]
        self.assertTrue(health["enabled"])
        self.assertEqual(health["maxFrameAgeMs"], 1000)
        self.assertIn("reportedAt", health)
        plugin.set_enabled(False)
        self.assertFalse(adapter._observation()["state"]["recognition"]["enabled"])
        plugin.set_enabled(True)
        await service._publish_frame({"robot_id": "robot", "epoch": 1, "counter": 7,
            "frame_type": CAMERA_JPEG_FRAME_TYPE, "payload": JPEG, "received_at": now})
        await asyncio.wait_for(plugin._queue.join(), 2)
        self.assertEqual(plugin.errors, 0)
        self.assertEqual(len(bridge.sent), 1)

        message = bridge.sent[0]
        self.assertEqual(message["type"], "environment.telemetry")
        self.assertEqual(message["telemetry"]["kind"], "vision.recognition")
        perception = message["telemetry"]["perception"]
        self.assertEqual((perception["robotId"], perception["epoch"], perception["frameCounter"]), ("robot", 1, 7))
        self.assertEqual(perception["gatewayInstance"], service.instance_id)
        self.assertEqual(perception["timeBasis"], "gateway_receipt")
        self.assertNotIn("base64", json.dumps(message))
        self.assertEqual(perception["objects"][0]["label"], "keys")
        adapter._bridge_ready = False
        await adapter.publish_camera_analysis(analyses[0], max_frame_age_s=1)
        adapter._bridge_ready = True
        now += 1
        await adapter.publish_camera_analysis(analyses[0], max_frame_age_s=1)
        now = 10.0
        connection.epoch = 2
        await adapter.publish_camera_analysis(analyses[0], max_frame_age_s=1)
        self.assertEqual(len(bridge.sent), 1, "unready, expired and prior-session results must not be replayed")

    async def test_remote_failure_reaches_existing_observation_path_without_success(self):
        from Emulator.tests.test_environment_adapter import FakeWebSocket

        now = 10.0
        service = GatewayService(GatewayServiceConfig(tokens={"robot": "fixture"}), clock=lambda: now)
        connection = GatewayConnection(service, FakeWebSocket(), "robot", 1)
        service._connections["robot"] = connection
        adapter = EnvironmentAdapter(service, EnvironmentAdapterConfig(token="fixture", receipt_path=":memory:"))
        self.addCleanup(adapter.receipts.close)
        bridge = FakeWebSocket()
        adapter._websocket, adapter._bridge_ready = bridge, True
        backend = await self.remote_backend(api_key="wrong-secret")

        async def observe(analysis):
            await adapter.publish_camera_analysis(analysis, max_frame_age_s=1)

        plugin = CameraFramePlugin(service, backend, observe=observe)
        self.addAsyncCleanup(plugin.aclose)
        with self.assertLogs("gateway.plugins", level="WARNING"):
            await service._publish_frame({"robot_id": "robot", "epoch": 1, "counter": 7,
                "frame_type": CAMERA_JPEG_FRAME_TYPE, "payload": JPEG, "received_at": now})
            await asyncio.wait_for(plugin._queue.join(), 2)
        self.assertEqual(plugin.errors, 1)
        message = json.loads(bridge.sent[0])
        self.assertEqual(message["type"], "environment.observation")
        failure = message["observation"]["metadata"]["recognitionFailure"]
        self.assertEqual((failure["robotId"], failure["epoch"], failure["frameCounter"]), ("robot", 1, 7))
        self.assertIn("HTTP 401", failure["reason"])
        self.assertNotIn("wrong-secret", json.dumps(message))
        self.assertNotIn("vision.recognition", json.dumps(message))

    async def test_invalid_startup_configuration_does_not_create_gateway_state(self):
        from gateway.server.__main__ import _parser, _run_production

        cases = (
            (["--vision-url", self.endpoint], "fixture-token"),
            (["--vision-model", "fixture"], "fixture-token"),
            (["--vision-url", self.endpoint, "--vision-model", "fixture"], ""),
            (["--vision-url", self.endpoint, "--vision-model", "fixture", "--vision-max-frame-age-s", "nan"], "fixture-token"),
            (["--vision-url", "http://example.com/v1/chat/completions", "--vision-model", "fixture"], "fixture-token"),
            (["--vision-url", self.endpoint, "--vision-model", "fixture", "--vision-timeout-s", "nan"], "fixture-token"),
        )
        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory) / "gateway-state"
            for arguments, token in cases:
                with self.subTest(arguments=arguments), patch.dict(os.environ,
                    {"AINEKIO_ENVIRONMENT_ADAPTER_TOKEN": token}, clear=True):
                    args = _parser().parse_args(["--data-dir", str(data_dir), *arguments])
                    with self.assertRaises(ValueError):
                        await _run_production(args)
                    self.assertFalse(data_dir.exists())

    async def test_authenticated_perception_to_native_steering_and_correlated_result(self):
        """Simulated task/model decisions, real HTTPS client and native P4 model.

        This is software evidence, not hosted-model inference or physical motion.
        """
        from Emulator.tests.test_action_receipts import action, accepted
        from Emulator.tests.test_environment_adapter import FakeWebSocket

        now = 100.0
        service = GatewayService(GatewayServiceConfig(tokens={"robot": "fixture"}), clock=lambda: now)
        body, bridge = FakeWebSocket(), FakeWebSocket()
        connection = GatewayConnection(service, body, "robot", 7,
            (BODY_CAPABILITIES_FEATURE, BODY_COMMANDS_FEATURE, COMMAND_DEADLINE_FEATURE,
             LOCOMOTION_FEATURE, WALK_STEERING_FEATURE), model="v2-12servo",
            capabilities={"motion": True, "camera": True, "commands": ["walk", "stop"]})
        connection.observe_body_clock({"clock_ms": 20000})
        service._connections["robot"] = connection
        adapter = EnvironmentAdapter(service, EnvironmentAdapterConfig(
            token="fixture", receipt_path=":memory:", robot_id="robot"), clock=lambda: now)
        self.addCleanup(adapter.receipts.close)
        self.addCleanup(connection.cancel_pending)
        adapter._websocket, adapter._bridge_ready = bridge, True
        backend = await self.remote_backend()

        async def observe(analysis):
            await adapter.publish_camera_analysis(analysis, max_frame_age_s=1)

        plugin = CameraFramePlugin(service, backend, observe=observe)
        self.addAsyncCleanup(plugin.aclose)
        await service._publish_frame({"robot_id": "robot", "epoch": 7, "counter": 7,
            "frame_type": CAMERA_JPEG_FRAME_TYPE, "payload": JPEG, "received_at": now})
        await asyncio.wait_for(plugin._queue.join(), 2)
        perception = json.loads(bridge.sent[0])["telemetry"]["perception"]
        self.assertEqual(perception["objects"][0]["label"], "keys")
        self.assertEqual(self.requests[0][1]["Authorization"], "Bearer fixture-key")

        # The task owner supplies the decision; recognition cannot dispatch it.
        self.assertEqual(body.sent, [])
        original = {**action("perception-steering"), "continuous": True,
                    "speed": 40, "forward": 65, "turn": 25}
        adapter.receipts.receive(original, accepted(original["id"]))
        task = asyncio.create_task(adapter._process_environment_action(original))
        self.addAsyncCleanup(self._cancel_task, task)

        async def wire(count):
            async def wait():
                while len(body.sent) < count:
                    await asyncio.sleep(0.001)
            await asyncio.wait_for(wait(), 2)
            return json.loads(body.sent[count - 1])

        initial = await wire(1)
        await connection._handle_control({"t": "ack", "seq": initial["seq"]})
        self.assertEqual(adapter.receipts.action(original["id"])["state"], "started")
        self.assertIsNone(adapter.receipts.action(original["id"])["result"])
        updates = []
        for revision, controls in enumerate((
            {"speed": 40, "forward": 65, "turn": -25}, {"speed": 0}), 1):
            request = {"type": "environment.action.update", "version": 1,
                "sessionId": adapter.config.session_id, "gatewayInstance": service.instance_id,
                "robotId": "robot", "epoch": 7, "actionId": original["id"],
                "bodyLease": original["bodyLease"], "revision": revision,
                "validForMs": 1000, "controls": controls}
            await adapter._schedule_walk_update(request, bridge)
            update = await wire(revision + 1)
            updates.append(update)
            self.assertEqual(update["update"], initial["seq"])
            await connection._handle_control({"t": "ack", "seq": update["seq"]})
            await asyncio.wait_for(adapter._walk_update_task, 2)
            result = json.loads(bridge.sent[-1])
            self.assertEqual((result["actionId"], result["revision"], result["status"]),
                             (original["id"], revision, "acknowledged"))
            self.assertEqual(adapter.receipts.action(original["id"])["state"], "started")
            self.assertFalse(task.done(), "An update acknowledgement cannot complete the original task")

        root = Path(__file__).resolve().parents[2]
        native_build = root / "build/steering-recognition/flow"
        native = native_build / "v2_model/v2_walk_command"

        def execute_native():
            subprocess.run(["cmake", "-S", str(root / "Slave/firmware/esp32p4-wifi6/tests"),
                "-B", str(native_build), f"-DPython3_EXECUTABLE={sys.executable}"],
                check=True, capture_output=True)
            subprocess.run(["cmake", "--build", str(native_build), "--target", "v2_walk_command",
                "--parallel", "2"], check=True, capture_output=True)
            commands = json.dumps(initial) + "\n5000 " + json.dumps(updates[0]) + "\n10000 " + json.dumps(updates[1]) + "\n"
            run = subprocess.run([str(native), "40000", "50"], input=commands,
                text=True, capture_output=True, check=True)
            return [json.loads(line) for line in run.stdout.splitlines()]

        samples = await asyncio.to_thread(execute_native)
        self.assertTrue(samples[-1]["complete"], "The real model must finish before simulated DONE")
        self.assertGreater(samples[-1]["phase"], 0)
        await connection._handle_control({"t": "done", "seq": initial["seq"]})
        await asyncio.wait_for(task, 2)
        terminal = json.loads(adapter.receipts.action(original["id"])["result"])
        self.assertEqual((terminal["actionId"], terminal["type"]), (original["id"], "completed"))

    @staticmethod
    async def _cancel_task(task):
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


class RecognitionContractTests(unittest.TestCase):
    def test_invalid_model_claims_are_rejected(self):
        for value in (
            {**SCENE, "action": "walk"},
            {**SCENE, "objects": [{"label": "keys", "score": True}]},
            {**SCENE, "objects": [{"label": "keys", "score": float("nan")}]},
            {**SCENE, "objects": [{"label": "keys", "distance": 0.5}]},
            {**SCENE, "objects": [{"label": "keys", "box": {"x": 0.9, "y": 0.1, "width": 0.2, "height": 0.1}}]},
            {**SCENE, "objects": [{"label": "keys"}] * 33},
        ):
            with self.subTest(value_kind=str(value)[:60]), self.assertRaises(ValueError):
                parse_recognition(value, backend="fixture", model="fixture")


if __name__ == "__main__":
    unittest.main()
