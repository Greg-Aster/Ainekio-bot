#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def frame_bytes(value: dict[str, object]) -> bytes:
    frame_type = int(value["type"])
    counter = int(value["counter"])
    if "payload_hex" in value:
        payload = bytes.fromhex(str(value["payload_hex"]))
    else:
        repeated = bytes.fromhex(str(value["payload_repeat"]))
        payload = repeated * int(value["payload_count"])
    return bytes([frame_type]) + counter.to_bytes(4, "little") + payload


def main() -> int:
    decoder = Path(sys.argv[1])
    fixture = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
    failures: list[str] = []
    for case in fixture["cases"]:
        values = case.get("frames") or [case.get("frame")]
        if "raw_hex" in case:
            values = [None]
        for index, value in enumerate(values):
            encoded = bytes.fromhex(case["raw_hex"]) if value is None else frame_bytes(value)
            result = subprocess.run(
                [str(decoder)],
                input=encoded,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            actual_valid = result.returncode == 0
            if actual_valid != case["valid"]:
                failures.append(f"{case['name']}[{index}]: exit={result.returncode}")
            if actual_valid:
                actual_known = result.stdout.strip() == b"known"
                if actual_known != case["known_type"]:
                    failures.append(f"{case['name']}[{index}]: known={actual_known}")
    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    print("portable C decoder consumed all binary-v1 golden fixtures")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
