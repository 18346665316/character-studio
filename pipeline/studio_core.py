"""Studio owns code; workspaces own source assets; deliverables contain gated output."""
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid
import zipfile

from mixamo_state import require_ready, read_state
from asset_inspector import inspect_download
from progress import update as progress_update, read as progress_read, track_failures

BASE_DIR = Path(__file__).resolve().parent.parent
PYTHON = BASE_DIR / '.local/python/bin/python3'
SESSION = BASE_DIR / '.local/auth/mixamo_session.json'
GODOT = os.environ.get('GODOT_BIN', '/Applications/Godot.app/Contents/MacOS/Godot')


def slug(value):
    if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]*', value):
        raise argparse.ArgumentTypeError('名称只能包含字母、数字、下划线和短横线')
    return value


def new_batch():
    return datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8]


def run(args, cwd=BASE_DIR):
    subprocess.run([str(a) for a in args], cwd=cwd, check=True, env={**os.environ, 'PYTHONUNBUFFERED': '1'})


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def workspace(character):
    return BASE_DIR / 'workspaces' / slug(character)


def model_path(character, override=None):
    if override:
        path = Path(override).resolve()
    else:
        # Never fall back to a vertex-only upload that loses its colors in Mixamo.
        candidates = sorted((workspace(character) / 'models/prepared').glob('*/mixamo.zip'),
                            key=lambda p: p.stat().st_mtime)
        if not candidates:
            raise ValueError(f'角色缺少带贴图上传包；先运行 ./studio prepare --character {character}')
        path = candidates[-1]
    if not path.is_file():
        raise ValueError(f'找不到角色模型: {path}')
    return path


def controller(*args):
    command=[str(a) for a in [PYTHON, BASE_DIR / 'pipeline/mixamo_controller.py', *args]]
    process=subprocess.Popen(command, cwd=BASE_DIR, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True, bufsize=1,
                             env={**os.environ, 'PYTHONUNBUFFERED':'1'})
    reason=None
    try:
        for line in process.stdout:
            print(line, end='', flush=True)
            if line.startswith('Mixamo 任务失败:'):
                reason=line.split(':',1)[1].strip()
        code=process.wait()
    except BaseException:
        process.terminate()
        process.wait()
        raise
    finally:
        process.stdout.close()
    if code:
        if reason:
            if ('网格面数与角色不符' in reason or '默认人偶' in reason) and '自动恢复' not in reason:
                reason+='。Mixamo 云端人物可能已改变；请在“人工绑定”恢复并确认本角色，再新建动作下载任务。无需重新建模。'
            raise ValueError(reason)
        raise subprocess.CalledProcessError(code,command)


@track_failures
def generate(character, image):
    progress_update(character, 'reconstruction', '正在生成新的 3D 模型')
    source = Path(image).resolve()
    if not source.is_file():
        raise ValueError(f'找不到原画: {source}')
    ws = workspace(character)
    # Preserve every input and reconstruction; never silently overwrite earlier work.
    batch = new_batch()
    input_dir = ws / 'inputs' / batch
    input_dir.mkdir(parents=True)
    copied = input_dir / source.name
    shutil.copy2(source, copied)
    output = ws / 'intermediates' / batch
    run([PYTHON, BASE_DIR / 'vendor/TripoSR/run.py', copied,
         '--output-dir', output, '--model-save-format', 'obj'])
    mesh = output / '0/mesh.obj'
    if not mesh.is_file():
        raise ValueError('3D 生成没有产出 mesh.obj')
    models = ws / 'models'
    models.mkdir(exist_ok=True)
    # Keep old canonical models before replacement.
    for suffix in ['obj', 'zip']:
        previous = models / f'{character}.{suffix}'
        if previous.exists():
            history = models / 'history' / batch
            history.mkdir(parents=True, exist_ok=True)
            shutil.move(str(previous), history / previous.name)
    obj = models / f'{character}.obj'
    shutil.copy2(mesh, obj)
    with zipfile.ZipFile(models / f'{character}.zip', 'w', zipfile.ZIP_DEFLATED) as bundle:
        bundle.write(obj, obj.name)
    print(f'模型已写入 {models}')


@track_failures
def rig(character, model=None):
    progress_update(character, 'rig', '请在 Mixamo 浏览器中摆点并验收', status='waiting')
    controller('upload', model_path(character, model), '--character', character)
    require_ready(character)


