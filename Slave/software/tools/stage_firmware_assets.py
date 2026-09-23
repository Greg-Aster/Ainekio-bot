#!/usr/bin/env python3
"""Stage seed and device-local assets for the firmware LittleFS image."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path


WAKE_SCHEMA = "ainekio-microwakeword-v1"
WAKE_ENGINE = "micro_wake_word"


def _validate_wake_packages(root: Path) -> None:
    wake_root = root / "wake"
    if not wake_root.exists():
        return
    if not wake_root.is_dir():
        raise ValueError("wake asset path must be a directory")

    for package_dir in sorted(wake_root.iterdir()):
        if not package_dir.is_dir():
            raise ValueError(f"unexpected file in wake asset directory: {package_dir.name}")

        manifest_path = package_dir / "manifest.json"
        if not manifest_path.is_file():
            raise ValueError(f"wake package {package_dir.name!r} is missing manifest.json")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise ValueError(
                f"wake package {package_dir.name!r} has an invalid manifest"
            ) from error

        if manifest.get("schema") != WAKE_SCHEMA:
            raise ValueError(f"wake package {package_dir.name!r} has the wrong schema")
        if manifest.get("engine") != WAKE_ENGINE:
            raise ValueError(f"wake package {package_dir.name!r} has the wrong engine")
        if manifest.get("id") != package_dir.name:
            raise ValueError(f"wake package {package_dir.name!r} has a mismatched id")

        model_name = manifest.get("model")
        if (
            not isinstance(model_name, str)
            or not model_name
            or Path(model_name).name != model_name
        ):
            raise ValueError(f"wake package {package_dir.name!r} has an invalid model name")
        model_path = package_dir / model_name
        if not model_path.is_file():
            raise ValueError(f"wake package {package_dir.name!r} is missing its model")

        expected_digest = manifest.get("sha256")
        actual_digest = hashlib.sha256(model_path.read_bytes()).hexdigest()
        if expected_digest != actual_digest:
            raise ValueError(f"wake package {package_dir.name!r} model SHA-256 mismatch")


def stage_assets(*, seed_dir: Path, local_dir: Path, output_dir: Path, profile: str = "full") -> Path:
    if not seed_dir.is_dir():
        raise ValueError(f"seed asset directory does not exist: {seed_dir}")
    output = output_dir.resolve()
    sources = (seed_dir.resolve(), local_dir.resolve())
    if any(output == source or output in source.parents or source in output.parents for source in sources):
        raise ValueError("output directory must be separate from asset sources")
    if profile not in {"full", "p4"}:
        raise ValueError("unknown firmware asset profile")

    shutil.rmtree(output_dir, ignore_errors=True)
    output_dir.mkdir(parents=True)
    for source in (seed_dir, local_dir):
        if not source.exists():
            continue
        if not source.is_dir():
            raise ValueError(f"local asset path is not a directory: {source}")
        if profile == "full":
            shutil.copytree(source, output_dir, dirs_exist_ok=True)
            if source == seed_dir:
                (output_dir / "motions-v1.json").unlink(missing_ok=True)
        else:
            # The P4 currently consumes only voice and wake assets. Do not
            # import V1 gait geometry or unselected display assets into flash.
            for name in ("audio-v1.json", "audio", "wake"):
                item = source / name
                if item.is_dir():
                    shutil.copytree(item, output_dir / name, dirs_exist_ok=True)
                elif item.is_file():
                    shutil.copy2(item, output_dir / name)

    _validate_wake_packages(output_dir)
    return output_dir


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed-dir", type=Path, required=True)
    parser.add_argument("--local-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--profile", choices=("full", "p4"), default="full")
    args = parser.parse_args()
    staged = stage_assets(**vars(args))
    print(staged)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
