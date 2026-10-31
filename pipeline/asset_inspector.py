"""Import one downloaded file in isolation and inspect its actual geometry/animation."""
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import uuid
import zipfile

BASE_DIR = Path(__file__).resolve().parent.parent


def inspect_download(path):
    job = BASE_DIR / '.local/jobs' / ('inspect-' + uuid.uuid4().hex[:12])
    project = job / 'godot'
    shutil.copytree(BASE_DIR / 'pipeline/godot', project, ignore=shutil.ignore_patterns('.godot'))
    source = Path(path)
    copied = project / ('asset' + source.suffix.lower())
    shutil.copy2(source, copied)
    result = job / 'inspection.json'
    godot = os.environ.get('GODOT_BIN', '/Applications/Godot.app/Contents/MacOS/Godot')
    with (job / 'inspect.log').open('w') as log:
        common = [godot, '--headless', '--path', str(project)]
        subprocess.run(common + ['--editor', '--import', '--log-file', str(job / 'import-engine.log')],
                       stdout=log, stderr=subprocess.STDOUT, timeout=180, check=True)
        subprocess.run(common + ['--script', 'res://inspect_asset.gd', '--log-file', str(job / 'inspect-engine.log'),
                                 '--', 'res://' + copied.name, str(result)],
                       stdout=log, stderr=subprocess.STDOUT, timeout=60, check=True)
    return json.loads(result.read_text())


def source_geometry(path):
    import trimesh
    source = Path(path)
    textured = 0
    if source.suffix.lower() == '.zip':
        with zipfile.ZipFile(source) as bundle:
            models = [n for n in bundle.namelist() if Path(n).suffix.lower() in ('.obj', '.glb')]
            if len(models) != 1:
                raise ValueError('上传包需要恰好包含一个 OBJ/GLB 模型')
            textured = int(any(n.lower().endswith('.mtl') for n in bundle.namelist()) and any(Path(n).suffix.lower() in ('.png', '.jpg', '.jpeg') for n in bundle.namelist()))
            mesh = trimesh.load(io.BytesIO(bundle.read(models[0])), file_type=Path(models[0]).suffix[1:], force='mesh')
    elif source.suffix.lower() in ('.obj', '.glb', '.gltf'):
        mesh = trimesh.load(source, force='mesh')
    else:
        return inspect_download(source)
    return {'triangles': len(mesh.faces), 'mesh_names': [], 'textured_surfaces': textured}
