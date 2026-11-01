"""Render arrangement sources together; never normalize posed sprite silhouettes."""
from task_lock import serialized
import json
from pathlib import Path
import shutil


def settings(value):
    if not isinstance(value,dict): raise ValueError('缺少编排统一渲染设置')
    result={k:value.get(k) for k in ('renderer','view','frame_size','supersample','equipment_id')}
    if result['renderer'] not in ('godot','blender') or result['view'] not in ('front','side','three_quarter') or type(result['frame_size']) is not int or result['frame_size'] not in (64,128) or type(result['supersample']) is not int or result['supersample'] not in (1,2,4):
        raise ValueError('无效的编排渲染设置')
    if result['equipment_id'] is not None:
        from asset_repository import name
        result['equipment_id']=name(result['equipment_id'])
    if value.get('body_height') is not None:
        if type(value['body_height']) is not int or value['body_height'] not in (48,64,96,128): raise ValueError('无效的人物像素高度')
        result['body_height'] = value['body_height']
    return result


def make_plan(assets,character,recipe):
    from asset_repository import name,read
    character=name(character)
    opts=settings(recipe)
    refs=recipe.get('sources')
    if not isinstance(refs,list) or not 1<=len(refs)<=64 or any(not isinstance(r,str) for r in refs):
        raise ValueError('请选择 1–64 个编排动作')
    refs=sorted(set(refs))
    c=assets.sequence_inputs(character)
    if not c['rig']['ready']: raise ValueError('请先恢复当前人物已验收的绑定')
    binding=read(assets.root/'.local/mixamo'/character/'state.json',{})
    rig=binding.get('bound_sha256')
    available={d['id']+'/'+clip['name']:(d,clip) for d in c['deliveries'] if d.get('kind')!='sequence' for clip in d['clips']}
    sources=[]
    for ref in refs:
        if ref not in available: raise ValueError('编排引用的原始渲染不存在或不属于此人物')
        delivery,clip=available[ref]
        batch=name(delivery['batch']);filename=clip['name']+'.fbx'
        source=assets.scoped(f'workspaces/{character}/animations/{batch}/{filename}',f'workspaces/{character}/animations')
        receipt_path=assets.scoped(f'workspaces/{character}/animations/{batch}/batch.json',f'workspaces/{character}/animations')
        receipt=read(receipt_path,{})
        manifest_path=assets.scoped(f'deliverables/{character}/{delivery["id"]}/manifest.json',f'deliverables/{character}')
        manifest=read(manifest_path,{})
        sha=receipt.get('files',{}).get(filename)
        if receipt.get('character')!=character or receipt.get('batch')!=batch or not rig or receipt.get('rig_sha256')!=rig:
            raise ValueError('编排动作不属于当前绑定，不能统一渲染')
        if not source.is_file() or not sha or assets.digest(source)!=sha or manifest.get('source',{}).get('files',{}).get(filename)!=sha:
            raise ValueError('编排原动画文件或来源记录已变化，请重新登记')
        from motion_heading import records as heading_records
        heading = heading_records(assets.root, character, {filename:sha}).get(filename)
        sources.append({'heading':heading,'ref':ref,'path':str(source.relative_to(assets.root)),'sha256':sha,'target':'clip_'+sha[:20]+'.fbx'})
    pin=None
    if opts['equipment_id']:
        from equipment import load
        from equipment_usage import load as usage_load,fingerprint
        config=load(assets.root,character,None,opts['equipment_id'])
        if config['rig_sha256']!=rig: raise ValueError('编排装备不属于当前绑定')
        pin=fingerprint(usage_load(assets.root,character,opts['equipment_id']))
    return {'recipe':{'sources':refs,**opts},'rig_sha256':rig,'sources':sources,'equipment_usage_sha256':pin}


@serialized(lambda root, *args, **kwargs: root)
def render(root,character,plan):
    from asset_repository import AssetRepository,atomic
    import studio_core as studio
    assets=AssetRepository(root)
    if make_plan(assets,character,plan['recipe'])!=plan:
        raise ValueError('编排源文件、绑定或武器设置已变化，请重新生成预览')
    batch=studio.new_batch()
    directory=assets.scoped(f'workspaces/{character}/animations/{batch}',f'workspaces/{character}/animations')
    directory.mkdir(parents=True)
    files={}
    for source in plan['sources']:
        path=assets.scoped(source['path'],f'workspaces/{character}/animations')
        if assets.digest(path)!=source['sha256']: raise ValueError('编排源动作在准备期间已变化')
        if source['target'] not in files: shutil.copy2(path,directory/source['target'])
        files[source['target']]=source['sha256']
    atomic(directory/'batch.json',{'character':character,'batch':batch,'kind':'sequence','rig_sha256':plan['rig_sha256'],'files':files})
    r=plan['recipe']
    studio.progress_update(character,'render','正在将编排全部动作合并测量，统一相机、尺寸和坐标基准')
    destination=studio.bake(character,batch,r['view'],r['frame_size'],r['supersample'],r['equipment_id'],r['renderer'],plan['equipment_usage_sha256'], **({'body_height':r['body_height']} if r.get('body_height') else {}))
    # Assert the renderer actually used one projection, not just equal PNG dimensions.
    manifest=json.loads((destination/'manifest.json').read_text())
    cameras=[manifest[Path(f).stem+'_spritesheet.png'].get('camera') for f in files]
    if not cameras or not cameras[0] or any(camera!=cameras[0] for camera in cameras):
        raise ValueError('编排动作未使用相同相机，拒绝发布为统一预览')
    record={'recipe':r,'delivery':destination.name,'clips':{s['ref']:Path(s['target']).stem for s in plan['sources']},'camera':cameras[0], 'heading_sources':{s['target']:s['sha256'] for s in plan['sources']}}
    from motion_heading import records as heading_records
    record['headings'] = heading_records(root, character, record['heading_sources'])
    atomic(assets.scoped(f'workspaces/{character}/sequence_preview.json',f'workspaces/{character}'),record)
    return record
