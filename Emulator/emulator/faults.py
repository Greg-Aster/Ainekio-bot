from __future__ import annotations

import ipaddress
import json
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


MAX_FAULT_REQUEST_BYTES = 4096


@dataclass(frozen=True)
class FaultSnapshot:
    battery_volts: float
    control_stall_ms: int
    speaker_delay_ms: int
    drop_link_pending: bool
    oversize_camera_pending: bool
    malformed_control_pending: bool


class EmulatorFaultController:
    def __init__(self, *, battery_volts: float = 8.0) -> None:
        self._lock = threading.Lock()
        self._battery_volts = _bounded_float(battery_volts, 0.0, 20.0, "battery")
        self._control_stall_ms = 0
        self._speaker_delay_ms = 0
        self._drop_link = False
        self._oversize_camera = False
        self._malformed_control = False

    def snapshot(self) -> FaultSnapshot:
        with self._lock:
            return FaultSnapshot(
                self._battery_volts,
                self._control_stall_ms,
                self._speaker_delay_ms,
                self._drop_link,
                self._oversize_camera,
                self._malformed_control,
            )

    def set_battery(self, volts: float) -> None:
        value = _bounded_float(volts, 0.0, 20.0, "battery")
        with self._lock:
            self._battery_volts = value

    def set_control_stall(self, milliseconds: int) -> None:
        value = _bounded_int(milliseconds, 0, 30000, "control stall")
        with self._lock:
            self._control_stall_ms = value

    def set_speaker_delay(self, milliseconds: int) -> None:
        value = _bounded_int(milliseconds, 0, 5000, "speaker delay")
        with self._lock:
            self._speaker_delay_ms = value

    def request_drop_link(self) -> None:
        with self._lock:
            self._drop_link = True

    def request_oversize_camera(self) -> None:
        with self._lock:
            self._oversize_camera = True

    def request_malformed_control(self) -> None:
        with self._lock:
            self._malformed_control = True

    def take_drop_link(self) -> bool:
        return self._take("_drop_link")

    def take_oversize_camera(self) -> bool:
        return self._take("_oversize_camera")

    def take_malformed_control(self) -> bool:
        return self._take("_malformed_control")

    def _take(self, name: str) -> bool:
        with self._lock:
            value = bool(getattr(self, name))
            setattr(self, name, False)
            return value


class FaultControlServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], controller: EmulatorFaultController) -> None:
        _require_loopback(address[0])
        super().__init__(address, _FaultHandler)
        self.controller = controller


class _FaultHandler(BaseHTTPRequestHandler):
    server: FaultControlServer

    def do_GET(self) -> None:
        if self.path != "/status":
            self._send(404, {"error": "not_found"})
            return
        self._send(200, self.server.controller.snapshot().__dict__)

    def do_POST(self) -> None:
        try:
            payload = self._payload()
            controller = self.server.controller
            if self.path == "/battery":
                controller.set_battery(payload["volts"])
            elif self.path == "/stall-control":
                controller.set_control_stall(payload["milliseconds"])
            elif self.path == "/speaker-congestion":
                controller.set_speaker_delay(payload["milliseconds"])
            elif self.path == "/drop-link":
                controller.request_drop_link()
            elif self.path == "/oversize-camera":
                controller.request_oversize_camera()
            elif self.path == "/malformed-control":
                controller.request_malformed_control()
            else:
                self._send(404, {"error": "not_found"})
                return
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            self._send(400, {"error": "invalid_request"})
            return
        self._send(200, controller.snapshot().__dict__)

    def _payload(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if not 0 <= length <= MAX_FAULT_REQUEST_BYTES:
            raise ValueError("request body is oversized")
        if length == 0:
            return {}
        value = json.loads(self.rfile.read(length))
        if not isinstance(value, dict):
            raise ValueError("request body must be an object")
        return value

    def _send(self, status: int, payload: object) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *args: object) -> None:
        return None


def start_fault_control_server(
    host: str,
    port: int,
    controller: EmulatorFaultController,
) -> tuple[FaultControlServer, threading.Thread]:
    server = FaultControlServer((host, port), controller)
    thread = threading.Thread(
        target=server.serve_forever,
        name="ainekio-emulator-faults",
        daemon=True,
    )
    thread.start()
    return server, thread


def _require_loopback(host: str) -> None:
    try:
        address = ipaddress.ip_address(host)
    except ValueError as exc:
        raise ValueError("fault control host must be a loopback IP address") from exc
    if not address.is_loopback:
        raise ValueError("fault control server may only bind to loopback")


def _bounded_float(value: object, minimum: float, maximum: float, name: str) -> float:
    number = float(value)
    if not minimum <= number <= maximum:
        raise ValueError(f"{name} is out of range")
    return number


def _bounded_int(value: object, minimum: int, maximum: int, name: str) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{name} is out of range")
    return value
