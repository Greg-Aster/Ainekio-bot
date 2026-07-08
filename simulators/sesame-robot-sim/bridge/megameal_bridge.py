#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import socket
import ssl
import struct
import sys
from dataclasses import asdict
from typing import Any
from urllib.parse import urlparse

from ainekio_motion.backend import VirtualBackend
from ainekio_motion.commands import SUPPORTED_COMMANDS, parse_robot_command
from ainekio_motion.safety import SafetyController
from ainekio_motion.sequences import SequenceEngine
from ainekio_motion.types import MotionCommand, RobotCommand, now_ms

MEGAMEAL_ROBOT_ID = "ainekio-sesame"
DEFAULT_BRIDGE_URL = "ws://127.0.0.1:4322/__megameal-dev-bridge"
MIN_MEGAMEAL_ANGLE_DEG = -60.0
MAX_MEGAMEAL_ANGLE_DEG = 60.0
LEFT_SERVO_PREFIX = "L"


def hardware_servo_angle_to_megameal(servo: str, angle: float) -> float:
    """Convert hardware-style 0..180 servo angle to Megameal signed degrees."""

    relative = float(angle) - 90.0
    if servo.startswith(LEFT_SERVO_PREFIX):
        relative = -relative
    return max(MIN_MEGAMEAL_ANGLE_DEG, min(MAX_MEGAMEAL_ANGLE_DEG, relative))


def build_motion_event(
    command_name: str,
    *,
    issued_at_ms: int | None = None,
    ttl_ms: int = 1200,
    motor_stagger_ms: int = 20,
) -> dict[str, Any]:
    command = parse_robot_command(command_name)
    if command is None:
        supported = ", ".join(sorted(SUPPORTED_COMMANDS))
        raise ValueError(
            f"Unsupported robot command {command_name!r}. Supported: {supported}"
        )

    base_time = issued_at_ms if issued_at_ms is not None else now_ms()
    motion_command = MotionCommand(
        command,
        issued_at_ms=base_time,
        ttl_ms=ttl_ms,
        source="megameal-bridge",
    )
    safety = SafetyController()
    decision = safety.accept(motion_command, at_ms=base_time)
    backend = VirtualBackend(
        sequence_engine=SequenceEngine(motor_stagger_ms=motor_stagger_ms)
    )
    frames = backend.apply(decision.command, start_ms=0)
    payload_frames = [
        {
            "servo": frame.servo,
            "angleDeg": hardware_servo_angle_to_megameal(frame.servo, frame.angle),
            "atMs": frame.at_ms,
        }
        for frame in frames
    ]

    return {
        "schemaVersion": 1,
        "robot": MEGAMEAL_ROBOT_ID,
        "sequence": f"ainekio-motion:{decision.command.command.value}",
        "command": decision.command.command.value,
        "issuedAtMs": base_time,
        "ttlMs": decision.command.ttl_ms,
        "frames": payload_frames,
    }


def build_controller_command(
    motion_event: dict[str, Any],
    *,
    command_id: str | None = None,
    issued_at_ms: int | None = None,
    target_session_id: str | None = None,
) -> dict[str, Any]:
    issued_at = issued_at_ms if issued_at_ms is not None else now_ms()
    command: dict[str, Any] = {
        "id": command_id or f"ainekio-motion-{issued_at}",
        "issuedAt": issued_at,
        "type": "submitMotionEvent",
        "motionEvent": motion_event,
    }
    if target_session_id:
        command["targetSessionId"] = target_session_id
    return {"type": "controller:command", "command": command}


