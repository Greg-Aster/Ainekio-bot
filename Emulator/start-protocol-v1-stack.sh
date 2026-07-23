#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

port_is_listening() {
  python3 - "$1" "$2" <<'PY'
import socket
import sys

host = sys.argv[1]
port = int(sys.argv[2])
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
    probe.settimeout(0.2)
    raise SystemExit(0 if probe.connect_ex((host, port)) == 0 else 1)
PY
}

occupied_services=()
while IFS='|' read -r label host port; do
  if port_is_listening "$host" "$port"; then
    occupied_services+=("${label} (${host}:${port})")
  fi
done <<EOF
Sesame simulator|127.0.0.1|${PORT:-8765}
Simulator shim|${AINEKIO_SIMULATOR_SHIM_HOST:-127.0.0.1}|${AINEKIO_SIMULATOR_SHIM_PORT:-8788}
Robot gateway|127.0.0.1|8790
Operator dashboard|127.0.0.1|8791
Fault controls|127.0.0.1|8792
EOF

if (( ${#occupied_services[@]} != 0 )); then
  echo "Ainekio cannot start because required services are already listening:" >&2
  printf '  - %s\n' "${occupied_services[@]}" >&2
  echo "Another Ainekio stack may already be running. Stop it with Ctrl+C before starting a new one." >&2
  exit 1
fi

export AINEKIO_ROBOT_ID="${AINEKIO_ROBOT_ID:-ainekio-emulator-01}"
if [[ -z "${AINEKIO_ENVIRONMENT_ADAPTER_TOKEN:-}" ]]; then
  echo "AINEKIO_ENVIRONMENT_ADAPTER_TOKEN is required." >&2
  exit 1
fi
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
  trap - EXIT
  for pid in "${PIDS[@]:-}"; do
    kill -TERM -- "-$pid" 2>/dev/null || true
  done
  sleep 0.5
  for pid in "${PIDS[@]:-}"; do
    kill -KILL -- "-$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
}

start_process() {
  local name="$1"
  shift
  setsid "$@" &
  local pid=$!
  PIDS+=("$pid")
  sleep 0.6
  if ! kill -0 "$pid" 2>/dev/null; then
    echo "${name} exited during startup." >&2
    wait "$pid"
  fi
}

trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

echo "Ainekio dashboard password: ${AINEKIO_DASHBOARD_PASSWORD}"
echo "Robot id: ${AINEKIO_ROBOT_ID}"
echo "Environment adapter token: configured"

start_process "Sesame simulator" "$SCRIPT_DIR/sesame-robot-sim/run.sh"
start_process "Simulator shim" "$SCRIPT_DIR/start-simulator-shim.sh"
start_process "Gateway" env \
  PYTHONPATH="$REPO_ROOT/Master:$REPO_ROOT/Slave/software${PYTHONPATH:+:$PYTHONPATH}" \
  python3 -m gateway.server \
    --dashboard-primary-view simulator \
    --data-dir "$AINEKIO_STACK_DATA_DIR"
start_process "Body emulator" "$SCRIPT_DIR/start-protocol-v1-emulator.sh" \
  --robot-id "$AINEKIO_ROBOT_ID"

echo
echo "Ainekio protocol-v1 emulator is running."
echo "  Dashboard:        http://127.0.0.1:8791/"
echo "  Sesame simulator: http://127.0.0.1:${PORT:-8765}/"
echo "  Robot gateway:    ws://127.0.0.1:8790/robot"
echo "  Environment:      ws://127.0.0.1:8790/environment"
echo "  Fault controls:   http://127.0.0.1:8792/status"
echo "  Runtime data:     ${AINEKIO_STACK_DATA_DIR}"
echo "Press Ctrl+C to stop the stack."

set +e
wait -n "${PIDS[@]}"
set -e
echo "A stack process exited; stopping the rest." >&2
exit 1
