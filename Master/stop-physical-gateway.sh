#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DATA_DIR="$(realpath -m "${AINEKIO_GATEWAY_DATA_DIR:-$REPO_ROOT/build/gateway/physical}")"
PID_FILE="$DATA_DIR/physical-gateway.pid"
STOP_TIMEOUT="${AINEKIO_STOP_TIMEOUT:-5}"
SERVICE_UNIT="ainekio-gateway.service"
disable_service=0

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  echo "Usage: $0 [--disable]"
  echo "Stops only the physical Ainekio gateway using $DATA_DIR."
  echo "Pass --disable to also prevent the user service from starting automatically."
  echo "Set AINEKIO_STOP_TIMEOUT to change the ${STOP_TIMEOUT}-second timeout."
  exit 0
fi
if (( $# == 1 )) && [[ "$1" == "--disable" ]]; then
  disable_service=1
elif (( $# != 0 )); then
  echo "Usage: $0 [--disable]" >&2
  exit 2
fi
if [[ ! "$STOP_TIMEOUT" =~ ^[0-9]+$ ]]; then
  echo "AINEKIO_STOP_TIMEOUT must be a non-negative whole number." >&2
  exit 2
fi
if ! command -v pgrep >/dev/null 2>&1; then
  echo "Cannot locate the physical gateway because pgrep is not installed." >&2
  exit 1
fi

process_matches_gateway() {
  local pid="$1"
  local cwd argument next_argument
  local found_module=0
  local found_data_dir=0
  local -a arguments=()

  [[ "$pid" =~ ^[0-9]+$ && -r "/proc/$pid/cmdline" ]] || return 1
  cwd="$(readlink -e "/proc/$pid/cwd" 2>/dev/null || true)"
  [[ "$cwd" == "$REPO_ROOT" ]] || return 1
  mapfile -d '' -t arguments <"/proc/$pid/cmdline" || return 1

  for (( index = 0; index < ${#arguments[@]}; ++index )); do
    argument="${arguments[$index]}"
    next_argument="${arguments[$((index + 1))]:-}"
    if [[ "$argument" == "-m" && "$next_argument" == "gateway.server" ]]; then
      found_module=1
    elif [[ "$argument" == "--data-dir" && -n "$next_argument" ]] &&
         [[ "$(realpath -m "$next_argument")" == "$DATA_DIR" ]]; then
      found_data_dir=1
    fi
  done
  (( found_module && found_data_dir ))
}

declare -a gateway_pids=()
add_gateway_pid() {
  local candidate="$1"
  local existing
  process_matches_gateway "$candidate" || return
  for existing in "${gateway_pids[@]}"; do
    [[ "$existing" == "$candidate" ]] && return
  done
  gateway_pids+=("$candidate")
}

service_changed=0
if (( disable_service )); then
  if ! command -v systemctl >/dev/null 2>&1; then
    echo "Cannot disable $SERVICE_UNIT because systemctl is not installed." >&2
    exit 1
  fi
  echo "Stopping and disabling supervised physical gateway service..."
  if ! systemctl --user disable --now "$SERVICE_UNIT"; then
    echo "Could not disable $SERVICE_UNIT; no process fallback was attempted." >&2
    exit 1
  fi
  service_changed=1
elif command -v systemctl >/dev/null 2>&1 &&
     systemctl --user is-active --quiet "$SERVICE_UNIT" 2>/dev/null; then
  echo "Stopping supervised physical gateway service..."
  if ! systemctl --user stop "$SERVICE_UNIT"; then
    echo "Could not stop $SERVICE_UNIT; no process fallback was attempted." >&2
    exit 1
  fi
  service_changed=1
fi

if [[ -r "$PID_FILE" ]]; then
  IFS= read -r recorded_pid <"$PID_FILE" || true
  add_gateway_pid "${recorded_pid:-}"
fi
while IFS= read -r candidate; do
  [[ -n "$candidate" && "$candidate" != "$$" ]] || continue
  add_gateway_pid "$candidate"
done < <(pgrep -f 'python3 -m gateway\.server' 2>/dev/null || true)

if (( ${#gateway_pids[@]} == 0 )); then
  rm -f "$PID_FILE"
  if (( service_changed )); then
    echo "Physical Ainekio gateway stopped."
  else
    echo "The physical Ainekio gateway is not running."
  fi
  exit 0
fi

echo "Stopping the physical Ainekio gateway (PID(s): ${gateway_pids[*]})..."
for pid in "${gateway_pids[@]}"; do
  kill -TERM "$pid" 2>/dev/null || true
done

deadline=$((SECONDS + STOP_TIMEOUT))
while :; do
  still_running=0
  for pid in "${gateway_pids[@]}"; do
    if process_matches_gateway "$pid"; then
      still_running=1
      break
    fi
  done
  (( still_running )) || break
  if (( SECONDS >= deadline )); then
    echo "Gateway did not stop within ${STOP_TIMEOUT} seconds; it was not force-killed." >&2
    exit 1
  fi
  sleep 0.1
done

rm -f "$PID_FILE"
echo "Physical Ainekio gateway stopped."
