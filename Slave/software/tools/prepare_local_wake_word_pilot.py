#!/usr/bin/env python3
"""Prepare a local-only microWakeWord pilot dataset and training config."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
from collections.abc import Iterable, Iterator
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import yaml
from mmap_ninja.ragged import RaggedMmap
from scipy.io import wavfile
from scipy.signal import resample_poly

from microwakeword.audio.audio_utils import generate_features_for_clip


SAMPLE_RATE = 16_000
FEATURE_STEP_MS = 10
CORRECTION_FACTOR = 0.91875

OWNER_VALIDATION_STEMS = {"10ainekio", "12ainekio"}
OWNER_TESTING_STEMS = {"11ainekio", "13ainekio"}

NEGATIVE_PHRASES = {
    "training": [
        "eye neck",
        "eye necky",
        "eye neck ee",
        "an echo",
        "hey Niko",
        "I like Neo",
        "I need audio",
        "I need you",
        "a neck injury",
        "my neck is sore",
        "the audio is ready",
        "hello there",
        "good morning",
        "please take a picture",
        "the robot is ready",
        "can you hear me",
    ],
    "validation": [
        "eye neck oh",
        "hey Nico",
        "turn around",
        "what time is it",
    ],
    "testing": [
        "eye neck easy",
        "an equal",
        "please come here",
        "the camera is ready",
    ],
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--training-root",
        type=Path,
        default=Path.home() / "ainekio-wake-training",
    )
    parser.add_argument("--run-name", default="pilot-v1")
    parser.add_argument(
        "--piper",
        type=Path,
        default=Path.home() / "metahuman/bin/piper/piper",
    )
    parser.add_argument(
        "--voices-dir",
        type=Path,
        default=Path.home() / "metahuman/out/voices",
    )
    parser.add_argument("--training-steps", type=int, default=2_000)
    return parser.parse_args()


def natural_key(path: Path) -> tuple[object, ...]:
    parts: list[object] = []
    current = ""
    digit = False
    for character in path.stem:
        if current and character.isdigit() != digit:
            parts.append(int(current) if digit else current)
            current = ""
        current += character
        digit = character.isdigit()
    if current:
        parts.append(int(current) if digit else current)
    return tuple(parts)


def ensure_sources(training_root: Path, piper: Path, voices: dict[str, Path]) -> None:
    required = [
        training_root / "positive-corpus/v1",
        training_root / "owner-recordings/raw",
        training_root / "owner-recordings/corrected-speed-0p91875",
        piper,
        *voices.values(),
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError("missing required pilot input: " + ", ".join(missing))


def split_synthetic(files: Iterable[Path]) -> dict[str, list[Path]]:
    by_voice: dict[str, list[Path]] = {}
    for path in files:
        by_voice.setdefault(path.name.split("-", 1)[0], []).append(path)

    result = {"training": [], "validation": [], "testing": []}
    for voice_files in by_voice.values():
        ordered = sorted(voice_files, key=natural_key)
        held_out = max(1, math.ceil(len(ordered) * 0.1))
        result["training"].extend(ordered[: -2 * held_out])
        result["validation"].extend(ordered[-2 * held_out : -held_out])
        result["testing"].extend(ordered[-held_out:])
    return result


def split_owner(training_root: Path) -> dict[str, list[Path]]:
    raw_dir = training_root / "owner-recordings/raw"
    corrected_dir = training_root / "owner-recordings/corrected-speed-0p91875"
    result = {"training": [], "validation": [], "testing": []}
    raw_files = sorted(raw_dir.glob("*.wav"), key=natural_key)
    if len(raw_files) != 13:
        raise ValueError(f"expected 13 owner originals, found {len(raw_files)}")
    for raw in raw_files:
        corrected = corrected_dir / f"{raw.stem}-speed-0p91875.wav"
        if not corrected.is_file():
            raise FileNotFoundError(f"missing corrected pair for {raw.name}")
        if raw.stem in OWNER_VALIDATION_STEMS:
            split = "validation"
        elif raw.stem in OWNER_TESTING_STEMS:
            split = "testing"
        else:
            split = "training"
        result[split].extend([raw, corrected])
    return result


def piper_generate(
    piper: Path,
    model: Path,
    phrase: str,
    output: Path,
    length_scale: float,
    noise_scale: float,
) -> None:
    process = subprocess.run(
        [
            str(piper),
            "--quiet",
            "--model",
            str(model),
            "--output_file",
            str(output),
            "--length_scale",
            str(length_scale),
            "--noise_scale",
            str(noise_scale),
            "--noise_w",
            "0.8",
            "--sentence_silence",
            "0.1",
        ],
        input=phrase + "\n",
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if process.returncode != 0:
        raise RuntimeError(
            f"Piper failed for {output.name}: {process.stderr.strip()}"
        )


def generate_negative_speech(
    run_root: Path,
    piper: Path,
    voices: dict[str, Path],
) -> dict[str, list[Path]]:
    result = {"training": [], "validation": [], "testing": []}
    lengths = (0.9, 1.1)
    noises = (0.6, 0.85)
    for split, phrases in NEGATIVE_PHRASES.items():
        output_dir = run_root / "audio/negative-speech" / split
        output_dir.mkdir(parents=True, exist_ok=False)
        for phrase_index, phrase in enumerate(phrases, start=1):
            for voice_index, (voice_name, model) in enumerate(voices.items()):
                variant = (phrase_index + voice_index) % 2
                output = output_dir / (
                    f"p{phrase_index:02d}-{voice_name}-v{variant + 1}.wav"
                )
                piper_generate(
                    piper,
                    model,
                    phrase,
                    output,
                    lengths[variant],
                    noises[variant],
                )
                result[split].append(output)
    return result


def normalize_signal(signal: np.ndarray, amplitude: float) -> np.ndarray:
    peak = float(np.max(np.abs(signal)))
    if peak > 0.0:
        signal = signal * (amplitude / peak)
    return np.clip(signal * 32767.0, -32768.0, 32767.0).astype(np.int16)


def noise_signal(kind: int, duration_seconds: float, rng: np.random.Generator) -> np.ndarray:
    sample_count = int(SAMPLE_RATE * duration_seconds)
    time = np.arange(sample_count, dtype=np.float32) / SAMPLE_RATE
    white = rng.normal(0.0, 1.0, sample_count).astype(np.float32)
    if kind == 0:
        signal = white
    elif kind == 1:
        signal = np.cumsum(white, dtype=np.float32)
        signal -= np.mean(signal)
    elif kind == 2:
        signal = (
            0.7 * np.sin(2.0 * np.pi * 60.0 * time)
            + 0.25 * np.sin(2.0 * np.pi * 120.0 * time)
            + 0.25 * white
        )
    else:
        signal = 0.05 * white
    return signal


def generate_noise(run_root: Path) -> dict[str, list[Path]]:
    rng = np.random.default_rng(20260715)
    result = {"training": [], "validation_ambient": [], "testing_ambient": []}
    settings = {
        "training": (32, 1.5),
        "validation_ambient": (4, 10.0),
        "testing_ambient": (4, 10.0),
    }
    for split, (count, duration) in settings.items():
        output_dir = run_root / "audio/negative-noise" / split
        output_dir.mkdir(parents=True, exist_ok=False)
        for index in range(count):
            signal = noise_signal(index % 4, duration, rng)
            amplitude = (0.005, 0.015, 0.04, 0.1)[index % 4]
            output = output_dir / f"noise-{index + 1:03d}.wav"
            wavfile.write(output, SAMPLE_RATE, normalize_signal(signal, amplitude))
            result[split].append(output)
    return result


def load_audio(path: Path) -> np.ndarray:
    sample_rate, audio = wavfile.read(path)
    source_dtype = audio.dtype
    if audio.ndim == 2:
        audio = np.mean(audio.astype(np.float32), axis=1)
    elif np.issubdtype(audio.dtype, np.integer):
        audio = audio.astype(np.float32)
    else:
        audio = np.asarray(audio, dtype=np.float32)

    if np.issubdtype(source_dtype, np.integer):
        audio /= 32768.0
    if sample_rate != SAMPLE_RATE:
        divisor = math.gcd(sample_rate, SAMPLE_RATE)
        audio = resample_poly(audio, SAMPLE_RATE // divisor, sample_rate // divisor)
    return np.clip(audio, -1.0, 1.0).astype(np.float32)


def feature_generator(paths: Iterable[Path]) -> Iterator[np.ndarray]:
    for path in paths:
        yield generate_features_for_clip(load_audio(path), FEATURE_STEP_MS)


def write_feature_set(
    run_root: Path,
    name: str,
    splits: dict[str, list[Path]],
) -> Path:
    feature_root = run_root / "features" / name
    for split, paths in splits.items():
        if not paths:
            continue
        output = feature_root / split / f"{name}_mmap"
        output.parent.mkdir(parents=True, exist_ok=True)
        RaggedMmap.from_generator(
            out_dir=str(output),
            sample_generator=feature_generator(paths),
            batch_size=100,
            verbose=True,
        )
    return feature_root


def write_config(
    run_root: Path,
    feature_roots: dict[str, Path],
    training_steps: int,
) -> Path:
    config = {
        "window_step_ms": FEATURE_STEP_MS,
        "train_dir": str(run_root / "model"),
        "features": [
            {
                "features_dir": str(feature_roots["synthetic-positive"]),
                "sampling_weight": 2.0,
                "penalty_weight": 1.0,
                "truth": True,
                "truncation_strategy": "truncate_start",
                "type": "mmap",
            },
            {
                "features_dir": str(feature_roots["owner-positive"]),
                "sampling_weight": 4.0,
                "penalty_weight": 1.0,
                "truth": True,
                "truncation_strategy": "truncate_start",
                "type": "mmap",
            },
            {
                "features_dir": str(feature_roots["negative-speech"]),
                "sampling_weight": 5.0,
                "penalty_weight": 1.0,
                "truth": False,
                "truncation_strategy": "random",
                "type": "mmap",
            },
            {
                "features_dir": str(feature_roots["negative-noise"]),
                "sampling_weight": 1.0,
                "penalty_weight": 1.0,
                "truth": False,
                "truncation_strategy": "random",
                "type": "mmap",
            },
        ],
        "training_steps": [training_steps],
        "positive_class_weight": [1.0],
        "negative_class_weight": [1.0],
        "learning_rates": [0.001],
        "batch_size": 64,
        "time_mask_max_size": [5],
        "time_mask_count": [1],
        "freq_mask_max_size": [4],
        "freq_mask_count": [1],
        "mix_up_augmentation_prob": [0.0],
        "freq_mix_augmentation_prob": [0.0],
        "eval_step_interval": 200,
        "clip_duration_ms": 1500,
        "target_minimization": 0.0,
        "minimization_metric": None,
        "maximization_metric": "auc",
    }
    path = run_root / "training_parameters.yaml"
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return path


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_provenance(
    run_root: Path,
    datasets: dict[str, dict[str, list[Path]]],
    config_path: Path,
) -> None:
    payload = {
        "schema": "ainekio-local-wake-pilot-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "wake_word": "Ainekio",
        "generator_text": "Ay-neck-ee-oh",
        "approximate_ipa": "/aɪ nɛk iː oʊ/",
        "owner_speed_correction": CORRECTION_FACTOR,
        "training_config": str(config_path),
        "training_config_sha256": file_digest(config_path),
        "datasets": {
            name: {
                split: {"count": len(paths), "files": [str(path) for path in paths]}
                for split, paths in splits.items()
            }
            for name, splits in datasets.items()
        },
        "limitations": [
            "pilot data volume only",
            "locally generated negative speech is not a broad ambient corpus",
            "synthetic noise is not real room audio",
            "not validated on the final robot microphone",
        ],
    }
    (run_root / "provenance.json").write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    args = parse_args()
    if args.training_steps < 1:
        raise ValueError("--training-steps must be positive")

    voices = {
        "joe": args.voices_dir / "en_US-joe-medium.onnx",
        "ryan": args.voices_dir / "en_US-ryan-high.onnx",
        "lessac": args.voices_dir / "en_US-lessac-medium.onnx",
        "amy": args.voices_dir / "en_US-amy-medium.onnx",
    }
    ensure_sources(args.training_root, args.piper, voices)

    run_root = args.training_root / "runs" / args.run_name
    if run_root.exists():
        raise FileExistsError(f"pilot run already exists: {run_root}")
    run_root.mkdir(parents=True)

    datasets = {
        "synthetic-positive": split_synthetic(
            (args.training_root / "positive-corpus/v1").glob("*.wav")
        ),
        "owner-positive": split_owner(args.training_root),
        "negative-speech": generate_negative_speech(run_root, args.piper, voices),
        "negative-noise": generate_noise(run_root),
    }
    feature_roots = {
        name: write_feature_set(run_root, name, splits)
        for name, splits in datasets.items()
    }
    config_path = write_config(run_root, feature_roots, args.training_steps)
    write_provenance(run_root, datasets, config_path)

    counts = {
        name: {split: len(paths) for split, paths in splits.items()}
        for name, splits in datasets.items()
    }
    print(json.dumps({"run_root": str(run_root), "counts": counts}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
