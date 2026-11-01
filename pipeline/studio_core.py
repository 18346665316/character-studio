"""Studio owns code; workspaces own source assets; deliverables contain gated output."""
from task_lock import serialized, child_options, task_lock
import argparse
from contextlib import nullcontext
from datetime import datetime
import hashlib
import json
import math
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
    subprocess.run([str(a) for a in args], cwd=cwd, check=True, **child_options())


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


@serialized(lambda *args, **kwargs: BASE_DIR)
def controller(*args):
    command=[str(a) for a in [PYTHON, BASE_DIR / 'pipeline/mixamo_controller.py', *args]]
    process=subprocess.Popen(command, cwd=BASE_DIR, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True, bufsize=1,
                             **child_options())
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


@serialized(lambda *args, **kwargs: BASE_DIR)
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


@serialized(lambda *args, **kwargs: BASE_DIR)
@track_failures
def rig(character, model=None):
    progress_update(character, 'rig', '请在 Mixamo 浏览器中摆点并验收', status='waiting')
    controller('upload', model_path(character, model), '--character', character)
    require_ready(character)


@serialized(lambda *args, **kwargs: BASE_DIR)
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


def validate_sheet(path, frame_size=128, frame_count=None, allow_small=False):
    from PIL import Image
    import numpy as np
    from sheet_layout import layout,tiles
    with Image.open(path) as source:
        im=source.convert('RGBA')
    spec=layout(im,frame_size,frame_count)
    unique=set();colorful=False;small=[];boxes=[];adjacent_duplicates=0;last_hash=None
    first=None;last=None;areas=[];centers=[]
    for i,frame in enumerate(tiles(im,frame_size,spec['frame_count'])):
        box=frame.getchannel('A').getbbox()
        if box is None:raise ValueError(f'{path.name}: 第 {i+1} 帧存在透明空帧')
        if box[0]<=0 or box[1]<=0 or box[2]>=frame_size or box[3]>=frame_size:
            raise ValueError(f'{path.name}: 第 {i+1} 帧角色触及画布边缘，可能裁切')
        if box[3]-box[1]<frame_size*.35:small.append(i+1)
        key=hashlib.sha256(frame.tobytes()).digest();unique.add(key)
        adjacent_duplicates+=int(key==last_hash);last_hash=key
        pixels=np.asarray(frame);mask=pixels[:,:,3]>200;rgb=pixels[mask,:3].astype(float)
        if len(rgb) and float(np.mean(rgb.max(axis=1)-rgb.min(axis=1)))>=8:colorful=True
        areas.append(int(mask.sum()));centers.append(((box[0]+box[2])/2,(box[1]+box[3])/2))
        if first is None:first=mask.copy()
        last=mask.copy();boxes.append(box)
    if small and not allow_small:raise ValueError(f'{path.name}: 角色在画面中过小')
    if len(unique)<2:raise ValueError(f'{path.name}: 所有帧完全相同，拒绝作为动作交付')
    warnings=[]
    if not colorful:warnings.append({'code':'low_saturation','message':'画面色彩饱和度低，请复核是否符合原画；黑白或灰度画风可正常使用，贴图缺失由源模型检查判断'})
    if small:warnings.append({'code':'small_character','message':'部分帧人物占比偏小，请检查取景（蹲伏或跳跃也可能触发）','frames':small})
    ratio=adjacent_duplicates/max(1,spec['frame_count']-1)
    if ratio>.8:warnings.append({'code':'duplicate_frames','message':'超过 80% 相邻帧画面相同，请复核微小动作是否仍可见'})
    shifts=[float(np.linalg.norm(np.asarray(b)-np.asarray(a))) for a,b in zip(centers,centers[1:])]
    abrupt=[i+2 for i,shift in enumerate(shifts) if shift>frame_size*.25]
    if abrupt:warnings.append({'code':'abrupt_displacement','message':'相邻帧轮廓中心位移超过画布 25%，请复核快速动作或异常跳位','frames':abrupt})
    if max(areas)/max(1,min(areas))>3:warnings.append({'code':'coverage_change','message':'前景面积变化超过 3 倍，请复核姿态、装备切换或比例异常'})
    seam=float(np.count_nonzero(first^last)/max(1,np.count_nonzero(first|last)))
    return {**spec,'unique_frames':len(unique),'sha256':digest(path),
        'quality':{'status':'review' if warnings else 'passed','warnings':warnings,
        'metrics':{'adjacent_duplicate_ratio':ratio,'max_center_step_pixels':max(shifts,default=0),'foreground_area_ratio':max(areas)/max(1,min(areas))},
        'loop':{'status':'review' if seam>.15 else 'unchecked','silhouette_endpoint_difference':seam,'message':'首尾轮廓差异较大，仅在需要循环时复核' if seam>.15 else '端点接近不代表速度连续，循环适用性仍需确认'}}}


