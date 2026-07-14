#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def main() -> int:
    decoder = Path(sys.argv[1])
    fixture_root = Path(sys.argv[2])
    failures: list[str] = []
    for filename, expected_valid in (
        ("control-valid-v1.json", True),
        ("control-invalid-v1.json", False),
    ):
        fixture = json.loads((fixture_root / filename).read_text(encoding="utf-8"))
        for case in fixture["cases"]:
            encoded = json.dumps(case["message"], separators=(",", ":")).encode("utf-8")
            result = subprocess.run(
                [str(decoder)],
                input=encoded,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            actual_valid = result.returncode == 0
            if actual_valid != expected_valid:
                failures.append(
                    f"{filename}:{case['name']}: expected valid={expected_valid}, "
                    f"exit={result.returncode}, stderr={result.stderr.decode().strip()}"
                )
    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    print("portable C decoder consumed all control-v1 golden fixtures")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
