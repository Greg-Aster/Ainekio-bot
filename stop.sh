#!/usr/bin/env bash
set -u

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STOP_TIMEOUT="${AINEKIO_STOP_TIMEOUT:-5}"

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  echo "Usage: ./stop.sh"
  echo "Stops the local Ainekio emulator, gateway, dashboard, and environment adapter."
  echo "Set AINEKIO_STOP_TIMEOUT to change the ${STOP_TIMEOUT}-second graceful shutdown timeout."
  exit 0
fi

if (( $# != 0 )); then
  echo "Usage: ./stop.sh" >&2
  exit 2
fi

if [[ ! "$STOP_TIMEOUT" =~ ^[0-9]+$ ]]; then
  echo "AINEKIO_STOP_TIMEOUT must be a non-negative whole number." >&2
  exit 2
fi

if ! command -v pgrep >/dev/null 2>&1; then
  echo "Ainekio cannot stop automatically because pgrep is not installed." >&2
  exit 1
fi

declare -a FOUND_PIDS=()

add_pid() {
  local candidate="$1"
  local existing

  for existing in "${FOUND_PIDS[@]}"; do
    if [[ "$existing" == "$candidate" ]]; then
      return
    fi
  done
  FOUND_PIDS+=("$candidate")
}

process_cwd() {
  readlink -e "/proc/$1/cwd" 2>/dev/null || true
}

process_command() {
  tr '\0' ' ' < "/proc/$1/cmdline" 2>/dev/null || true
}

find_supervisors() {
  local pid cwd command
  FOUND_PIDS=()

  while IFS= read -r pid; do
    [[ -n "$pid" && "$pid" != "$$" ]] || continue
    cwd="$(process_cwd "$pid")"
    command="$(process_command "$pid")"
    if [[ "$cwd" == "$REPO_ROOT" && "$command" == *"Emulator/start-protocol-v1-stack.sh"* ]]; then
      add_pid "$pid"
    fi
  done < <(pgrep -f 'Emulator/start-protocol-v1-stack\.sh' 2>/dev/null || true)
}

find_services() {
  local pid cwd command
  FOUND_PIDS=()

  while IFS= read -r pid; do
    [[ -n "$pid" && "$pid" != "$$" ]] || continue
    cwd="$(process_cwd "$pid")"
    command="$(process_command "$pid")"

    case "$command" in
      *"$REPO_ROOT/Emulator/sesame-robot-sim/run.sh"* | \
      *"$REPO_ROOT/Emulator/start-simulator-shim.sh"* | \
      *"$REPO_ROOT/Emulator/start-protocol-v1-emulator.sh"*)
        add_pid "$pid"
        ;;
      *"python3 -m gateway.server"* | \
      *"python3 -m emulator.body"* | \
      *"python3 -m emulator.backends.sesame_shim"*)
        if [[ "$cwd" == "$REPO_ROOT" ]]; then
          add_pid "$pid"
        fi
        ;;
      *"python3 -m http.server "*)
        if [[ "$cwd" == "$REPO_ROOT/Emulator/sesame-robot-sim/app" ]]; then
          add_pid "$pid"
        fi
        ;;
    esac
  done < <(
    pgrep -f 'sesame-robot-sim/run\.sh|start-simulator-shim\.sh|start-protocol-v1-emulator\.sh|python3 -m (gateway\.server|emulator\.body|emulator\.backends\.sesame_shim|http\.server)' 2>/dev/null || true
  )
}

wait_for_exit() {
  local deadline=$((SECONDS + STOP_TIMEOUT))
  local pid running

  while :; do
    running=0
    for pid in "$@"; do
      if kill -0 "$pid" 2>/dev/null; then
        running=1
        break
      fi
    done

    if (( running == 0 )); then
      return 0
    fi
    if (( SECONDS >= deadline )); then
      return 1
    fi
    sleep 0.1
  done
}

find_supervisors
supervisors=("${FOUND_PIDS[@]}")

if (( ${#supervisors[@]} != 0 )); then
  echo "Stopping Ainekio stack (supervisor PID(s): ${supervisors[*]})..."
  for pid in "${supervisors[@]}"; do
    kill -TERM "$pid" 2>/dev/null || true
  done
  if ! wait_for_exit "${supervisors[@]}"; then
    echo "Supervisor shutdown timed out; forcing it to stop." >&2
    for pid in "${supervisors[@]}"; do
      kill -KILL "$pid" 2>/dev/null || true
    done
    wait_for_exit "${supervisors[@]}" || true
  fi
fi

find_services
services=("${FOUND_PIDS[@]}")

if (( ${#services[@]} != 0 )); then
  if (( ${#supervisors[@]} == 0 )); then
    echo "Ainekio stack supervisor was not found; stopping remaining service PID(s): ${services[*]}..."
  else
    echo "Stopping remaining Ainekio service PID(s): ${services[*]}..."
  fi

  for pid in "${services[@]}"; do
    kill -TERM "$pid" 2>/dev/null || true
  done

  if ! wait_for_exit "${services[@]}"; then
    echo "Graceful shutdown timed out; forcing remaining Ainekio services to stop." >&2
    for pid in "${services[@]}"; do
      kill -KILL "$pid" 2>/dev/null || true
    done
    wait_for_exit "${services[@]}" || true
  fi
fi

find_services
if (( ${#FOUND_PIDS[@]} != 0 )); then
  echo "Some Ainekio services are still running (PID(s): ${FOUND_PIDS[*]})." >&2
  exit 1
fi

if (( ${#supervisors[@]} == 0 && ${#services[@]} == 0 )); then
  echo "No Ainekio stack is running."
else
  echo "Ainekio stack stopped."
fi
