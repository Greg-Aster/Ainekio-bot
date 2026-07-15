#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="${AINEKIO_CONFIG_FILE:-$REPO_ROOT/.env}"

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  echo "Usage: ./start.sh"
  echo "Starts the complete local Ainekio emulator, gateway, dashboard, and environment adapter."
  echo "Configuration: ${AINEKIO_CONFIG_FILE:-$REPO_ROOT/.env}"
  echo "Press Ctrl+C to stop every process."
  exit 0
fi

if (( $# != 0 )); then
  echo "Usage: ./start.sh" >&2
  exit 2
fi

if [[ -f "$CONFIG_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$CONFIG_FILE"
  set +a
fi

if [[ -z "${AINEKIO_ENVIRONMENT_ADAPTER_TOKEN:-}" ]]; then
  echo "Ainekio cannot start: AINEKIO_ENVIRONMENT_ADAPTER_TOKEN is not configured." >&2
  echo "Create $CONFIG_FILE from .env.example and configure the same adapter token in MetaHuman OS." >&2
  exit 1
fi

exec "$REPO_ROOT/Emulator/start-protocol-v1-stack.sh"
