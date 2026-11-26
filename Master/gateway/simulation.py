"""Virtual simulation server, pairing builder, and headless host runner.

Single Body Control owner for:
  1. Serving the static `simulator.ainek.io/dist` bundle locally on a dedicated
     HTTP port (default 8792) so LAN and headless browsers run without HTTPS
     mixed-content blocks or weakening Body Control's admin CSP on :8791.
  2. Provisioning scoped virtual robot tokens (`ainekio-v2-sim`, `ainekio-v3-sim`,
     `ainekio-v1-sim`) in `RobotTokenStore` without touching physical robot pairings.
  3. Generating zero-log `#hash` launch URLs and `ainekio-pair:` codes for both
     the local simulator server and remote `https://simulator.ainek.io`, including
     multiplayer room create/join options.
  4. Running a managed headless Chromium/Chrome process on the Brain host so an
     autonomous robot can wander the virtual world and stay in a multiplayer room
     24/7 even when all operator browsers are closed.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode, urlsplit

from gateway.security import RobotTokenStore
from gateway.server.service import GatewayError, GatewayService


VALID_SIM_MODELS = ("v1", "v2", "v3")
VALID_SIM_LEVELS = (
    "v2_lab",
    "observatory",
    "yggdrasil",
    "miranda",
    "solitude",
    "sci-fi-room",
)
VALID_MP_MODES = ("solo", "host", "join")

DEFAULT_REMOTE_SIMULATOR_URL = "https://simulator.ainek.io"
DEFAULT_SIMULATOR_PORT = 8792

_ROOM_SANITIZE_RE = re.compile(r"[^a-z0-9-]+")
_ROBOT_ID_RE = re.compile(r"^[A-Za-z0-9._-]{3,64}$")

_MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".xml": "application/xml; charset=utf-8",
    ".wasm": "application/wasm",
    ".glb": "model/gltf-binary",
    ".bin": "application/octet-stream",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
    ".txt": "text/plain; charset=utf-8",
}


def default_simulator_dist_dir() -> Path:
    env_dir = os.environ.get("AINEKIO_SIMULATOR_DIST", "").strip()
    if env_dir:
        return Path(env_dir).expanduser().resolve()
    repo_root = Path(__file__).resolve().parents[2]
    candidates = (
        repo_root / "apps" / "simulator" / "dist",
        repo_root / "apps" / "simulator.ainek.io" / "dist",
        repo_root.parent / "Merkin" / "apps" / "simulator.ainek.io" / "dist",
    )
    for candidate in candidates:
        if (candidate / "index.html").is_file():
            return candidate.resolve()
    return candidates[0].resolve()


def find_chrome_binary() -> str | None:
    env_bin = os.environ.get("AINEKIO_CHROME_BIN", "").strip()
    if env_bin and os.path.isfile(env_bin) and os.access(env_bin, os.X_OK):
        return env_bin
    for candidate in (
        "google-chrome",
        "google-chrome-stable",
        "chromium",
        "chromium-browser",
    ):
        found = shutil.which(candidate)
        if found:
            return found
    return None


def normalize_room_name(room: str) -> str:
    collapsed = re.sub(r"\s+", "-", room.strip().lower())
    return _ROOM_SANITIZE_RE.sub("", collapsed)[:48]


def default_robot_id_for_model(model: str) -> str:
    if model not in VALID_SIM_MODELS:
        return "ainekio-v2-sim"
    return f"ainekio-{model}-sim"


def encode_pairing_code(bundle: dict[str, Any]) -> str:
    raw = json.dumps(bundle, separators=(",", ":")).encode("utf-8")
    b64 = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    return f"ainekio-pair:{b64}"


def build_launch_url(base_url: str, bundle: dict[str, Any]) -> str:
    clean_base = base_url.strip().rstrip("/") + "/"
    params = {k: str(v) for k, v in bundle.items() if v is not None and str(v) != ""}
    return f"{clean_base}#{urlencode(params)}"


class _SimulatorStaticServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, server_address: tuple[str, int], dist_root: Path) -> None:
        self.dist_root = dist_root.resolve()
        super().__init__(server_address, _SimulatorStaticHandler)


class _SimulatorStaticHandler(BaseHTTPRequestHandler):
    server: _SimulatorStaticServer

    def log_message(self, format: str, *args: object) -> None:
        # Keep static asset requests quiet in gateway console logs.
        return

    def do_HEAD(self) -> None:
        self._serve(send_body=False)

    def do_GET(self) -> None:
        self._serve(send_body=True)

    def _serve(self, *, send_body: bool) -> None:
        raw_path = urlsplit(self.path).path
        rel = raw_path.lstrip("/")
        if not rel or raw_path.endswith("/"):
            rel = f"{rel}index.html"
        root = self.server.dist_root
        try:
            target = (root / rel).resolve()
            target.relative_to(root)
        except (ValueError, OSError):
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        if target.is_dir():
            target = (target / "index.html").resolve()
        if not target.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content_type = _MIME_TYPES.get(target.suffix.lower(), "application/octet-stream")
        try:
            data = target.read_bytes()
        except OSError:
            self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if send_body:
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                return


class SimulationManager:
    def __init__(
        self,
        *,
        gateway: GatewayService,
        event_loop: Any,
        token_store: RobotTokenStore,
        bind_host: str = "127.0.0.1",
        gateway_port: int = 8790,
        simulator_port: int | None = None,
        dist_dir: Path | None = None,
        chrome_bin: str | None = None,
        initial_settings: dict[str, Any] | None = None,
        save_settings_cb: Callable[[dict[str, Any]], None] | None = None,
        on_event: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        self._gateway = gateway
        self._event_loop = event_loop
        self._token_store = token_store
        self._bind_host = bind_host
        self._gateway_port = int(gateway_port)
        env_port = os.environ.get("AINEKIO_SIMULATOR_PORT", "").strip()
        self._requested_port = (
            int(simulator_port)
            if simulator_port is not None
            else (int(env_port) if env_port else DEFAULT_SIMULATOR_PORT)
        )
        self._explicit_dist_dir = dist_dir.resolve() if dist_dir is not None else None
        self._chrome_bin = chrome_bin if chrome_bin is not None else find_chrome_binary()
        self._save_settings_cb = save_settings_cb
        self._on_event = on_event
        self._lock = threading.RLock()

        default_cf_host = os.environ.get("AINEKIO_CLOUDFLARE_ROBOT_HOSTNAME", "robot-gateway.ainek.io").strip()
        default_remote_ws = f"wss://{default_cf_host}/robot" if default_cf_host else "wss://robot-gateway.ainek.io/robot"

        saved = dict(initial_settings or {})
        model = str(saved.get("model") or "v2")
        if model not in VALID_SIM_MODELS:
            model = "v2"
        level = str(saved.get("level") or "v2_lab")
        if level not in VALID_SIM_LEVELS:
            level = "v2_lab"
        mp = str(saved.get("mp") or "solo")
        if mp not in VALID_MP_MODES:
            mp = "solo"

        self._settings: dict[str, Any] = {
            "model": model,
            "robot_id": str(saved.get("robot_id") or default_robot_id_for_model(model)),
            "level": level,
            "mp": mp,
            "room": normalize_room_name(str(saved.get("room") or "")),
            "display_name": str(saved.get("display_name") or "").strip()[:24],
            "remote_simulator_url": str(saved.get("remote_simulator_url") or DEFAULT_REMOTE_SIMULATOR_URL).strip()
            or DEFAULT_REMOTE_SIMULATOR_URL,
            "remote_ws_url": str(saved.get("remote_ws_url") or default_remote_ws).strip() or default_remote_ws,
        }

        self._http_server: _SimulatorStaticServer | None = None
        self._http_thread: threading.Thread | None = None
        self._http_error: str | None = None

        self._headless_proc: subprocess.Popen[bytes] | None = None
        self._headless_profile_dir: Path | None = None
        self._headless_config: dict[str, Any] | None = None
        self._headless_started_at: float | None = None
        self._headless_last_error: str | None = None

    def _emit(self, event: str, **data: Any) -> None:
        if self._on_event is not None:
            try:
                self._on_event(event, data)
            except Exception:
                pass

    @property
    def dist_dir(self) -> Path:
        return self._explicit_dist_dir if self._explicit_dist_dir is not None else default_simulator_dist_dir()

    def dist_available(self) -> bool:
        return (self.dist_dir / "index.html").is_file()

    def ensure_local_server(self) -> int:
        with self._lock:
            if self._http_server is not None:
                return int(self._http_server.server_address[1])
            dist_root = self.dist_dir
            if not (dist_root / "index.html").is_file():
                self._http_error = f"Built simulator bundle not found at {dist_root}"
                raise GatewayError(self._http_error)
            bind = "0.0.0.0" if self._bind_host == "0.0.0.0" else "127.0.0.1"
            try:
                srv = _SimulatorStaticServer((bind, self._requested_port), dist_root)
            except OSError:
                # Fall back to an ephemeral port if the default port is already in use.
                srv = _SimulatorStaticServer((bind, 0), dist_root)
            self._http_server = srv
            self._http_error = None
            t = threading.Thread(target=srv.serve_forever, name="ainekio-local-simulator", daemon=True)
            self._http_thread = t
            t.start()
            port = int(srv.server_address[1])
            self._emit("local_simulator_server_started", bind=bind, port=port)
            return port

    def _validate_and_apply_options(self, payload: dict[str, Any]) -> dict[str, Any]:
        model = str(payload.get("model") or self._settings["model"]).strip().lower()
        if model not in VALID_SIM_MODELS:
            raise ValueError(f"Unsupported simulator robot model: {model}")
        prev_model = self._settings["model"]
        raw_robot_id = str(payload.get("robot_id") or "").strip()
        if not raw_robot_id:
            if model != prev_model and self._settings["robot_id"] == default_robot_id_for_model(prev_model):
                robot_id = default_robot_id_for_model(model)
            else:
                robot_id = self._settings["robot_id"]
        else:
            robot_id = raw_robot_id
        if not _ROBOT_ID_RE.fullmatch(robot_id):
            raise ValueError("Invalid virtual robot_id")

        level = str(payload.get("level") or self._settings["level"]).strip()
        if level not in VALID_SIM_LEVELS:
            raise ValueError(f"Unsupported simulator level: {level}")

        mp = str(payload.get("mp") or self._settings["mp"]).strip().lower()
        if mp not in VALID_MP_MODES:
            raise ValueError(f"Unsupported multiplayer mode: {mp}")

        room = normalize_room_name(
            str(payload["room"]) if "room" in payload and payload["room"] is not None else self._settings["room"]
        )
        if mp == "host" and not room:
            room = "ainekio-world"
        if mp in ("host", "join") and len(room) < 3:
            raise ValueError("Multiplayer room name must be at least 3 letters or numbers")

        display_name = (
            str(payload["display_name"]).strip()[:24]
            if "display_name" in payload and payload["display_name"] is not None
            else self._settings["display_name"]
        )
        remote_sim_url = (
            str(payload.get("remote_simulator_url") or self._settings["remote_simulator_url"]).strip()
            or DEFAULT_REMOTE_SIMULATOR_URL
        )
        if not (remote_sim_url.startswith("https://") or remote_sim_url.startswith("http://")):
            raise ValueError("Remote simulator URL must start with https:// or http://")

        remote_ws_url = str(payload.get("remote_ws_url") or self._settings["remote_ws_url"]).strip()
        if remote_ws_url and not (remote_ws_url.startswith("ws://") or remote_ws_url.startswith("wss://")):
            if remote_ws_url.startswith("https://"):
                remote_ws_url = "wss://" + remote_ws_url[len("https://") :]
            elif remote_ws_url.startswith("http://"):
                remote_ws_url = "ws://" + remote_ws_url[len("http://") :]
            else:
                remote_ws_url = f"wss://{remote_ws_url}"
        if remote_ws_url and urlsplit(remote_ws_url).path in ("", "/"):
            remote_ws_url = remote_ws_url.rstrip("/") + "/robot"

        self._settings.update(
            {
                "model": model,
                "robot_id": robot_id,
                "level": level,
                "mp": mp,
                "room": room,
                "display_name": display_name,
                "remote_simulator_url": remote_sim_url,
                "remote_ws_url": remote_ws_url,
            }
        )
        if self._save_settings_cb is not None:
            try:
                self._save_settings_cb(dict(self._settings))
            except Exception:
                pass
        return dict(self._settings)

    def _ensure_token(self, robot_id: str, *, rotate: bool = False) -> str:
        existing = self._token_store.snapshot().get(robot_id)
        if existing and not rotate:
            self._event_loop.call_soon_threadsafe(self._gateway.set_token, robot_id, existing)
            return existing
        token = self._token_store.generate(robot_id)
        self._event_loop.call_soon_threadsafe(self._gateway.set_token, robot_id, token)
        self._emit("virtual_robot_token_provisioned", robot_id=robot_id, rotated=rotate)
        return token

    def _reap_headless_locked(self) -> None:
        proc = self._headless_proc
        if proc is None:
            return
        rc = proc.poll()
        if rc is None:
            return
        self._headless_proc = None
        if rc != 0 and self._headless_last_error is None:
            self._headless_last_error = f"Headless browser exited (code {rc})"
        self._cleanup_profile_dir_locked()

    def _cleanup_profile_dir_locked(self) -> None:
        pdir = self._headless_profile_dir
        self._headless_profile_dir = None
        if pdir is not None:
            shutil.rmtree(pdir, ignore_errors=True)

    def _host_from_request(self, request_host: str | None) -> str:
        if not request_host:
            return "127.0.0.1"
        raw = request_host.strip()
        if raw.startswith("[") and "]" in raw:
            return raw[: raw.index("]") + 1]
        return raw.split(":")[0] or "127.0.0.1"

    def _effective_local_host(self, request_host: str | None, client_host: str | None) -> str:
        """Prefer 127.0.0.1 when the browser is on the Brain host itself so
        Firefox/Chrome grant a Secure Context (`navigator.mediaDevices`) for Tap to Talk.
        """
        host_only = self._host_from_request(request_host)
        if client_host:
            clean_client = client_host.strip()
            if clean_client in ("127.0.0.1", "::1", "::ffff:127.0.0.1") or clean_client == host_only:
                return "127.0.0.1"
        return host_only

    def status(
        self,
        *,
        request_host: str | None = None,
        client_host: str | None = None,
        include_secrets: bool = False,
        robots: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            self._reap_headless_locked()
            cfg = dict(self._settings)
            sim_port: int | None = None
            if self._http_server is not None:
                sim_port = int(self._http_server.server_address[1])
            elif include_secrets and self.dist_available():
                try:
                    sim_port = self.ensure_local_server()
                except GatewayError:
                    sim_port = None

            host_only = self._effective_local_host(request_host, client_host)
            local_ws = f"ws://{host_only}:{self._gateway_port}/robot"
            local_sim_base = f"http://{host_only}:{sim_port}" if sim_port is not None else None
            remote_sim_base = cfg["remote_simulator_url"].rstrip("/")
            remote_ws = (
                local_ws
                if host_only in ("127.0.0.1", "localhost", "[::1]")
                and not os.environ.get("AINEKIO_CLOUDFLARE_TUNNEL_ID", "").strip()
                and cfg["remote_ws_url"] == "wss://robot-gateway.ainek.io/robot"
                else cfg["remote_ws_url"]
            )

            if robots is not None:
                gw_robots = robots
            else:
                status_fn = getattr(self._gateway, "status", None)
                gw_robots = status_fn().get("robots", {}) if callable(status_fn) else {}
            active_id = cfg["robot_id"]
            conn_info = gw_robots.get(active_id)
            room = cfg["room"]
            headless_running = self._headless_proc is not None
            hc = dict(self._headless_config) if (headless_running and self._headless_config) else None
            active_room = (hc.get("room") if hc else None) or (room if len(room) >= 3 else None)
            viewer_level = (hc.get("level") if hc else None) or cfg["level"]
            room_invite_url = (
                f"{remote_sim_base}/?room={active_room}" if active_room else None
            )
            local_room_invite_url = (
                f"{local_sim_base}/?room={active_room}" if local_sim_base and active_room else None
            )
            local_viewer_url = (
                build_launch_url(local_sim_base, {"level": viewer_level, "mp": "join", "room": active_room})
                if local_sim_base and active_room
                else None
            )
            remote_viewer_url = (
                build_launch_url(remote_sim_base, {"level": viewer_level, "mp": "join", "room": active_room})
                if active_room
                else None
            )
            viewer_mode = bool(headless_running and hc and hc.get("room"))

            out: dict[str, Any] = {
                "settings": cfg,
                "models": list(VALID_SIM_MODELS),
                "levels": list(VALID_SIM_LEVELS),
                "local_server": {
                    "available": self.dist_available(),
                    "running": self._http_server is not None,
                    "port": sim_port,
                    "url": f"{local_sim_base}/" if local_sim_base else None,
                    "error": self._http_error,
                },
                "headless": {
                    "supported": self._chrome_bin is not None and self.dist_available(),
                    "chrome_available": self._chrome_bin is not None,
                    "running": headless_running,
                    "pid": self._headless_proc.pid if self._headless_proc is not None else None,
                    "started_at": self._headless_started_at if headless_running else None,
                    "config": hc,
                    "error": self._headless_last_error,
                },
                "robot": {
                    "robot_id": active_id,
                    "paired": active_id in self._token_store.snapshot(),
                    "connected": bool(conn_info and conn_info.get("connected")),
                    "epoch": conn_info.get("epoch") if isinstance(conn_info, dict) else None,
                    "model": conn_info.get("model") if isinstance(conn_info, dict) else None,
                },
                "links": {
                    "local_ws_url": local_ws,
                    "remote_ws_url": cfg["remote_ws_url"],
                    "room_invite_url": room_invite_url,
                    "local_room_invite_url": local_room_invite_url,
                },
            }

            if include_secrets:
                token = self._ensure_token(active_id, rotate=False)
                common_bundle = {
                    "robotId": active_id,
                    "token": token,
                    "model": cfg["model"],
                    "level": cfg["level"],
                    "mp": cfg["mp"],
                    **({"room": room} if room and cfg["mp"] != "solo" else {}),
                    **({"name": cfg["display_name"]} if cfg["display_name"] else {}),
                }
                local_bundle = {"bc": local_ws, **common_bundle}
                remote_bundle = {"bc": cfg["remote_ws_url"], **common_bundle}
                same_machine_remote_bundle = {"bc": remote_ws, **common_bundle}
                out["launch"] = {
                    "robot_id": active_id,
                    "viewer_mode": viewer_mode,
                    "local_viewer_url": local_viewer_url,
                    "remote_viewer_url": remote_viewer_url,
                    "local_simulator_url": (
                        build_launch_url(local_sim_base, local_bundle) if local_sim_base else None
                    ),
                    "remote_simulator_url": build_launch_url(remote_sim_base, same_machine_remote_bundle),
                    "remote_wan_simulator_url": build_launch_url(remote_sim_base, remote_bundle),
                    "pairing_code": encode_pairing_code(remote_bundle),
                    "local_pairing_code": encode_pairing_code(local_bundle),
                }
            return out

    def start_local_server(
        self, *, request_host: str | None = None, client_host: str | None = None
    ) -> dict[str, Any]:
        with self._lock:
            self.ensure_local_server()
            return self.status(request_host=request_host, client_host=client_host, include_secrets=True)

    def prepare(
        self,
        payload: dict[str, Any],
        *,
        request_host: str | None = None,
        client_host: str | None = None,
        rotate: bool = False,
        for_tab: bool = False,
    ) -> dict[str, Any]:
        with self._lock:
            self._reap_headless_locked()
            cfg = self._validate_and_apply_options(payload)
            stopped_solo_headless = False
            if (
                for_tab
                and self._headless_proc is not None
                and self._headless_config is not None
                and not self._headless_config.get("room")
                and self._headless_config.get("robot_id") == cfg["robot_id"]
            ):
                # A Solo background runner has no multiplayer room to view and
                # would otherwise compete with the newly opened interactive tab
                # for the same `/robot` session.
                self.stop_headless_locked()
                stopped_solo_headless = True
            if rotate:
                self._ensure_token(cfg["robot_id"], rotate=True)
            res = self.status(request_host=request_host, client_host=client_host, include_secrets=True)
            if stopped_solo_headless and "launch" in res:
                res["launch"]["stopped_solo_headless"] = True
            return res

    def start_headless(
        self, payload: dict[str, Any], *, request_host: str | None = None, client_host: str | None = None
    ) -> dict[str, Any]:
        with self._lock:
            cfg = self._validate_and_apply_options(payload)
            if not self._chrome_bin:
                raise GatewayError("No Chrome or Chromium binary found on this host for background simulation")
            sim_port = self.ensure_local_server()
            self.stop_headless_locked()

            token = self._ensure_token(cfg["robot_id"], rotate=False)
            room = cfg["room"]
            bundle = {
                "bc": f"ws://127.0.0.1:{self._gateway_port}/robot",
                "robotId": cfg["robot_id"],
                "token": token,
                "model": cfg["model"],
                "level": cfg["level"],
                "mp": cfg["mp"],
                **({"room": room} if room and cfg["mp"] != "solo" else {}),
                **({"name": cfg["display_name"]} if cfg["display_name"] else {}),
            }
            launch_url = build_launch_url(f"http://127.0.0.1:{sim_port}", bundle)
            profile_dir = Path(tempfile.mkdtemp(prefix="ainekio-headless-sim-"))
            cmd = [
                self._chrome_bin,
                "--headless=new",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-gpu-sandbox",
                "--enable-webgl",
                "--ignore-gpu-blocklist",
                "--enable-unsafe-swiftshader",
                "--autoplay-policy=no-user-gesture-required",
                "--disable-background-timer-throttling",
                "--disable-renderer-backgrounding",
                "--disable-backgrounding-occluded-windows",
                "--window-size=960,720",
                f"--user-data-dir={profile_dir}",
                launch_url,
            ]
            try:
                proc = subprocess.Popen(
                    cmd,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
            except OSError as exc:
                shutil.rmtree(profile_dir, ignore_errors=True)
                self._headless_last_error = str(exc)
                raise GatewayError(f"Failed to start headless browser: {exc}") from exc

            self._headless_proc = proc
            self._headless_profile_dir = profile_dir
            self._headless_started_at = time.time()
            self._headless_last_error = None
            self._headless_config = {
                "robot_id": cfg["robot_id"],
                "model": cfg["model"],
                "level": cfg["level"],
                "mp": cfg["mp"],
                "room": room if cfg["mp"] != "solo" else "",
            }
            self._emit(
                "headless_simulation_started",
                pid=proc.pid,
                robot_id=cfg["robot_id"],
                model=cfg["model"],
                level=cfg["level"],
                mp=cfg["mp"],
                room=room if cfg["mp"] != "solo" else "",
            )
            return self.status(request_host=request_host, client_host=client_host, include_secrets=True)

    def stop_headless_locked(self) -> None:
        proc = self._headless_proc
        self._headless_proc = None
        if proc is not None and proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except OSError:
                try:
                    proc.terminate()
                except OSError:
                    pass
            try:
                proc.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except OSError:
                    try:
                        proc.kill()
                    except OSError:
                        pass
                try:
                    proc.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    pass
            self._emit("headless_simulation_stopped", pid=proc.pid)
        self._headless_started_at = None
        self._headless_config = None
        self._cleanup_profile_dir_locked()

    def stop_headless(self, *, request_host: str | None = None) -> dict[str, Any]:
        with self._lock:
            self.stop_headless_locked()
            self._headless_last_error = None
            return self.status(request_host=request_host, include_secrets=False)

    def revoke_virtual_token(self, robot_id: str | None = None, *, request_host: str | None = None) -> dict[str, Any]:
        with self._lock:
            target = (robot_id or self._settings["robot_id"]).strip()
            if self._headless_proc is not None and self._headless_config and self._headless_config.get("robot_id") == target:
                self.stop_headless_locked()
            self._token_store.revoke(target)
            fut = asyncio.run_coroutine_threadsafe(self._gateway.revoke_token(target), self._event_loop)
            try:
                fut.result(timeout=3.0)
            except Exception:
                pass
            self._emit("virtual_robot_token_revoked", robot_id=target)
            return self.status(request_host=request_host, include_secrets=False)

    def close(self) -> None:
        with self._lock:
            self.stop_headless_locked()
            srv = self._http_server
            self._http_server = None
            if srv is not None:
                try:
                    srv.shutdown()
                    srv.server_close()
                except Exception:
                    pass
            t = self._http_thread
            self._http_thread = None
            if t is not None and t.is_alive():
                t.join(timeout=2.0)
