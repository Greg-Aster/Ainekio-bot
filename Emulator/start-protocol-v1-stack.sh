#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

export AINEKIO_ROBOT_ID="${AINEKIO_ROBOT_ID:-ainekio-emulator-01}"
if [[ -z "${AINEKIO_ROBOT_TOKEN:-}" ]]; then
  AINEKIO_ROBOT_TOKEN="$(openssl rand -hex 24)"
  export AINEKIO_ROBOT_TOKEN
fi
if [[ -z "${AINEKIO_DASHBOARD_PASSWORD:-}" ]]; then
  AINEKIO_DASHBOARD_PASSWORD="$(openssl rand -base64 18 | tr -d '\n')"
  export AINEKIO_DASHBOARD_PASSWORD
fi
export AINEKIO_STACK_DATA_DIR="${AINEKIO_STACK_DATA_DIR:-$REPO_ROOT/build/emulator-stack/$$}"

PIDS=()

cleanup() {
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
  "$@" &
  local pid=$!
  PIDS+=("$pid")
  sleep 0.6
  if ! kill -0 "$pid" 2>/dev/null; then
    echo "${name} exited during startup." >&2
    wait "$pid"
  fi
}

trap cleanup EXIT INT TERM

echo "Ainekio dashboard password: ${AINEKIO_DASHBOARD_PASSWORD}"
echo "Robot id: ${AINEKIO_ROBOT_ID}"

start_process "Sesame simulator" "$SCRIPT_DIR/sesame-robot-sim/run.sh"
start_process "Simulator shim" "$SCRIPT_DIR/start-simulator-shim.sh"
start_process "Gateway" env \
  PYTHONPATH="$REPO_ROOT/Master:$REPO_ROOT/Slave/software${PYTHONPATH:+:$PYTHONPATH}" \
  python3 -m gateway.server --data-dir "$AINEKIO_STACK_DATA_DIR"
start_process "Body emulator" "$SCRIPT_DIR/start-protocol-v1-emulator.sh" \
  --robot-id "$AINEKIO_ROBOT_ID"

echo
echo "Ainekio protocol-v1 emulator is running."
echo "  Dashboard:        http://127.0.0.1:8791/"
echo "  Sesame simulator: http://127.0.0.1:${PORT:-8765}/"
echo "  Robot gateway:    ws://127.0.0.1:8790/robot"
echo "  Fault controls:   http://127.0.0.1:8792/status"
echo "  Runtime data:     ${AINEKIO_STACK_DATA_DIR}"
echo "Press Ctrl+C to stop the stack."

while true; do
  for pid in "${PIDS[@]}"; do
    if ! kill -0 "$pid" 2>/dev/null; then
      echo "A stack process exited; stopping the rest." >&2
      exit 1
    fi
  done
  sleep 1
done
