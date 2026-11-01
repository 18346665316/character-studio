"""Source-hash keyed heading calibration shared by previews and both renderers."""
from task_lock import serialized
import json
import math
import shutil
import subprocess
from pathlib import Path


def effective(record):
    """Unconfirmed estimates are advisory, including records from the old policy."""
    value = dict(record)
    if value.get('status') != 'confirmed':
        value.setdefault('estimated_degrees', value.get('degrees', 0.0))
        value['degrees'] = 0.0
        value['status'] = 'suggested' if value.get('status') in ('automatic', 'suggested') else 'uncertain'
        value['reason'] = '仅供参考；默认保留原动作朝向' if value['status'] == 'suggested' else '无法可靠估计；保留原动作朝向'
    return value


def records(root, character, files):
    directory = root/'workspaces'/character/'motion_heading'
    result = {}
    for filename, sha in files.items():
        path = directory/(sha+'.json')
        if path.is_file():
            data = json.loads(path.read_text())
            if data.get('source_sha256') == sha:
                result[filename] = effective(data)
    return result


@serialized(lambda root, *args, **kwargs: root)
def save(root, character, sha, record):
    from asset_repository import atomic
    directory = root/'workspaces'/character/'motion_heading'
    directory.mkdir(parents=True, exist_ok=True)
    value = {**record, 'source_sha256':sha, 'schema':1}
    degrees = value.get('degrees')
    if type(degrees) not in (int, float) or not math.isfinite(degrees) or not -180 <= degrees <= 180:
        raise ValueError('朝向补偿必须在 -180° 到 180° 之间')
    value = effective(value)
    atomic(directory/(sha+'.json'), value)
    return value


def stage(root, character, project, files, directory, godot, job):
    shutil.copy2(root/'pipeline/heading/runtime.gd', project/'heading_runtime.gd')
    shutil.copy2(root/'pipeline/heading/estimate.gd', project/'heading_estimate.gd')
    current = records(root, character, files)
    missing = {f:sha for f,sha in files.items() if f not in current}
    if missing:
        (project/'heading_request.json').write_text(json.dumps({'files':missing,'directory':directory}))
        with (job/'heading.log').open('w') as log:
            subprocess.run([godot,'--headless','--path',str(project),'--script','res://heading_estimate.gd',
                            '--log-file',str(job/'heading-engine.log')],stdout=log,stderr=subprocess.STDOUT,check=True,timeout=180)
        estimates = json.loads((project/'heading_estimates.json').read_text())
        for filename, sha in missing.items():
            # Do not overwrite a calibration confirmed while the estimator was running.
            if filename not in records(root, character, {filename:sha}):
                save(root, character, sha, estimates[filename])
        current = records(root, character, files)
    (project/'heading.json').write_text(json.dumps(current,ensure_ascii=False,indent=2))
    return current
