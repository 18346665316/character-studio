#!/usr/bin/env bash
set -euo pipefail
BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec "$BASE_DIR/.local/python/bin/python3" "$BASE_DIR/pipeline/mixamo_controller.py" "$@"