class WebSocketClient:
    def __init__(self, url: str, *, timeout: float = 5.0) -> None:
        self.url = url
        self.timeout = timeout
        self._socket: socket.socket | None = None

    def __enter__(self) -> "WebSocketClient":
        self.connect()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def connect(self) -> None:
        parsed = urlparse(self.url)
        if parsed.scheme not in {"ws", "wss"}:
            raise ValueError("Bridge URL must use ws:// or wss://")
        if not parsed.hostname:
            raise ValueError("Bridge URL must include a host")

        port = parsed.port or (443 if parsed.scheme == "wss" else 80)
        raw = socket.create_connection((parsed.hostname, port), timeout=self.timeout)
        raw.settimeout(self.timeout)
        if parsed.scheme == "wss":
            context = ssl.create_default_context()
            sock: socket.socket = context.wrap_socket(raw, server_hostname=parsed.hostname)
        else:
            sock = raw

        key = base64.b64encode(os.urandom(16)).decode("ascii")
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"
        host = parsed.hostname
        if parsed.port:
            host = f"{host}:{parsed.port}"

        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        )
        sock.sendall(request.encode("ascii"))
        response = self._read_http_response(sock)
        if b" 101 " not in response.split(b"\r\n", 1)[0]:
            raise RuntimeError(f"WebSocket upgrade failed: {response[:120]!r}")

        accept = self._header(response, b"sec-websocket-accept")
        expected = base64.b64encode(
            hashlib.sha1(
                (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")
            ).digest()
        ).decode("ascii")
        if accept != expected:
            raise RuntimeError("WebSocket upgrade returned an invalid accept key")

        self._socket = sock

    def send_json(self, value: dict[str, Any]) -> None:
        self._send_text(json.dumps(value, separators=(",", ":")))

    def receive_json(self) -> dict[str, Any]:
        text = self._receive_text()
        value = json.loads(text)
        if not isinstance(value, dict):
            raise RuntimeError("Bridge returned a non-object message")
        return value

    def close(self) -> None:
        if self._socket is None:
            return
        try:
            self._socket.sendall(b"\x88\x80" + os.urandom(4))
        finally:
            self._socket.close()
            self._socket = None

    @staticmethod
    def _read_http_response(sock: socket.socket) -> bytes:
        chunks: list[bytes] = []
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            chunks.append(chunk)
            response = b"".join(chunks)
            if b"\r\n\r\n" in response:
                return response
        raise RuntimeError("WebSocket upgrade returned no HTTP response")

    @staticmethod
    def _header(response: bytes, name: bytes) -> str | None:
        prefix = name.lower() + b":"
        for line in response.split(b"\r\n")[1:]:
            if line.lower().startswith(prefix):
                return line.split(b":", 1)[1].strip().decode("ascii")
        return None

    def _send_text(self, text: str) -> None:
        if self._socket is None:
            raise RuntimeError("WebSocket is not connected")
        payload = text.encode("utf-8")
        header = bytearray([0x81])
        length = len(payload)
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.extend([0x80 | 126])
            header.extend(struct.pack("!H", length))
        else:
            header.extend([0x80 | 127])
            header.extend(struct.pack("!Q", length))
        mask = os.urandom(4)
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        self._socket.sendall(bytes(header) + mask + masked)

    def _receive_text(self) -> str:
        if self._socket is None:
            raise RuntimeError("WebSocket is not connected")
        first = self._socket.recv(2)
        if len(first) < 2:
            raise RuntimeError("Incomplete WebSocket frame")
        opcode = first[0] & 0x0F
        length = first[1] & 0x7F
        if length == 126:
            length = struct.unpack("!H", self._read_exact(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", self._read_exact(8))[0]
        payload = self._read_exact(length)
        if opcode == 0x8:
            raise RuntimeError("WebSocket closed by bridge")
        if opcode != 0x1:
            raise RuntimeError(f"Unsupported WebSocket opcode {opcode}")
        return payload.decode("utf-8")

    def _read_exact(self, length: int) -> bytes:
        if self._socket is None:
            raise RuntimeError("WebSocket is not connected")
        chunks: list[bytes] = []
        remaining = length
        while remaining > 0:
            chunk = self._socket.recv(remaining)
            if not chunk:
                raise RuntimeError("Incomplete WebSocket frame payload")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)


def send_motion_event(
    url: str,
    motion_event: dict[str, Any],
    *,
    target_session_id: str | None = None,
    wait_for_result: bool = True,
) -> dict[str, Any] | None:
    message = build_controller_command(
        motion_event,
        target_session_id=target_session_id,
    )
    with WebSocketClient(url) as client:
        client.send_json({"type": "bridge:hello", "role": "controller"})
        ready = client.receive_json()
        if ready.get("type") != "bridge:ready":
            raise RuntimeError(f"Unexpected bridge hello response: {ready!r}")
        client.send_json(message)
        if not wait_for_result:
            return None
        while True:
            response = client.receive_json()
            if response.get("type") == "game:command-result":
                result = response.get("result")
                if not isinstance(result, dict):
                    raise RuntimeError("Bridge command result was malformed")
                return result


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Send safe Ainekio motion commands to Megameal."
    )
    parser.add_argument("command", help="Semantic robot command, for example walk")
    parser.add_argument("--url", default=DEFAULT_BRIDGE_URL, help="Megameal bridge URL")
    parser.add_argument("--ttl-ms", type=int, default=1200, help="Motion event TTL")
    parser.add_argument(
        "--motor-stagger-ms",
        type=int,
        default=20,
        help="Delay between servo frames in each sequence step",
    )
    parser.add_argument("--target-session-id", help="Optional Megameal session id")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the bridge command JSON without connecting",
    )
    parser.add_argument(
        "--no-wait",
        action="store_true",
        help="Send the command without waiting for a game command result",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    try:
        motion_event = build_motion_event(
            args.command,
            ttl_ms=args.ttl_ms,
            motor_stagger_ms=args.motor_stagger_ms,
        )
        controller_command = build_controller_command(
            motion_event,
            target_session_id=args.target_session_id,
        )
        if args.dry_run:
            print(json.dumps(controller_command, indent=2, sort_keys=True))
            return 0

        result = send_motion_event(
            args.url,
            motion_event,
            target_session_id=args.target_session_id,
            wait_for_result=not args.no_wait,
        )
        if result is not None:
            print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except Exception as error:
        print(f"megameal bridge error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
