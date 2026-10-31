"""Render a reusable eight-view static review before cloud upload."""
import os
from pathlib import Path
import shutil
import subprocess
import uuid
from PIL import Image


def preview(base, model):
    base, model = Path(base), Path(model)
    job = base / '.local/jobs' / ('preview-' + uuid.uuid4().hex[:12])
    project = job / 'godot'
    project.mkdir(parents=True)
    shutil.copy2(base / 'pipeline/godot/static_preview.gd', project / 'static_preview.gd')
    shutil.copy2(model / 'preview.glb', project / 'model.glb')
    (project / 'project.godot').write_text('''config_version=5
[application]
config/name="Studio Static Review"
run/main_scene="res://preview.tscn"
[display]
window/size/viewport_width=512
window/size/viewport_height=512
[rendering]
renderer/rendering_method="gl_compatibility"
''')
    (project / 'preview.tscn').write_text('''[gd_scene load_steps=2 format=3]
[ext_resource type="Script" path="res://static_preview.gd" id="1"]
[node name="Preview" type="Node3D"]
script = ExtResource("1")
''')
    target = model / 'previews'
    target.mkdir(exist_ok=True)
    godot = os.environ.get('GODOT_BIN', '/Applications/Godot.app/Contents/MacOS/Godot')
    with (job / 'preview.log').open('w') as log:
        subprocess.run([godot, '--headless', '--editor', '--import', '--path', str(project),
                        '--log-file', str(job / 'import-engine.log')], stdout=log, stderr=subprocess.STDOUT, check=True, timeout=180)
        subprocess.run([godot, '--path', str(project), '--log-file', str(job / 'render-engine.log'),
                        '--', str(target)], stdout=log, stderr=subprocess.STDOUT, check=True, timeout=120)
    sheet = Image.new('RGB', (1024, 512), '#e9edf0')
    for i in range(8):
        image = Image.open(target / f'view_{i:02d}.png').convert('RGB').resize((256, 256), Image.Resampling.LANCZOS)
        sheet.paste(image, ((i % 4) * 256, (i // 4) * 256))
    sheet.save(target / 'contact_sheet.png')
    return target / 'contact_sheet.png'