@serialized(lambda *args, **kwargs: BASE_DIR)
@track_failures
def prepare(character, render_preview=True):
    progress_update(character, 'prepare', '正在准备 UV 贴图、上传包与静态预览')
    from prepare_model import prepare_character
    prepared = prepare_character(BASE_DIR, character)
    if render_preview:
        from preview_model import preview
        print(f'请先目视检查静态预览: {preview(BASE_DIR, prepared)}')
    return prepared


def make_preview(sheet, destination, duration_seconds, frame_size=None, frame_count=None, frame_durations=None):
    from PIL import Image
    image = Image.open(sheet).convert('RGBA')
    from sheet_layout import layout,tiles
    frame_size = frame_size or image.height
    count = layout(image,frame_size,frame_count)["frame_count"]
    frames = []
    for tile in tiles(image,frame_size,count):
        background = Image.new('RGBA', (frame_size, frame_size), '#e9edf0')
        background.alpha_composite(tile)
        frames.append(background.convert('RGB').resize((384, 384), Image.Resampling.NEAREST))
    # GIF timing is quantized to centiseconds. Distribute rounding to retain total duration.
    durations = frame_durations if frame_durations is not None else [duration_seconds/count]*count
    if len(durations)!=count or any(not math.isfinite(v) or v<=0 for v in durations) or abs(sum(durations)-duration_seconds)>1e-6:
        raise ValueError('逐帧时长与动作总时长不一致')
    elapsed=0.;previous=0;delays=[]
    for seconds in durations:
        elapsed+=seconds*100;current=round(elapsed)
        delays.append(max(10,(current-previous)*10));previous=current
    frames[0].save(destination, save_all=True, append_images=frames[1:], duration=delays, loop=0)


def make_game_version(sheet, timing, quality, equipment_usage=None, profile="balanced"):
    """Create a reusable game representation from an already finished pixel sheet."""
    from compact_frames import compact,write_spriteframes
    staging=sheet.parent;stem=sheet.name.removesuffix('_spritesheet.png')
    game=staging/'game';game.mkdir(exist_ok=True)
    protected=[]
    for event in (equipment_usage or {}).get('clips',{}).get(stem,{}).get('events',[]):
        index=math.ceil(event['at']*timing['frame_count']-1e-8)
        protected.extend((max(0,index-1),min(timing['frame_count']-1,index)))
    result=compact(sheet,game/sheet.name,timing,protected,profile=profile)
    result['quality']=quality
    result['sha256']=digest(game/sheet.name)
    result.update(sheet='game/'+sheet.name,gif='game/'+stem+'_preview.gif',spriteframes='game/'+stem+'.tres')
    (game/(stem+'_render.json')).write_text(json.dumps(result,indent=2)+'\n')
    make_preview(game/sheet.name,staging/result['gif'],timing['duration_seconds'],timing['frame_width'],result['frame_count'],result['frame_durations_seconds'])
    write_spriteframes(staging/result['spriteframes'],sheet.name,result)
    return result


