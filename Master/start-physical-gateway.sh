#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

ENV_FILE="$REPO_ROOT/.env"
if [[ -f "$ENV_FILE" ]]; then
  declare -A explicit_ainekio_env=()
  while IFS='=' read -r -d '' env_name env_value; do
    if [[ "$env_name" == AINEKIO_* ]]; then
      explicit_ainekio_env["$env_name"]="$env_value"
    fi
  done < <(env -0)

  allexport_was_enabled=0
  if [[ "$-" == *a* ]]; then
    allexport_was_enabled=1
  fi
  set -a
  # shellcheck disable=SC1090 -- this is the operator's repo-local environment file.
  source "$ENV_FILE"
  if (( ! allexport_was_enabled )); then
    set +a
  fi

  for env_name in "${!explicit_ainekio_env[@]}"; do
    printf -v "$env_name" '%s' "${explicit_ainekio_env[$env_name]}"
    export "$env_name"
  done
  unset explicit_ainekio_env env_name env_value allexport_was_enabled
fi

DATA_DIR="${AINEKIO_GATEWAY_DATA_DIR:-$REPO_ROOT/build/gateway/physical}"
GATEWAY_HOST="${AINEKIO_GATEWAY_HOST:-0.0.0.0}"
GATEWAY_PORT="${AINEKIO_GATEWAY_PORT:-8790}"
DASHBOARD_HOST="${AINEKIO_DASHBOARD_HOST:-127.0.0.1}"
DASHBOARD_PORT="${AINEKIO_DASHBOARD_PORT:-8791}"
LOCAL_DISCOVERY="${AINEKIO_LOCAL_DISCOVERY:-1}"

if [[ -z "${AINEKIO_ENVIRONMENT_ADAPTER_TOKEN:-}" ]]; then
  echo "AINEKIO_ENVIRONMENT_ADAPTER_TOKEN is required for the MetaHuman Environment Bridge." >&2
  exit 2
fi

if [[ ! -f "$DATA_DIR/robot-tokens.json" && -z "${AINEKIO_ROBOT_TOKEN:-}" ]]; then
  echo "First launch requires AINEKIO_ROBOT_TOKEN to seed the physical robot identity." >&2
  echo "Set AINEKIO_ROBOT_ID (default: ainekio-01) and a strong AINEKIO_ROBOT_TOKEN." >&2
  exit 2
fi

export AINEKIO_ROBOT_ID="${AINEKIO_ROBOT_ID:-ainekio-01}"
export AINEKIO_ENVIRONMENT_SESSION_ID="${AINEKIO_ENVIRONMENT_SESSION_ID:-$AINEKIO_ROBOT_ID}"
mkdir -p "$DATA_DIR"

lan_addresses="$(hostname -I 2>/dev/null || true)"
advertised_host="${AINEKIO_GATEWAY_ADVERTISED_HOST:-}"
if [[ -z "$advertised_host" ]]; then
  if [[ "$GATEWAY_HOST" != "0.0.0.0" && "$GATEWAY_HOST" != "::" ]]; then
    advertised_host="$GATEWAY_HOST"
  elif command -v ip >/dev/null 2>&1; then
    advertised_host="$(
      ip -4 route get 1.1.1.1 2>/dev/null |
        awk '{for (field = 1; field <= NF; ++field) if ($field == "src") {print $(field + 1); exit}}'
    )"
  fi
fi
if [[ -z "$advertised_host" && -n "$lan_addresses" ]]; then
  advertised_host="${lan_addresses%% *}"
fi

echo "Starting the physical Ainekio gateway."
echo "  Gateway bind:       ${GATEWAY_HOST}:${GATEWAY_PORT}"
if [[ -n "$advertised_host" ]]; then
  echo "  Direct LAN check:   ws://${advertised_host}:${GATEWAY_PORT}/robot"
  echo "  Environment URL:    ws://127.0.0.1:${GATEWAY_PORT}/environment"
else
  echo "  Robot setup URL:    unavailable; set AINEKIO_GATEWAY_ADVERTISED_HOST"
fi
echo "  Local dashboard:    http://${DASHBOARD_HOST}:${DASHBOARD_PORT}/"
if [[ -n "$lan_addresses" ]]; then
  echo "  Brain LAN addresses: ${lan_addresses}"
fi
echo "  Robot ID:           ${AINEKIO_ROBOT_ID}"
echo "  Runtime data:       ${DATA_DIR}"
if [[ -n "${AINEKIO_DASHBOARD_PASSWORD:-}" ]]; then
  echo "  Dashboard password: configured from environment"
else
  echo "  Dashboard password: existing verifier"
fi
echo "Press Ctrl+C to stop the gateway."

cd "$REPO_ROOT"

discovery_pid=""
cleanup_discovery() {
  if [[ -n "$discovery_pid" ]] && kill -0 "$discovery_pid" 2>/dev/null; then
    kill "$discovery_pid" 2>/dev/null || true
    wait "$discovery_pid" 2>/dev/null || true
  fi
}
trap cleanup_discovery EXIT

if [[ "$LOCAL_DISCOVERY" == "1" ]]; then
  if ! command -v avahi-publish-service >/dev/null 2>&1; then
    echo "Local discovery requires avahi-publish-service." >&2
    exit 2
  fi
  avahi-publish-service \
    --service \
    "Ainekio Gateway" \
    _ainekio._tcp \
    "$GATEWAY_PORT" \
    "protocol=1" \
    "path=/robot" \
    "transport=lan" \
    "tls=0" &
  discovery_pid=$!
  echo "  Local discovery:   _ainekio._tcp.local"
else
  echo "  Local discovery:   disabled explicitly"
fi

env \
  AINEKIO_GATEWAY_ADVERTISED_HOST="$advertised_host" \
  PYTHONPATH="$REPO_ROOT/Master:$REPO_ROOT/Slave/software${PYTHONPATH:+:$PYTHONPATH}" \
  python3 -m gateway.server \
    --host "$GATEWAY_HOST" \
    --port "$GATEWAY_PORT" \
    --dashboard-host "$DASHBOARD_HOST" \
    --dashboard-port "$DASHBOARD_PORT" \
    --dashboard-primary-view camera \
    --data-dir "$DATA_DIR" \
    "$@"
