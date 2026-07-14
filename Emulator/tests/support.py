from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BUILD_DIR = Path("/tmp/ainekio-emulator-owner-layout-test-build")


def build_core_library() -> Path:
    subprocess.run(
        ["cmake", "-S", str(ROOT / "Emulator" / "emulator"), "-B", str(BUILD_DIR)],
        check=True,
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["cmake", "--build", str(BUILD_DIR)],
        check=True,
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    return BUILD_DIR / "libainekio_emulator_core.so"
