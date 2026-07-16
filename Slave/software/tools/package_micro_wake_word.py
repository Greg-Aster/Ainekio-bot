#!/usr/bin/env python3
"""Package a locally trained microWakeWord TFLite model for Ainekio LittleFS."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path


SCHEMA = "ainekio-microwakeword-v1"
ENGINE = "micro_wake_word"
MODEL_ID = re.compile(r"^[a-z0-9][a-z0-9_]{0,31}$")
MODEL_MINIMUM_BYTES = 1024
MODEL_MAXIMUM_BYTES = 512 * 1024


def package_model(
    *,
    model: Path,
    output_dir: Path,
    model_id: str,
    wake_word: str,
    author: str,
    license_name: str,
    training_revision: str,
    trained_languages: list[str],
    probability_cutoff: float,
    feature_step_size: int,
    sliding_window_size: int,
    tensor_arena_size: int,
    replace: bool = False,
) -> Path:
    if not MODEL_ID.fullmatch(model_id):
        raise ValueError("model id must match [a-z0-9][a-z0-9_]{0,31}")
    for name, value, maximum in (
        ("wake word", wake_word, 64),
        ("author", author, 128),
        ("license", license_name, 128),
        ("training revision", training_revision, 128),
    ):
        if not value or len(value) > maximum:
            raise ValueError(f"{name} must contain 1-{maximum} characters")
    if not trained_languages or any(
        not language or len(language) > 16 for language in trained_languages
    ):
        raise ValueError("at least one bounded trained language is required")
    if not 1 / 255 <= probability_cutoff <= 1.0:
        raise ValueError("probability cutoff must be at least 1/255 and at most 1")
    if feature_step_size not in {10, 20, 30}:
        raise ValueError("feature step size must be 10, 20, or 30 ms")
    if not 1 <= sliding_window_size <= 32:
        raise ValueError("sliding window size must be in the range 1-32")
    if not 8 * 1024 <= tensor_arena_size <= 256 * 1024:
        raise ValueError("tensor arena size must be in the range 8192-262144")

    model_bytes = model.read_bytes()
    if not MODEL_MINIMUM_BYTES <= len(model_bytes) <= MODEL_MAXIMUM_BYTES:
        raise ValueError(
            f"model must be {MODEL_MINIMUM_BYTES}-{MODEL_MAXIMUM_BYTES} bytes"
        )
    if len(model_bytes) < 8 or model_bytes[4:8] != b"TFL3":
        raise ValueError("model is not a TensorFlow Lite FlatBuffer (missing TFL3)")

    output_dir.mkdir(parents=True, exist_ok=True)
    model_name = f"{model_id}.tflite"
    destination = output_dir / model_name
    manifest_path = output_dir / "manifest.json"
    if not replace and (destination.exists() or manifest_path.exists()):
        raise FileExistsError(
            "package already exists; pass --replace to overwrite its model and manifest"
        )

    digest = hashlib.sha256(model_bytes).hexdigest()
    manifest = {
        "schema": SCHEMA,
        "engine": ENGINE,
        "id": model_id,
        "wake_word": wake_word,
        "author": author,
        "license": license_name,
        "training_revision": training_revision,
        "trained_languages": trained_languages,
        "model": model_name,
        "sha256": digest,
        "micro": {
            "probability_cutoff": probability_cutoff,
            "feature_step_size": feature_step_size,
            "sliding_window_size": sliding_window_size,
            "tensor_arena_size": tensor_arena_size,
        },
    }

    model_temporary = output_dir / f".{model_name}.tmp"
    manifest_temporary = output_dir / ".manifest.json.tmp"
    shutil.copyfile(model, model_temporary)
    manifest_temporary.write_text(
        json.dumps(manifest, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    model_temporary.replace(destination)
    manifest_temporary.replace(manifest_path)
    return manifest_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--id", dest="model_id", default="ainekio")
    parser.add_argument("--wake-word", default="Ainekio")
    parser.add_argument("--author", required=True)
    parser.add_argument("--license", dest="license_name", required=True)
    parser.add_argument("--training-revision", required=True)
    parser.add_argument(
        "--trained-language",
        dest="trained_languages",
        action="append",
        default=[],
        help="repeat for each trained language, for example --trained-language en",
    )
    parser.add_argument("--probability-cutoff", type=float, default=0.97)
    parser.add_argument(
        "--feature-step-size",
        type=int,
        choices=(10, 20, 30),
        default=10,
    )
    parser.add_argument("--sliding-window-size", type=int, default=5)
    parser.add_argument("--tensor-arena-size", type=int, default=26080)
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()
    manifest = package_model(**vars(args))
    print(manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
