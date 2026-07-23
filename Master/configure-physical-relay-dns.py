#!/usr/bin/env python3
"""Safely create the one DNS record used by the physical robot relay."""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


API_ROOT = "https://api.cloudflare.com/client/v4"
ZONE_NAME = "ainek.io"
EXPECTED_ACCOUNT_ID = "85ab4e804339eb1a39a5a8d9da96ab39"
RECORD_NAME = "robot-gateway.ainek.io"
TUNNEL_ID = "ddf3b49b-0ef4-4442-b997-f3372a6cd393"
RECORD_TARGET = f"{TUNNEL_ID}.cfargotunnel.com"


class CloudflareError(RuntimeError):
    """A sanitized Cloudflare API failure."""


def request_json(
    token: str,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(
        f"{API_ROOT}{path}",
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "Ainekio-physical-relay-DNS/1",
        },
    )
    try:
        with urlopen(request, timeout=20) as response:
            result = json.load(response)
    except HTTPError as error:
        try:
            error_body = json.load(error)
        except (json.JSONDecodeError, UnicodeDecodeError):
            error_body = {"errors": [{"message": "unparseable error response"}]}
        messages = [
            item.get("message", "unknown API error")
            for item in error_body.get("errors", [])
            if isinstance(item, dict)
        ]
        raise CloudflareError(
            f"Cloudflare returned HTTP {error.code}: {messages or ['unknown API error']}"
        ) from error
    except URLError as error:
        raise CloudflareError(f"Cloudflare request failed: {error.reason}") from error

    if not result.get("success"):
        messages = [
            item.get("message", "unknown API error")
            for item in result.get("errors", [])
            if isinstance(item, dict)
        ]
        raise CloudflareError(f"Cloudflare rejected the request: {messages}")
    return result


def one_zone(token: str) -> dict[str, Any]:
    query = urlencode({"name": ZONE_NAME, "status": "active"})
    zones = request_json(token, "GET", f"/zones?{query}").get("result", [])
    if not isinstance(zones, list) or len(zones) != 1:
        raise CloudflareError(
            f"expected one active {ZONE_NAME} zone, received {len(zones)}"
        )
    zone = zones[0]
    account = zone.get("account") or {}
    if account.get("id") != EXPECTED_ACCOUNT_ID:
        raise CloudflareError(
            "the ainek.io zone is not in the account that owns the robot tunnel"
        )
    return zone


def named_records(token: str, zone_id: str) -> list[dict[str, Any]]:
    query = urlencode({"name": RECORD_NAME})
    records = request_json(
        token, "GET", f"/zones/{zone_id}/dns_records?{query}"
    ).get("result", [])
    if not isinstance(records, list):
        raise CloudflareError("Cloudflare returned an invalid DNS-record list")
    return records


def is_expected(record: dict[str, Any]) -> bool:
    return (
        record.get("type") == "CNAME"
        and record.get("name") == RECORD_NAME
        and str(record.get("content", "")).rstrip(".").lower()
        == RECORD_TARGET.lower()
        and record.get("proxied") is True
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Dry-run or create the exact Cloudflare DNS route for Ainekio."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="create the record; without this flag the command is read-only",
    )
    args = parser.parse_args()

    token = os.environ.get("CLOUDFLARE_API_TOKEN", "")
    if not token:
        parser.error(
            "CLOUDFLARE_API_TOKEN is required; use a short-lived token scoped "
            "to Zone:Read and DNS:Edit for ainek.io"
        )

    zone = one_zone(token)
    zone_id = str(zone["id"])
    existing = named_records(token, zone_id)
    if existing:
        if len(existing) == 1 and is_expected(existing[0]):
            print(f"DNS route already correct: {RECORD_NAME} -> {RECORD_TARGET}")
            return 0
        raise CloudflareError(
            f"refusing to overwrite {len(existing)} existing record(s) named {RECORD_NAME}"
        )

    print(f"Zone verified: {ZONE_NAME} in expected Cloudflare account")
    print(f"Planned CNAME: {RECORD_NAME} -> {RECORD_TARGET} (proxied)")
    if not args.apply:
        print("Dry run only; rerun with --apply to create this exact record.")
        return 0

    request_json(
        token,
        "POST",
        f"/zones/{zone_id}/dns_records",
        {
            "type": "CNAME",
            "name": RECORD_NAME,
            "content": RECORD_TARGET,
            "proxied": True,
            "ttl": 1,
            "comment": "Ainekio physical robot WebSocket relay",
        },
    )
    verified = named_records(token, zone_id)
    if len(verified) != 1 or not is_expected(verified[0]):
        raise CloudflareError("record creation returned, but exact verification failed")
    print(f"Created and verified: {RECORD_NAME} -> {RECORD_TARGET}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except CloudflareError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1) from error
