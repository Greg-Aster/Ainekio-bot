from __future__ import annotations

import argparse
import asyncio
import errno
import ipaddress
import logging
import math
import os
import signal
import sys
import threading
from collections.abc import Callable
from pathlib import Path
from time import monotonic

import websockets
from websockets.legacy.server import serve

from gateway.dashboard.auth import AuditLog
from gateway.dashboard.server import start_dashboard_server
from gateway.environment_adapter import EnvironmentAdapter, EnvironmentAdapterConfig
from gateway.hotspot import RobotHotspot
from gateway.perception import VisionBackend
from gateway.plugins import CameraFramePlugin
from gateway.security import DashboardPasswordStore, RobotTokenStore
from protocol.binary_helpers import MIC_PCM_FRAME_TYPE

from .service import GatewayService, GatewayServiceConfig, MAX_WEBSOCKET_MESSAGE_BYTES
from .stub import GatewayStub, GatewayStubConfig, build_phase_one_commands

WEBSOCKET_OPEN_TIMEOUT_SECONDS = 10.0
MICROPHONE_AUDIT_INTERVAL_SECONDS = 1.0
EXPECTED_DISCONNECT_ERRNOS = frozenset(
    error_number
    for error_number in (
        getattr(errno, "ECONNABORTED", None),
        getattr(errno, "ECONNRESET", None),
        getattr(errno, "EHOSTDOWN", None),
        getattr(errno, "EHOSTUNREACH", None),
        getattr(errno, "ENETDOWN", None),
        getattr(errno, "ENETUNREACH", None),
        getattr(errno, "ENOTCONN", None),
        getattr(errno, "EPIPE", None),
        getattr(errno, "ETIMEDOUT", None),
    )
    if error_number is not None
)


