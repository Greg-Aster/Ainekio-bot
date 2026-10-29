#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname -- "$SCRIPT_DIR")"
source "$SCRIPT_DIR/gateway-env.sh"
ainekio_load_environment "$REPO_ROOT"
cd "$REPO_ROOT"
export PYTHONPATH="$REPO_ROOT/Master:$REPO_ROOT/Slave/software${PYTHONPATH:+:$PYTHONPATH}"
export MPLCONFIGDIR="${MPLCONFIGDIR:-$REPO_ROOT/build/neural-gait/matplotlib}"
export MUJOCO_GL="${MUJOCO_GL:-egl}"
exec "${AINEKIO_NEURAL_GAIT_PYTHON:-$REPO_ROOT/build/gait-training-env/bin/python}" \
  -m gateway.neural_gait.server \
  --directory "${AINEKIO_NEURAL_GAIT_DATA_DIR:-$REPO_ROOT/build/neural-gait}" \
  --port "${AINEKIO_NEURAL_GAIT_PORT:-8796}" \
  --device "${AINEKIO_NEURAL_GAIT_DEVICE:-cpu}" "$@"
