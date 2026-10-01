from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from gateway.environment_adapter import EnvironmentAdapter, EnvironmentAdapterConfig
from gateway.perception import LocalVisionBackend, parse_recognition
from gateway.plugins import CameraFramePlugin
from gateway.server.service import GatewayConnection, GatewayService, GatewayServiceConfig
from protocol.binary_helpers import CAMERA_JPEG_FRAME_TYPE


JPEG = b"\xff\xd8\xff\xd9"
SCENE = {"summary": "Small metal objects on a table", "objects": [
    {"label": "keys", "box": {"x": 0.4, "y": 0.5, "width": 0.002, "height": 0.003}},
], "uncertainties": ["Identity of the keys is unverified"]}


class RecognitionBackendTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.requests = []
        self.result = {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(SCENE)}}]}
        self.status = 200
        self.delay = 0
        self.trickle = False
        self.length_extra = 0
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                owner.requests.append((self.path, dict(self.headers), json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
                if owner.delay:
                    time.sleep(owner.delay)
                data = json.dumps(owner.result).encode()
                self.send_response(owner.status)
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
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.endpoint = f"http://127.0.0.1:{self.server.server_port}/v1/chat/completions"

    async def asyncTearDown(self):
        await asyncio.to_thread(self.server.shutdown)
        self.server.server_close()
        self.thread.join(timeout=1)

    async def test_real_http_backend_preserves_image_and_uncertainty_without_inventing_scores(self):
        backend = LocalVisionBackend(self.endpoint, "fixture-vision", api_key="fixture-key")
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

    async def test_remote_endpoint_and_redirect_are_rejected(self):
        for endpoint in ("http://example.com/v1/chat/completions", "http://10.0.0.2/v1/chat/completions",
                         "http://user:password@127.0.0.1/v1/chat/completions"):
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                LocalVisionBackend(endpoint, "fixture")
        self.status = 302
        with self.assertRaisesRegex(ValueError, "HTTP 302"):
            await asyncio.to_thread(LocalVisionBackend(self.endpoint, "fixture"), JPEG)
        self.assertEqual(len(self.requests), 1)

    async def test_timeout_and_slow_trickle_have_a_request_deadline(self):
        backend = LocalVisionBackend(self.endpoint, "fixture", timeout_s=0.1)
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
        backend = LocalVisionBackend(self.endpoint, "fixture")
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

        plugin = CameraFramePlugin(service, LocalVisionBackend(self.endpoint, "fixture-vision"), observe=observe)
        self.addAsyncCleanup(plugin.aclose)
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