@serialized(lambda *args, **kwargs: BASE_DIR)
@track_failures
def bake(character, batch, view="three_quarter", frame_size=128, supersample=1, equipment_id=None, renderer="godot", equipment_usage_sha256=None, selected_files=None, body_height=None):
    if renderer not in ('godot','blender'):
        raise ValueError('未知渲染后端')
    if frame_size not in (64, 128) or supersample not in (1, 2, 4):
        raise ValueError('Unsupported frame size or supersampling factor')
    if body_height is not None:
        from sprite_projection import BODY_HEIGHTS
        if type(body_height) is not int or body_height not in BODY_HEIGHTS: raise ValueError('无效的人物像素高度')
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
    if selected_files is not None:
        if not isinstance(selected_files,list) or not selected_files or any(not isinstance(f,str) or f not in files for f in selected_files) or len(set(selected_files))!=len(selected_files):
            raise ValueError('所选动作不属于此来源')
        files={f:files[f] for f in selected_files}
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
    if body_height is not None:
        from sprite_projection import stage_reference
        reference_sha = stage_reference(BASE_DIR, character, data, project, digest)
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
    from motion_heading import stage as stage_heading
    stage_heading(BASE_DIR, character, project, files, 'res://animations', GODOT, job)
    projection = None
    if body_height is not None:
        progress_update(character, 'render', '正在以标准站姿测量人物像素密度与完整动作画布', job=str(job), batch=batch)
        with (job/'measure.log').open('w') as log:
            subprocess.run([GODOT,'--path',str(project),'--rendering-method','gl_compatibility',
                '--log-file',str(job/'measure-engine.log'),'--','--output',str(staging),
                '--view',view,'--frame-size','64','--measure-only'],stdout=log,stderr=subprocess.STDOUT,check=True,timeout=1200)
        from sprite_projection import plan
        projection = plan(json.loads((staging/'measurement.json').read_text()),body_height,supersample,reference_sha)
        (project/'projection.json').write_text(json.dumps(projection,indent=2))
        (staging/'projection.json').write_text(json.dumps(projection,indent=2))
        frame_size, render_size = projection['frame_size'], projection['render_size']
    if renderer == 'godot':
        progress_update(character, 'render', '正在测量动作范围并渲染图集', job=str(job), batch=batch)
        with (job / 'bake.log').open('w') as log:
            subprocess.run([GODOT, '--path', str(project), '--rendering-method', 'gl_compatibility',
                            '--log-file', str(job / 'render-engine.log'), '--', '--output', str(staging), '--view', view, '--frame-size', str(render_size)], stdout=log,
                           stderr=subprocess.STDOUT, check=True, timeout=1200)
    else:
        progress_update(character, 'render', 'Blender 正在测量姿态范围并渲染图集', job=str(job), batch=batch)
        from blender_backend import render
        render(BASE_DIR, project, staging, job, view, render_size, GODOT)
    progress_update(character, 'validate', '正在检查配色、空帧、裁切和时序，并生成预览', job=str(job), batch=batch)
    from pixel_finish import finish_batch
    sheet_paths=[];timings={};results=[];rejected=job/'rejected'
    def reject(name,reason):
        rejected.mkdir(exist_ok=True)
        for suffix in ('_spritesheet.png','_render.json','_preview.gif'):
            path=staging/(Path(name).stem+suffix)
            if path.exists():path.rename(rejected/path.name)
        for suffix in ('_spritesheet.png','_render.json','_preview.gif','.tres'):
            path=staging/'game'/(Path(name).stem+suffix)
            if path.exists():
                rejected.mkdir(exist_ok=True)
                path.rename(rejected/('game_'+path.name))
        results.append({'name':Path(name).stem,'status':'failed','reason':str(reason)})
    for name in files:
        sheet=staging/f'{Path(name).stem}_spritesheet.png'
        try:
            timing=json.loads((staging/f'{Path(name).stem}_render.json').read_text())
            count=timing['frame_count'];duration=timing['duration_seconds']
            if type(count) is not int or count<1 or not isinstance(duration,(int,float)) or not math.isfinite(duration) or duration<=0:
                raise ValueError('图集帧数和动作时长记录不一致')
            validate_sheet(sheet,render_size,count,allow_small=True)
            timings[sheet.name]={**timing,'frame_width':render_size}
            sheet_paths.append(sheet)
        except (ValueError,OSError,KeyError) as exc:reject(name,exc)
    if not sheet_paths:
        (job/'quality.json').write_text(json.dumps({'schema':1,'summary':{'passed':0,'review':0,'failed':len(results)},'results':results},ensure_ascii=False,indent=2))
        raise ValueError('全部动作质量检查失败：'+'；'.join(r['reason'] for r in results))
    if projection:
        from pixel_finish import finish_texture_batch
        pixel_settings=finish_texture_batch(sheet_paths,frame_size=frame_size,layouts=timings)
        pixel_settings.update(body_height_px=body_height,projection=projection)
    else:
        pixel_settings=finish_batch(sheet_paths,frame_size=frame_size,layouts=timings)
    pixel_settings.update(render_size=render_size,supersample=supersample)
    metadata={'renderer':renderer,'pixel_style':pixel_settings}
    for sheet in sheet_paths:
        name=sheet.stem.replace('_spritesheet','')+'.fbx'
        try:
            timing=timings[sheet.name].copy()
            info=validate_sheet(sheet,frame_size,timing['frame_count'],allow_small=True)
            if projection:
                timing.update(projection=projection, body_height_px=body_height, anchor_px=projection['anchor_px'])
            timing.update(frame_width=frame_size,frame_height=frame_size,render_width=render_size,columns=info['columns'],rows=info['rows'])
            (staging/f'{Path(name).stem}_render.json').write_text(json.dumps(timing,indent=2)+'\n')
            compact_info=make_game_version(sheet,timing,info['quality'],equipment_usage)
            metadata[sheet.name]={**info,**timing,'game':compact_info}
            make_preview(sheet,staging/f'{Path(name).stem}_preview.gif',timing['duration_seconds'],frame_size,timing['frame_count'])
            results.append({'name':Path(name).stem,**info['quality'],'duration_seconds':timing['duration_seconds'],'frame_count':timing['frame_count'],'fps':timing.get('fps',timing['frame_count']/timing['duration_seconds']),'source_fps':timing.get('source_fps'),'game_frame_count':compact_info['frame_count']})
        except (ValueError,OSError,KeyError) as exc:
            metadata.pop(sheet.name,None);reject(name,exc)
    counts={status:sum(r['status']==status for r in results) for status in ('passed','review','failed')}
    metadata['quality_report']={'schema':1,'summary':counts,'results':results,'scope':'Automated structural and raster checks; artistic review remains necessary.'}
    (job/'quality.json').write_text(json.dumps(metadata['quality_report'],ensure_ascii=False,indent=2))
    if counts['passed']+counts['review']==0 or data.get('kind')=='sequence' and counts['failed']:
        raise ValueError('动作质量检查失败：'+'；'.join(r['reason'] for r in results if r['status']=='failed'))
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
    metadata['review'] = 'Only clips passing hard checks are exported; inspect quality_report for review flags and rejected clips.'
    (staging / 'manifest.json').write_text(json.dumps(metadata, indent=2) + '\n')
    destination = BASE_DIR / 'deliverables' / character / job_id
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Publish valid clips together; rejected raster assets stay in the local job.
    staging.rename(destination)
    progress_update(character, 'complete', f'质检完成：通过 {counts["passed"]}，需复核 {counts["review"]}，失败 {counts["failed"]}；已保留可用动作', status='complete', output=str(destination), job=str(job), batch=batch)
    print(f'基础质量检查通过，交付目录: {destination}；美术效果仍需目视验收。')
    return destination


