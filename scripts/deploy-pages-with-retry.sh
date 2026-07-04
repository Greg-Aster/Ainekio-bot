#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 || $# -gt 3 ]]; then
  echo "Usage: $0 <dist-dir> <project-name> [branch]" >&2
  exit 64
fi

dist_dir="$1"
project_name="$2"
branch="${3:-${DEPLOY_BRANCH:-${CI_COMMIT_REF_NAME:-main}}}"
max_attempts="${CF_DEPLOY_MAX_ATTEMPTS:-5}"
delay_seconds="${CF_DEPLOY_RETRY_DELAY_SECONDS:-10}"

is_retryable_failure() {
  local output="$1"

  [[ "$output" == *"503 Service Unavailable"* ]] \
    || [[ "$output" == *"502 Bad Gateway"* ]] \
    || [[ "$output" == *"504 Gateway Timeout"* ]] \
    || [[ "$output" == *"no healthy upstream"* ]] \
    || [[ "$output" == *"Received a malformed response from the API"* ]] \
    || [[ "$output" == *"A request to the Cloudflare API"* ]]
}

attempt=1
while true; do
  set +e
  deploy_output="$(pnpm dlx wrangler pages deploy "$dist_dir" --project-name "$project_name" --branch "$branch" 2>&1)"
  deploy_status=$?
  set -e

  printf '%s\n' "$deploy_output"

  if [[ $deploy_status -eq 0 ]]; then
    exit 0
  fi

  if [[ $attempt -ge $max_attempts ]] || ! is_retryable_failure "$deploy_output"; then
    exit $deploy_status
  fi

  echo "Cloudflare Pages deploy failed with a retryable API error. Retrying in ${delay_seconds}s (attempt $((attempt + 1))/${max_attempts})..."
  sleep "$delay_seconds"

  attempt=$((attempt + 1))
  if [[ $delay_seconds -lt 60 ]]; then
    delay_seconds=$((delay_seconds * 2))
    if [[ $delay_seconds -gt 60 ]]; then
      delay_seconds=60
    fi
  fi
done
