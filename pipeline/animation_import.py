"""Shared, scale-independent source animation import policy for Studio projects.

Only staged projects are changed. Original FBX/GLB files and historical
published deliveries remain immutable. Lossy key reduction belongs after
rendering, where errors can be measured in target pixels.
"""
from pathlib import Path
import re
import shutil

POLICY_VERSION = 'source-keys-v1'
PLUGIN = 'res://addons/studio_animation_import/plugin.cfg'


def prepare(project):
    project = Path(project)
    target = project / 'addons/studio_animation_import'
    target.mkdir(parents=True, exist_ok=True)
    for name in ('plugin.cfg', 'plugin.gd', 'policy.gd'):
        shutil.copy2(Path(__file__).with_name('animation_import_plugin') / name, target / name)
    settings = project / 'project.godot'
    text = settings.read_text()
    section = re.search(r'^\[editor_plugins\]\s*\n(.*?)(?=^\[|\Z)', text, re.M | re.S)
    if section:
        body = section.group(1)
        enabled = re.search(r'^enabled\s*=\s*PackedStringArray\((.*?)\)\s*$', body, re.M)
        if enabled:
            if PLUGIN not in enabled.group(1):
                values = enabled.group(1).strip()
                body = body[:enabled.start()] + 'enabled=PackedStringArray(' + values + (', ' if values else '') + f'"{PLUGIN}")\n' + body[enabled.end():]
        else:
            body += f'enabled=PackedStringArray("{PLUGIN}")\n'
        text = text[:section.start(1)] + body + text[section.end(1):]
    else:
        text += f'\n[editor_plugins]\nenabled=PackedStringArray("{PLUGIN}")\n'
    settings.write_text(text)
    return {'version': POLICY_VERSION, 'optimizer': False, 'compression': False}
