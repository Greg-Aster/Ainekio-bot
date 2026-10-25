from __future__ import annotations

import asyncio
import base64
import http.client
import importlib.util
import json
import math
import re
import struct
import sys
import threading
from collections.abc import AsyncIterator
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit
from uuid import uuid4

from gateway.security import DashboardPasswordStore, RobotTokenStore, _atomic_secure_json, _read_json
from gateway.environment_adapter import EnvironmentAdapter
from gateway.hotspot import RobotHotspot
from gateway.host_audio import HostAudio
from gateway.body_events import validate_settings
from gateway.server.service import GatewayError, GatewayService
from protocol.binary_helpers import CAMERA_JPEG_FRAME_TYPE
from protocol.control_v1 import ProtocolValidationError

from .auth import AuditLog, DashboardSession, DashboardSessions, LoginRateLimiter, SESSION_TTL_SECONDS


MAX_REQUEST_BODY_BYTES = 16 * 1024
SESSION_COOKIE = "ainekio_dashboard_session"
DEFAULT_TEST_TONE_VOLUME_PERCENT = 15
PCM_S16_MAX = 32767
TEST_TONE_FRAME_COUNT = 100
STATIC_ROOT = Path(__file__).with_name("static")
FREESTYLE_ROOT = Path(__file__).resolve().parents[3] / "experiments" / "freestyle"
ROBOT_MAINTENANCE = {
    "/api/robot/idle-rest": "/api/idle-rest",
    "/api/robot/gait-learning": "/api/gait-learning",
    "/api/robot/servo-feedback": "/api/servo-feedback",
    "/api/robot/logs": "/api/logs",
    "/api/robot/recording": "/api/recording",
    "/api/robot/recordings": "/api/recordings",
    "/api/robot/firmware": "/api/firmware",
    "/api/robot/firmware/activate": "/api/firmware/activate",
}
STATIC_FILES = {
    "/": ("dashboard.html", "text/html; charset=utf-8", True),
    "/login": ("login.html", "text/html; charset=utf-8", False),
    "/assets/dashboard.css": ("dashboard.css", "text/css; charset=utf-8", False),
    "/assets/dashboard.js": ("dashboard.js", "text/javascript; charset=utf-8", False),
    "/assets/gait-history.js": ("gait-history.js", "text/javascript; charset=utf-8", False),
}
# Generated from the same face definitions and C renderer used by the P4.
# Extend the existing explicit static-file map; request paths never become
# filesystem paths. The older monochrome body keeps its own face controls.
for _face_file in (STATIC_ROOT / "faces").glob("*"):
    _face_type = {".json": "application/json", ".png": "image/png", ".webp": "image/webp"}.get(_face_file.suffix)
    if _face_type:
        STATIC_FILES[f"/assets/faces/{_face_file.name}"] = (
            f"faces/{_face_file.name}", _face_type, False,
        )


class DashboardHttpServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        server_address: tuple[str, int],
        *,
        gateway: GatewayService,
        event_loop: asyncio.AbstractEventLoop,
        password_store: DashboardPasswordStore,
        token_store: RobotTokenStore,
        audit_log: AuditLog | None = None,
        primary_view: str = "camera",
        hotspot: RobotHotspot | None = None,
        environment_adapter: EnvironmentAdapter | None = None,
    ) -> None:
        if primary_view not in {"camera", "simulator"}:
            raise ValueError("primary_view must be camera or simulator")
        super().__init__(server_address, DashboardHandler)
        self.gateway = gateway
        self.host_audio = HostAudio()
        self.freestyle = None
        self.gait_learning = None
        self.camera_recognition = None
        self.control_settings_path = password_store.path.with_name("sensing-controls.json")
        self.control_settings = (_read_json(self.control_settings_path)
            if self.control_settings_path.exists() else {"recognition": True, "cameras": {}})
        for robot_id, settings in self.control_settings.get("body_events", {}).items():
            self.gateway.body_events.configure(robot_id, settings)
        self.gateway.motion_systems = dict(self.control_settings.get("motion_systems", {}))
        self.event_loop = event_loop
        self.password_store = password_store
        self.token_store = token_store
        self.audit_log = audit_log or AuditLog()
        self.sessions = DashboardSessions(
            path=password_store.path.with_name("dashboard-sessions.json"),
            password_revision=password_store.revision(),
        )
        self.login_limiter = LoginRateLimiter()
        self.authentication_lock = threading.RLock()
        self.stop_latched = False
        self.primary_view = primary_view
        self.hotspot = hotspot if hotspot is not None else RobotHotspot()
        self.environment_adapter = environment_adapter
        self._camera_condition = threading.Condition()
        self._camera_frames: dict[str, tuple[int, bytes, dict]] = {}
        self._camera_snapshots: dict[str, tuple[int, bytes, dict]] = {}
        gateway.subscribe_frames(self._record_camera_frame)
        self.freestyle_recorder = None

    def start_freestyle(self):
        if (FREESTYLE_ROOT / "bridge.py").is_file():
            self._setup_freestyle()

    def _setup_freestyle(self):
        # The experiment owns its model, recording, and optional execution.
        # Removing its directory leaves ordinary Body Control startup intact.
        package = "ainekio_freestyle_experiment"
        if package not in sys.modules:
            spec = importlib.util.spec_from_file_location(package, FREESTYLE_ROOT / "__init__.py",
                submodule_search_locations=[str(FREESTYLE_ROOT)])
            module = importlib.util.module_from_spec(spec)
            sys.modules[package] = module
            spec.loader.exec_module(module)
        from importlib import import_module
        from gateway.gait_learning_service import RobotLearningTransport
        recorder = import_module(package + ".recordings").Recorder(
            self.password_store.path.with_name("freestyle-recordings.sqlite"))
        self.freestyle_recorder = recorder
        self.gateway.subscribe_commands(recorder.command)
        self.gateway.subscribe_events(recorder.event)
        self.gateway.subscribe_diagnostics(recorder.diagnostic)
        self.freestyle = import_module(package + ".bridge").Bridge(
            self.gateway, RobotLearningTransport(self.gateway, self.token_store, persistent=False),
            recorder=recorder, settings_path=self.password_store.path.with_name("freestyle-settings.json"))
        self.gateway.freestyle_motion = self.freestyle.submit
        self.gateway.freestyle_result = self.freestyle.result
        self.gateway.freestyle_cancel = self.freestyle.cancel

    async def close_freestyle(self):
        self.gateway.freestyle_motion = None
        self.gateway.freestyle_result = None
        self.gateway.freestyle_cancel = None
        if self.freestyle is not None:
            await self.freestyle.close()
        if self.freestyle_recorder is not None:
            recorder = self.freestyle_recorder
            self.gateway.unsubscribe_commands(recorder.command)
            self.gateway.unsubscribe_events(recorder.event)
            self.gateway.unsubscribe_diagnostics(recorder.diagnostic)
            await asyncio.to_thread(recorder.close)

    def call_gateway(self, awaitable: Any, *, timeout: float | None = 10.0) -> object:
        future = asyncio.run_coroutine_threadsafe(awaitable, self.event_loop)
        return future.result(timeout=timeout)

    async def set_motion_system(self, robot_id, system):
        if system not in {"library", "freestyle"}:
            raise ValueError("Choose library or freestyle")
        saved = {**self.control_settings, "motion_systems": {
            **self.control_settings.get("motion_systems", {}), robot_id: system}}
        _atomic_secure_json(self.control_settings_path, saved)
        self.control_settings = saved
        self.gateway.motion_systems[robot_id] = system
        await self.gateway._publish_event({"t": "motion_system", "robot_id": robot_id, "system": system})
        return {"robot_id": robot_id, "system": system}

    async def body_event_status(self):
        return self.gateway.body_events.status()

    async def set_body_events(self, robot_id, settings):
        settings = validate_settings(settings)
        saved = {**self.control_settings, "body_events": {
            **self.control_settings.get("body_events", {}), robot_id: settings}}
        _atomic_secure_json(self.control_settings_path, saved)
        self.control_settings = saved
        self.gateway.body_events.configure(robot_id, settings)
        return {"robot_id": robot_id, "settings": settings}

    async def request_body_wake(self, robot_id):
        if self.environment_adapter is None:
            raise GatewayError("The Environment Bridge is not configured")
        robot = self.gateway.status()["robots"].get(robot_id)
        if robot is None or robot.get("connection_state") != "online":
            raise GatewayError("Select a connected robot")
        event = self.gateway.body_events.wake(robot_id, robot["epoch"], "explicit_good_morning_request")
        if event is None:
            return {"submitted": False, "reason": "Wake events are disabled"}
        await self.gateway._publish_event(event)
        return {"submitted": True, "event_id": event["event_id"]}

    async def ground_calibration(self, robot_id, request):
        if self.camera_recognition is None:
            raise GatewayError("Camera processing is not configured")
        result = await self.camera_recognition.configure_ground_plane(robot_id, request)
        if request.get("operation") == "fit":
            saved = {**self.control_settings, "ground_calibrations": {
                **self.control_settings.get("ground_calibrations", {}), robot_id: result["calibration"]}}
            _atomic_secure_json(self.control_settings_path, saved)
            self.control_settings = saved
        return result

    async def trial_status(self):
        status = await self.gateway.status_snapshot()
        if (FREESTYLE_ROOT / "bridge.py").is_file():
            status["freestyle"] = self.freestyle.status() if self.freestyle else {"settings": {}, "jobs": {}}
        camera = self.camera_recognition
        for robot_id, robot in status.get("robots", {}).items():
            robot["locomotion_measurement"] = camera.locomotion_measurement(robot_id) if camera else {
                "robotId": robot_id, "available": False, "reason": "Camera processing is not configured"}
            if self.gait_learning:
                robot["gait_training"] = self.gait_learning.status(robot_id)
        return status

    async def freestyle_request(self, payload):
        if not (FREESTYLE_ROOT / "bridge.py").is_file():
            raise GatewayError("Freestyle experiment is not installed")
        if self.freestyle is None:
            self._setup_freestyle()
        robot = _required_string(payload, "robot_id")
        if payload.get("operation") == "corrections":
            return {"corrections": [{"review_id":r["id"], "job_id":r["job_id"], "request":r["request"]}
                    for r in await self.freestyle.corrections(robot)]}
        if payload.get("operation") == "test-correction":
            return await self.freestyle.test_correction(robot, _required_string(payload, "review_id"))
        if payload.get("operation") == "configure":
            return await self.freestyle.configure(robot, _required_string(payload, "endpoint"),
                                                  _required_bool(payload, "recover_events"))
        if payload.get("operation") == "trial":
            return self.freestyle.trial(robot, _required_string(payload, "job_id"))
        if payload.get("operation") == "review":
            return self.freestyle.review(robot, _required_string(payload, "job_id"),
                _required_string(payload, "outcome"), payload.get("note", ""),
                payload.get("corrected_request"), payload.get("corrected_program"), payload.get("generation_index"))
        return await self.freestyle.submit(robot, _required_string(payload, "request"),
                                           _required_bool(payload, "execute"))

    async def depth_motion(self, robot_id, request):
        if self.camera_recognition is None:
            raise GatewayError("Camera processing is not configured")
        if request.get("operation") == "sample":
            consumer = f"dashboard-depth:{uuid4()}"
            try:
                result = await self.camera_recognition.depth_demand(robot_id, consumer, True)
                return {"measurement": result.get("measurement")}
            finally:
                await self.camera_recognition.depth_demand(robot_id, consumer, False)
        config = await self.camera_recognition.configure_depth(robot_id, request)
        saved = {**self.control_settings, "depth_motion": {
            **self.control_settings.get("depth_motion", {}), robot_id: config}}
        _atomic_secure_json(self.control_settings_path, saved)
        self.control_settings = saved
        return {"settings": config}

    async def set_recognition(self, enabled: bool) -> dict[str, object]:
        if self.camera_recognition is None:
            raise GatewayError("Recognition backend is not configured")
        settings = {**self.control_settings, "recognition": enabled}
        _atomic_secure_json(self.control_settings_path, settings)
        self.control_settings = settings
        self.camera_recognition.set_enabled(enabled)
        return {"ok": True, "enabled": enabled}

    async def person_status(self) -> dict[str, object]:
        status = getattr(self.camera_recognition, "identity_status", None)
        return status() if status else {"configured": False}

    async def recognition_status(self) -> dict[str, object]:
        if self.camera_recognition is None:
            return {"configured": False, "enabled": False, "observation": None}
        return self.camera_recognition.recognition_status()

    async def recognition_frame(self, robot_id: str, after_id: str | None) -> dict[str, object] | None:
        if self.camera_recognition is None:
            return None
        analysis = self.camera_recognition.current_analysis(robot_id)
        if analysis is None:
            return None
        # Read the image and observation atomically on the camera worker's loop.
        # New raw frames cannot replace the image that produced these boxes.
        frame_id = f"{self.gateway.instance_id}:{analysis.robot_id}:{analysis.epoch}:{analysis.counter}"
        result = {"id": frame_id,
            "observation": self.camera_recognition.analysis_observation(analysis)}
        if frame_id != after_id:
            result["jpeg"] = base64.b64encode(analysis.jpeg).decode("ascii")
        return result

    async def set_saved_camera(self, robot_id: str, settings: dict[str, object]) -> dict[str, object]:
        sequence = await self.gateway.set_camera(robot_id=robot_id, **settings)
        saved = {**self.control_settings, "cameras": {**self.control_settings["cameras"], robot_id: settings}}
        _atomic_secure_json(self.control_settings_path, saved)
        self.control_settings = saved
        return {"ok": True, "seq": sequence, "saved": True}

    async def restore_camera(self, event: dict[str, object]) -> None:
        if event.get("t") != "connection" or event.get("status") != "connected":
            return
        robot_id = event.get("robot_id")
        settings = self.control_settings["cameras"].get(robot_id)
        if settings is not None:
            try:
                await self.gateway.set_camera(robot_id=robot_id, **settings)
            except (GatewayError, ValueError) as error:
                self.audit_log.record("camera_settings_restore_failed", robot_id=robot_id, error=str(error))

    def _record_camera_frame(self, frame: dict[str, object]) -> None:
        if frame.get("frame_type") != CAMERA_JPEG_FRAME_TYPE:
            return
        robot_id = frame.get("robot_id")
        counter = frame.get("counter")
        payload = frame.get("payload")
        if (
            not isinstance(robot_id, str)
            or type(counter) is not int
            or not isinstance(payload, bytes)
        ):
            return
        with self._camera_condition:
            metadata = {"epoch": frame.get("epoch"), **(frame.get("camera_metadata") or {})}
            observation = (counter, payload, metadata)
            self._camera_frames[robot_id] = observation
            if metadata.get("origin") == "request":
                self._camera_snapshots[robot_id] = observation
            self._camera_condition.notify_all()

    def wait_for_camera_frame(
        self,
        robot_id: str,
        after_counter: int | None,
        *,
        timeout: float = 10.0,
        request_sequence: int | None = None,
        epoch: int | None = None,
    ) -> tuple[int, bytes, dict] | None:
        frames = self._camera_snapshots if request_sequence is not None else self._camera_frames
        def frame_is_new() -> bool:
            frame = frames.get(robot_id)
            return frame is not None and (
                after_counter is None or frame[0] != after_counter
            ) and (request_sequence is None or (
                frame[2].get("origin_id") == request_sequence and frame[2].get("epoch") == epoch))

        with self._camera_condition:
            if not self._camera_condition.wait_for(frame_is_new, timeout=timeout):
                return None
            return frames[robot_id]


