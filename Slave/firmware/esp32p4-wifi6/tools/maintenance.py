#!/usr/bin/env python3
"""P4 recording/OTA client for the existing HTTP configuration server.

Use on the trusted robot LAN or WPA2 setup AP. The pairing token is prompted
privately (or read from AINEKIO_ROBOT_TOKEN); HTTP itself is not encrypted.
"""
import argparse
import getpass
import http.client
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("address", help="Robot IP or http://robot-ip (not the gateway)")
    commands = parser.add_subparsers(dest="command", required=True)
    record = commands.add_parser("record")
    record.add_argument("operation", choices=["start", "stop", "status"])
    commands.add_parser("status")
    upload = commands.add_parser("upload")
    upload.add_argument("image", type=Path, help="ainekio_p4_body.bin application only")
    activate = commands.add_parser("activate")
    activate.add_argument("operation", choices=["next_boot", "restart"])
    args = parser.parse_args()
    url = urlsplit(args.address if "://" in args.address else "http://" + args.address)
    if url.scheme != "http" or not url.hostname or url.username or url.password or url.path not in ("", "/"):
        parser.error("Use the robot's local HTTP address without credentials or a path")
    token = os.environ.get("AINEKIO_ROBOT_TOKEN") or getpass.getpass("Robot pairing token: ")
    if not token or "\r" in token or "\n" in token:
        parser.error("A valid pairing token is required")
    connection = http.client.HTTPConnection(url.hostname, url.port or 80, timeout=30)
    headers = {"Authorization": "Bearer " + token, "Connection": "close"}
    try:
        if args.command == "upload":
            # http.client reads this file in bounded blocks; no whole-image copy.
            with args.image.open("rb") as image:
                headers["Content-Length"] = str(os.fstat(image.fileno()).st_size)
                headers["Content-Type"] = "application/octet-stream"
                print("Uploading; robot enters Doze and closes recording. Watch its screen for progress.", file=sys.stderr)
                connection.request("POST", "/api/firmware", body=image, headers=headers)
        else:
            path, operation = "/api/firmware", None
            if args.command == "record":
                path = "/api/recording"
                operation = None if args.operation == "status" else args.operation
            elif args.command == "activate":
                path, operation = "/api/firmware/activate", args.operation
            connection.request("POST" if operation else "GET", path, body=operation, headers=headers)
        result = connection.getresponse()
        body = result.read().decode("utf-8")
        try:
            print(json.dumps(json.loads(body), indent=2))
        except ValueError:
            print(body)
        return 0 if 200 <= result.status < 300 else 1
    except (OSError, http.client.HTTPException) as error:
        print(f"Request failed: {error}. Read robot status before retrying activation.", file=sys.stderr)
        return 1
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
