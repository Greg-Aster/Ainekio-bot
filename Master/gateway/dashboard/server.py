from __future__ import annotations

import asyncio
import json
import math
import struct
import threading
from collections.abc import AsyncIterator
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from gateway.security import DashboardPasswordStore, RobotTokenStore, _atomic_secure_json, _read_json
from gateway.environment_adapter import EnvironmentAdapter
from gateway.hotspot import RobotHotspot
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
STATIC_FILES = {
    "/": ("dashboard.html", "text/html; charset=utf-8", True),
    "/login": ("login.html", "text/html; charset=utf-8", False),
    "/assets/dashboard.css": ("dashboard.css", "text/css; charset=utf-8", False),
    "/assets/dashboard.js": ("dashboard.js", "text/javascript; charset=utf-8", False),
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
        self.camera_recognition = None
        self.control_settings_path = password_store.path.with_name("sensing-controls.json")
        self.control_settings = (_read_json(self.control_settings_path)
            if self.control_settings_path.exists() else {"recognition": True, "cameras": {}})
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
        self._camera_frames: dict[str, tuple[int, bytes]] = {}
        gateway.subscribe_frames(self._record_camera_frame)

    def call_gateway(self, awaitable: Any, *, timeout: float = 10.0) -> object:
        future = asyncio.run_coroutine_threadsafe(awaitable, self.event_loop)
        return future.result(timeout=timeout)

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
            self._camera_frames[robot_id] = (counter, payload)
            self._camera_condition.notify_all()

    def wait_for_camera_frame(
        self,
        robot_id: str,
        after_counter: int | None,
        *,
        timeout: float = 10.0,
    ) -> tuple[int, bytes] | None:
        def frame_is_new() -> bool:
            frame = self._camera_frames.get(robot_id)
            return frame is not None and (
                after_counter is None or frame[0] != after_counter
            )

        with self._camera_condition:
            if not self._camera_condition.wait_for(frame_is_new, timeout=timeout):
                return None
            return self._camera_frames[robot_id]


class DashboardHandler(BaseHTTPRequestHandler):
    server: DashboardHttpServer

    def do_GET(self) -> None:
        parsed_url = urlsplit(self.path)
        path = parsed_url.path
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
            status = self.server.call_gateway(self.server.gateway.status_snapshot())
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
                    "person_recognition": self.server.call_gateway(self.server.person_status()),
                    "recognition": ({"configured": True, "enabled": self.server.camera_recognition.enabled,
                        "maxAgeMs": self.server.camera_recognition.max_frame_age_s * 1000,
                        **self.server.camera_recognition.metrics()}
                        if self.server.camera_recognition is not None else {"configured": False, "enabled": False}),
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
        if path == "/api/camera/frame":
            if self._require_session() is None:
                return
            self._camera_frame(parsed_url.query)
            return
        self._send_json({"error": "not_found"}, status=HTTPStatus.NOT_FOUND)

    def _speech_output(self, output_target: str | None = None) -> dict[str, object]:
        adapter = self.server.environment_adapter
        if adapter is None:
            raise GatewayError("MetaHuman Environment Bridge is not configured")
        return self.server.call_gateway(adapter.speech_output_settings(output_target))

    def _camera_frame(self, query_string: str) -> None:
        query = parse_qs(query_string, keep_blank_values=True)
        robot_ids = query.get("robot_id", [])
        if len(robot_ids) != 1 or not robot_ids[0]:
            self._send_json(
                {"error": "robot_id is required"},
                status=HTTPStatus.BAD_REQUEST,
            )
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
        frame = self.server.wait_for_camera_frame(robot_ids[0], after_counter)
        if frame is None:
            self.send_response(HTTPStatus.NO_CONTENT)
            self._security_headers()
            self.end_headers()
            return
        counter, payload = frame
        try:
            self._send_bytes(
                payload,
                "image/jpeg",
                extra_headers={"X-Ainekio-Camera-Counter": str(counter)},
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

    def _dispatch_api(self, path: str, payload: dict[str, object]) -> dict[str, object]:
        robot_id = _optional_string(payload, "robot_id")
        if path in {"/api/people/enroll", "/api/people/forget"}:
            camera = self.server.camera_recognition
            if camera is None:
                raise GatewayError("Named-person recognition is not configured")
            if path.endswith("/enroll"):
                return self.server.call_gateway(camera.enroll_person(payload), timeout=30)
            return self.server.call_gateway(camera.forget_person(_required_string(payload, "personId")))
        if path == "/api/recognition":
            return self.server.call_gateway(self.server.set_recognition(_required_bool(payload, "enabled")))
        if path == "/api/behavior-control":
            adapter = self.server.environment_adapter
            if adapter is None:
                raise GatewayError("MetaHuman Environment Bridge is not configured")
            enabled = _required_bool(payload, "enabled") if "enabled" in payload else None
            return self.server.call_gateway(adapter.behavior_settings(enabled))
        if path == "/api/speech-output":
            target = _required_string(payload, "outputTarget")
            if target not in {"local", "robot"}:
                raise ValueError("outputTarget must be local or robot")
            response = self._speech_output(target)
            self.server.audit_log.record("speech_output_changed", output_target=target)
            return response
        if path == "/api/settings/network":
            network = self.server.call_gateway(
                self.server.hotspot.set_enabled(_required_bool(payload, "hotspot"))
            )
            self.server.audit_log.record("host_network_changed", **network)
            return {"ok": True, "host_network": network}
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
        limit = (MAX_JPEG_BYTES * 4 // 3 + 4096) if urlsplit(self.path).path == "/api/people/enroll" else MAX_REQUEST_BODY_BYTES
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
