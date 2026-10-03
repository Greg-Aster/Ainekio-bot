#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

check_only=0
if (( $# > 1 )); then
  echo "Usage: $0 [--check]" >&2
  exit 2
fi
if (( $# == 1 )); then
  if [[ "$1" != "--check" ]]; then
    echo "Usage: $0 [--check]" >&2
    exit 2
  fi
  check_only=1
fi

source "$SCRIPT_DIR/gateway-env.sh"
ainekio_load_environment "$REPO_ROOT"

if ! command -v cloudflared >/dev/null 2>&1; then
  echo "cloudflared is required to run the physical robot relay." >&2
  exit 2
fi

TUNNEL_ID="${AINEKIO_CLOUDFLARE_TUNNEL_ID:-}"
CREDENTIALS_FILE="${AINEKIO_CLOUDFLARE_CREDENTIALS_FILE:-}"
PUBLIC_HOSTNAME="robot-gateway.ainek.io"
GATEWAY_PORT="${AINEKIO_GATEWAY_PORT:-8790}"
ORIGIN_SERVICE="http://127.0.0.1:${GATEWAY_PORT}"
ENVIRONMENT_HOSTNAME="${AINEKIO_CLOUDFLARE_ENVIRONMENT_HOSTNAME:-}"
ENVIRONMENT_SERVICE="tcp://127.0.0.1:${GATEWAY_PORT}"

if [[ ! "$TUNNEL_ID" =~ ^[0-9a-fA-F-]{36}$ ]]; then
  echo "AINEKIO_CLOUDFLARE_TUNNEL_ID must be a Cloudflare tunnel UUID." >&2
  exit 2
fi
if [[ -z "$CREDENTIALS_FILE" || "$CREDENTIALS_FILE" != /* ]]; then
  echo "AINEKIO_CLOUDFLARE_CREDENTIALS_FILE must be an absolute path." >&2
  exit 2
fi
if [[ ! "$CREDENTIALS_FILE" =~ ^[A-Za-z0-9._/-]+$ ]]; then
  echo "The Cloudflare credentials path contains unsupported characters." >&2
  exit 2
fi
if [[ ! -r "$CREDENTIALS_FILE" ]]; then
  echo "Cloudflare tunnel credentials are not readable: $CREDENTIALS_FILE" >&2
  exit 2
fi

credentials_realpath="$(realpath "$CREDENTIALS_FILE")"
case "$credentials_realpath" in
  "$REPO_ROOT"/*)
    echo "Refusing Cloudflare credentials stored inside the repository." >&2
    exit 2
    ;;
esac

RUNTIME_DIR="$REPO_ROOT/build/gateway/cloudflare"
RUNTIME_CONFIG="$RUNTIME_DIR/ainekio-robot.yml"
install -d -m 700 "$RUNTIME_DIR"
umask 077
{
  printf 'tunnel: %s\n' "$TUNNEL_ID"
  printf 'credentials-file: %s\n' "$credentials_realpath"
  printf '\n'
  printf 'ingress:\n'
  printf '  - hostname: %s\n' "$PUBLIC_HOSTNAME"
  printf '    path: ^/robot$\n'
  printf '    service: %s\n' "$ORIGIN_SERVICE"
  if [[ -n "$ENVIRONMENT_HOSTNAME" ]]; then
    printf '  - hostname: %s\n' "$ENVIRONMENT_HOSTNAME"
    printf '    service: %s\n' "$ENVIRONMENT_SERVICE"
  fi
  printf '  - service: http_status:404\n'
} >"$RUNTIME_CONFIG"

cloudflared tunnel --config "$RUNTIME_CONFIG" ingress validate
robot_rule="$(
  cloudflared tunnel --config "$RUNTIME_CONFIG" ingress rule \
    "https://${PUBLIC_HOSTNAME}/robot"
)"
environment_rule="$(
  cloudflared tunnel --config "$RUNTIME_CONFIG" ingress rule \
    "https://${PUBLIC_HOSTNAME}/environment"
)"
if [[ "$robot_rule" != *"${ORIGIN_SERVICE}"* ]]; then
  echo "The /robot URL did not select the gateway origin rule." >&2
  exit 2
fi
if [[ "$environment_rule" != *"http_status:404"* ]]; then
  echo "The /environment URL did not select the blocking rule." >&2
  exit 2
fi
if (( check_only )); then
  echo "Physical relay configuration check passed."
  echo "  Public robot URL:   wss://${PUBLIC_HOSTNAME}/robot"
  echo "  Local origin:       ${ORIGIN_SERVICE}/robot"
  echo "  Robot hostname:     /robot only; dashboard is not routed"
  if [[ -n "$ENVIRONMENT_HOSTNAME" ]]; then
    echo "  Access TCP hostname: ${ENVIRONMENT_HOSTNAME} -> ${ENVIRONMENT_SERVICE}"
    echo "  Protect this hostname with Cloudflare Access before running the relay."
  fi
  echo "  Runtime config:     ${RUNTIME_CONFIG}"
  exit 0
fi

echo "Starting the physical Ainekio Cloudflare relay."
echo "  Public robot URL:   wss://${PUBLIC_HOSTNAME}/robot"
echo "  Local origin:       ${ORIGIN_SERVICE}/robot"
echo "  Robot hostname:     /robot only; dashboard is not routed"
if [[ -n "$ENVIRONMENT_HOSTNAME" ]]; then
  echo "  Access TCP hostname: ${ENVIRONMENT_HOSTNAME} -> ${ENVIRONMENT_SERVICE}"
  echo "  Desktop: cloudflared access tcp --hostname ${ENVIRONMENT_HOSTNAME} --url 127.0.0.1:18790"
fi
echo "  Runtime config:     ${RUNTIME_CONFIG}"
echo "Press Ctrl+C to stop the relay."

exec cloudflared tunnel \
  --config "$RUNTIME_CONFIG" \
  --no-autoupdate \
  run "$TUNNEL_ID"
