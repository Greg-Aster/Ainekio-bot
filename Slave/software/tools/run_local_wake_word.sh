#!/usr/bin/env bash
set -euo pipefail

training_root="${AINEKIO_WAKE_TRAINING_ROOT:-${HOME}/ainekio-wake-training}"
venv="${training_root}/.venv"

if [[ ! -x "${venv}/bin/python" ]]; then
  echo "Ainekio wake-word environment not found: ${venv}" >&2
  exit 2
fi

python_version="$(${venv}/bin/python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
site_packages="${venv}/lib/python${python_version}/site-packages"
nvidia_root="${site_packages}/nvidia"
cuda_library_path=""

if [[ -d "${nvidia_root}" ]]; then
  for library_dir in "${nvidia_root}"/*/lib; do
    [[ -d "${library_dir}" ]] || continue
    if [[ -z "${cuda_library_path}" ]]; then
      cuda_library_path="${library_dir}"
    else
      cuda_library_path="${cuda_library_path}:${library_dir}"
    fi
  done
fi

if [[ -n "${cuda_library_path}" ]]; then
  export LD_LIBRARY_PATH="${cuda_library_path}${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"
fi
export PATH="${venv}/bin:${PATH}"

if [[ $# -eq 0 ]]; then
  echo "usage: $0 COMMAND [ARG ...]" >&2
  exit 2
fi

exec "$@"
