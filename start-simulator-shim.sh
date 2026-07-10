#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

HOST="${AINEKIO_SIMULATOR_SHIM_HOST:-127.0.0.1}"
PORT="${AINEKIO_SIMULATOR_SHIM_PORT:-8788}"

PYTHONPATH="$SCRIPT_DIR/motion/src${PYTHONPATH:+:$PYTHONPATH}" \
  python3 -m ainekio_motion.simulator_shim --host "$HOST" --port "$PORT"
