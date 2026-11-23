#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/../../.." && pwd)"
BUILD_DIR="$REPO_ROOT/build/gait-wasm"
OUT_DIR="${1:-$REPO_ROOT/apps/simulator/public/sim}"
EMSDK_IMAGE="${AINEKIO_EMSDK_IMAGE:-emscripten/emsdk:3.1.73}"

mkdir -p "$BUILD_DIR" "$OUT_DIR"

if command -v emcmake >/dev/null 2>&1; then
  emcmake cmake -S "$SCRIPT_DIR" -B "$BUILD_DIR" -DCMAKE_BUILD_TYPE=Release
  cmake --build "$BUILD_DIR" --target ainekio_v2_firmware -j"$(nproc)"
else
  docker run --rm \
    -u "$(id -u):$(id -g)" \
    -v "$REPO_ROOT:/work" \
    -w /work \
    "$EMSDK_IMAGE" \
    bash -lc 'emcmake cmake -S Master/gateway/neural_gait -B build/gait-wasm -DCMAKE_BUILD_TYPE=Release && cmake --build build/gait-wasm --target ainekio_v2_firmware -j"$(nproc)"'
fi

cp "$BUILD_DIR/ainekio-v2-firmware.mjs" "$OUT_DIR/ainekio-v2-firmware.mjs"
cp "$BUILD_DIR/ainekio-v2-firmware.wasm" "$OUT_DIR/ainekio-v2-firmware.wasm"
ls -lh "$OUT_DIR/ainekio-v2-firmware.mjs" "$OUT_DIR/ainekio-v2-firmware.wasm"
