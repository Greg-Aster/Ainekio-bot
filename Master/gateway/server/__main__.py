from __future__ import annotations

import argparse
import asyncio
import os
import sys
import threading
from pathlib import Path

import websockets

from gateway.dashboard.auth import AuditLog
from gateway.dashboard.server import start_dashboard_server
from gateway.bridge_client import GatewayBridge, GatewayBridgeConfig
from gateway.security import DashboardPasswordStore, RobotTokenStore

from .service import GatewayService, GatewayServiceConfig, MAX_WEBSOCKET_MESSAGE_BYTES
from .stub import GatewayStub, GatewayStubConfig, build_phase_one_commands


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Ainekio protocol-v1 gateway.")
    parser.add_argument("--host", default="127.0.0.1", help="Robot WebSocket bind address")
    parser.add_argument("--port", type=int, default=8790, help="Robot WebSocket port")
    parser.add_argument("--profile", choices=("home", "tether"), default="home")
    parser.add_argument("--dashboard-host", default="127.0.0.1")
    parser.add_argument("--dashboard-port", type=int, default=8791)
    parser.add_argument("--data-dir", type=Path, default=Path("build/gateway"))
    parser.add_argument(
        "--metahuman-url",
        default=os.environ.get("AINEKIO_METAHUMAN_URL"),
        help="Optional MetaHuman OS base URL for the environment bridge",
    )
    parser.add_argument(
        "--metahuman-session-id",
        default=os.environ.get("AINEKIO_METAHUMAN_SESSION_ID", "ainekio-sim-1"),
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


async def _run_stub(args: argparse.Namespace, token: str) -> None:
    names = [name.strip() for name in args.commands.split(",") if name.strip()]
    stub = GatewayStub(
        GatewayStubConfig(auth_token=token, profile=args.profile),
        build_phase_one_commands(names),
    )
    async with websockets.serve(
        stub.handler,
        args.host,
        args.port,
        max_size=MAX_WEBSOCKET_MESSAGE_BYTES,
        max_queue=32,
        ping_interval=None,
    ):
        print(f"Ainekio gateway stub listening at ws://{args.host}:{args.port}/robot")
        await asyncio.Future()


async def _run_production(args: argparse.Namespace) -> None:
    metahuman_token = os.environ.get("MH_ENVIRONMENT_BRIDGE_TOKEN", "").strip()
    if args.metahuman_url and not metahuman_token:
        raise RuntimeError(
            "MH_ENVIRONMENT_BRIDGE_TOKEN is required when --metahuman-url is configured"
        )

    args.data_dir.mkdir(parents=True, exist_ok=True)
    password_store = DashboardPasswordStore(args.data_dir / "dashboard-auth.json")
    password_store.initialize(
        output=sys.stdout,
        password=os.environ.get("AINEKIO_DASHBOARD_PASSWORD"),
    )
    token_store = RobotTokenStore(args.data_dir / "robot-tokens.json")
    _seed_environment_token(token_store)

    audit_log = AuditLog(args.data_dir / "operations.jsonl")
    service = GatewayService(
        GatewayServiceConfig(tokens=token_store.snapshot(), profile=args.profile)
    )
    service.subscribe_commands(
        lambda command: audit_log.record("gateway_command", **_audit_fields(command))
    )
    service.subscribe_events(
        lambda event: audit_log.record("body_event", **_audit_fields(event))
    )
    service.subscribe_frames(
        lambda frame: audit_log.record("media_frame", **_audit_fields(frame))
    )
    dashboard = start_dashboard_server(
        args.dashboard_host,
        args.dashboard_port,
        gateway=service,
        event_loop=asyncio.get_running_loop(),
        password_store=password_store,
        token_store=token_store,
        audit_log=audit_log,
    )
    dashboard_thread = threading.Thread(
        target=dashboard.serve_forever,
        name="ainekio-dashboard",
        daemon=True,
    )
    dashboard_thread.start()
    bridge = None
    if args.metahuman_url:
        bridge = GatewayBridge(
            service,
            GatewayBridgeConfig(
                base_url=args.metahuman_url,
                service_token=metahuman_token,
                session_id=args.metahuman_session_id,
                robot_id=os.environ.get("AINEKIO_ROBOT_ID"),
            ),
        )
        bridge.start(asyncio.get_running_loop())

    try:
        async with websockets.serve(
            service.handler,
            args.host,
            args.port,
            max_size=MAX_WEBSOCKET_MESSAGE_BYTES,
            max_queue=32,
            ping_interval=None,
        ):
            print(f"Ainekio robot gateway: ws://{args.host}:{args.port}/robot")
            print(f"Ainekio dashboard:    http://{args.dashboard_host}:{args.dashboard_port}/")
            await asyncio.Future()
    finally:
        if bridge is not None:
            bridge.request_stop()
        await asyncio.to_thread(dashboard.shutdown)
        dashboard.server_close()
        dashboard_thread.join(timeout=2.0)


def _seed_environment_token(token_store: RobotTokenStore) -> None:
    token = os.environ.get("AINEKIO_ROBOT_TOKEN")
    if not token:
        return
    robot_id = os.environ.get("AINEKIO_ROBOT_ID", "ainekio-emulator-01")
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
    }
    return {key: value for key, value in payload.items() if key in allowed}


def main() -> int:
    args = _parser().parse_args()
    if args.stub:
        token = os.environ.get("AINEKIO_ROBOT_TOKEN")
        if not token:
            raise SystemExit(
                "AINEKIO_ROBOT_TOKEN must be set; tokens are not stored in the repo"
            )
        asyncio.run(_run_stub(args, token))
    else:
        asyncio.run(_run_production(args))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