@track_failures
def download(character, names, batch):
    binding = require_ready(character,allow_cloud_recovery=True)
    progress_update(character, 'download', '开始动作下载与角色检查', batch=batch)
    target = workspace(character) / 'animations' / slug(batch)
    if target.exists():
        raise ValueError(f'动作批次已存在，拒绝覆盖: {target}')
    target.mkdir(parents=True)
    paths = []
    used = set()
    for name in names:
        action = slug(name.lower().replace(' ', '_'))
        if action in used:
            raise ValueError(f'重复动作名: {name}')
        used.add(action)
        path = target / f'{action}.fbx'
        progress_update(character, 'download', f'正在下载并验证 {name}', action=name, batch=batch)
        controller('download', name, path, '--character', character)
        progress_update(character, 'download', f'{name} 已下载并通过检查', action=name, batch=batch)
        if not path.is_file() or path.stat().st_size == 0:
            raise ValueError(f'动作未成功下载: {name}')
        paths.append(path)
    # Created only after every requested action has downloaded successfully.
    (target / 'batch.json').write_text(json.dumps({
        'character': character, 'batch': batch,
        'rig_sha256': binding['bound_sha256'],
        'files': {p.name: digest(p) for p in paths}
    }, indent=2) + '\n')
    return batch


def validate_sheet(path, frame_size=128):
    from PIL import Image
    import numpy as np
    with Image.open(path) as source:
        im = source.convert('RGBA')
    if im.height != frame_size or im.width % frame_size or not 8 <= im.width // frame_size <= 120:
        raise ValueError(f'{path.name}: 图集尺寸不符合 8–120 个 {frame_size}×{frame_size} 帧规范')
    frames = [im.crop((x, 0, x + frame_size, frame_size)) for x in range(0, im.width, frame_size)]
    for frame in frames:
        box = frame.getchannel('A').getbbox()
        if box is None:
            raise ValueError(f'{path.name}: 存在透明空帧')
        if box[0] <= 0 or box[1] <= 0 or box[2] >= frame_size or box[3] >= frame_size:
            raise ValueError(f'{path.name}: 角色触及画布边缘，可能裁切')
        if box[3] - box[1] < frame_size * 0.35:
            raise ValueError(f'{path.name}: 角色在画面中过小')
    unique = len({f.tobytes() for f in frames})
    if unique < 2:
        raise ValueError(f'{path.name}: 所有帧完全相同，拒绝作为动作交付')
    pixels = np.array(im)
    rgb = pixels[pixels[:, :, 3] > 200, :3].astype(float)
    if len(rgb) == 0 or float(np.mean(rgb.max(axis=1) - rgb.min(axis=1))) < 8:
        raise ValueError(f'{path.name}: 角色缺少可辨配色，疑似白模或灰模')
    return {'frame_width': frame_size, 'frame_height': frame_size,
            'frame_count': len(frames), 'unique_frames': unique, 'sha256': digest(path)}


@track_failures
def prepare(character, render_preview=True):
    progress_update(character, 'prepare', '正在准备 UV 贴图、上传包与静态预览')
    from prepare_model import prepare_character
    prepared = prepare_character(BASE_DIR, character)
    if render_preview:
        from preview_model import preview
        print(f'请先目视检查静态预览: {preview(BASE_DIR, prepared)}')
    return prepared


def make_preview(sheet, destination, duration_seconds):
    from PIL import Image
    image = Image.open(sheet).convert('RGBA')
    frame_size = image.height
    count = image.width // frame_size
    frames = []
    for i in range(count):
        background = Image.new('RGBA', (frame_size, frame_size), '#e9edf0')
        background.alpha_composite(image.crop((i * frame_size, 0, (i + 1) * frame_size, frame_size)))
        frames.append(background.convert('RGB').resize((384, 384), Image.Resampling.NEAREST))
    # GIF timing is quantized to centiseconds. Distribute rounding to retain total duration.
    ticks = duration_seconds * 100.0 / count
    delays = [max(10, (round((i + 1) * ticks) - round(i * ticks)) * 10) for i in range(count)]
    frames[0].save(destination, save_all=True, append_images=frames[1:], duration=delays, loop=0)


