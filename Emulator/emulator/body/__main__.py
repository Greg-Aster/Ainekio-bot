from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

from emulator.backends.sesame import SesameMotionBackend

from .client import BodyClientConfig, ProtocolV1BodyClient
from .core import PortableCore
from .session import BodySession


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Ainekio protocol-v1 body emulator.")
    parser.add_argument("--endpoint", default="ws://127.0.0.1:8790/robot")
    parser.add_argument("--robot-id", default="ainekio-emulator-01")
    parser.add_argument("--firmware-version", default="0.1.0-host")
    parser.add_argument("--shim-url", default="http://127.0.0.1:8788")
    parser.add_argument("--core-library", type=Path)
    parser.add_argument("--once", action="store_true")
    return parser


async def _run(args: argparse.Namespace, token: str) -> None:
    with PortableCore(args.core_library) as core:
        session = BodySession(core, SesameMotionBackend(args.shim_url))
        client = ProtocolV1BodyClient(
            BodyClientConfig(
                endpoint=args.endpoint,
                robot_id=args.robot_id,
                auth_token=token,
                firmware_version=args.firmware_version,
            ),
            session,
        )
        if args.once:
            await client.run_once()
        else:
            await client.run_forever()


def main() -> int:
    args = _parser().parse_args()
    token = os.environ.get("AINEKIO_ROBOT_TOKEN")
    if not token:
        raise SystemExit("AINEKIO_ROBOT_TOKEN must be set; tokens are not stored in the repo")
    asyncio.run(_run(args, token))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
