from __future__ import annotations

import argparse
import os
import sys
import time
from urllib.parse import urlsplit

from .adapter import create_adapter


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run the legacy simulator-only Ainekio MetaHuman environment adapter. "
            "It cannot connect to the protocol-v1 robot deployment socket."
        )
    )
    parser.add_argument("--base-url", default="http://192.168.0.44:4321", help="MetaHuman OS base URL")
    parser.add_argument("--session-id", default="ainekio-sim-1", help="Environment bridge session ID")
    parser.add_argument("--limit", type=int, default=10, help="Maximum actions per pushed stream event")
    parser.add_argument(
        "--simulator-shim-url",
        default=os.environ.get("AINEKIO_SIMULATOR_SHIM_URL"),
        help="Optional local simulator shim URL, for example http://127.0.0.1:8788",
    )
    args = parser.parse_args(argv)
    _require_metahuman_http_url(args.base_url, parser)

    adapter = create_adapter(
        base_url=args.base_url,
        session_id=args.session_id,
        simulator_shim_url=args.simulator_shim_url,
    )

    while True:
        try:
            print("connecting to MetaHuman environment bridge stream", flush=True)
            for result in adapter.stream_results(limit=max(1, args.limit)):
                print(
                    f"{result.status} action={result.action_id or '-'} "
                    f"command={result.command or '-'} frames={result.frames} message={result.message}",
                    flush=True,
                )
        except KeyboardInterrupt:
            raise
        except Exception as error:
            print(f"adapter stream error: {error}; reconnecting in 2s", flush=True)
            time.sleep(2)
    return 0


def _require_metahuman_http_url(base_url: str, parser: argparse.ArgumentParser) -> None:
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        parser.error("legacy adapter base URL must be a MetaHuman HTTP URL")
    if parsed.path.rstrip("/").endswith("/robot"):
        parser.error("legacy adapter cannot attach to the robot deployment endpoint")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
