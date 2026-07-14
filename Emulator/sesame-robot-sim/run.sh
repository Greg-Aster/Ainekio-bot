#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT="${PORT:-8765}"

echo "Serving Sesame Robot Simulator at http://127.0.0.1:${PORT}/"
echo "Press Ctrl+C to stop."

cd "${SCRIPT_DIR}/app"
python3 -m http.server "${PORT}" --bind 127.0.0.1