class DashboardHandler(BaseHTTPRequestHandler):
    server: DashboardHttpServer

    def do_GET(self) -> None:
        parsed_url = urlsplit(self.path)
        path = parsed_url.path
        if path == "/assets/freestyle.js" and (FREESTYLE_ROOT / "body_control.js").is_file():
            if self._require_session() is not None:
                self._send_bytes((FREESTYLE_ROOT / "body_control.js").read_bytes(), "text/javascript; charset=utf-8")
            return
        if path in ROBOT_MAINTENANCE:
            if self._require_session() is not None:
                self._robot_maintenance(path)
            return
        if path in STATIC_FILES:
            filename, content_type, requires_auth = STATIC_FILES[path]
            if path == "/login" and self._session() is not None:
                self.send_response(HTTPStatus.SEE_OTHER)
                self.send_header("Location", "/")
                self._security_headers()
                self.end_headers()
                return
            if requires_auth and self._session() is None:
                self.send_response(HTTPStatus.SEE_OTHER)
                self.send_header("Location", "/login")
                self._security_headers()
                self.end_headers()
                return
            self._send_static(filename, content_type)
            return
        if path == "/api/session":
            session = self._require_session()
            if session is not None:
                self._send_json({"csrf": session.csrf_token})
            return
        if path == "/api/status":
            if self._require_session() is None:
                return
            status = self.server.call_gateway(self.server.trial_status())
            networks = self.server.hotspot.connection_networks() if any(
                robot.get("local_address") and robot.get("transport", "lan") == "lan"
                for robot in status.get("robots", {}).values()
            ) else {}
            for robot in status.get("robots", {}).values():
                ssid = networks.get(robot.get("local_address"))
                if ssid and robot.get("transport", "lan") == "lan":
                    robot["connection_ssid"] = ssid
            self._send_json(
                {
                    **status,
                    "audit": self.server.audit_log.entries(),
                    "token_robot_ids": sorted(self.server.token_store.snapshot()),
                    "host_network": self.server.hotspot.snapshot(),
                    "camera_settings": self.server.control_settings["cameras"],
                    "motion_systems": self.server.control_settings.get("motion_systems", {}),
                    "depth_settings": self.server.control_settings.get("depth_motion", {}),
                    "body_events": self.server.call_gateway(self.server.body_event_status()),
                    "person_recognition": self.server.call_gateway(self.server.person_status()),
                    "recognition": self.server.call_gateway(self.server.recognition_status()),
                }
            )
            return
        if path == "/api/speech-output":
            if self._require_session() is None:
                return
            try:
                self._send_json(self._speech_output())
            except GatewayError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.SERVICE_UNAVAILABLE)
            return
        if path == "/api/host-audio":
            if self._require_session() is None:
                return
            self._send_json(self.server.call_gateway(self.server.host_audio.snapshot()))
            return
        if path == "/api/camera/frame":
            if self._require_session() is None:
                return
            self._camera_frame(parsed_url.query)
            return
        self._send_json({"error": "not_found"}, status=HTTPStatus.NOT_FOUND)

    def _speech_output(self, playback_target: str | None = None, computer_device: str | None = None) -> dict[str, object]:
        adapter = self.server.environment_adapter
        if adapter is None:
            raise GatewayError("MetaHuman Environment Bridge is not configured")
        return self.server.call_gateway(adapter.speech_output_settings(playback_target,
            **({'computer_device':computer_device} if computer_device is not None else {})))

    def _camera_frame(self, query_string: str) -> None:
        query = parse_qs(query_string, keep_blank_values=True)
        robot_ids = query.get("robot_id", [])
        if len(robot_ids) != 1 or not robot_ids[0]:
            self._send_json(
                {"error": "robot_id is required"},
                status=HTTPStatus.BAD_REQUEST,
            )
            return
        if query.get("view") == ["recognition"]:
            self._send_json(self.server.call_gateway(self.server.recognition_frame(
                robot_ids[0], query.get("after_id", [None])[0])))
            return
        after_counter: int | None = None
        after_values = query.get("after", [])
        if after_values:
            if len(after_values) != 1:
                self._send_json(
                    {"error": "invalid after counter"},
                    status=HTTPStatus.BAD_REQUEST,
                )
                return
            try:
                after_counter = int(after_values[0])
            except ValueError:
                self._send_json(
                    {"error": "invalid after counter"},
                    status=HTTPStatus.BAD_REQUEST,
                )
                return
            if not 0 <= after_counter <= 0xFFFFFFFF:
                self._send_json(
                    {"error": "invalid after counter"},
                    status=HTTPStatus.BAD_REQUEST,
                )
                return
        request_sequence = epoch = None
        if "request_seq" in query or "epoch" in query:
            try:
                if len(query.get("request_seq", [])) != 1 or len(query.get("epoch", [])) != 1:
                    raise ValueError
                request_sequence, epoch = int(query["request_seq"][0]), int(query["epoch"][0])
                if request_sequence < 1 or epoch < 0:
                    raise ValueError
            except ValueError:
                self._send_json({"error": "request_seq and epoch must identify one snapshot"}, status=HTTPStatus.BAD_REQUEST)
                return
        frame = self.server.wait_for_camera_frame(robot_ids[0], after_counter,
            request_sequence=request_sequence, epoch=epoch)
        if frame is None:
            self.send_response(HTTPStatus.NO_CONTENT)
            self._security_headers()
            self.end_headers()
            return
        counter, payload, metadata = frame
        headers = {"X-Ainekio-Camera-Counter": str(counter)}
        for field, suffix in (("epoch", "Epoch"), ("origin", "Origin"), ("origin_id", "Origin-Id")):
            if metadata.get(field) is not None:
                headers["X-Ainekio-Camera-"+suffix] = str(metadata[field])
        try:
            self._send_bytes(
                payload,
                "image/jpeg",
                extra_headers=headers,
            )
        except (BrokenPipeError, ConnectionResetError):
            return

    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        if path == "/api/login":
            self._login()
            return

        session = self._require_session()
        if session is None:
            return
        if self.headers.get("X-Ainekio-CSRF") != session.csrf_token:
            self._send_json({"error": "csrf"}, status=HTTPStatus.FORBIDDEN)
            return
        if path == "/api/gait-learning/train":
            self._train_gait_learning()
            return
        if path in ROBOT_MAINTENANCE:
            self._robot_maintenance(path, post=True)
            return
        if path == "/api/logout":
            token = self._session_token()
            self.server.sessions.revoke(token)
            self._send_json(
                {"ok": True},
                extra_headers={
                    "Set-Cookie": (
                        f"{SESSION_COOKIE}=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0"
                    )
                },
            )
            return

        payload = self._read_json()
        if payload is None:
            return
        if path == "/api/settings/password":
            self._change_password(payload)
            return
        try:
            response = self._dispatch_api(path, payload)
        except GatewayError as exc:
            self.server.audit_log.record("dashboard_request_failed", path=path,
                robot_id=payload.get("robot_id"), name=payload.get("name"),
                error=str(exc), error_type=type(exc).__name__, http_status=409)
            self._send_json({"error": str(exc)}, status=HTTPStatus.CONFLICT)
            return
        except (ProtocolValidationError, ValueError, KeyError) as exc:
            self.server.audit_log.record("dashboard_request_failed", path=path,
                robot_id=payload.get("robot_id"), name=payload.get("name"),
                error=str(exc), error_type=type(exc).__name__, http_status=400)
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return
        except TimeoutError:
            self.server.audit_log.record("dashboard_request_failed", path=path,
                robot_id=payload.get("robot_id"), name=payload.get("name"),
                error="gateway timeout", error_type="TimeoutError", http_status=504)
            self._send_json({"error": "gateway timeout"}, status=HTTPStatus.GATEWAY_TIMEOUT)
            return
        self._send_json(response)

    def _train_gait_learning(self) -> None:
        """Host-only fit in this request thread; does not submit robot motion."""
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 8*1024*1024:
                raise ValueError("Upload up to 8 MiB of tracking records per fit")
            payload = json.loads(self.rfile.read(length))
            from ..gait_learning import fit
            result = fit(payload["batches"], float(payload.get("gain", .5)))
            self._send_json(result)
        except (ValueError, KeyError, TypeError) as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
        except ImportError:
            self._send_json({"error": "Install NumPy in the gateway Python environment for training"}, status=HTTPStatus.SERVICE_UNAVAILABLE)

    def _robot_maintenance(self, path: str, *, post: bool = False) -> None:
        """Stream between browser and selected robot; credentials stay here.

        Runs in the existing HTTP request thread, never the robot control loop.
        Neither direction buffers an entire image or recording in memory.
        """
        upstream = None
        started = False
        try:
            query = parse_qs(urlsplit(self.path).query, keep_blank_values=True)
            robot_ids = query.get("robot_id", [])
            if len(robot_ids) != 1 or not robot_ids[0]:
                raise ValueError("Select one robot")
            robot_id = robot_ids[0]
            address = self.server.call_gateway(self.server.gateway.maintenance_address(robot_id))
            token = self.server.token_store.snapshot().get(robot_id)
            if not token:
                raise GatewayError("Robot pairing token is unavailable")
            target = ROBOT_MAINTENANCE[path]
            name = None
            if "name" in query:
                names = query["name"]
                if len(names) != 1 or not re.fullmatch(r"video-[0-9a-fA-F]{8}-[0-9]{8,10}\.avi(?:\.part)?", names[0]):
                    raise ValueError("Invalid recording name")
                name = names[0]
                target += "?" + urlencode({"name": name})
            headers = {"Authorization": "Bearer " + token, "Connection": "close"}
            upstream = http.client.HTTPConnection(address, 80, timeout=30)
            if post:
                if path == "/api/robot/firmware":
                    length = int(self.headers.get("Content-Length", "0"))
                    if length <= 0:
                        raise ValueError("Choose an application firmware binary")
                    upstream.putrequest("POST", target)
                    for key, value in headers.items(): upstream.putheader(key, value)
                    upstream.putheader("Content-Type", "application/octet-stream")
                    upstream.putheader("Content-Length", str(length))
                    upstream.endheaders()
                    remaining = length
                    while remaining:
                        chunk = self.rfile.read(min(65536, remaining))
                        if not chunk: raise ConnectionError("Firmware upload interrupted")
                        upstream.send(chunk)
                        remaining -= len(chunk)
                else:
                    payload = self._read_json()
                    if payload is None: return
                    operation = _required_string(payload, "op")
                    if path in ("/api/robot/servo-feedback", "/api/robot/gait-learning", "/api/robot/idle-rest"):
                        headers["Content-Type"] = "application/json"
                        operation = json.dumps(payload, allow_nan=False)
                    upstream.request("POST", target, operation, headers)
            else:
                upstream.request("GET", target, headers=headers)
            response = upstream.getresponse()
            if response.status >= 400:
                detail = response.read(16384).decode("utf-8", errors="replace")
                try: message = json.loads(detail).get("error", detail)
                except ValueError: message = f"Robot maintenance returned HTTP {response.status}"
                # A robot's 401 is not an expired dashboard login.
                self._send_json({"error": message}, status=HTTPStatus.BAD_GATEWAY)
                return
            self.send_response(response.status)
            self._security_headers()
            self.send_header("Content-Type", response.getheader("Content-Type", "application/json"))
            length = response.getheader("X-Recording-Bytes") if name else response.getheader("Content-Length")
            if length is not None:
                self.send_header("Content-Length", str(int(length)))
            if name:
                self.send_header("Content-Disposition", f'attachment; filename="{name}"')
            self.send_header("Connection", "close")
            self.close_connection = True
            self.end_headers()
            started = True
            while chunk := response.read(65536):
                self.wfile.write(chunk)
            if post:
                self.server.audit_log.record("robot_maintenance", robot_id=robot_id, operation=path)
        except (GatewayError, ValueError) as exc:
            if not started: self._send_json({"error": str(exc)}, status=HTTPStatus.CONFLICT)
        except (OSError, http.client.HTTPException, TimeoutError):
            if not started:
                self._send_json({"error": "Robot transfer interrupted. Refresh status to check the outcome."},
                                status=HTTPStatus.BAD_GATEWAY)
        finally:
            if upstream is not None: upstream.close()

    def _dispatch_api(self, path: str, payload: dict[str, object]) -> dict[str, object]:
        robot_id = _optional_string(payload, "robot_id")
        if path == "/api/host-audio":
            try:
                return self.server.call_gateway(self.server.host_audio.submit(
                    _required_string(payload, "op"), payload.get("address")))
            except OSError as error:
                raise GatewayError(str(error)) from error
        if path == "/api/motion-system":
            return self.server.call_gateway(self.server.set_motion_system(
                _required_string(payload, "robot_id"), _required_string(payload, "system")))
        if path == "/api/freestyle":
            return self.server.call_gateway(self.server.freestyle_request(payload))
        if path == "/api/gait-learning/service":
            service = self.server.gait_learning
            if service is None:
                raise GatewayError("Host gait learning service is not running")
            robot_id = _required_string(payload, "robot_id")
            operation = payload.get("op", "status")
            if operation == "history":
                return self.server.call_gateway(service.history(robot_id))
            if operation == "configure":
                return self.server.call_gateway(service.configure(robot_id, payload.get("settings", {})))
            if operation == "analyze":
                async def analyze():
                    return service.analyze(robot_id)
                return self.server.call_gateway(analyze())
            if operation == "restore":
                return self.server.call_gateway(service.restore(robot_id,
                    _required_string(payload, "gait"), _required_string(payload, "model_id")))
            if operation == "status":
                async def status():
                    return service.status(robot_id)
                return self.server.call_gateway(status())
            raise ValueError("Unknown host gait-learning operation")
        if path in {"/api/people/enroll", "/api/people/forget"}:
            camera = self.server.camera_recognition
            if camera is None:
                raise GatewayError("Named-person recognition is not configured")
            if path.endswith("/enroll"):
                return self.server.call_gateway(camera.enroll_person(payload), timeout=30)
            return self.server.call_gateway(camera.forget_person(_required_string(payload, "personId")))
        if path == "/api/body-events":
            return self.server.call_gateway(self.server.set_body_events(
                _required_string(payload, "robot_id"), payload.get("settings")))
        if path == "/api/body-events/good-morning":
            return self.server.call_gateway(self.server.request_body_wake(_required_string(payload, "robot_id")))
        if path == "/api/recognition":
            return self.server.call_gateway(self.server.set_recognition(_required_bool(payload, "enabled")))
        if path == "/api/vision/target":
            camera = self.server.camera_recognition
            if camera is None:
                raise GatewayError("Recognition is not configured")
            return self.server.call_gateway(camera.configure_vision({**payload, "requestId": str(uuid4())}), timeout=None)
        if path == "/api/behavior-control":
            adapter = self.server.environment_adapter
            if adapter is None:
                raise GatewayError("MetaHuman Environment Bridge is not configured")
            enabled = _required_bool(payload, "enabled") if "enabled" in payload else None
            return self.server.call_gateway(adapter.behavior_settings(enabled))
        if path == "/api/speech-output":
            target = _required_string(payload, "playbackTarget")
            if target not in {"computer", "robot"}:
                raise ValueError("playbackTarget must be computer or robot")
            device = payload.get('computerDevice')
            if device is not None and not isinstance(device,str):
                raise ValueError('computerDevice must be an audio output name')
            response = self._speech_output(target, device)
            self.server.audit_log.record("speech_output_changed", output_target=target)
            return response
        if path == "/api/settings/network":
            network = self.server.call_gateway(
                self.server.hotspot.set_enabled(_required_bool(payload, "hotspot"))
            )
            self.server.audit_log.record("host_network_changed", **network)
            return {"ok": True, "host_network": network}
        if path == "/api/motion-plan":
            frames = payload.get("frames")
            if not isinstance(frames, list):
                raise ValueError("frames must be a list of [duration_ms, joint_targets_centidegrees]")
            sequence = self.server.call_gateway(self.server.gateway.queue_motion_plan(
                frames, end=_required_string(payload, "end"), robot_id=robot_id))
            self.server.audit_log.record("motion_plan_issued", robot_id=robot_id, sequence=sequence)
            return {"ok": True, "seq": sequence}
        if path == "/api/intent":
            name = _required_string(payload, "name")
            params = payload.get("params")
            if params is not None and not isinstance(params, dict):
                raise ValueError("params must be an object")
            sequence = self.server.call_gateway(
                self.server.gateway.queue_intent(name, params, robot_id=robot_id)
            )
            self.server.audit_log.record("intent_issued", robot_id=robot_id, name=name)
            if self.server.stop_latched:
                self.server.stop_latched = False
                self.server.audit_log.record("stop_cleared", robot_id=robot_id)
            return {"ok": True, "seq": sequence}
        if path == "/api/stop":
            sequence = self.server.call_gateway(
                self.server.gateway.estop(robot_id=robot_id, detach=False)
            )
            self.server.stop_latched = True
            self.server.audit_log.record("stop_issued", robot_id=robot_id)
            return {"ok": True, "seq": sequence}
        if path == "/api/detach":
            sequence = self.server.call_gateway(
                self.server.gateway.estop(robot_id=robot_id, detach=True)
            )
            self.server.stop_latched = True
            self.server.audit_log.record("detach_issued", robot_id=robot_id)
            return {"ok": True, "seq": sequence}
        if path == "/api/profile":
            sequence = self.server.call_gateway(
                self.server.gateway.set_profile(
                    _required_string(payload, "name"),
                    robot_id=robot_id,
                )
            )
            return {"ok": True, "seq": sequence}
        if path == "/api/state":
            sleep_s = payload.get("sleep_s")
            if sleep_s is not None and type(sleep_s) is not int:
                raise ValueError("sleep_s must be an integer")
            sequence = self.server.call_gateway(
                self.server.gateway.set_state(
                    _required_string(payload, "name"),
                    sleep_s,
                    robot_id=robot_id,
                )
            )
            return {"ok": True, "seq": sequence}
        if path == "/api/snap":
            sequence = self.server.call_gateway(
                self.server.gateway.request_snap(robot_id=robot_id)
            )
            return {"ok": True, "seq": sequence}
        if path == "/api/camera/ground-calibration":
            return self.server.call_gateway(self.server.ground_calibration(
                _required_string(payload, "robot_id"), payload), timeout=None)
        if path == "/api/camera/depth":
            return self.server.call_gateway(self.server.depth_motion(
                _required_string(payload, "robot_id"), payload), timeout=None)
        if path == "/api/camera":
            options = {"snapshot_resolution": _required_string(payload, "snapshot_res")} if "snapshot_res" in payload else {}
            for key in ("exposure_us", "gain_x16", "jpeg_quality"):
                if key in payload:
                    options[key] = _required_int(payload, key)
            return self.server.call_gateway(self.server.set_saved_camera(_required_string(payload, "robot_id"), {
                "on": _required_bool(payload, "on"), "fps": _required_int(payload, "fps"),
                "resolution": _required_string(payload, "res"), **options}))
        if path == "/api/speaker":
            volume = _required_int(payload, "volume_percent")
            if not 0 <= volume <= 100:
                raise ValueError("volume_percent must be between 0 and 100")
            sequence = self.server.call_gateway(
                self.server.gateway.set_speaker_volume(volume_percent=volume, robot_id=robot_id)
            )
            return {"ok": True, "seq": sequence}
        if path == "/api/microphone":
            options = {"gain_db": _required_int(payload, "gain_db")} if "gain_db" in payload else {}
            sequence = self.server.call_gateway(
                self.server.gateway.set_microphone(
                    on=_required_bool(payload, "on"),
                    gate=_required_string(payload, "gate"),
                    robot_id=robot_id,
                    **options,
                )
            )
            return {"ok": True, "seq": sequence}
        if path == "/api/wake":
            options = {"threshold": _required_number(payload, "threshold")} if "threshold" in payload else {}
            sequence = self.server.call_gateway(
                self.server.gateway.set_wake_configuration(
                    enabled=_required_bool(payload, "enabled"),
                    model=_required_string(payload, "model"),
                    robot_id=robot_id,
                    **options,
                )
            )
            return {"ok": True, "seq": sequence}
        if path == "/api/speaker-test":
            volume_percent = payload.get(
                "volume_percent",
                DEFAULT_TEST_TONE_VOLUME_PERCENT,
            )
            if type(volume_percent) is not int:
                raise ValueError("volume_percent must be an integer")
            if not 1 <= volume_percent <= 100:
                raise ValueError("volume_percent must be between 1 and 100")
            sequence = self.server.call_gateway(
                self.server.gateway.tts_speak(
                    _test_tone_frames(volume_percent),
                    robot_id=robot_id,
                )
            )
            return {"ok": True, "seq": sequence}
        if path == "/api/calibration/mode":
            sequence = self.server.call_gateway(
                self.server.gateway.set_calibration_mode(
                    _required_string(payload, "mode"),
                    robot_id=robot_id,
                )
            )
            return {"ok": True, "seq": sequence}
        if path == "/api/balance":
            operation = _required_string(payload, "op")
            values = {key: value for key, value in payload.items() if key not in {"op", "robot_id"}}
            result = self.server.call_gateway(self.server.gateway.body_balance(
                operation, values, robot_id=robot_id), timeout=8.0)
            self.server.audit_log.record("balance_confirmed", robot_id=robot_id,
                                         operation=operation, sequence=result["seq"])
            return {"ok": True, "seq": result["seq"], "balance": result}
        if path == "/api/motion-speed":
            operation = _required_string(payload, "op")
            values = {key: value for key, value in payload.items() if key not in {"op", "robot_id"}}
            result = self.server.call_gateway(self.server.gateway.body_motion_speed(
                operation, values, robot_id=robot_id), timeout=8.0)
            self.server.audit_log.record("motion_speed_confirmed", robot_id=robot_id,
                                         operation=operation, sequence=result["seq"])
            return {"ok": True, "seq": result["seq"], "motion_speed": result}
        if path == "/api/settings/robot":
            operation = _required_string(payload, "op")
            if operation == "apply" and payload.get("confirmed") is not True:
                raise ValueError("confirm restarting the robot to apply settings")
            values = {key: value for key, value in payload.items() if key not in {"op", "robot_id", "confirmed"}}
            result = self.server.call_gateway(self.server.gateway.body_robot_settings(
                operation, values, robot_id=robot_id), timeout=12.0)
            self.server.audit_log.record("robot_settings_confirmed", robot_id=robot_id, operation=operation, sequence=result["seq"])
            return {"ok": True, "settings": result}
        if path == "/api/storage":
            operation = _required_string(payload, "op")
            if operation == "clear" and payload.get("confirmed") is not True:
                raise ValueError("confirm clearing the body's logs and captures")
            result = self.server.call_gateway(self.server.gateway.body_storage(operation, robot_id=robot_id), timeout=12.0)
            self.server.audit_log.record("storage_confirmed", robot_id=robot_id, operation=operation, sequence=result["seq"])
            return {"ok": True, "seq": result["seq"], "storage": result}
        if path == "/api/calibration/body":
            operation = _required_string(payload, "op")
            values = {key: value for key, value in payload.items() if key not in {"op", "robot_id"}}
            result = self.server.call_gateway(self.server.gateway.body_calibration(
                operation, values, robot_id=robot_id,
            ))
            self.server.audit_log.record("body_calibration_confirmed", robot_id=robot_id,
                                         operation=operation, sequence=result["seq"])
            return {"ok": True, "seq": result["seq"], "calibration": result}
        if path == "/api/calibration/servo":
            sequence = self.server.call_gateway(
                self.server.gateway.set_servo(
                    _required_int(payload, "id"),
                    _required_number(payload, "deg"),
                    _required_int(payload, "ms"),
                    robot_id=robot_id,
                )
            )
            return {"ok": True, "seq": sequence}
        if path == "/api/calibration/limits":
            sequence = self.server.call_gateway(
                self.server.gateway.set_servo_limits(
                    _required_int(payload, "id"),
                    _required_number(payload, "min"),
                    _required_number(payload, "max"),
                    _required_number(payload, "center"),
                    _required_bool(payload, "invert"),
                    robot_id=robot_id,
                )
            )
            return {"ok": True, "seq": sequence}
        if path == "/api/calibration/save":
            sequence = self.server.call_gateway(
                self.server.gateway.save_calibration(robot_id=robot_id)
            )
            self.server.audit_log.record("calibration_saved", robot_id=robot_id)
            return {"ok": True, "seq": sequence}
        if path == "/api/calibration/neutral":
            sequences = []
            for servo_id in range(8):
                sequences.append(
                    self.server.call_gateway(
                        self.server.gateway.set_servo(
                            servo_id,
                            90.0,
                            400,
                            robot_id=robot_id,
                        )
                    )
                )
            return {"ok": True, "sequences": sequences}
        if path == "/api/calibration/detach":
            sequence = self.server.call_gateway(
                self.server.gateway.estop(robot_id=robot_id, detach=True)
            )
            self.server.stop_latched = True
            self.server.audit_log.record("detach_issued", robot_id=robot_id)
            return {"ok": True, "seq": sequence}
        if path == "/api/tokens/generate":
            new_robot_id = _required_string(payload, "robot_id")
            token = self.server.token_store.generate(new_robot_id)
            self.server.event_loop.call_soon_threadsafe(
                self.server.gateway.set_token,
                new_robot_id,
                token,
            )
            self.server.audit_log.record("robot_token_generated", robot_id=new_robot_id)
            return {"ok": True, "robot_id": new_robot_id, "token": token}
        if path == "/api/tokens/revoke":
            target_robot_id = _required_string(payload, "robot_id")
            self.server.token_store.revoke(target_robot_id)
            self.server.call_gateway(self.server.gateway.revoke_token(target_robot_id))
            self.server.audit_log.record("robot_token_revoked", robot_id=target_robot_id)
            return {"ok": True}
        raise ValueError("unknown API command")

    def _change_password(self, payload: dict[str, object]) -> None:
        current = payload.get("current_password")
        password = payload.get("new_password")
        confirmation = payload.get("confirm_password")
        if not isinstance(current, str) or not isinstance(password, str):
            self._send_json({"error": "Password fields must contain text."}, status=HTTPStatus.BAD_REQUEST)
            return
        if password != confirmation:
            self._send_json({"error": "The new passwords do not match."}, status=HTTPStatus.BAD_REQUEST)
            return
        address = self.client_address[0]
        with self.server.authentication_lock:
            # Recheck after acquiring the lock: another browser may have just
            # changed the password and revoked this session.
            if self._require_session() is None:
                return
            if not self.server.login_limiter.allow_attempt(address):
                self._send_json({"error": "Too many attempts. Try again shortly."}, status=HTTPStatus.TOO_MANY_REQUESTS)
                return
            if not self.server.password_store.verify(current):
                self._send_json({"error": "The current password is incorrect."}, status=HTTPStatus.FORBIDDEN)
                return
            self.server.password_store.set_password(password)
            self.server.sessions.password_changed(self.server.password_store.revision(), self._session_token())
            self.server.login_limiter.clear(address)
            self.server.audit_log.record("dashboard_password_changed", address=address)
        self._send_json({"ok": True})

    def _login(self) -> None:
        with self.server.authentication_lock:
            self._login_locked()

    def _login_locked(self) -> None:
        address = self.client_address[0]
        if not self.server.login_limiter.allow_attempt(address):
            self.server.audit_log.record("login_rate_limited", address=address)
            self._send_json({"error": "rate_limited"}, status=HTTPStatus.TOO_MANY_REQUESTS)
            return
        payload = self._read_json()
        if payload is None:
            return
        password = payload.get("password")
        if not isinstance(password, str) or not self.server.password_store.verify(password):
            self.server.audit_log.record("login_failed", address=address)
            self._send_json({"error": "authentication_failed"}, status=HTTPStatus.UNAUTHORIZED)
            return
        self.server.login_limiter.clear(address)
        token, session = self.server.sessions.create()
        self._send_json(
            {"ok": True, "csrf": session.csrf_token},
            extra_headers={
                "Set-Cookie": (
                    f"{SESSION_COOKIE}={token}; Path=/; HttpOnly; SameSite=Strict; "
                    f"Max-Age={SESSION_TTL_SECONDS}"
                )
            },
        )

    def _session_token(self) -> str | None:
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
        except Exception:
            return None
        morsel = cookie.get(SESSION_COOKIE)
        return morsel.value if morsel is not None else None

    def _session(self) -> DashboardSession | None:
        with self.server.authentication_lock:
            return self.server.sessions.get(self._session_token())

    def _require_session(self) -> DashboardSession | None:
        session = self._session()
        if session is None:
            self._send_json({"error": "authentication_required"}, status=HTTPStatus.UNAUTHORIZED)
        return session

    def _read_json(self) -> dict[str, object] | None:
        try:
            length = int(self.headers.get("Content-Length", "0") or "0")
        except ValueError:
            self._send_json({"error": "invalid_content_length"}, status=HTTPStatus.BAD_REQUEST)
            return None
        from protocol.binary_helpers import MAX_JPEG_BYTES
        limit = (MAX_JPEG_BYTES * 4 // 3 + 4096) if urlsplit(self.path).path in {"/api/people/enroll", "/api/vision/target"} else MAX_REQUEST_BODY_BYTES
        if length <= 0 or length > limit:
            self._send_json({"error": "invalid_body_size"}, status=HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            return None
        try:
            payload = json.loads(self.rfile.read(length))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_json({"error": "invalid_json"}, status=HTTPStatus.BAD_REQUEST)
            return None
        if not isinstance(payload, dict):
            self._send_json({"error": "body_must_be_object"}, status=HTTPStatus.BAD_REQUEST)
            return None
        return payload

    def _send_static(self, filename: str, content_type: str) -> None:
        body = (STATIC_ROOT / filename).read_bytes()
        if filename == "dashboard.html":
            if (FREESTYLE_ROOT / "body_control.js").is_file():
                body = body.replace(b'<script src="/assets/dashboard.js" defer></script>',
                    b'<script src="/assets/freestyle.js" defer></script><script src="/assets/dashboard.js" defer></script>')
            body = body.replace(
                b'data-dashboard-primary="camera"',
                f'data-dashboard-primary="{self.server.primary_view}"'.encode("ascii"),
                1,
            )
        self._send_bytes(body, content_type)

    def _send_bytes(
        self,
        body: bytes,
        content_type: str,
        *,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self.send_response(HTTPStatus.OK)
        self._security_headers()
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for name, value in (extra_headers or {}).items():
            self.send_header(name, value)
        try:
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            return

    def _send_json(
        self,
        payload: dict[str, object],
        *,
        status: int = HTTPStatus.OK,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self._security_headers()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        for name, value in (extra_headers or {}).items():
            self.send_header(name, value)
        try:
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            return

    def _security_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; connect-src 'self'; img-src 'self' blob:; "
            "frame-src http://127.0.0.1:8765",
        )
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")

    def log_message(self, format: str, *args: object) -> None:
        return None


def start_dashboard_server(
    host: str,
    port: int,
    *,
    gateway: GatewayService,
    event_loop: asyncio.AbstractEventLoop,
    password_store: DashboardPasswordStore,
    token_store: RobotTokenStore,
    audit_log: AuditLog | None = None,
    primary_view: str = "camera",
    hotspot: RobotHotspot | None = None,
    environment_adapter: EnvironmentAdapter | None = None,
) -> DashboardHttpServer:
    return DashboardHttpServer(
        (host, port),
        gateway=gateway,
        event_loop=event_loop,
        password_store=password_store,
        token_store=token_store,
        audit_log=audit_log,
        primary_view=primary_view,
        hotspot=hotspot,
        environment_adapter=environment_adapter,
    )


def _required_string(payload: dict[str, object], name: str) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _optional_string(payload: dict[str, object], name: str) -> str | None:
    value = payload.get(name)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _required_int(payload: dict[str, object], name: str) -> int:
    value = payload.get(name)
    if type(value) is not int:
        raise ValueError(f"{name} must be an integer")
    return value


def _required_number(payload: dict[str, object], name: str) -> float:
    value = payload.get(name)
    if type(value) not in {int, float} or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    return float(value)


def _required_bool(payload: dict[str, object], name: str) -> bool:
    value = payload.get(name)
    if type(value) is not bool:
        raise ValueError(f"{name} must be a boolean")
    return value


async def _test_tone_frames(
    volume_percent: int = DEFAULT_TEST_TONE_VOLUME_PERCENT,
) -> AsyncIterator[bytes]:
    if not 1 <= volume_percent <= 100:
        raise ValueError("volume_percent must be between 1 and 100")
    amplitude = round(PCM_S16_MAX * volume_percent / 100)
    phase = 0
    # The canonical speaker sender owns pacing for every PCM source.
    for _frame in range(TEST_TONE_FRAME_COUNT):
        samples = []
        for _sample in range(320):
            value = int(
                amplitude
                * math.sin(2.0 * math.pi * 440.0 * phase / 16000.0)
            )
            samples.append(value)
            phase += 1
        yield struct.pack("<320h", *samples)
