#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PIDS=()

cleanup() {
  echo
  echo "Stopping Ainekio simulator stack..."
  for pid in "${PIDS[@]:-}"; do
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
    fi
  done
  wait 2>/dev/null || true
}

start_process() {
  local name="$1"
  shift
  echo
  echo "Starting ${name}..."
  "$@" &
  local pid=$!
  PIDS+=("$pid")
  echo "  pid: ${pid}"
  sleep 0.7
  if ! kill -0 "$pid" 2>/dev/null; then
    echo "${name} exited during startup."
    wait "$pid"
  fi
}

trap cleanup EXIT INT TERM

echo "================================"
echo "  Ainekio Simulator Stack"
echo "================================"

start_process "Sesame simulator" "$SCRIPT_DIR/simulators/sesame-robot-sim/run.sh"
start_process "Ainekio simulator shim" "$SCRIPT_DIR/start-simulator-shim.sh"
start_process "Ainekio adapter" "$SCRIPT_DIR/start-ainekio-adapter.sh"

echo
echo "Ainekio simulator stack is running."
echo "  Sesame simulator: http://127.0.0.1:${PORT:-8765}/"
echo "  Simulator shim:   http://127.0.0.1:${AINEKIO_SIMULATOR_SHIM_PORT:-8788}/health"
echo "  Shim monitor:     http://127.0.0.1:${AINEKIO_SIMULATOR_SHIM_PORT:-8788}/monitor"
echo "  MetaHuman target: ${AINEKIO_METAHUMAN_URL:-http://192.168.0.44:4321}"
echo
echo "Open the Sesame simulator page and send an Environment Mode command in MetaHuman."
echo "Press Ctrl+C here to stop all three Ainekio processes."

while true; do
  for pid in "${PIDS[@]}"; do
    if ! kill -0 "$pid" 2>/dev/null; then
      echo
      echo "A stack process exited; stopping the rest."
      exit 1
    fi
  done
  sleep 1
done
