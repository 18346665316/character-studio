"""Stage verified character assets in a neutral animation inspection viewer."""
import json
from pathlib import Path
import shutil
import subprocess

from asset_inspector import inspect_download
from mixamo_state import check_mesh_identity, check_motion
from progress import update, track_failures


def verified_batch(root, character, batch, digest):
    source = root / 'workspaces' / character / 'animations' / batch
    receipt_path = source / 'batch.json'
    if not receipt_path.is_file():
        raise ValueError('人物预览需要指定完整且含 batch.json 的动作批次')
    receipt = json.loads(receipt_path.read_text())
    if receipt.get('character') != character or receipt.get('batch') != batch:
        raise ValueError('角色或批次与来源记录不一致')
    files = receipt.get('files', {})
    if not isinstance(files, dict) or not files:
        raise ValueError('动作批次为空')
    selected, inspection, reference = {}, {}, None
    for name, sha in files.items():
        if Path(name).name != name or Path(name).suffix.lower() != '.fbx':
            raise ValueError(f'人物预览仅接受本批次内的 FBX 文件名: {name}')
        path = source / name
        if not path.is_file() or path.is_symlink() or path.resolve().parent != source.resolve():
            raise ValueError(f'动作文件缺失或指向批次外: {name}')
        if digest(path) != sha:
            raise ValueError(f'动作源文件已变更: {name}')
        info = inspect_download(path)
        check_motion(info)
        if info.get('textured_surfaces', 0) < 1 or info.get('skinned_meshes', 0) < 1:
            raise ValueError(f'{name}: 缺少贴图或蒙皮')
        if not info.get('bone_names'):
            raise ValueError(f'{name}: 缺少骨骼检查结果')
        if reference is not None:
            check_mesh_identity(info, reference)
            if info['bone_names'] != reference['bone_names']:
                raise ValueError(f'{name}: 骨骼结构与该角色其他动作不一致')
        reference = info if reference is None else reference
        selected[name], inspection[name] = path, info
    return receipt, selected, inspection


@track_failures
def review(character, batch, capture_only=False, equipment_editor=None):
    import studio_core as studio
    character, batch = studio.slug(character), studio.slug(batch)
    root = studio.BASE_DIR
    update(character, 'validate', '正在检查指定人物动作的来源、贴图、蒙皮和骨骼', batch=batch)
    receipt, files, inspection = verified_batch(root, character, batch, studio.digest)
    review_id = studio.new_batch()
    output = root / 'workspaces' / character / 'reviews' / review_id
    project = output / 'viewer'
    job = root / '.local/jobs' / ('character-review-' + review_id)
    job.mkdir(parents=True)
    shutil.copytree(root / 'pipeline/character_preview', project,
                    ignore=shutil.ignore_patterns('.godot', '*.uid'))
    assets = project / 'assets'
    assets.mkdir()
    for name, path in files.items():
        shutil.copy2(path, assets / name)
        if studio.digest(assets / name) != receipt['files'][name]:
            raise ValueError('复制期间人物动作源发生变化')
    spec = {'character': character, 'batch': batch, 'files': receipt['files'], 'inspection': inspection}
    # Character-specific visual decisions live in the workspace, not the template.
    settings = root / 'workspaces' / character / 'review_settings.json'
    if settings.is_file():
        config = json.loads(settings.read_text())
        if config.get('files') == receipt['files']:
            spec['reviewed_accessory_faces'] = config.get('reviewed_accessory_faces', [])
    if equipment_editor:
        from equipment import copy_runtime, stage_model
        copy_runtime(root, project)
        if equipment_editor.get('model'):
            stage_model(equipment_editor['draft'],equipment_editor['model'],project)
        shutil.copy2(root / 'pipeline/equipment/editor.gd', project / 'equipment_editor.gd')
        shutil.copy2(root / 'pipeline/equipment/handles.gd', project / 'equipment_handles.gd')
        spec.update(equipment_draft=equipment_editor['draft'], equipment_output=equipment_editor['output'],
                    equipment_screenshot=equipment_editor['screenshot'])
    (project / 'review.json').write_text(json.dumps(spec, ensure_ascii=False, indent=2) + '\n')
    update(character, 'import', '正在导入人物专用检查台', output=str(output), job=str(job), batch=batch)
    with (job / 'import.log').open('w') as log:
        subprocess.run([studio.GODOT, '--headless', '--editor', '--path', str(project), '--import',
                        '--log-file', str(job / 'import-engine.log')],
                       stdout=log, stderr=subprocess.STDOUT, check=True, timeout=180)
    update(character, 'review', '正在检查人物动作与多角度外观', output=str(output), job=str(job), batch=batch)
    args = [studio.GODOT, '--path', str(project), '--log-file', str(job / 'review-engine.log')]
    if capture_only:
        args += ['--', '--capture']
    with (job / 'review.log').open('w') as log:
        subprocess.run(args, stdout=log, stderr=subprocess.STDOUT, check=True,
                       timeout=180 if capture_only else None)
    report = project / 'character-report.json'
    if capture_only:
        if not report.is_file() or not (project / 'captures/front.png').is_file():
            raise ValueError('人物预览没有生成完整的检查记录或画面')
        shutil.copy2(report, output / 'character-report.json')
    update(character, 'review', '人物检查台已生成，等待形体与变形验收', status='waiting',
           output=str(output), job=str(job), batch=batch)
    print(f'人物检查: {project / "project.godot"}', flush=True)
    return output
