#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

BASE_URL="${AINEKIO_METAHUMAN_URL:-http://192.168.0.44:4321}"
SESSION_ID="${AINEKIO_SESSION_ID:-ainekio-sim-1}"
LIMIT="${AINEKIO_ACTION_LIMIT:-10}"
SIMULATOR_SHIM_URL="${AINEKIO_SIMULATOR_SHIM_URL:-http://127.0.0.1:8788}"

echo "Starting Ainekio adapter"
echo "  MetaHuman: $BASE_URL"
echo "  Session:   $SESSION_ID"
echo "  Simulator: $SIMULATOR_SHIM_URL"
echo

PYTHONPATH="$SCRIPT_DIR:$SCRIPT_DIR/legacy/motion/src${PYTHONPATH:+:$PYTHONPATH}" \
  python3 -m ainekio_motion.cli \
    --base-url "$BASE_URL" \
    --session-id "$SESSION_ID" \
    --limit "$LIMIT" \
    --simulator-shim-url "$SIMULATOR_SHIM_URL"