class ConciseWebSocketDisconnectFilter(logging.Filter):
    """Keep expected network loss visible without an internal library traceback."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.msg != "data transfer failed" or record.exc_info is None:
            return True
        error = record.exc_info[1]
        if (
            not isinstance(error, OSError)
            or error.errno not in EXPECTED_DISCONNECT_ERRNOS
        ):
            return True
        record.levelno = logging.WARNING
        record.levelname = "WARNING"
        record.msg = "WebSocket peer disconnected: %s"
        record.args = (error,)
        record.exc_info = None
        record.exc_text = None
        return True


def _websocket_logger() -> logging.Logger:
    logger = logging.getLogger("ainekio.gateway.websocket")
    if not any(
        isinstance(existing, ConciseWebSocketDisconnectFilter)
        for existing in logger.filters
    ):
        logger.addFilter(ConciseWebSocketDisconnectFilter())
    return logger


class MicrophoneFrameAudit:
    """Keep microphone evidence without doing disk I/O for every PCM frame."""

    def __init__(
        self,
        audit_log: AuditLog,
        *,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self._audit_log = audit_log
        self._clock = clock
        self._last_microphone_at: dict[str, tuple[object, float]] = {}

    def record(self, frame: dict[str, object]) -> None:
        if frame.get("frame_type") == MIC_PCM_FRAME_TYPE:
            robot_id = str(frame.get("robot_id", ""))
            epoch = frame.get("epoch")
            now = self._clock()
            previous = self._last_microphone_at.get(robot_id)
            if (
                previous is not None
                and previous[0] == epoch
                and now - previous[1] < MICROPHONE_AUDIT_INTERVAL_SECONDS
            ):
                return
            self._last_microphone_at[robot_id] = (epoch, now)
        self._audit_log.record("media_frame", **_audit_fields(frame))


class BoundedHandshakeProtocol(websockets.WebSocketServerProtocol):
    async def process_request(self, path: str, request_headers: object):
        # Speech replies have no whole-message size ceiling. The adapter
        # validates their format and streams small PCM frames to the robot.
        if path == "/environment":
            self.max_size = None
        return await super().process_request(path, request_headers)

    async def handshake(self, *args: object, **kwargs: object) -> str:
        try:
            return await asyncio.wait_for(
                super().handshake(*args, **kwargs),
                timeout=WEBSOCKET_OPEN_TIMEOUT_SECONDS,
            )
        except TimeoutError as exc:
            raise websockets.exceptions.InvalidHandshake(
                "opening handshake timed out"
            ) from exc


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Ainekio protocol-v1 gateway.")
    parser.add_argument("--host", default="127.0.0.1", help="Robot WebSocket bind address")
    parser.add_argument("--port", type=int, default=8790, help="Robot WebSocket port")
    parser.add_argument("--profile", choices=("home", "tether"), default="home")
    parser.add_argument("--dashboard-host", default="127.0.0.1")
    parser.add_argument("--dashboard-port", type=int, default=8791)
    parser.add_argument(
        "--dashboard-primary-view",
        choices=("camera", "simulator"),
        default="camera",
        help="Primary Body Control panel",
    )
    parser.add_argument("--data-dir", type=Path, default=Path("build/gateway"))
    parser.add_argument("--vision-url", default=os.environ.get("AINEKIO_VISION_URL"),
                        help="Configured Chat Completions endpoint (remote requires authenticated HTTPS); disabled when omitted")
    parser.add_argument("--vision-model", default=os.environ.get("AINEKIO_VISION_MODEL"))
    parser.add_argument("--vision-yolo-weights", default=os.environ.get("AINEKIO_VISION_YOLO_WEIGHTS"), help="Explicit local YOLO .pt file; optional offline detector instead of the configured URL")
    parser.add_argument("--vision-yolo-device", default=os.environ.get("AINEKIO_VISION_YOLO_DEVICE", "cpu"))
    parser.add_argument("--vision-yolo-image-size", type=int, default=os.environ.get("AINEKIO_VISION_YOLO_IMAGE_SIZE", "640"))
    parser.add_argument("--vision-face-detector", default=os.environ.get("AINEKIO_VISION_FACE_DETECTOR"), help="Local YuNet ONNX file for enrolled people")
    parser.add_argument("--vision-face-recognizer", default=os.environ.get("AINEKIO_VISION_FACE_RECOGNIZER"), help="Local SFace ONNX file; no automatic downloads")
    parser.add_argument("--vision-timeout-s", type=float, default=2.0)
    parser.add_argument("--vision-max-frame-age-s", type=float, default=1.0)
    parser.add_argument(
        "--environment-session-id",
        default=os.environ.get("AINEKIO_ENVIRONMENT_SESSION_ID", "ainekio-01"),
        help="Session ID exposed by the authenticated environment adapter",
    )
    parser.add_argument(
        "--stub",
        action="store_true",
        help="Run the scripted development stub without the dashboard",
    )
    parser.add_argument(
        "--commands",
        default="stand",
        help="Comma-separated stub script: stand,neutral,walk,stop",
    )
    return parser


def _advertised_host(bind_host: str) -> str | None:
    configured = os.environ.get("AINEKIO_GATEWAY_ADVERTISED_HOST", "").strip()
    if configured:
        return configured
    if bind_host not in {"0.0.0.0", "::"}:
        return bind_host
    return None


def _request_uses_relay(websocket: object) -> bool:
    headers = getattr(websocket, "request_headers", None)
    return headers is not None and (
        headers.get("CF-Ray") is not None
        or headers.get("CF-Connecting-IP") is not None
    )


def _robot_transport(websocket: object) -> str:
    return "relay" if _request_uses_relay(websocket) else "lan"


def _peer_is_loopback(websocket: object) -> bool:
    remote_address = getattr(websocket, "remote_address", None)
    if not isinstance(remote_address, tuple) or not remote_address:
        return False
    try:
        return ipaddress.ip_address(str(remote_address[0])).is_loopback
    except ValueError:
        return False


def _print_gateway_addresses(
    *, bind_host: str, port: int, environment_enabled: bool
) -> None:
    print(f"Ainekio gateway bind: {bind_host}:{port}")
    host = _advertised_host(bind_host)
    if host is None:
        print("Ainekio robot setup URL unavailable; configure an advertised host.")
    else:
        print(f"Ainekio robot setup URL: ws://{host}:{port}/robot")
    print(
        f"Ainekio environment URL: ws://127.0.0.1:{port}/environment"
        if environment_enabled
        else "Ainekio environment: disabled"
    )


async def _run_stub(args: argparse.Namespace, token: str) -> None:
    names = [name.strip() for name in args.commands.split(",") if name.strip()]
    stub = GatewayStub(
        GatewayStubConfig(auth_token=token, profile=args.profile),
        build_phase_one_commands(names),
    )
    async with serve(
        stub.handler,
        args.host,
        args.port,
        max_size=MAX_WEBSOCKET_MESSAGE_BYTES,
        max_queue=32,
        ping_interval=None,
        close_timeout=1.0,
        create_protocol=BoundedHandshakeProtocol,
        logger=_websocket_logger(),
    ):
        _print_gateway_addresses(
            bind_host=args.host,
            port=args.port,
            environment_enabled=False,
        )
        await asyncio.Future()


async def _run_production(args: argparse.Namespace) -> None:
    adapter_token = os.environ.get("AINEKIO_ENVIRONMENT_ADAPTER_TOKEN", "").strip()
    yolo_weights = getattr(args, "vision_yolo_weights", None)
    if yolo_weights and (args.vision_url or args.vision_model):
        raise ValueError("select local YOLO weights or a vision URL/model, not both")
    if bool(args.vision_url) != bool(args.vision_model):
        raise ValueError("vision requires both --vision-url and --vision-model")
    if (args.vision_url or yolo_weights) and not adapter_token:
        raise ValueError("recognition requires the authenticated Environment Bridge")
    if (args.vision_url or yolo_weights) and (not math.isfinite(args.vision_max_frame_age_s) or not 0.1 <= args.vision_max_frame_age_s <= 30):
        raise ValueError("vision frame age must be between 0.1 and 30 seconds")
    backend = VisionBackend(args.vision_url, args.vision_model,
        timeout_s=args.vision_timeout_s, api_key=os.environ.get("AINEKIO_VISION_API_KEY", "")) if args.vision_url else None
    if yolo_weights:
        from gateway.yolo_backend import YoloBackend
        backend = YoloBackend(yolo_weights, device=args.vision_yolo_device, image_size=args.vision_yolo_image_size)

    args.data_dir.mkdir(parents=True, exist_ok=True)
    face_detector, face_recognizer = getattr(args, "vision_face_detector", None), getattr(args, "vision_face_recognizer", None)
    if face_detector or face_recognizer:
        if not (yolo_weights and face_detector and face_recognizer):
            raise ValueError("Named people require local YOLO, YuNet and SFace model paths")
        from gateway.person_identity import FaceGallery, LocalFaces, PersonIdentityBackend
        faces = LocalFaces(face_detector, face_recognizer)
        backend = PersonIdentityBackend(backend, faces, FaceGallery(args.data_dir / "known-people.json", faces.model_hash))
    password_store = DashboardPasswordStore(args.data_dir / "dashboard-auth.json")
    password_store.initialize(
        output=sys.stdout,
        password=os.environ.get("AINEKIO_DASHBOARD_PASSWORD"),
    )
    token_store = RobotTokenStore(args.data_dir / "robot-tokens.json")
    _seed_environment_token(token_store)

    audit_log = AuditLog(args.data_dir / "operations.jsonl")
    service = GatewayService(
        GatewayServiceConfig(tokens=token_store.snapshot(), profile=args.profile), token_store=token_store
    )
    service.subscribe_commands(
        lambda command: audit_log.record("gateway_command", **_audit_fields(command))
    )
    service.subscribe_events(
        lambda event: audit_log.record("body_event", **_audit_fields(event))
    )
    service.subscribe_diagnostics(
        lambda diagnostic: audit_log.record(str(diagnostic["event"]), **_audit_fields(diagnostic))
    )
    service.subscribe_frames(MicrophoneFrameAudit(audit_log).record)
    adapter = EnvironmentAdapter(
        service,
        EnvironmentAdapterConfig(
            token=adapter_token,
            receipt_path=str(args.data_dir / "environment-actions.sqlite"),
            session_id=args.environment_session_id,
            # AINEKIO_ROBOT_ID seeds pairing, not bridge device selection.
            # The bridge follows the single connected V1 or V2 body.
            freestyle_enabled=os.environ.get("AINEKIO_FREESTYLE_ENABLED", "1") == "1",
        ),
    ) if adapter_token else None
    hotspot = RobotHotspot()
    dashboard = start_dashboard_server(
        args.dashboard_host,
        args.dashboard_port,
        gateway=service,
        event_loop=asyncio.get_running_loop(),
        password_store=password_store,
        token_store=token_store,
        audit_log=audit_log,
        primary_view=args.dashboard_primary_view,
        hotspot=hotspot,
        environment_adapter=adapter,
    )
    dashboard_thread = threading.Thread(
        target=dashboard.serve_forever,
        name="ainekio-dashboard",
        daemon=True,
    )
    dashboard_thread.start()
    async def publish_recognition(analysis):
        await adapter.publish_camera_analysis(analysis, max_frame_age_s=args.vision_max_frame_age_s)

    camera = CameraFramePlugin(service, backend, observe=publish_recognition,
        max_frame_age_s=args.vision_max_frame_age_s) if backend else None
    adapter.recognition_status = camera.metrics if camera is not None else None
    dashboard.camera_recognition = camera
    if camera is not None:
        camera.set_enabled(dashboard.control_settings["recognition"])
    service.subscribe_events(dashboard.restore_camera)

    async def route(websocket: object, path: str) -> None:
        if path == "/robot":
            await service.handler(
                websocket,
                path,
                transport=_robot_transport(websocket),
            )
            return
        if (
            path == "/environment"
            and adapter is not None
            and _peer_is_loopback(websocket)
            and not _request_uses_relay(websocket)
        ):
            await adapter.handler(websocket)
            return
        await websocket.close(code=1008, reason="wrong or unavailable endpoint")

    loop = asyncio.get_running_loop()
    stopped = loop.create_future()
    def request_stop() -> None:
        if not stopped.done():
            stopped.set_result(None)
    previous_sigterm = signal.signal(signal.SIGTERM, lambda *_: loop.call_soon_threadsafe(request_stop))
    try:
        await hotspot.start()
        async with serve(
            route,
            args.host,
            args.port,
            max_size=MAX_WEBSOCKET_MESSAGE_BYTES,
            max_queue=32,
            ping_interval=None,
            close_timeout=1.0,
            create_protocol=BoundedHandshakeProtocol,
            logger=_websocket_logger(),
        ) as server:
            _print_gateway_addresses(
                bind_host=args.host,
                port=args.port,
                environment_enabled=adapter is not None,
            )
            print(f"Ainekio dashboard:    http://{args.dashboard_host}:{args.dashboard_port}/")
            try:
                await stopped
            finally:
                server.close()
                await service.close()
                # Environment and not-yet-paired sockets share this server.
                # Release them before asyncio.Server.wait_closed waits for all
                # accepted transports on Python 3.12.
                established = []
                for websocket in tuple(server.websockets):
                    if websocket.open:
                        established.append(websocket.close(1001, "gateway stopped"))
                    elif not websocket.closed:
                        websocket.transport.close()
                await asyncio.gather(*established)
    finally:
        signal.signal(signal.SIGTERM, previous_sigterm)
        try:
            if camera is not None:
                await camera.aclose()
            await asyncio.to_thread(dashboard.shutdown)
            dashboard.server_close()
            dashboard_thread.join(timeout=2.0)
        finally:
            await hotspot.close()


def _seed_environment_token(token_store: RobotTokenStore) -> None:
    token = os.environ.get("AINEKIO_ROBOT_TOKEN")
    if not token:
        return
    robot_id = os.environ.get("AINEKIO_ROBOT_ID", "ainekio-emulator-01")
    if robot_id not in token_store.snapshot():
        token_store.set(robot_id, token)


def _audit_fields(payload: dict[str, object]) -> dict[str, object]:
    allowed = {
        "robot_id",
        "epoch",
        "seq",
        "t",
        "name",
        "op",
        "code",
        "frame_type",
        "counter",
        "status",
        "close_code",
        "close_reason",
        "control_frames_received",
        "json_pings_sent",
        "last_control_type",
        "rssi",
        "mic_drops",
        "msg", "error", "command_type", "dir", "gait", "steps", "speed",
        "stride", "rate", "forward", "turn", "update", "playback_rate",
        "body_clock_ms", "clock_age_ms", "clock_samples", "clock_max_gap_ms",
        "clock_gap_ms", "clock_advance_ms", "action_age_ms", "clock_ms",
        "motion_timing", "output_timing", "controller_queue_depth",
        "output_ready", "output_armed", "output_fault",
    }
    return {key: value for key, value in payload.items() if key in allowed}


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.stub:
            token = os.environ.get("AINEKIO_ROBOT_TOKEN")
            if not token:
                raise SystemExit(
                    "AINEKIO_ROBOT_TOKEN must be set; tokens are not stored in the repo"
                )
            asyncio.run(_run_stub(args, token))
        else:
            asyncio.run(_run_production(args))
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
