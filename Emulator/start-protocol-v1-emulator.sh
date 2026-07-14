#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

if [[ -z "${AINEKIO_ROBOT_TOKEN:-}" ]]; then
  echo "AINEKIO_ROBOT_TOKEN must be set; tokens are not stored in the repo." >&2
  exit 1
fi

cmake -S "$SCRIPT_DIR/emulator" -B "$REPO_ROOT/build/emulator"
cmake --build "$REPO_ROOT/build/emulator"

PYTHONPATH="$SCRIPT_DIR:$REPO_ROOT/Slave/software${PYTHONPATH:+:$PYTHONPATH}" \
  python3 -m emulator.body "$@"
