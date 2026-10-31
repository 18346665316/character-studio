"""Independent compression of published pixel sheets; immutable input deliveries."""
import json
import shutil
from pathlib import Path
from panel import Panel,atomic,name
import studio_core as studio


def plan(root,character,delivery,clips):
    panel=Panel(root);name(character);name(delivery)
    directory=panel.scoped(f'deliverables/{character}/{delivery}',f'deliverables/{character}')
    manifest_path=panel.scoped(f'deliverables/{character}/{delivery}/manifest.json',f'deliverables/{character}/{delivery}')
    data=json.loads(manifest_path.read_text())
    if data.get('source',{}).get('character')!=character or data.get('source',{}).get('kind')=='sequence':
        raise ValueError('请选择本人物的普通动作图集')
    if not isinstance(clips,list) or not 1<=len(clips)<=64 or any(not isinstance(c,str) for c in clips) or len(set(clips))!=len(clips):
        raise ValueError('请选择 1–64 个已有图集动作')
    hashes={}
    for clip in clips:
        name(clip);filename=clip+'_spritesheet.png';info=data.get(filename)
        if not isinstance(info,dict) or info.get('timing_mode')=='variable':
            raise ValueError('缺少完整采样图集，不能对精简结果再次累积压缩')
        path=panel.scoped(str((directory/filename).relative_to(panel.root)),f'deliverables/{character}/{delivery}')
        if not path.is_file():raise ValueError('原图集不存在')
        hashes[filename]=panel.digest(path)
    return {'delivery':delivery,'clips':clips,'manifest_sha256':panel.digest(manifest_path),'sheet_sha256':hashes}


def run(root,character,pinned):
    root=Path(root);directory=root/'deliverables'/character/pinned['delivery']
    if plan(root,character,pinned['delivery'],pinned['clips'])!=pinned:
        raise ValueError('原图集或清单已变化，请重新创建精简任务')
    data=json.loads((directory/'manifest.json').read_text());job_id=studio.new_batch()
    job=root/'.local/jobs'/job_id;staging=job/'staging';staging.mkdir(parents=True)
    studio.progress_update(character,'validate','正在精简已有图集，无需重新渲染',job=str(job))
    result={k:v for k,v in data.items() if not k.endswith('_spritesheet.png') and k!='quality_report'}
    result['operation']={'type':'compact','source_delivery':pinned['delivery'],'source_manifest_sha256':pinned['manifest_sha256']}
    results=[]
    for clip in pinned['clips']:
        filename=clip+'_spritesheet.png';original=data[filename]
        source=directory/filename
        if studio.digest(source)!=pinned['sheet_sha256'][filename]:raise ValueError('原图集在读取期间已变化')
        shutil.copy2(source,staging/filename)
        if studio.digest(staging/filename)!=pinned['sheet_sha256'][filename]:raise ValueError('图集复制期间发生变化')
        try:
            quality=studio.validate_sheet(staging/filename,original['frame_width'],original['frame_count'],allow_small=True)['quality']
            timing={k:v for k,v in original.items() if k not in ('game','quality','sha256','unique_frames')}
            timing.setdefault('fps',timing['frame_count']/timing['duration_seconds'])
            game=studio.make_game_version(staging/filename,timing,quality,(data.get('equipment') or {}).get('usage'))
            result[filename]={**original,'quality':quality,'game':game}
            atomic(staging/(clip+'_render.json'),timing)
            studio.make_preview(staging/filename,staging/(clip+'_preview.gif'),timing['duration_seconds'],timing['frame_width'],timing['frame_count'])
            results.append({'name':clip,**quality,'frame_count':timing['frame_count'],'game_frame_count':game['frame_count'],'duration_seconds':timing['duration_seconds'],'fps':timing['fps'],'source_fps':timing.get('source_fps')})
            studio.progress_update(character,'validate',f'{clip}: {timing["frame_count"]} → {game["frame_count"]} 帧，时长不变',job=str(job))
        except (ValueError,OSError,KeyError,TypeError) as exc:
            result.pop(filename,None)
            rejected=job/'rejected';rejected.mkdir(exist_ok=True)
            for folder in (staging,staging/'game'):
                for suffix in ('_spritesheet.png','_render.json','_preview.gif','.tres'):
                    path=folder/(clip+suffix)
                    if path.is_file():path.rename(rejected/(('game_' if folder.name=='game' else '')+path.name))
            results.append({'name':clip,'status':'failed','reason':str(exc)})
            studio.progress_update(character,'validate',f'{clip}: 精简失败，已隔离；继续处理其他动作',job=str(job))
    result['quality_report']={'schema':1,'summary':{s:sum(r['status']==s for r in results) for s in ('passed','review','failed')},'results':results}
    atomic(job/'quality.json',result['quality_report'])
    counts=result['quality_report']['summary']
    if counts['passed']+counts['review']==0:
        raise ValueError('全部动作精简失败：'+'；'.join(r['reason'] for r in results))
    atomic(staging/'manifest.json',result)
    # Preserve equipment snapshots carried by the original delivery.
    for filename in ('equipment.json','equipment_usage.json'):
        if (directory/filename).is_file():
            source=Panel(root).scoped(str((directory/filename).relative_to(root)),f'deliverables/{character}/{pinned["delivery"]}')
            shutil.copy2(source,staging/filename)
    destination=root/'deliverables'/character/job_id;staging.rename(destination)
    studio.progress_update(character,'complete',f'精简完成：通过 {counts["passed"]}，需复核 {counts["review"]}，失败 {counts["failed"]}；原图集保留',status='complete',output=str(destination),job=str(job))
    return destination
