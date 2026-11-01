"""Resumable production of a coherent character action set from one request."""
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path
from asset_repository import AssetRepository, atomic, name, read
from task_lock import serialized


def key(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def plan(assets, character, params):
    c = assets.character(character)
    if not c['rig']['ready']: raise ValueError('请先完成人物骨骼绑定，之后可一键生产动作集')
    binding = read(assets.root/'.local/mixamo'/character/'state.json', {})
    rig = binding.get('bound_sha256')
    if not rig: raise ValueError('缺少已验收绑定记录')
    if params.get('rig_sha256') and params['rig_sha256'] != rig: raise ValueError('绑定已变化，请新建整套生成任务')
    actions = params.get('actions')
    if not isinstance(actions, list) or not 1 <= len(actions) <= 12: raise ValueError('请填写1–12个动作')
    clean = []
    for a in actions:
        if not isinstance(a, dict): raise ValueError('动作配置无效')
        role, title, loop = name(a.get('role')), a.get('title'), a.get('loop')
        if not isinstance(title, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9 _-]{0,59}', title.strip()): raise ValueError('请填写 Mixamo 英文动作标题')
        if type(loop) is not bool: raise ValueError('请指定动作是否循环')
        clean.append({'role':role, 'title':title.strip(), 'loop':loop})
    if len({a['role'] for a in clean}) != len(clean) or len({a['title'].lower().replace(' ', '_') for a in clean}) != len(clean): raise ValueError('动作标识或标题重复')
    opts = {k:params.get(k, v) for k, v in dict(renderer='godot', view='three_quarter', body_height=96, supersample=4, colors=64, profile='balanced', equipment_id=None).items()}
    if opts['renderer'] not in ('godot','blender') or opts['view'] not in ('front','side','three_quarter'): raise ValueError('无效渲染器或视角')
    if type(opts['body_height']) is not int or opts['body_height'] not in (48,64,96,128) or type(opts['supersample']) is not int or opts['supersample'] not in (1,2,4): raise ValueError('无效人物像素高度或超采样')
    if type(opts['colors']) is not int or opts['colors'] not in (0,32,64,128) or opts['profile'] not in ('balanced','smooth','compact'): raise ValueError('无效颜色或精简设置')
    usage_pin = None
    if opts['equipment_id']:
        from equipment import load
        from equipment_usage import load as usage_load, fingerprint
        opts['equipment_id'] = name(opts['equipment_id'])
        config = load(assets.root, character, None, opts['equipment_id'])
        if config['rig_sha256'] != rig: raise ValueError('装备不属于当前绑定')
        usage_pin = fingerprint(usage_load(assets.root, character, opts['equipment_id']))
    if params.get('equipment_usage_sha256') and params['equipment_usage_sha256'] != usage_pin: raise ValueError('武器持用设置已变化，请新建任务')
    from motion_heading import records
    sources = {}
    for a in clean:
        pinned = params.get('sources', {}).get(a['role']) if 'sources' in params else None
        if 'sources' not in params:
            for b in c['batches']:
                if not b['current_rig']: continue
                filename = next((f for f in b['files'] if b.get('titles', {}).get(f, Path(f).stem.replace('_',' ')).lower() == a['title'].lower()), None)
                if filename:
                    pinned = {'batch':b['id'], 'file':filename, 'sha256':b['hashes'][filename]};break
        if pinned:
            batch, filename = name(pinned['batch']), pinned['file']
            if Path(filename).name != filename or not filename.endswith('.fbx'): raise ValueError('动作源文件名无效')
            receipt = read(assets.scoped(f'workspaces/{character}/animations/{batch}/batch.json', f'workspaces/{character}'), {})
            source = assets.scoped(f'workspaces/{character}/animations/{batch}/{filename}', f'workspaces/{character}')
            if receipt.get('character') != character or receipt.get('rig_sha256') != rig or receipt.get('files',{}).get(filename) != pinned['sha256'] or assets.digest(source) != pinned['sha256']: raise ValueError('原动作来源已变化，请新建任务')
            heading = records(assets.root, character, {filename:pinned['sha256']})
            value = {**pinned, 'heading':heading.get(filename)}
            if 'sources' in params and value != pinned: raise ValueError('动作校准已变化，请新建任务')
            sources[a['role']] = value
        else: sources[a['role']] = None
    title = params.get('title', '角色动作集')
    if not isinstance(title,str) or not 1 <= len(title.strip()) <= 60: raise ValueError('动作集名称需为1–60字符')
    revision = params.get('base_revision', (read(assets.root/'workspaces'/character/'action_set.json',{}) or {}).get('revision',0))
    if type(revision) is not int or revision < 0: raise ValueError('无效修订号')
    return {'title':title.strip(), 'actions':clean, **opts, 'rig_sha256':rig, 'equipment_usage_sha256':usage_pin, 'base_revision':revision, 'sources':sources}


def intact(assets, character, checkpoint):
    """Verify immutable checkpoint inputs before skipping expensive stages."""
    try:
        folder = assets.scoped(f'deliverables/{character}/{name(checkpoint["delivery"])}', f'deliverables/{character}')
        return bool(checkpoint.get('hashes')) and all(assets.digest(assets.scoped(str((folder/f).relative_to(assets.root)), f'deliverables/{character}')) == sha for f,sha in checkpoint['hashes'].items())
    except (KeyError, ValueError, OSError): return False


def checkpoint(assets, character, folder):
    folder = Path(folder)
    files = [p for p in folder.rglob('*') if p.is_file()]
    for p in files: assets.scoped(str(p.relative_to(assets.root)), f'deliverables/{character}')
    return {'delivery':folder.name, 'hashes':{str(p.relative_to(folder)):assets.digest(p) for p in files}}


@serialized(lambda root, *args, **kwargs: root)
def run(root, job, persist, download):
    """download(title, checkpoint, persist) reuses the established Mixamo worker."""
    import studio_core as studio
    root = Path(root).resolve();assets = AssetRepository(root);character = job['character'];p = job['params']
    if plan(assets, character, p) != p: raise ValueError('生产配置或来源已变化，请新建任务')
    out = job.setdefault('outputs', {});state = out.setdefault('production', {'roles':{}, 'renders':[]})
    state.pop('error', None)
    atomic(root/'workspaces'/character/'production.json', {'config':p, 'task':job['id']})
    def progress(stage, message):
        state['stage'] = stage;persist();studio.progress_update(character, stage, message)
    def fail(role, exc):
        state['roles'][role] = {'status':'failed', 'error':str(exc)};persist()
        print(f'[整套生产] {role}: {exc}', flush=True)
    resolved = {}
    for index,a in enumerate(p['actions']):
        role, title = a['role'], a['title']
        progress('download', f'整套动作 {index+1}/{len(p["actions"])}：准备 {title}')
        try:
            original = p['sources'].get(role)
            if original:
                source = root/'workspaces'/character/'animations'/original['batch']/original['file']
            else:
                receipt = state.setdefault('downloads', {}).setdefault(role, {})
                filename=title.lower().replace(' ','_')+'.fbx'
                source=root/'workspaces'/character/'animations'/receipt.get('batch','pending')/filename
                if not (receipt.get('source_sha256') and source.is_file() and assets.digest(source)==receipt['source_sha256']):
                    download(title, receipt, persist)
                    source=root/'workspaces'/character/'animations'/receipt['batch']/filename
            from asset_inspector import inspect_download
            from mixamo_state import check_animation, check_motion
            binding = read(root/'.local/mixamo'/character/'state.json', {})
            if binding.get('bound_sha256') != p['rig_sha256']: raise ValueError('Mixamo 绑定已变化，请恢复人物后新建任务')
            sha=assets.digest(source)
            inspections=state.setdefault('inspections',{})
            info=inspections.get(sha)
            if info is None:info=inspect_download(source)
            check_animation(info,binding['geometry']);check_motion(info)
            if info.get('textured_surfaces',0)<1: raise ValueError('动作缺失贴图')
            inspections[sha]=info
            if not original:receipt['source_sha256']=sha
            if original and sha != original['sha256']: raise ValueError('动作来源已变化')
            resolved[role] = {'path':str(source.relative_to(root)), 'sha256':sha, 'file':title.lower().replace(' ','_')+'.fbx'}
            state['roles'][role] = {'status':'source_ready'};persist()
        except (ValueError, OSError, KeyError, RuntimeError, subprocess.SubprocessError) as exc: fail(role, exc)
    if not resolved: raise ValueError('所有动作准备失败；查看任务中的逐动作错误后重试')
    # Copy into a single batch, retaining hashes and source-hash keyed heading calibrations.
    source_key = key({'rig':p['rig_sha256'], 'sources':resolved})
    batches = state.setdefault('batches', {})
    batch = batches.setdefault(source_key, studio.new_batch());persist()
    directory = assets.scoped(f'workspaces/{character}/animations/{batch}', f'workspaces/{character}');directory.mkdir(parents=True,exist_ok=True)
    files = {}
    for role,source in resolved.items():
        origin = assets.scoped(source['path'], f'workspaces/{character}')
        if assets.digest(origin) != source['sha256']: raise ValueError('动作在准备期间发生变化')
        target = directory/source['file'];shutil.copy2(origin,target)
        if assets.digest(target) != source['sha256']: raise ValueError('动作复制校验失败')
        files[source['file']] = source['sha256']
    atomic(directory/'batch.json', {'character':character,'batch':batch,'rig_sha256':p['rig_sha256'],'files':files,'action_roles':{s['file']:r for r,s in resolved.items()},'loop_intent':{resolved[a['role']]['file']:a['loop'] for a in p['actions'] if a['role'] in resolved}})
    atomic(directory/'request.json', {'names':[a['title'] for a in p['actions'] if a['role'] in resolved]})
    from motion_heading import records
    headings = records(root, character, files)
    render_spec = {k:p[k] for k in ('renderer','view','body_height','supersample','equipment_id','rig_sha256','equipment_usage_sha256')}
    # Match each role's source/settings against prior successful renders, even on partial retry.
    covered = {}
    cache = root/'.local/production'/character
    cache.mkdir(parents=True,exist_ok=True)
    for role,source in resolved.items():
        signature = key({'source':source['sha256'],'file':source['file'],'heading':headings.get(source['file']),**render_spec})
        receipt = read(cache/(signature+'.json'),{})
        if intact(assets, character, receipt): covered[role] = receipt
    def remember_render(folder, roles):
        cp = checkpoint(assets,character,folder);data = read(Path(folder)/'manifest.json',{})
        for role in roles:
            source = resolved[role]
            if source['file'].removesuffix('.fbx')+'_spritesheet.png' not in data:
                reason = next((r.get('reason','画面检查失败') for r in data.get('quality_report',{}).get('results',[]) if r['name']==source['file'].removesuffix('.fbx')), '缺少输出图集')
                fail(role, reason);continue
            covered[role] = cp
            signature = key({'source':source['sha256'],'file':source['file'],'heading':headings.get(source['file']),**render_spec})
            atomic(cache/(signature+'.json'),cp)
        state['renders'].append(cp);persist()
    def bake(roles):
        progress('render', '统一渲染：'+', '.join(roles))
        destination = studio.bake(character,batch,p['view'],64,p['supersample'],p['equipment_id'],p['renderer'],p['equipment_usage_sha256'],selected_files=[resolved[r]['file'] for r in roles],body_height=p['body_height'])
        remember_render(destination, roles)
    missing = [r for r in resolved if r not in covered]
    if missing:
        try: bake(missing)
        except (ValueError, OSError, RuntimeError, subprocess.SubprocessError) as exc:
            if len(missing)==1: fail(missing[0],exc)
            else:
                print(f'整批渲染失败，逐动作隔离：{exc}', flush=True)
                for role in missing:
                    try: bake([role])
                    except (ValueError, OSError, RuntimeError, subprocess.SubprocessError) as single: fail(role,single)
    if not covered: raise ValueError('所有动作渲染失败；已下载动作保留，重试无需重新下载')
    progress('validate', '正在汇集整套原色图集，统一配色和精简')
    # Assemble one immutable original-color delivery so palette fitting sees every action.
    raw_key = key({r:cp for r,cp in covered.items()})
    raw = state.get('raw', {})
    if raw.get('key')!=raw_key or not intact(assets,character,raw):raw=read(cache/('raw-'+raw_key+'.json'),{})
    if raw.get('key') != raw_key or not intact(assets,character,raw):
        identity = studio.new_batch();stage=root/'.local/jobs'/identity/'staging';stage.mkdir(parents=True)
        data = None;usage_clips = {}
        for role,cp in covered.items():
            folder=root/'deliverables'/character/cp['delivery'];manifest=read(folder/'manifest.json',{})
            if data is None:
                data = {k:v for k,v in manifest.items() if not k.endswith('_spritesheet.png') and k not in ('quality_report','operation')}
                for filename in ('equipment.json','equipment_usage.json'):
                    if (folder/filename).is_file():shutil.copy2(folder/filename,stage/filename)
            clip=resolved[role]['file'].removesuffix('.fbx');filename=clip+'_spritesheet.png'
            data[filename] = manifest[filename]
            for suffix in ('_spritesheet.png','_render.json','_preview.gif'):
                if (folder/(clip+suffix)).is_file():shutil.copy2(folder/(clip+suffix),stage/(clip+suffix))
            # Game samples will be regenerated after applying the shared palette.
            data[filename] = {k:v for k,v in data[filename].items() if k not in ('game','color_comparison')}
            usage_clips.update((manifest.get('equipment') or {}).get('usage',{}).get('clips',{}))
        if data.get('equipment'):
            data['equipment']['usage']['clips']=usage_clips
            atomic(stage/'equipment_usage.json', data['equipment']['usage'])
        data['source']={'character':character,'batch':batch,'files':{s['file']:s['sha256'] for r,s in resolved.items() if r in covered},'action_roles':{resolved[r]['file']:r for r in covered}}
        data['production']={'task':job['id'],'config':p};data['color_processing']=None
        atomic(stage/'manifest.json',data)
        target=root/'deliverables'/character/identity;target.parent.mkdir(parents=True,exist_ok=True);stage.rename(target)
        raw={**checkpoint(assets,character,target),'key':raw_key}
        atomic(cache/('raw-'+raw_key+'.json'),raw)
    state['raw']=raw;persist()
    finish_key=key({'raw':raw,'colors':p['colors'],'profile':p['profile']})
    finished=state.get('finished',{})
    if finished.get('key')!=finish_key or not intact(assets,character,finished):finished=read(cache/('finish-'+finish_key+'.json'),{})
    if finished.get('key')!=finish_key or not intact(assets,character,finished):
        from palette_delivery import plan as palette_plan, run as palette_run
        clips=[resolved[r]['file'].removesuffix('.fbx') for r in covered]
        destination=palette_run(root,character,palette_plan(root,character,{'delivery':raw['delivery'],'clips':clips,'colors':p['colors'],'profile':p['profile'],'preserve_timing':False,'label':p['title']}))
        finished={**checkpoint(assets,character,destination),'key':finish_key}
        atomic(cache/('finish-'+finish_key+'.json'),finished)
    state['finished']=finished;persist()
    manifest=read(root/'deliverables'/character/finished['delivery']/'manifest.json',{})
    actions={}
    for a in p['actions']:
        role=a['role'];clip=resolved.get(role,{}).get('file','').removesuffix('.fbx')
        if role in covered and manifest.get(clip+'_spritesheet.png',{}).get('game'):
            actions[role]={'delivery':finished['delivery'],'clip':clip,'variant':'game','loop':a['loop'],'reviewed':False}
            state['roles'][role]={'status':'ready'}
        else:
            actions[role]={'loop':a['loop'],'reviewed':False}
            state['roles'].setdefault(role,{'status':'failed','error':'没有可用图集'})
    out['result']={'title':p['title'],'actions':actions}
    failed=[r for r,a in actions.items() if not a.get('delivery')]
    persist()
    if failed:
        progress('validate',f'已完成 {len(actions)-len(failed)}/{len(actions)}；异常动作：'+', '.join(failed))
        raise ValueError('部分动作失败：'+', '.join(failed)+'。重试将复用已完成下载和渲染；当前正式动作集保持不变')
    from action_set import save as save_set
    current=read(root/'workspaces'/character/'action_set.json',{}) or {}
    expected=state.get('published_revision',p['base_revision'])
    if current.get('revision',0)!=expected: raise ValueError('生产期间动作集已被修改；新成果已保留，请在高级管理中查看，避免覆盖他人修改')
    from action_set import source as set_source, inspect as inspect_set
    candidate=json.loads(json.dumps(out['result']))
    for choice in candidate['actions'].values():
        _,_,choice['fingerprint']=set_source(root,character,choice)
    validation=inspect_set(root,character,candidate)
    if not validation['complete']:raise ValueError('整套一致性检查失败：'+'；'.join(validation['errors']))
    saved=save_set(root,character,{**out['result'],'revision':expected})
    if not saved['validation']['complete']: raise ValueError('整套一致性检查失败：'+'；'.join(saved['validation']['errors']))
    state['published_revision']=saved['recipe']['revision'];state['stage']='complete';out['action_set']=saved['recipe'];persist()
    studio.progress_update(character,'complete','整套动作已生成，可切换预览并导出；美术与具体表演仍需整套复核',status='complete')
