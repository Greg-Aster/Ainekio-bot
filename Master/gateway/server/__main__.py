from __future__ import annotations

import argparse
import asyncio
import os

import websockets

from .stub import GatewayStub, GatewayStubConfig, build_phase_one_commands


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the local Ainekio protocol-v1 gateway stub.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8790)
    parser.add_argument("--profile", choices=("home", "tether"), default="home")
    parser.add_argument(
        "--commands",
        default="stand",
        help="Comma-separated phase-1 script: stand,neutral,walk,stop",
    )
    return parser


async def _run(args: argparse.Namespace, token: str) -> None:
    names = [name.strip() for name in args.commands.split(",") if name.strip()]
    stub = GatewayStub(
        GatewayStubConfig(auth_token=token, profile=args.profile),
        build_phase_one_commands(names),
    )
    async with websockets.serve(
        stub.handler,
        args.host,
        args.port,
        max_size=(120 * 1024) + 5,
        max_queue=32,
        ping_interval=None,
    ):
        print(f"Ainekio gateway stub listening at ws://{args.host}:{args.port}/robot")
        await asyncio.Future()


def main() -> int:
    args = _parser().parse_args()
    token = os.environ.get("AINEKIO_ROBOT_TOKEN")
    if not token:
        raise SystemExit("AINEKIO_ROBOT_TOKEN must be set; tokens are not stored in the repo")
    asyncio.run(_run(args, token))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
