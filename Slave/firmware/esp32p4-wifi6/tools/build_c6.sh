#!/usr/bin/env bash
set -euo pipefail
target_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
test "${IDF_PATH:-}" != "" || { echo "Source ESP-IDF 5.5.4 export.sh first" >&2; exit 1; }
hosted_dir="$target_dir/managed_components/espressif__esp_hosted"
test -f "$hosted_dir/slave/CMakeLists.txt" || { echo "Build the P4 once to resolve pinned components" >&2; exit 1; }
# Work on a build-local copy. Never alter downloaded component source files.
mkdir -p "$target_dir/build/c6-source"
cp -a "$hosted_dir/." "$target_dir/build/c6-source/"
if test -f "$target_dir/coprocessor.dependencies.lock"; then
    cp "$target_dir/coprocessor.dependencies.lock" "$target_dir/build/c6-source/slave/dependencies.lock"
fi
cd "$target_dir/build/c6-source/slave"
idf.py -B "$target_dir/build/c6" -D IDF_TARGET=esp32c6 \
    -D SDKCONFIG="$target_dir/build/c6.sdkconfig" \
    -D "SDKCONFIG_DEFAULTS=sdkconfig.defaults;sdkconfig.defaults.esp32c6;$target_dir/coprocessor.defaults" build
printf 'C6 image: %s\n' "$target_dir/build/c6/network_adapter.bin"