@serialized(lambda *args, **kwargs: BASE_DIR)
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


@serialized(lambda *args, **kwargs: BASE_DIR)
def build(character, image, names, view):
    generate(character, image)
    prepare(character)
    rig(character)
    return bake(character, download(character, names, new_batch()), view)


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
            p.add_argument('--body-height', type=int, choices=[48,64,96,128], default=None)
            p.add_argument('--supersample', type=int, choices=[1, 2, 4], default=1)
        if command == 'build':
            p.add_argument('--actions', default='Idle,Running')
    args = parser.parse_args()
    try:
        mutating = args.command in ('3d', 'prepare', 'rig', 'anim', 'bake', 'build', 'adopt', 'review', 'login')
        with task_lock(BASE_DIR) if mutating else nullcontext():
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
                    bake(args.character, args.batch, args.view, args.frame_size, args.supersample, args.equipment, args.renderer, body_height=args.body_height)
                elif args.command == 'build':
                    names = [v.strip() for v in args.actions.split(',') if v.strip()]
                    if not names or len({slug(v.lower().replace(' ', '_')) for v in names}) != len(names):
                        raise ValueError('动作列表为空或存在重名')
                    build(args.character, args.image, names, args.view)
                return 0
            except (ValueError, OSError, subprocess.SubprocessError) as exc:
                if hasattr(args, 'character'):
                    current = progress_read(args.character) or {}
                    progress_update(args.character, current.get('stage', 'validate'), str(exc), status='failed')
                raise
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        print(f'任务失败: {exc}。没有发布新的交付资产；请检查工作区和 .local/jobs 日志。', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
