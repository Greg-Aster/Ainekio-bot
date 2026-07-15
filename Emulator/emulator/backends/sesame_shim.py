from __future__ import annotations

import argparse
import json
import queue
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib import error, request

DEFAULT_SHIM_URL = "http://127.0.0.1:8788"
MAX_MOTION_BODY_BYTES = 16 * 1024
RESULT_TIMEOUT_SECONDS = 2.0
_RESULT_STATUSES = frozenset({"accepted", "rejected", "cancelled"})


@dataclass(frozen=True)
class MotionResult:
    status: str
    detail: str | None = None


@dataclass
class _PendingMotion:
    event: threading.Event
    result: MotionResult | None = None


class SimulatorShimClient:
    def __init__(self, base_url: str = DEFAULT_SHIM_URL, *, timeout_s: float = 3.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s

    def publish_motion(self, payload: dict[str, Any]) -> MotionResult:
        body = json.dumps(payload).encode("utf-8")
        req = request.Request(
            f"{self.base_url}/motion",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=self.timeout_s) as response:
                response_payload = json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"simulator shim HTTP {exc.code}: {detail}") from exc
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"simulator shim unavailable: {exc}") from exc

        status = response_payload.get("result")
        if status not in _RESULT_STATUSES:
            raise RuntimeError("simulator shim returned an invalid execution result")
        detail = response_payload.get("detail")
        return MotionResult(status=status, detail=detail if isinstance(detail, str) else None)


class MotionHub:
    def __init__(self) -> None:
        self._subscribers: set[queue.Queue[dict[str, Any]]] = set()
        self._pending: dict[str, _PendingMotion] = {}
        self._lock = threading.Lock()

    def subscribe(self) -> queue.Queue[dict[str, Any]]:
        subscriber: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
        with self._lock:
            self._subscribers.add(subscriber)
        return subscriber

    def unsubscribe(self, subscriber: queue.Queue[dict[str, Any]]) -> None:
        with self._lock:
            self._subscribers.discard(subscriber)

    def publish(self, payload: dict[str, Any]) -> int:
        with self._lock:
            self._publish_locked(payload)
            return len(self._subscribers)

    def publish_and_wait(
        self,
        payload: dict[str, Any],
        *,
        timeout_s: float,
    ) -> tuple[int, MotionResult | None]:
        action_id = payload.get("actionId")
        if not isinstance(action_id, str) or not action_id or len(action_id) > 128:
            raise ValueError("motion actionId must be a non-empty string of at most 128 characters")

        pending = _PendingMotion(event=threading.Event())
        with self._lock:
            if action_id in self._pending:
                raise ValueError("motion actionId is already pending")
            self._pending[action_id] = pending
            self._publish_locked(payload)
            subscribers = len(self._subscribers)

        if subscribers > 0:
            pending.event.wait(timeout_s)

        with self._lock:
            self._pending.pop(action_id, None)
            return subscribers, pending.result

    def report_result(self, action_id: str, result: MotionResult) -> bool:
        if result.status not in _RESULT_STATUSES:
            return False
        with self._lock:
            pending = self._pending.get(action_id)
            if pending is None or pending.result is not None:
                return False
            pending.result = result
            pending.event.set()
            return True

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {
                "subscribers": len(self._subscribers),
                "pending": len(self._pending),
            }

    def _publish_locked(self, payload: dict[str, Any]) -> None:
        for subscriber in self._subscribers:
            try:
                subscriber.get_nowait()
            except queue.Empty:
                pass
            subscriber.put_nowait(payload)


class SimulatorShimServer(ThreadingHTTPServer):
    def __init__(self, server_address: tuple[str, int]) -> None:
        super().__init__(server_address, SimulatorShimHandler)
        self.hub = MotionHub()


