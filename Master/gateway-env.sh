#!/usr/bin/env bash
# Shared configuration for the existing gateway, stop and relay entrypoints.
# Explicit AINEKIO_* environment variables retain precedence over .env.
ainekio_load_environment() {
  local REPO_ROOT="$1"
  local ENV_FILE="$REPO_ROOT/.env"
  local env_name env_value allexport_was_enabled
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
}
