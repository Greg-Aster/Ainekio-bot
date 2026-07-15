from __future__ import annotations

import asyncio
import json
import math
import struct
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from gateway.security import DashboardPasswordStore, RobotTokenStore
from gateway.server.service import GatewayError, GatewayService
from protocol.control_v1 import ProtocolValidationError

from .auth import AuditLog, DashboardSession, DashboardSessions, LoginRateLimiter


MAX_REQUEST_BODY_BYTES = 16 * 1024
SESSION_COOKIE = "ainekio_dashboard_session"
STATIC_ROOT = Path(__file__).with_name("static")
STATIC_FILES = {
    "/": ("dashboard.html", "text/html; charset=utf-8", True),
    "/login": ("login.html", "text/html; charset=utf-8", False),
    "/assets/dashboard.css": ("dashboard.css", "text/css; charset=utf-8", False),
    "/assets/dashboard.js": ("dashboard.js", "text/javascript; charset=utf-8", False),
}


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
    ) -> None:
        super().__init__(server_address, DashboardHandler)
        self.gateway = gateway
        self.event_loop = event_loop
        self.password_store = password_store
        self.token_store = token_store
        self.audit_log = audit_log or AuditLog()
        self.sessions = DashboardSessions()
        self.login_limiter = LoginRateLimiter()
        self.stop_latched = False

    def call_gateway(self, awaitable: Any, *, timeout: float = 10.0) -> object:
        future = asyncio.run_coroutine_threadsafe(awaitable, self.event_loop)
        return future.result(timeout=timeout)


class DashboardHandler(BaseHTTPRequestHandler):
    server: DashboardHttpServer

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path in STATIC_FILES:
            filename, content_type, requires_auth = STATIC_FILES[path]
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
            self._send_json(
                {
                    **status,
                    "audit": self.server.audit_log.entries(),
                    "token_robot_ids": sorted(self.server.token_store.snapshot()),
                }
            )
            return
        self._send_json({"error": "not_found"}, status=HTTPStatus.NOT_FOUND)

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
        try:
            response = self._dispatch_api(path, payload)
        except GatewayError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.CONFLICT)
            return
        except (ProtocolValidationError, ValueError, KeyError) as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return
        except TimeoutError:
            self._send_json({"error": "gateway timeout"}, status=HTTPStatus.GATEWAY_TIMEOUT)
            return
        self._send_json(response)

    def _dispatch_api(self, path: str, payload: dict[str, object]) -> dict[str, object]:
        robot_id = _optional_string(payload, "robot_id")
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
            sequence = self.server.call_gateway(self.server.gateway.estop(robot_id=robot_id))
            self.server.stop_latched = True
            self.server.audit_log.record("stop_issued", robot_id=robot_id)
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
            sequence = self.server.call_gateway(
                self.server.gateway.set_camera(
                    on=_required_bool(payload, "on"),
                    fps=_required_int(payload, "fps"),
                    resolution=_required_string(payload, "res"),
                    robot_id=robot_id,
                )
            )
            return {"ok": True, "seq": sequence}
        if path == "/api/microphone":
            sequence = self.server.call_gateway(
                self.server.gateway.set_microphone(
                    on=_required_bool(payload, "on"),
                    gate=_required_string(payload, "gate"),
                    robot_id=robot_id,
                )
            )
            return {"ok": True, "seq": sequence}
        if path == "/api/speaker-test":
            sequence = self.server.call_gateway(
                self.server.gateway.tts_speak(
                    _test_tone_frames(),
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
            sequence = self.server.call_gateway(self.server.gateway.estop(robot_id=robot_id))
            self.server.stop_latched = True
            self.server.audit_log.record("stop_issued", robot_id=robot_id)
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

    def _login(self) -> None:
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
                    "Max-Age=28800"
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
        if length <= 0 or length > MAX_REQUEST_BODY_BYTES:
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
        self.send_response(HTTPStatus.OK)
        self._security_headers()
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

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
        self.end_headers()
        self.wfile.write(body)

    def _security_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; connect-src 'self'; frame-src http://127.0.0.1:8765",
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
) -> DashboardHttpServer:
    return DashboardHttpServer(
        (host, port),
        gateway=gateway,
        event_loop=event_loop,
        password_store=password_store,
        token_store=token_store,
        audit_log=audit_log,
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


def _test_tone_frames() -> list[bytes]:
    frames: list[bytes] = []
    phase = 0
    for _ in range(10):
        samples = []
        for _sample in range(320):
            value = int(5000 * math.sin(2.0 * math.pi * 440.0 * phase / 16000.0))
            samples.append(value)
            phase += 1
        frames.append(struct.pack("<320h", *samples))
    return frames