@track_failures
def bake(character, batch, view="three_quarter", frame_size=128, supersample=1, equipment_id=None, renderer="godot", equipment_usage_sha256=None):
    if renderer not in ('godot','blender'):
        raise ValueError('未知渲染后端')
    if frame_size not in (64, 128) or supersample not in (1, 2, 4):
        raise ValueError('Unsupported frame size or supersampling factor')
    render_size = frame_size * supersample
    progress_update(character, 'validate', '正在检查源动作的贴图和动态轨道', batch=batch)
    source = workspace(character) / 'animations' / slug(batch)
    receipt = source / 'batch.json'
    if not receipt.is_file():
        raise ValueError(f'批次缺少来源记录: {receipt}。历史动作需人工确认角色归属后，使用 adopt 登记。')
    data = json.loads(receipt.read_text())
    if data.get('character') != character or data.get('batch') != batch:
        raise ValueError('批次角色/名称不匹配')
    files = data.get('files', {})
    if not files:
        raise ValueError('批次没有动作文件')
    for name, sha in files.items():
        if Path(name).name != name or Path(name).suffix.lower() not in ('.fbx', '.glb'):
            raise ValueError(f'非法批次文件名: {name}')
        if digest(source / name) != sha:
            raise ValueError(f'动作文件已变更，需要重新登记: {name}')
    if view not in ('front', 'side', 'three_quarter'):
        raise ValueError('未知视角')
    # Legacy receipts cannot bypass texture/skin/motion inspection.
    from mixamo_state import check_motion
    for name in files:
        info = inspect_download(source / name)
        check_motion(info)
        if info.get('textured_surfaces', 0) < 1:
            raise ValueError(f'{name}: 缺失贴图，禁止发布白模动画；请重新绑定带贴图上传包')
    equipment_usage = None
    equipment_config = None
    if equipment_id:
        from equipment import load as load_equipment
        equipment_config = load_equipment(BASE_DIR, character, batch, equipment_id)
        from equipment_usage import load as load_usage, fingerprint, recipe
        settings=load_usage(BASE_DIR,character,equipment_id)
        if equipment_usage_sha256 and fingerprint(settings)!=equipment_usage_sha256:
            raise ValueError('武器持用设置已变化，请创建新的导出任务')
        equipment_usage=recipe(settings,files)
    job_id = new_batch()
    job = BASE_DIR / '.local/jobs' / job_id
    project = job / 'godot'
    shutil.copytree(BASE_DIR / 'pipeline/godot', project, ignore=shutil.ignore_patterns('.godot'))
    if equipment_config:
        from equipment import copy_runtime, stage_model
        copy_runtime(BASE_DIR, project)
        stage_model(equipment_config,BASE_DIR/'workspaces'/character/'equipment'/equipment_id/'weapon.glb',project)
        (project / 'equipment.json').write_text(json.dumps(equipment_config, indent=2))
        (project / 'equipment_usage.json').write_text(json.dumps(equipment_usage,indent=2))
    inputs = project / 'animations'
    inputs.mkdir()
    for name in files:
        shutil.copy2(source / name, inputs / name)
    staging = job / 'staging'
    staging.mkdir()
    (job / 'job.json').write_text(json.dumps({
        'character': character, 'batch': batch, 'source_files': files,
        'renderer': renderer, 'quality_gate': 'textured-moving-visible-v2'
    }, indent=2) + '\n')
    print(f'仅烘焙角色 {character} / 批次 {batch}；日志与暂存: {job}', flush=True)
    # Headless is suitable for importing, but dummy rendering cannot capture sprites.
    progress_update(character, 'import', '正在准备 Blender 的动画与装备' if renderer == 'blender' else '正在将指定动作批次导入 Godot', job=str(job), batch=batch)
    with (job / 'import.log').open('w') as log:
        subprocess.run([GODOT, '--headless', '--editor', '--path', str(project), '--import',
                        '--log-file', str(job / 'import-engine.log')],
                       stdout=log, stderr=subprocess.STDOUT, check=True, timeout=180)
    if renderer == 'godot':
        progress_update(character, 'render', '正在测量动作范围并渲染图集', job=str(job), batch=batch)
        with (job / 'bake.log').open('w') as log:
            subprocess.run([GODOT, '--path', str(project), '--rendering-method', 'gl_compatibility',
                            '--log-file', str(job / 'render-engine.log'), '--', '--output', str(staging), '--view', view, '--frame-size', str(render_size)], stdout=log,
                           stderr=subprocess.STDOUT, check=True, timeout=180)
    else:
        progress_update(character, 'render', 'Blender 正在测量姿态范围并渲染图集', job=str(job), batch=batch)
        from blender_backend import render
        render(BASE_DIR, project, staging, job, view, render_size, GODOT)
    progress_update(character, 'validate', '正在检查配色、空帧、裁切和时序，并生成预览', job=str(job), batch=batch)
    from pixel_finish import finish_batch
    sheet_paths = [staging / f'{Path(name).stem}_spritesheet.png' for name in files]
    # Inspect raw colors before quantization so a palette cannot conceal a lost material.
    for sheet in sheet_paths:
        validate_sheet(sheet, render_size)
    pixel_settings = finish_batch(sheet_paths, frame_size=frame_size)
    pixel_settings.update(render_size=render_size, supersample=supersample)
    metadata = {'renderer': renderer, 'pixel_style': pixel_settings}
    for name in files:
        sheet = staging / f'{Path(name).stem}_spritesheet.png'
        metadata[sheet.name] = validate_sheet(sheet, frame_size)
        timing_path = staging / f'{Path(name).stem}_render.json'
        timing = json.loads(timing_path.read_text())
        if timing['frame_count'] != metadata[sheet.name]['frame_count'] or timing['duration_seconds'] <= 0:
            raise ValueError('图集帧数和动作时长记录不一致')
        timing.update(frame_width=frame_size, frame_height=frame_size, render_width=render_size)
        timing_path.write_text(json.dumps(timing, indent=2) + '\n')
        metadata[sheet.name].update(timing)
        make_preview(sheet, staging / f'{Path(name).stem}_preview.gif', timing['duration_seconds'])
    if data.get('kind')=='sequence':
        cameras=[metadata[f'{Path(name).stem}_spritesheet.png'].get('camera') for name in files]
        if not cameras or not cameras[0] or any(camera!=cameras[0] for camera in cameras):
            raise ValueError('编排动作相机参数不一致，拒绝发布统一预览')
    metadata['source'] = {'character': character, 'batch': batch, 'job': job_id, 'files': files}
    if data.get('kind')=='sequence': metadata['source']['kind']='sequence'
    if equipment_config:
        metadata['equipment'] = {'id': equipment_id, 'config': equipment_config, 'usage':equipment_usage}
        (staging / 'equipment_usage.json').write_text(json.dumps(equipment_usage,indent=2))
        (staging / 'equipment.json').write_text(json.dumps(equipment_config, ensure_ascii=False, indent=2))
    metadata['review'] = 'Automated checks passed; artistic quality and gameplay fit require visual review.'
    (staging / 'manifest.json').write_text(json.dumps(metadata, indent=2) + '\n')
    destination = BASE_DIR / 'deliverables' / character / job_id
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Promotion is all-or-nothing; failed jobs remain under .local/jobs.
    staging.rename(destination)
    progress_update(character, 'complete', '图集与预览已生成；等待目视美术验收', status='complete', output=str(destination), job=str(job), batch=batch)
    print(f'基础质量检查通过，交付目录: {destination}；美术效果仍需目视验收。')
    return destination


