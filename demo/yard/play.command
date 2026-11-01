#!/bin/zsh
set -e
demo_directory="${0:A:h}"
repository_root="${demo_directory:h:h}"
if [[ ! -f "$demo_directory/assets/character_assets/hunyuan-guard/character.tscn" ]]; then
  "$repository_root/.local/python/bin/python3" "$repository_root/pipeline/build_yard_demo.py"
fi
if [[ ! -d "$demo_directory/.godot/imported" ]]; then
  /Applications/Godot.app/Contents/MacOS/Godot --headless --editor --path "$demo_directory" --import
fi
exec /Applications/Godot.app/Contents/MacOS/Godot --path "$demo_directory"
