#!/bin/zsh
set -euo pipefail
building_demo_dir="$(cd "$(dirname "$0")" && pwd)"
building_studio_root="$(cd "$building_demo_dir/../.." && pwd)"
building_godot_bin="/Applications/Godot.app/Contents/MacOS/Godot"
if [[ ! -f "$building_demo_dir/assets/building.json" ]]; then
  cd "$building_studio_root"
  "$building_studio_root/.local/python/bin/python3" pipeline/build_building_demo.py
fi
"$building_godot_bin" --headless --editor --path "$building_demo_dir" --import
exec "$building_godot_bin" --path "$building_demo_dir" res://building.tscn
