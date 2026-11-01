"""Reusable palette assets and immutable color-processed deliveries."""
import json
from pathlib import Path
import numpy as np
from asset_repository import AssetRepository,name,atomic
from task_lock import serialized
from color_clustering import make_palette,apply_palette
from compact_delivery import plan as source_plan
import studio_core as studio


def load_palette(root,palette_id):
    assets=AssetRepository(root);name(palette_id)
    path=assets.scoped('palettes/'+palette_id+'/palette.json','palettes')
    data=json.loads(path.read_text());rgb=data.get('rgb')
    if not isinstance(rgb,list) or not 1<=len(rgb)<=128 or any(not isinstance(c,list) or len(c)!=3 or any(type(v)is not int or not 0<=v<=255 for v in c) for c in rgb):raise ValueError('调色板数据无效')
    return data


def catalog(root):
    result=[]
    for path in sorted((Path(root)/'palettes').glob('*/palette.json'),reverse=True):
        try:result.append(load_palette(root,path.parent.name))
        except (ValueError,OSError):continue
    return result


def plan(root,character,params):
    base=source_plan(root,character,params.get('delivery'),params.get('clips'),params.get('profile','balanced'))
    manifest=json.loads((Path(root)/'deliverables'/character/base['delivery']/'manifest.json').read_text())
    if manifest.get('color_processing'):raise ValueError('请从处理前的原色图集创建颜色版本，避免反复限色')
    colors=params.get('colors',64);palette_id=params.get('palette_id')
    if palette_id:
        data=load_palette(root,palette_id);colors=len(data['rgb'])
    elif type(colors)is not int or colors not in (0,32,64,128):raise ValueError('请选择32、64或128色')
    label=params.get('label','')
    if not isinstance(label,str):raise ValueError('调色板名称无效')
    label=label.strip()
    if len(label)>60:raise ValueError('调色板名称最多60字')
    preserve=params.get('preserve_timing','profile' not in params)
    if type(preserve)is not bool:raise ValueError('无效的时序保留选项')
    timing_delivery=params.get('timing_delivery',base['delivery'])
    timing_plan=source_plan(root,character,timing_delivery,params.get('clips'))
    # Timing can only be reused from a derivative of the same original delivery.
    cursor=timing_delivery;seen=set()
    while cursor!=base['delivery']:
        if cursor in seen:raise ValueError('时序来源循环')
        seen.add(cursor)
        record=json.loads((Path(root)/'deliverables'/character/cursor/'manifest.json').read_text())
        cursor=record.get('operation',{}).get('source_delivery')
        if not cursor:raise ValueError('时序来源不是该原色图集的衍生版本')
        name(cursor)
    result={**base,'preserve_timing':preserve,'timing_delivery':timing_delivery,'timing_manifest_sha256':timing_plan['manifest_sha256'],'colors':colors,'palette_id':palette_id or None,'label':label}
    if palette_id:result['palette_sha256']=studio.digest(Path(root)/'palettes'/palette_id/'palette.json')
    return result