def adopt(character, batch):
    """Explicit human declaration for legacy files; never silently infer their owner."""
    source = workspace(character) / 'animations' / slug(batch)
    if (source / 'batch.json').exists():
        raise ValueError('批次已有来源记录，拒绝覆盖')
    files = sorted(p for p in source.glob('*') if p.suffix.lower() in ('.fbx', '.glb'))
    if not files:
        raise ValueError(f'没有动作文件: {source}')
    (source / 'batch.json').write_text(json.dumps({
        'character': character, 'batch': batch,
        'provenance': 'User explicitly confirmed ownership with studio adopt',
        'files': {p.name: digest(p) for p in files}
    }, indent=2) + '\n')
    print(f'已登记 {len(files)} 个历史动作；烘焙时仍须通过质量检查。')


def status():
    print('Pixel Animation Studio')
    print(f'Python: {PYTHON} ({"就绪" if PYTHON.exists() else "缺失"})')
    print(f'Godot: {GODOT} ({"就绪" if Path(GODOT).exists() else "缺失"})')
    print(f'Mixamo 本地会话: {"已保存（有效性需联网验证）" if SESSION.exists() else "未保存"}')
    for name in ['workspaces', 'deliverables']:
        root = BASE_DIR / name
        entries = sorted(p.name for p in root.iterdir() if p.is_dir()) if root.exists() else []
        print(f'{name}/: {", ".join(entries) or "空"}')
        if name == 'workspaces':
            for character in entries:
                print(f'  {character}: Mixamo {read_state(character).get("status", "unbound")}')
                task = progress_read(character)
                if task:
                    print(f'    任务: {task["stage_label"]} / {task["status"]} · {task["message"]}')


