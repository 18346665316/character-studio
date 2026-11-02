#!/bin/zsh
set -euo pipefail
isometric_dir="$(cd "$(dirname "$0")" && pwd)"
studio_root="$(cd "$isometric_dir/../.." && pwd)"
godot_bin="/Applications/Godot.app/Contents/MacOS/Godot"
if [[ ! -f "$isometric_dir/assets/sources.json" ]]; then
  cd "$studio_root"
  "$studio_root/.local/python/bin/python3" pipeline/build_isometric_demo.py
fi
if [[ ! -d "$isometric_dir/.godot/imported" ]]; then
  "$godot_bin" --headless --editor --path "$isometric_dir" --import
fi
exec "$godot_bin" --path "$isometric_dir"