@serialized(lambda root,*args,**kwargs:root)
def run(root,character,pinned):
    root=Path(root)
    if plan(root,character,pinned)!=pinned:raise ValueError('图集或调色板已变化，请新建任务')
    source=root/'deliverables'/character/pinned['delivery'];data=json.loads((source/'manifest.json').read_text())
    job_id=studio.new_batch();stage=root/'.local/jobs'/job_id/'staging';stage.mkdir(parents=True)
    timing_data=json.loads((root/'deliverables'/character/pinned['timing_delivery']/'manifest.json').read_text())
    studio.progress_update(character,'validate','正在处理颜色，保留时序' if pinned['preserve_timing'] else '正在处理颜色并按新设置精简',job=job_id)
    sheets=[]
    import shutil
    inputs=stage.parent/'input';inputs.mkdir()
    for clip in pinned['clips']:
        filename=clip+'_spritesheet.png';path=source/filename;copy=inputs/filename
        if studio.digest(path)!=pinned['sheet_sha256'][filename]:raise ValueError('源图集已变化')
        shutil.copy2(path,copy)
        if studio.digest(copy)!=pinned['sheet_sha256'][filename]:raise ValueError('复制期间源图集已变化')
        sheets.append(copy)
    if pinned['colors']==0:
        palette=None
    elif pinned['palette_id']:
        palette=load_palette(root,pinned['palette_id'])
    else:
        palette={'schema':1,'id':job_id,'name':pinned['label'] or str(pinned['colors'])+'色调色板','rgb':make_palette(sheets,data,pinned['colors']).tolist(),'source':{'character':character,'delivery':pinned['delivery'],'sheets':pinned['sheet_sha256']}}
    rgb=np.asarray(palette['rgb'],dtype=np.uint8) if palette else None
    result={k:v for k,v in data.items() if not k.endswith('_spritesheet.png') and k!='quality_report'}
    result['color_processing']={'palette_id':palette['id'],'colors':len(rgb),'dither':False,'alpha':'unchanged'} if palette else None
    result['operation']={'type':'palette','source_delivery':pinned['delivery'],'source_manifest_sha256':pinned['manifest_sha256'],'timing_delivery':pinned['timing_delivery'],'preserve_timing':pinned['preserve_timing']}
    metrics={};quality_results=[]
    for clip in pinned['clips']:
        key=clip+'_spritesheet.png';original=data[key];path=stage/key
        if palette:metrics[clip]=apply_palette(inputs/key,path,rgb)
        else:shutil.copy2(inputs/key,path)
        timing={k:v for k,v in original.items() if k not in ('game','quality','sha256','unique_frames')}
        timing['color_processing']=result['color_processing']
        quality=studio.validate_sheet(path,timing['frame_width'],timing['frame_count'],allow_small=True)['quality']
        previous=timing_data[key].get('game')
        if pinned['preserve_timing']:
            game=write_selection(path,stage/'game',timing,previous,quality)
        else:
            game=studio.make_game_version(path,timing,quality,(data.get('equipment') or {}).get('usage'),profile=pinned.get('profile','balanced'))
        comparison=write_selection(inputs/key,stage/'comparison',timing,game,quality)

        info={**original,**timing,'sha256':studio.digest(path),'quality':quality,'game':game,'color_comparison':comparison}
        result[key]=info
        atomic(stage/(clip+'_render.json'),timing)
        studio.make_preview(path,stage/(clip+'_preview.gif'),timing['duration_seconds'],timing['frame_width'],timing['frame_count'])
        quality_results.append({'name':clip,**quality})
    result['quality_report']={'summary':{s:sum(v['status']==s for v in quality_results) for s in ('passed','review','failed')},'results':quality_results}
    result['color_metrics']=metrics
    if palette:atomic(stage/'palette.json',palette)
    atomic(stage/'manifest.json',result)
    import shutil
    for filename in ('projection.json','equipment.json','equipment_usage.json'):
        if (source/filename).is_file():shutil.copy2(source/filename,stage/filename)
    if palette and not pinned['palette_id']:atomic(root/'palettes'/palette['id']/'palette.json',palette)
    target=root/'deliverables'/character/job_id;stage.rename(target)
    studio.progress_update(character,'complete','颜色简化完成；原色保留，精简版已更新',status='complete',output=str(target))
    return target


def write_selection(source,folder,timing,selection,quality):
    """Copy an explicit source-frame selection without running frame reduction."""
    from PIL import Image
    from sheet_layout import tiles,blank
    from compact_frames import write_spriteframes
    import math
    count=timing['frame_count'];duration=timing['duration_seconds'];size=timing['frame_width']
    indices=selection.get('source_frame_indices') if selection else list(range(count))
    durations=selection.get('frame_durations_seconds') if selection else [duration/count]*count
    if not isinstance(indices,list) or not indices or any(type(i)is not int or not 0<=i<count for i in indices) or indices!=sorted(set(indices)):
        raise ValueError('原精简版缺少有效的源帧索引，无法保留时序')
    if not isinstance(durations,list) or len(durations)!=len(indices) or any(not math.isfinite(v) or v<=0 for v in durations) or abs(sum(durations)-duration)>1e-5:
        raise ValueError('原精简版时序不匹配')
    with Image.open(source) as image:frames=list(tiles(image.convert('RGBA'),size,count))
    sheet,cols,rows=blank(size,len(indices))
    for i,index in enumerate(indices):sheet.paste(frames[index],(i%cols*size,i//cols*size))
    folder.mkdir(exist_ok=True);path=folder/source.name;sheet.save(path);stem=source.name.removesuffix('_spritesheet.png');prefix=folder.name+'/'
    result={**timing,'frame_count':len(indices),'columns':cols,'rows':rows,'fps':len(indices)/duration,'timing_mode':'variable','frame_durations_seconds':durations,'source_frame_indices':indices,'source_frame_count':count,'quality':quality,'sha256':studio.digest(path),
            'compression':{**((selection or {}).get('compression') or {}),'timing_preserved':True,'source_bytes':source.stat().st_size,'output_bytes':path.stat().st_size},
            'sheet':prefix+source.name,'gif':prefix+stem+'_preview.gif','spriteframes':prefix+stem+'.tres'}
    atomic(folder/(stem+'_render.json'),result)
    studio.make_preview(path,folder/(stem+'_preview.gif'),duration,size,len(indices),durations)
    write_spriteframes(folder/(stem+'.tres'),source.name,result)
    return result