def main():
    parser = argparse.ArgumentParser(description='Pixel Studio：按角色和批次生产，检查后交付')
    subs = parser.add_subparsers(dest='command')
    subs.add_parser('status', help='查看环境、目录边界及任务阶段')
    subs.add_parser('panel', help='启动可操作的人物 Web 工作台')
    subs.add_parser('monitor', help='打开本地任务进度服务，显示刷新地址')
    subs.add_parser('login', help='保存 Mixamo 本机会话')
    subs.add_parser('web', help='打开第三方 TripoSR 预览台（输出不自动交付）')
    review_parser = subs.add_parser('review', help='检查人物多角度外观、骨骼和正式动作')
    review_parser.add_argument('--character', required=True, type=slug)
    review_parser.add_argument('--batch', required=True, type=slug)
    review_parser.add_argument('--capture-only', action='store_true', help='生成动作采样与多角度截图后退出')
    for command in ['3d', 'prepare', 'rig', 'anim', 'bake', 'build', 'adopt']:
        p = subs.add_parser(command)
        p.add_argument('--character', required=True, type=slug)
        if command in ['3d', 'build']:
            p.add_argument('image', help='输入原画路径')
        if command in ['rig', 'anim']:
            p.add_argument('--model', help='指定该角色的模型，否则使用工作区中的角色 ZIP')
        if command == 'anim':
            p.add_argument('name', help='Mixamo 动作名称')
        if command in ['bake', 'adopt']:
            p.add_argument('--batch', required=True, type=slug)
        if command == 'adopt':
            p.add_argument('--confirm-owner', required=True, action='store_true',
                           help='确认批次内动作确实属于指定角色')
        if command in ['build', 'bake']:
            p.add_argument('--view', choices=['front', 'side', 'three_quarter'], default='three_quarter')
        if command == 'bake':
            p.add_argument('--renderer', choices=['godot','blender'], default='godot')
            p.add_argument('--equipment', help='已确认的装备配置编号')
            p.add_argument('--frame-size', type=int, choices=[64, 128], default=128)
            p.add_argument('--supersample', type=int, choices=[1, 2, 4], default=1)
        if command == 'build':
            p.add_argument('--actions', default='Idle,Running')
    args = parser.parse_args()
    try:
        if args.command is None:
            parser.print_help()
        elif args.command == 'panel':
            from panel import serve
            serve()
        elif args.command == 'monitor':
            from monitor import serve
            serve()
        elif args.command == 'status':
            status()
        elif args.command == 'login':
            controller('login')
        elif args.command == 'web':
            print('第三方预览台：临时输出不进入 deliverables；正式生产请使用 studio 3d/build。')
            run([PYTHON, BASE_DIR / 'vendor/TripoSR/gradio_app.py'], cwd=BASE_DIR / 'vendor/TripoSR')
        elif args.command == '3d':
            generate(args.character, args.image)
        elif args.command == 'prepare':
            prepare(args.character)
        elif args.command == 'rig':
            rig(args.character, args.model)
        elif args.command == 'anim':
            require_ready(args.character, model_path(args.character, args.model))
            batch = download(args.character, [args.name], new_batch())
            print(f'动作批次: {batch}')
        elif args.command == 'adopt':
            adopt(args.character, args.batch)
        elif args.command == 'review':
            from review_character import review
            review(args.character, args.batch, args.capture_only)
        elif args.command == 'bake':
            bake(args.character, args.batch, args.view, args.frame_size, args.supersample, args.equipment, args.renderer)
        elif args.command == 'build':
            names = [v.strip() for v in args.actions.split(',') if v.strip()]
            if not names or len({slug(v.lower().replace(' ', '_')) for v in names}) != len(names):
                raise ValueError('动作列表为空或存在重名')
            generate(args.character, args.image)
            prepare(args.character)
            rig(args.character)
            bake(args.character, download(args.character, names, new_batch()), args.view)
        return 0
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        if hasattr(args, 'character'):
            current = progress_read(args.character) or {}
            progress_update(args.character, current.get('stage', 'validate'), str(exc), status='failed')
        print(f'任务失败: {exc}。没有发布新的交付资产；请检查工作区和 .local/jobs 日志。', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
