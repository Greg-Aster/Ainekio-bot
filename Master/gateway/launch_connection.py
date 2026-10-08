"""Interactive dashboard access choice for the existing physical launcher."""
from __future__ import annotations

import argparse
import ipaddress
import json
import os
from pathlib import Path
import select
import sys
import tempfile
from urllib.parse import urlsplit

MODES = ("local", "lan", "cloudflare")
LABELS = {"local": "This computer", "lan": "LAN / Wi-Fi", "cloudflare": "Cloudflare"}


def choose(mode: str, timeout: float) -> str:
    print("\nHow will you open Body Control?", file=sys.stderr)
    for index, name in enumerate(MODES, 1):
        print(f"  {index}) {LABELS[name]}{' [saved/default]' if name == mode else ''}", file=sys.stderr)
    print("LAN / Wi-Fi enables dashboard access on this network. Cloudflare uses an existing tunnel.", file=sys.stderr)
    print(f"Choose 1–3, or Enter for {LABELS[mode]}. Using it automatically in {timeout:g} seconds: ",
          end="", file=sys.stderr, flush=True)
    readable, _, _ = select.select([sys.stdin], [], [], timeout)
    answer = sys.stdin.readline().strip() if readable else ""
    if not readable:
        print(file=sys.stderr)
    if not answer:
        return mode
    if answer in ("1", "2", "3"):
        return MODES[int(answer) - 1]
    if answer in MODES:
        return answer
    raise ValueError("Choose 1, 2, or 3. No startup choice was saved.")


def configure(args: argparse.Namespace) -> tuple[str, str, str]:
    setting = Path(args.data_dir) / "dashboard-connection.json"
    saved = json.loads(setting.read_text()) if setting.exists() else {}
    if not isinstance(saved, dict):
        raise ValueError(f"Invalid startup settings in {setting}")
    mode = os.environ.get("AINEKIO_DASHBOARD_CONNECTION") or saved.get("mode", "local")
    if mode not in MODES:
        raise ValueError("AINEKIO_DASHBOARD_CONNECTION / saved mode must be local, lan, or cloudflare")
    timeout = float(os.environ.get("AINEKIO_DASHBOARD_CHOICE_TIMEOUT", "10"))
    if not 0 <= timeout <= 300:
        raise ValueError("AINEKIO_DASHBOARD_CHOICE_TIMEOUT must be between 0 and 300 seconds")
    if sys.stdin.isatty() and not os.environ.get("AINEKIO_DASHBOARD_CONNECTION"):
        mode = choose(mode, timeout)
    public_url = os.environ.get("AINEKIO_DASHBOARD_PUBLIC_URL") or saved.get("public_url", "")
    host = os.environ.get("AINEKIO_DASHBOARD_HOST") or ("0.0.0.0" if mode == "lan" else "127.0.0.1")
    local_host = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    if ":" in local_host:
        local_host = f"[{local_host}]"
    address = f"http://{local_host}:{args.port}/"
    if mode == "cloudflare":
        parsed = urlsplit(public_url)
        if (parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username
                or parsed.password or any(ord(char) < 32 for char in public_url)):
            raise ValueError("Set AINEKIO_DASHBOARD_PUBLIC_URL to the dashboard's public HTTP(S) address before choosing Cloudflare.")
        address = public_url
        print("Cloudflare access requires the existing tunnel to be running; this launcher does not start another tunnel.", file=sys.stderr)
    elif mode == "lan":
        if host in ("0.0.0.0", "::"):
            addresses = []
            for candidate in args.lan_addresses.split():
                ip = ipaddress.ip_address(candidate)
                if ip.version == 4 and not ip.is_loopback:
                    addresses.append(candidate)
            address = f"http://{addresses[0]}:{args.port}/" if addresses else f"http://<this-machine-LAN-IP>:{args.port}/"
        print(f"LAN dashboard listen address: {host}:{args.port} (existing login required).", file=sys.stderr)
    setting.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", dir=setting.parent, delete=False) as handle:
        temporary = Path(handle.name)
        json.dump({"mode": mode, "public_url": public_url}, handle)
        handle.write("\n")
    try:
        temporary.replace(setting)
    finally:
        temporary.unlink(missing_ok=True)
    return mode, host, address


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--port", required=True)
    parser.add_argument("--lan-addresses", default="")
    args = parser.parse_args()
    try:
        for value in configure(args):
            print(value)
    except (OSError, ValueError, TypeError) as error:
        print(f"Body Control startup choice: {error}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nStartup cancelled; saved choice unchanged.", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
