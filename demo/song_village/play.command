#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
exec /Applications/Godot.app/Contents/MacOS/Godot --path .
