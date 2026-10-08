"""Recorded-image perception through production gateway code to an in-memory body.

No hardware endpoint exists here. Internet/LAN socket connections are denied;
commands have exactly the FakeWebSocket destination used by ProgramBody.
YOLO weights and a public/approved recording must already exist locally.
"""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import os
from pathlib import Path
import socket
import sys
from time import monotonic


def deny_network(*args, **kwargs):
    raise RuntimeError("Recorded perception trial prohibits network destinations")


socket.socket.connect = deny_network
socket.socket.connect_ex = deny_network
socket.create_connection = deny_network
socket.socket.bind = deny_network
socket.socket.listen = deny_network

from Emulator.tests.program_ownership_harness import ProgramBody
from Emulator.tests.test_environment_adapter import FakeWebSocket
import gateway.environment_adapter.server as adapter_server
from gateway.plugins import CameraFramePlugin
from gateway.yolo_backend import YoloBackend
from protocol.binary_helpers import CAMERA_JPEG_FRAME_TYPE


class PerceptionBody(ProgramBody):
    def __init__(self):
        cancellation_timeout = adapter_server.CANCELLATION_TIMEOUT_SECONDS
        super().__init__()
        # Ownership unit tests accelerate this budget. Measure the production
        # confirmation budget in the visual demonstration instead.
        adapter_server.CANCELLATION_TIMEOUT_SECONDS = cancellation_timeout
        assert type(self.fixture.body) is FakeWebSocket
        assert self.fixture.connection.websocket is self.fixture.body
        import cv2
        self.cv2 = cv2
        self.video = None
        video_path = os.environ.get('AINEKIO_RECORDED_VIDEO')
        self.source = Path(video_path or os.environ['AINEKIO_RECORDED_IMAGE']).resolve(strict=True)
        if video_path:
            self.video = cv2.VideoCapture(str(self.source))
            if not self.video.isOpened():
                raise ValueError('Recorded video could not be decoded')
            self.video_fps = self.video.get(cv2.CAP_PROP_FPS)
            self.video_frames = int(self.video.get(cv2.CAP_PROP_FRAME_COUNT))
        else:
            self.image = cv2.imread(str(self.source))
            if self.image is None or self.image.shape[:2] != (1080, 810):
                raise ValueError('Photo replay requires the documented Ultralytics bus.jpg fixture')
        # Any library diagnostic stays off the JSON-lines channel.
        with contextlib.redirect_stdout(sys.stderr):
            backend = YoloBackend(os.environ["AINEKIO_YOLO_WEIGHTS"], device="cpu")
        self.backend = backend
        # Explicitly crop the one central person from the packaged public photo.
        # This edits pixels only. All detections/boxes still come from YOLO.
        if self.video is None:
            self.target = self.image[390:870, 220:350]
        self.artifacts = Path(os.environ['AINEKIO_PERCEPTION_ARTIFACTS'])
        self.artifacts.mkdir(parents=True, exist_ok=True)
        self.frames = {}
        self.started = monotonic()
        self.fixture.gateway.clock = lambda: 100 + monotonic() - self.started
        self.fixture.adapter.clock = self.fixture.gateway.clock
        self.fixture.connection.last_status = {"camera_ready": True}
        self.fixture.connection.capabilities["camera"] = True

        async def observe(analysis):
            await self.fixture.adapter.publish_camera_analysis(analysis, max_frame_age_s=1)
            if analysis.result:
                annotated = self.frames.pop(analysis.counter).copy()
                h, w = annotated.shape[:2]
                for obj in analysis.result.objects:
                    if obj.box:
                        x, y, width, height = obj.box
                        self.cv2.rectangle(annotated, (int(x*w), int(y*h)),
                            (int((x+width)*w), int((y+height)*h)), (0, 255, 0), 2)
                        self.cv2.putText(annotated, f'{obj.label} {obj.score:.2f}',
                            (int(x*w), max(20, int(y*h)-5)), self.cv2.FONT_HERSHEY_SIMPLEX, .5, (0,255,0), 1)
                self.cv2.imwrite(str(self.artifacts / f'{analysis.counter:03}-detected.jpg'), annotated)

        self.camera = CameraFramePlugin(self.fixture.gateway, backend, observe=observe, max_frame_age_s=1)

    async def request(self, request):
        # Synthetic heartbeats only; no camera or real body is opened.
        self.fixture.connection.last_control_at = self.fixture.gateway.clock()
        self.fixture.connection.observe_body_clock({"clock_ms": 20000 + int((monotonic() - self.started) * 1000)})
        if request["op"] == "frame":
            import numpy as np
            if self.video is not None:
                index = request['videoFrame']
                if type(index) is not int or not 0 <= index < self.video_frames:
                    raise ValueError('Video frame is outside the recording')
                self.video.set(self.cv2.CAP_PROP_POS_FRAMES, index)
                ok, frame = self.video.read()
                if not ok:
                    raise ValueError('Recorded frame could not be decoded')
            else:
                frame = np.zeros((480, 640, 3), dtype=np.uint8)
                resized = self.cv2.resize(self.target, (130, 360))
                offset = {"left": 30, "center": 255, "right": 480, "lost": None}[request["position"]]
                if offset is not None:
                    frame[60:420, offset:offset + 130] = resized
            self.frames = {request['counter']: frame}
            self.cv2.imwrite(str(self.artifacts / f"{request['counter']:03}-input.jpg"), frame)
            ok, encoded = self.cv2.imencode(".jpg", frame)
            assert ok
            await self.fixture.gateway._publish_frame({"robot_id": "robot", "epoch": self.fixture.connection.epoch,
                "counter": request["counter"], "frame_type": CAMERA_JPEG_FRAME_TYPE,
                "received_at": self.fixture.gateway.clock() - request.get("ageSeconds", 0),
                "payload": encoded.tobytes()})
            await asyncio.wait_for(self.camera._queue.join(), 10)
            result = self.snapshot()
            result["processing"] = self.camera.metrics()
            return result
        if request["op"] == "action" and request["action"].get("movementUpdate"):
            command = request["action"]
            update = command["movementUpdate"]
            owner = self.fixture.adapter._observation()["state"]["activeMovementUpdates"]
            before = len(self.fixture.body.sent)
            await self.fixture.adapter._schedule_walk_update({"type": "environment.action.update", "version": 1,
                "sessionId": command["sessionId"], "gatewayInstance": owner["gatewayInstance"],
                "robotId": owner["robotId"], "epoch": owner["epoch"], "actionId": update["actionId"],
                "bodyLease": command["bodyLease"], "revision": update["revision"],
                "validForMs": owner["maxValidityMs"], "controls": update["controls"]}, self.fixture.bridge)
            await self.await_dispatch(self.fixture.adapter._walk_update_task, before)
            if len(self.fixture.body.sent) > before:
                wire = json.loads(self.fixture.body.sent[-1])
                await self.fixture.connection._handle_control({"t": "ack", "seq": wire["seq"]})
            await asyncio.wait_for(self.fixture.adapter._walk_update_task, 5)
            return self.snapshot()
        return await super().request(request)


async def main():
    body = PerceptionBody()
    import torch, ultralytics
    print(json.dumps({"ready": body.snapshot(), "classes": body.backend.classes,
        "model": body.backend.model, "sourceSha256": hashlib.sha256(body.source.read_bytes()).hexdigest(),
        "video": {"fps": body.video_fps, "frames": body.video_frames} if body.video is not None else None,
        "versions": {"python": sys.version.split()[0], "torch": torch.__version__, "ultralytics": ultralytics.__version__, "opencv": body.cv2.__version__},
        "device": "cpu", "threads": torch.get_num_threads(), "physicalDestination": False}), flush=True)
    try:
        while line := await asyncio.to_thread(sys.stdin.readline):
            try:
                request = json.loads(line)
                result = await body.request(request)
                response = {"id": request.get("id"), "result": result}
            except Exception as error:
                response = {"error": f"{type(error).__name__}: {error}"}
            print(json.dumps(response), flush=True)
    finally:
        await body.camera.aclose()
        if body.video is not None:
            body.video.release()
        await body.fixture.asyncTearDown()


if __name__ == "__main__":
    asyncio.run(main())
