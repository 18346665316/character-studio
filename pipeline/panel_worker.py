"""One durable panel task; launched without a shell by the local panel server."""
import json
import os
from pathlib import Path
import sys
import traceback
from datetime import datetime, timezone

from task_lock import task_lock
import studio_core as studio
from mixamo_state import require_ready
from asset_inspector import inspect_download
from mixamo_state import check_animation


def stamp():
    return datetime.now(timezone.utc).isoformat()


def save(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    os.replace(temporary, path)


def execute(job, persist):
    character, action, params = job['character'], job['action'], job['params']
    ws = studio.workspace(character)
    outputs = job.setdefault('outputs', {})
    if action == 'reconstruct':
        image = (studio.BASE_DIR / params['image']).resolve()
        if not image.is_relative_to((ws / 'inputs').resolve()) or not image.is_file():
            raise ValueError('原画不在本角色输入目录中')
        source_hash = studio.digest(image)
        model = ws / 'models' / f'{character}.obj'
        checkpoint = outputs.get('reconstruction', {})
        if not (checkpoint.get('image_sha256') == source_hash and model.is_file()
                and checkpoint.get('model_sha256') == studio.digest(model)):
            studio.generate(character, image)
            outputs['reconstruction'] = {'image_sha256': source_hash, 'model_sha256': studio.digest(model)}
            persist()
        else:
            print('复用本任务已完成的重建结果，继续贴图准备', flush=True)
        outputs['prepared'] = str(studio.prepare(character).relative_to(studio.BASE_DIR))
    elif action == 'prepare':
        outputs['prepared'] = str(studio.prepare(character).relative_to(studio.BASE_DIR))
    elif action == 'import_model':
        from import_model import import_character
        studio.progress_update(character,'prepare','正在导入 GLB、校准尺寸并生成外观预览')
        outputs['prepared']=str(import_character(studio.BASE_DIR,character,studio.BASE_DIR/params['source'],params['up'],params['yaw']).relative_to(studio.BASE_DIR))
    elif action == 'optimize':
        from model_optimization import optimize
        studio.progress_update(character,'prepare','Blender 正在生成减面候选与四视图对照；当前绑定保持不变')
        outputs['optimization']=str(optimize(studio.BASE_DIR,character,params['prepared'],params['fingerprint']).relative_to(studio.BASE_DIR))
    elif action == 'adopt_model':
        from model_optimization import activate
        outputs['prepared']=str(activate(studio.BASE_DIR,character,params['experiment'],params['variant']).relative_to(studio.BASE_DIR))
        studio.progress_update(character,'review','已采用优化版本，请重新确认模型外观并进行骨骼绑定')
    elif action == 'rig':
        studio.rig(character)
    elif action == 'download':
        binding = require_ready(character, studio.model_path(character),allow_cloud_recovery=True)
        batch = outputs.setdefault('batch', studio.new_batch())
        persist()
        target = ws / 'animations' / batch
        target.mkdir(parents=True, exist_ok=True)
        request = {'character': character, 'rig_sha256': binding['bound_sha256'], 'names': params['actions']}
        request_path = target / 'request.json'
        if request_path.exists() and json.loads(request_path.read_text()) != request:
            raise ValueError('绑定版本或动作配置已变化，请创建新的下载任务')
        request_path.write_text(json.dumps(request, ensure_ascii=False, indent=2))
        files = []
        for name in params['actions']:
            path = target / (studio.slug(name.lower().replace(' ', '_')) + '.fbx')
            if path.is_file():
                try:
                    info = inspect_download(path)
                    check_animation(info, binding['geometry'])
                except (ValueError, OSError, KeyError):
                    rejected = target / ('rejected-' + studio.new_batch())
                    rejected.mkdir()
                    path.rename(rejected / path.name)
                    print(f'未通过检查的旧下载已保留至 {rejected}', flush=True)
                else:
                    print(f'复用已下载并验证的动作：{name}', flush=True)
            if not path.is_file():
                studio.progress_update(character, 'download', f'正在下载并验证 {name}', batch=batch, action=name)
                studio.controller('download', name, path, '--character', character)
            # Always verify even freshly downloaded files before publishing the batch.
            info = inspect_download(path)
            check_animation(info, binding['geometry'])
            files.append(path)
        receipt = {'character': character, 'batch': batch, 'rig_sha256': binding['bound_sha256'],
                   'files': {p.name: studio.digest(p) for p in files}}
        save(target / 'batch.json', receipt)
        studio.progress_update(character, 'download', '动作下载与结构检查完成，请生成预览并人工验收',
                               status='waiting', batch=batch)
    elif action == 'weapon':
        from weapon_assets import generate,load as load_weapon
        if outputs.get('weapon'):
            load_weapon(studio.BASE_DIR,outputs['weapon'])
        else:
            studio.progress_update(character,'weapon','正在按白底直立武器预设重建')
            result=generate(studio.BASE_DIR,studio.BASE_DIR/params['image'],params['name'],studio.BASE_DIR/'.local/weapon-jobs'/job['id'])
            outputs['weapon']=result['id'];persist()
            studio.progress_update(character,'weapon','武器已生成，请检查多角度模型并确认握点',status='waiting')
    elif action == 'equipment':
        from equipment import edit
        outputs['equipment'] = str(edit(character, params['batch'], params.get('equipment_id'),params.get('weapon_id')).relative_to(studio.BASE_DIR))
    elif action == 'review':
        from review_character import review
        outputs['review'] = str(review(character, params['batch'], capture_only=not params.get('heading_file'), heading_file=params.get('heading_file')).relative_to(studio.BASE_DIR))
    elif action == 'compact':
        from compact_delivery import run
        outputs['delivery']=str(run(studio.BASE_DIR,character,params))
    elif action == 'sequence':
        from sequence_render import render
        outputs['sequence_preview']=render(studio.BASE_DIR,character,params['plan'])
    elif action == 'bake':
        # studio.bake publishes and records its destination only after the full batch passes.
        studio.bake(character, params['batch'], params['view'], params['frame_size'], params['supersample'], params.get('equipment_id'), params.get('renderer','godot'), params.get('equipment_usage_sha256'), selected_files=params.get('files'), body_height=params.get('body_height'))
        from progress import read
        outputs['delivery'] = read(character)['output']
    else:
        raise ValueError('Unknown panel operation')
    persist()


def main():
    path = Path(sys.argv[1]).resolve()
    allowed = (studio.BASE_DIR / '.local/panel/tasks').resolve()
    if path.parent != allowed or path.suffix != '.json':
        raise ValueError('Invalid task receipt')
    # The inherited descriptor keeps the project lease alive across panel restarts.
    # Services explicitly forward the lease to their Python controller children.
    lock_fd = int(sys.argv[2])
    os.set_inheritable(lock_fd, False)
    job = json.loads(path.read_text())
    job.pop('quality_report',None)
    job.update(status='running', started_at=stamp(), pid=os.getpid(), error=None)
    save(path, job)
    try:
        if job['action'] in ('bake','sequence','compact'):
            studio.progress_update(job['character'],'validate','正在启动新任务，检查输入')
        with task_lock(studio.BASE_DIR, lock_fd):
            execute(job, lambda: save(path, job))
        job.update(status='succeeded', finished_at=stamp())
    except BaseException as exc:
        traceback.print_exc()
        if job['action'] in ('bake','sequence','compact'):
            progress=studio.progress_read(job['character']) or {}
            quality_path=Path(progress.get('job',''))/'quality.json'
            if quality_path.is_file() and quality_path.resolve().is_relative_to((studio.BASE_DIR/'.local/jobs').resolve()):
                job['quality_report']=json.loads(quality_path.read_text())
        job.update(status='failed', error=str(exc), finished_at=stamp())
        failure_stage={'reconstruct':'reconstruction','prepare':'prepare','rig':'rig','download':'download','review':'review','equipment':'equipment','bake':'render','sequence':'render','compact':'validate','weapon':'weapon'}.get(job['action'],'validate')
        studio.progress_update(job['character'], failure_stage, str(exc), status='failed')
    finally:
        save(path, job)
        os.close(lock_fd)
    return 0 if job['status'] == 'succeeded' else 1


if __name__ == '__main__':
    sys.exit(main())