class SimulatorShimHandler(BaseHTTPRequestHandler):
    server: SimulatorShimServer

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._send_cors_headers()
        self.end_headers()

    def do_GET(self) -> None:
        if self.path in {"/", "/monitor"}:
            self._send_monitor()
            return
        if self.path == "/health":
            self._send_json({"ok": True, **self.server.hub.stats()})
            return
        if self.path == "/events":
            self._stream_events()
            return
        self.send_error(404, "not found")

    def do_POST(self) -> None:
        if self.path == "/motion":
            self._receive_motion()
            return
        if self.path == "/result":
            self._receive_result()
            return
        self.send_error(404, "not found")

    def _receive_motion(self) -> None:
        payload = self._read_json_object()
        if payload is None:
            return
        try:
            subscribers, result = self.server.hub.publish_and_wait(
                payload,
                timeout_s=RESULT_TIMEOUT_SECONDS,
            )
        except ValueError as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=400)
            return

        print(
            "[simulator-shim] motion "
            f"command={payload.get('command', 'unknown')} "
            f"session={payload.get('sessionId', '-')} "
            f"frames={len(payload.get('frames', [])) if isinstance(payload.get('frames'), list) else 0} "
            f"subscribers={subscribers} "
            f"result={result.status if result else 'unavailable'}"
        )
        if subscribers == 0:
            self._send_json(
                {
                    "ok": True,
                    "subscribers": 0,
                    "result": "accepted",
                    "detail": "headless execution; no renderer subscriber",
                }
            )
            return
        if result is None:
            self._send_json({"ok": False, "error": "renderer result timeout"}, status=504)
            return
        if result.status != "accepted":
            self._send_json(
                {"ok": False, "error": result.detail or result.status},
                status=409,
            )
            return
        self._send_json(
            {
                "ok": True,
                "subscribers": subscribers,
                "result": result.status,
                "detail": result.detail,
            }
        )

    def _receive_result(self) -> None:
        payload = self._read_json_object()
        if payload is None:
            return
        action_id = payload.get("actionId")
        status = payload.get("status")
        detail = payload.get("detail")
        if (
            not isinstance(action_id, str)
            or not action_id
            or len(action_id) > 128
            or status not in _RESULT_STATUSES
            or (detail is not None and not isinstance(detail, str))
        ):
            self._send_json({"ok": False, "error": "invalid result payload"}, status=400)
            return
        accepted = self.server.hub.report_result(
            action_id,
            MotionResult(status=status, detail=detail),
        )
        self._send_json({"ok": accepted}, status=200 if accepted else 409)

    def _read_json_object(self) -> dict[str, Any] | None:
        raw_length = self.headers.get("Content-Length", "0") or "0"
        try:
            length = int(raw_length)
        except ValueError:
            self.send_error(400, "invalid Content-Length")
            return None
        if length <= 0 or length > MAX_MOTION_BODY_BYTES:
            self.send_error(413, "request body is empty or too large")
            return None
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self.send_error(400, "invalid JSON")
            return None
        if not isinstance(payload, dict):
            self.send_error(400, "payload must be an object")
            return None
        return payload

    def log_message(self, format: str, *args: object) -> None:
        print(f"[simulator-shim] {self.address_string()} - {format % args}")

    def _stream_events(self) -> None:
        subscriber = self.server.hub.subscribe()
        self.send_response(200)
        self._send_cors_headers()
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        self.wfile.write(b"event: connected\ndata: {\"ok\":true}\n\n")
        self.wfile.flush()

        try:
            while True:
                payload = subscriber.get()
                self._write_motion_event(payload)
        except (BrokenPipeError, ConnectionResetError):
            return
        finally:
            self.server.hub.unsubscribe(subscriber)

    def _write_motion_event(self, payload: dict[str, Any]) -> None:
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.wfile.write(b"event: motion\n")
        self.wfile.write(b"data: " + data + b"\n\n")
        self.wfile.flush()

    def _send_json(self, payload: dict[str, Any], *, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self._send_cors_headers()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_monitor(self) -> None:
        body = b"""<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Ainekio Simulator Monitor</title>
    <style>
      html, body { margin: 0; min-height: 100%; background: #0f172a; color: #f8fafc; font: 14px/1.4 system-ui, sans-serif; }
      main { max-width: 760px; margin: 0 auto; padding: 24px; }
      .stage { position: relative; height: 360px; border: 1px solid #334155; background: linear-gradient(#1e293b 1px, transparent 1px), linear-gradient(90deg, #1e293b 1px, transparent 1px); background-size: 24px 24px; overflow: hidden; }
      .bot { position: absolute; left: 50%; top: 50%; width: 36px; height: 46px; margin: -23px 0 0 -18px; border-radius: 9px; background: #38bdf8; box-shadow: 0 0 0 5px rgba(56, 189, 248, 0.2); transition: transform 260ms ease; }
      .bot:before { content: ""; position: absolute; left: 12px; top: -13px; border-left: 6px solid transparent; border-right: 6px solid transparent; border-bottom: 13px solid #38bdf8; }
      .grid { display: grid; grid-template-columns: 140px 1fr; gap: 8px 16px; margin-top: 16px; }
      .label { color: #94a3b8; }
      .ok { color: #86efac; }
      .bad { color: #fca5a5; }
      code { color: #bae6fd; }
    </style>
  </head>
  <body>
    <main>
      <h1>Ainekio Simulator Monitor</h1>
      <p>Keep this page open while an Ainekio emulator backend runs. It listens to <code>/events</code>.</p>
      <div class="stage"><div id="bot" class="bot"></div></div>
      <div class="grid">
        <div class="label">status</div><div id="status" class="bad">offline</div>
        <div class="label">command</div><div id="command">none</div>
        <div class="label">frames</div><div id="frames">0</div>
        <div class="label">session</div><div id="session">-</div>
      </div>
    </main>
    <script>
      let x = 0, y = 0, yaw = 0;
      const status = document.getElementById("status");
      const setText = (id, value) => document.getElementById(id).textContent = String(value);
      const setStatus = (online) => {
        status.textContent = online ? "online" : "offline";
        status.className = online ? "ok" : "bad";
      };
      const events = new EventSource("/events");
      events.addEventListener("connected", () => setStatus(true));
      events.addEventListener("motion", (event) => {
        setStatus(true);
        const payload = JSON.parse(event.data);
        const root = payload.rootMotion || {};
        x += Number(root.strafe || 0) * 32;
        y -= Number(root.forward || 0) * 40;
        yaw += Number(root.yaw || 0) * 25;
        x = Math.max(-330, Math.min(330, x));
        y = Math.max(-150, Math.min(150, y));
        document.getElementById("bot").style.transform = `translate(${x}px, ${y}px) rotate(${yaw}deg)`;
        setText("command", payload.command || "unknown");
        setText("frames", Array.isArray(payload.frames) ? payload.frames.length : 0);
        setText("session", payload.sessionId || "-");
      });
      events.onerror = () => setStatus(false);
    </script>
  </body>
</html>
"""
        self.send_response(200)
        self._send_cors_headers()
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")


def run_server(host: str = "127.0.0.1", port: int = 8788) -> None:
    server = SimulatorShimServer((host, port))
    print(f"Serving Ainekio simulator shim at http://{host}:{port}/")
    print(f"Open the shim monitor at http://{host}:{port}/monitor")
    print("Open the Sesame simulator at http://127.0.0.1:8765/ and keep this process running.")
    server.serve_forever()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the Ainekio host-emulator renderer shim.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8788)
    args = parser.parse_args(argv)
    run_server(args.host, args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
