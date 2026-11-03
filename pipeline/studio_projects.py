"""Project requirements, production context and live material references.

Legacy selection files remain readable; new library choices store references.
"""
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
import json
import math
from pathlib import Path
import secrets
import zipfile

from PIL import Image
from asset_repository import AssetRepository, atomic, read, name

KINDS = {
    'character': ('人物', '/characters.html?create=1', 'character'),
    'ground': ('地面', '/terrain.html?type=material', 'terrain'),
    'road': ('道路', '/terrain.html?type=terrain', 'terrain'),
    'water': ('水面', '/water.html', 'terrain'),
    'shore': ('水岸', '/water-shore.html', 'transition'),
    'transition': ('地表过渡', '/transition.html', 'transition'),
    'building': ('建筑', '/buildings.html', 'building'),
    'prop': ('物件', '/props.html', 'prop'),
    'component': ('围栏', '/components.html', 'component'),
}
DEFAULT_BASELINE = dict(view='isometric_2_1', cell_px=128, character_height_px=96,
                        style='', palette='', lighting='柔和中性光，统一左上方受光',camera_rules='',orientation_rules='')
ROUTES = {'/api/buildings/prepare':'buildings', '/api/terrain/generate':'terrain',
          '/api/props/generate':'props', '/api/components/generate':'components',
          '/api/tasks':'character', '/api/terrain/transition':'transitions'}


def now(): return datetime.now(timezone.utc).isoformat()
def identity(): return datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+secrets.token_hex(4)
def digest(content): return sha256(content).hexdigest()
def folder(root, pid): return AssetRepository(root).scoped('.local/studio/projects/'+name(pid), '.local/studio/projects')
def load(root, pid):
    p = read(folder(root,pid)/'project.json')
    if not p or p.get('id') != pid: raise ValueError('素材项目不存在')
    return p

def text(value, label, maximum=2000, empty=False):
    if not isinstance(value,str) or len(value.strip())>maximum or (not empty and not value.strip()):
        raise ValueError(label+'为空或过长')
    return value.strip()

def revision(p, data):
    if data.get('revision') != p['revision']: raise ValueError('项目已更新，请刷新后重试')

def item(p, iid):
    for entry in p['items']:
        if entry['id']==iid: return entry
    raise ValueError('素材清单项不存在')

def baseline(data):
    if not isinstance(data,dict): raise ValueError('共同基准格式无效')
    b = dict(DEFAULT_BASELINE, **{k:v for k,v in data.items() if k in DEFAULT_BASELINE})
    if b['view'] not in ('isometric_2_1','orthographic_three_quarter','top_down'): raise ValueError('项目视角无效')
    if type(b['cell_px']) is not int or b['cell_px'] not in (64,128): raise ValueError('地格宽度须为64或128')
    if type(b['character_height_px']) is not int or not 16<=b['character_height_px']<=512: raise ValueError('参考人物高度须为16–512px')
    for k in ('style','palette','lighting','camera_rules','orientation_rules'): b[k]=text(b[k], '共同基准', empty=True)
    return b

def catalog(root):
    return sorted((p for path in (Path(root)/'.local/studio/projects').glob('*/project.json')
                   if (p:=read(path))), key=lambda p:p['updated_at'], reverse=True)

def available(root):
    result=[]
    definitions=[('terrain','terrain-kits','/terrain.html','/terrain-asset/'),
                 ('transition','terrain-transitions','/transition.html','/transition-asset/'),
                 ('prop','prop-kits','/props.html','/prop-asset/'),
                 ('component','component-kits','/components.html','/component-asset/'),
                 ('building','building-kits','/buildings.html','/building-asset/')]
    for family,subtree,page,prefix in definitions:
        for path in (Path(root)/subtree).glob('*/manifest.json'):
            m=read(path,{})
            if not m.get('id') or path.parent.is_symlink(): continue
            kind=family
            if family=='terrain':
                kind='water' if m.get('material_kind')=='water' else 'ground' if m.get('asset_type')=='material' else 'road'
                if kind=='water': page_url='/water.html'
                else: page_url=page
            elif family=='transition':
                kind='shore' if m.get('transition_mode')=='shoreline' else 'transition'
                page_url='/water-shore.html' if kind=='shore' else page
            else: page_url=page
            image='sprite.png' if family in ('prop','building') else 'assembly.png' if family=='component' else 'preview.png'
            result.append(dict(id=m['id'],family=family,kind=kind,title=m.get('title',m['id']),
                               href=page_url+'?kit='+m['id'],image=prefix+m['id']+'/'+image))
    for c in AssetRepository(root).catalog():
        result.append(dict(id=c['id'],family='character',kind='character',title=c['display_name'],
                           href='/characters.html?character='+c['id'],image=None))
    return result

def current_assets(root, p, assets=None, tasks=None, choices=None):
    """Resolve the live material for each requirement, without making snapshots.

    A later explicit library choice overrides earlier production. New successful
    output replaces it; a failed or unfinished task leaves the last output visible.
    """
    assets = available(root) if assets is None else assets
    tasks = task_state(root, p) if tasks is None else tasks
    choices = candidates(root, p) if choices is None else choices
    result = {}
    for entry in p['items']:
        selected = entry.get('asset_ref') or entry.get('selected') or {}
        current = next((a for a in assets if a['id'] == selected.get('asset')
                        and a['family'] == selected.get('family')), None)
        for task in tasks:
            if task.get('context', {}).get('item') != entry['id']:
                continue
            if task.get('created_at', '') <= selected.get('selected_at', '') and selected:
                continue
            candidate = next((c for c in reversed(choices) if c['task'] == task['id']), None)
            if candidate:
                current = candidate
            elif task.get('status') not in ('failed', 'missing', 'queued', 'running') and not task.get('error'):
                output = next((a for a in assets if a['kind'] == entry['kind']
                               and a['id'] == (task.get('kit') or task.get('character'))), None)
                if output:
                    current = output
        if current:
            result[entry['id']] = dict(current)
            if not current.get('image'):
                from urllib.parse import urlencode
                result[entry['id']]['image'] = '/api/projects/current-image?' + urlencode(dict(project=p['id'], item=entry['id']))
    return result


def source(root, family, aid):
    name(aid)
    if family=='character':
        from action_set import export
        content=export(root,aid)
        with zipfile.ZipFile(BytesIO(content)) as archive:
            prefix='character_assets/'+aid+'/'
            m=json.loads(archive.read(prefix+'manifest.json'))
            animation=next(iter(m['actions']))
            info=m['actions'][animation]
            image=Image.open(BytesIO(archive.read(prefix+'assets/textures/'+animation+'.png'))).convert('RGBA')
            # Package frames are square; use the exported SpriteFrames region size.
            frames=archive.read(prefix+'animations.tres').decode()
            import re
            match=re.search(r'region = Rect2\(0, 0, ([\d.]+), ([\d.]+)\)',frames)
            if not match: raise ValueError('人物包缺少首帧区域')
            image=image.crop((0,0,int(float(match[1])),int(float(match[2]))))
            anchor=info.get('anchor_px',[image.width/2,image.height*.85])
        return content,image,dict(anchor_px=anchor,body_height_px=m.get('body_height_px'),view=m.get('view'))
    subtree={'terrain':'terrain-kits','transition':'terrain-transitions','prop':'prop-kits',
             'component':'component-kits','building':'building-kits'}.get(family)
    if not subtree: raise ValueError('素材类别无效')
    path=AssetRepository(root).scoped(subtree+'/'+aid,subtree)
    if family in ('terrain','transition'):
        from terrain_integrity import require
        require(root,subtree,aid)
        m=read(path/'manifest.json'); image_path=m.get('ground','preview.png')
        if family=='terrain' and m.get('projection_spec',{}).get('variants'):
            image_path=m['projection_spec']['variants'][0]['image']
    elif family=='prop':
        from static_props import load_package
        m=load_package(root,aid);image_path='sprite.png'
    elif family=='component':
        from fence_components import load_package
        m,_=load_package(root,aid);image_path='assembly.png'
    else:
        from building_pipeline import load_package
        m=load_package(root,aid);image_path='sprite.png'
    image_file=AssetRepository(root).scoped(subtree+'/'+aid+'/'+image_path,subtree+'/'+aid)
    with Image.open(image_file) as im: image=im.convert('RGBA')
    info=read(path/'integration.json',{}) if family=='building' else m
    anchor=info.get('anchor_px')
    if anchor is None and info.get('sprite_offset_px'): anchor=[-v for v in info['sprite_offset_px']]
    if family=='terrain' and m.get('projection_spec',{}).get('variants'):
        anchor=m['projection_spec']['variants'][0]['anchor_px']
    return (path/'kit.zip').read_bytes(),image,dict(anchor_px=anchor or [image.width/2,image.height],
                                                   view=m.get('view'),engine_acceptance='not_tested')


def candidates(root,p):
    result=[]
    for task in p['tasks']:
        if task['family']!='buildings': continue
        from building_pipeline import require_job,attempt_folder,verify_attempt
        from building_candidates import verify_evidence
        try:
            folder,job=require_job(root,task['id'])
            if job.get('purpose')=='template': continue
            for attempt in job['attempts']:
                target=attempt_folder(folder,attempt)
                try:
                    verify_attempt(folder,target,job);verify_evidence(folder,target)
                except (ValueError,OSError,KeyError): continue
                result.append(dict(id=task['id']+'--'+attempt,item=task['context']['item'],kind='building',family='building',
                    title=job['spec']['title']+' · 候选 '+str(job['attempts'].index(attempt)+1),
                    task=task['id'],attempt=attempt,
                    href='/buildings.html?task='+task['id'],
                    image='/api/buildings/file?task='+task['id']+'&attempt='+attempt+'&kind=sprite'))
        except (ValueError,OSError,KeyError): continue
    return result


def preview(root,p,entry,aid):
    candidate=next((c for c in candidates(root,p) if c['id']==aid and c['item']==entry['id']),None)
    if candidate:
        from building_pipeline import require_job,attempt_folder
        folder,job=require_job(root,candidate['task']);target=attempt_folder(folder,candidate['attempt'])
        with Image.open(target/'sprite.png') as original: im=original.convert('RGBA')
        bbox=im.getchannel('A').getbbox()
        meta=dict(anchor_px=[(bbox[0]+bbox[2])/2,bbox[3]],view='from_line_drawing')
    else:
        asset=next((a for a in available(root) if a['id']==aid and a['kind']==entry['kind']),None)
        if not asset: raise ValueError('素材不属于清单要求的类别')
        _,im,meta=source(root,asset['family'],aid)
    stream=BytesIO();im.save(stream,'PNG')
    import base64
    return dict(asset=aid,sha256=digest(stream.getvalue()),canvas_px=list(im.size),**meta,
                image='data:image/png;base64,'+base64.b64encode(stream.getvalue()).decode())


def selection_file(root,pid,selection,kind):
    if kind not in ('image','archive'): raise ValueError('无效选用资源')
    stem=selection['sha256'];name(stem)
    path=AssetRepository(root).scoped('.local/studio/projects/'+pid+'/selected/'+stem+('.png' if kind=='image' else '.zip'),'.local/studio/projects/'+pid+'/selected')
    expected=selection['image_sha256'] if kind=='image' else stem
    raw=path.read_bytes()
    if digest(raw)!=expected: raise ValueError('项目选用素材快照已变化')
    return raw

def change(root,data):
    action=data.get('action')
    obsolete_selection=None
    if action=='create':
        pid=identity();p=dict(id=pid,title=text(data.get('title'),'项目名称',60),revision=0,
                baseline_revision=1,baseline=baseline(data.get('baseline',{})),items=[],tasks=[],
                review=None,created_at=now(),updated_at=now(),releases=[])
    else:
        p=load(root,data.get('project'));pid=p['id'];revision(p,data)
    if action in ('adopt_candidate', 'use_candidate'):
        entry=item(p,data.get('item'))
        candidate=next((c for c in candidates(root,p) if c['id']==data.get('asset') and c['item']==entry['id']),None)
        if not candidate: raise ValueError('候选不属于此清单项')
        from building_pipeline import require_job,attempt_folder,digest as file_digest
        from building_candidates import save
        directory,job=require_job(root,candidate['task'])
        m=save(root,dict(task=job['id'],revision=job['revision'],attempt=candidate['attempt'],
               evidence_key=file_digest(attempt_folder(directory,candidate['attempt'])/'checks.json'),visual_only=True))
        data=dict(data,asset=m['id']);action='set_asset' if action=='use_candidate' else 'select'
    if action=='baseline':
        p['baseline']=baseline(data.get('baseline',{}));p['baseline_revision']+=1;p['review']=None
    elif action=='add':
        kind=data.get('kind')
        if kind not in KINDS: raise ValueError('素材类型无效')
        if len(p['items'])>=200: raise ValueError('项目清单最多200项')
        p['items'].append(dict(id=identity(),kind=kind,title=text(data.get('title'),'素材名称',60),
                              description=text(data.get('description',''),'需求描述',empty=True),selected=None))
        p['review']=None
    elif action=='import_items':
        rows=data.get('items')
        if not isinstance(rows,list) or not 1<=len(rows)<=200: raise ValueError('批量清单须包含1–200项')
        existing={(i['kind'],i['title']) for i in p['items']}
        additions=[]
        for row in rows:
            if not isinstance(row,dict) or row.get('kind') not in KINDS: raise ValueError('素材类型无效')
            title=text(row.get('title'),'素材名称',60)
            description=text(row.get('description',''),'需求描述',empty=True)
            key=(row['kind'],title)
            if key in existing: continue
            existing.add(key)
            additions.append(dict(id=identity(),kind=row['kind'],title=title,description=description,selected=None))
        if len(p['items'])+len(additions)>200: raise ValueError('项目清单最多200项')
        if not additions: return p
        p['items'].extend(additions);p['review']=None
    elif action=='bind_template':
        entry=item(p,data.get('item'))
        if entry['kind']!='building': raise ValueError('仅建筑需求可绑定模板')
        template=data.get('template_id')
        if template:
            from building_templates import load as load_template
            _,meta=load_template(root,template)
            if meta['view'] not in (p['baseline']['view'],'custom'): raise ValueError('模板视角与项目不一致')
        entry['template_id']=template or None
        p['review']=None
    elif action=='set_asset':
        entry=item(p,data.get('item'));family=KINDS[entry['kind']][2];aid=name(data.get('asset'))
        if not any(a['family']==family and a['id']==aid and a['kind']==entry['kind'] for a in available(root)):
            raise ValueError('素材不属于清单要求的类别')
        source(root,family,aid)  # Validate the live output; do not copy ZIPs or pictures.
        previous=entry.get('selected')
        entry['asset_ref']=dict(asset=aid,family=family,selected_at=now())
        entry['selected']=None;entry['placement']=None;p['review']=None
        if previous and not any((i.get('selected') or {}).get('sha256')==previous['sha256']
                                for i in p['items']+p.get('archived_items',[])):
            obsolete_selection=name(previous['sha256'])
    elif action=='select':
        entry=item(p,data.get('item'));family=KINDS[entry['kind']][2];aid=name(data.get('asset'))
        options=available(root)
        if not any(a['family']==family and a['id']==aid and a['kind']==entry['kind'] for a in options):
            raise ValueError('素材不属于清单要求的类别')
        content,image,meta=source(root,family,aid);sha=digest(content)
        output=AssetRepository(root).scoped('.local/studio/projects/'+pid+'/selected','.local/studio/projects/'+pid)
        output.mkdir(exist_ok=True)
        stream=BytesIO();image.save(stream,format='PNG');raw=stream.getvalue()
        archive=output/(sha+'.zip');preview=output/(sha+'.png')
        if archive.exists() and archive.read_bytes()!=content: raise ValueError('快照冲突')
        archive.write_bytes(content);preview.write_bytes(raw)
        entry.pop('asset_ref',None)
        entry['selected']=dict(asset=aid,family=family,sha256=sha,image_sha256=digest(raw),
                               canvas_px=list(image.size),baseline_revision=p['baseline_revision'],
                               selected_at=now(),**meta)
        entry['placement']=None;p['review']=None
    elif action=='edit_item':
        entry=item(p,data.get('item'))
        entry['title']=text(data.get('title'),'素材名称',60)
        entry['description']=text(data.get('description',''),'需求描述',empty=True)
        p['review']=None
    elif action=='archive_item':
        entry=item(p,data.get('item'));p['items'].remove(entry)
        p.setdefault('archived_items',[]).append(entry);p['review']=None
    elif action=='delete_item':
        entry=item(p,data.get('item'));p['items'].remove(entry);p['review']=None
        # Selected previews/ZIPs are shared by content hash within one project.
        selected=entry.get('selected')
        if selected and not any((i.get('selected') or {}).get('sha256')==selected['sha256'] for i in p['items']+p.get('archived_items',[])):
            obsolete_selection=name(selected['sha256'])
    elif action=='restore_item':
        if len(p['items'])>=200: raise ValueError('项目清单最多200项')
        entry=next((i for i in p.get('archived_items',[]) if i['id']==data.get('item')),None)
        if not entry: raise ValueError('归档清单项不存在')
        p['archived_items'].remove(entry);p['items'].append(entry);p['review']=None
    elif action=='review':
        current = current_assets(root, p)
        if not current: raise ValueError('请先制作或选择素材')
        placements=data.get('placements',{})
        for entry in p['items']:
            if entry['id'] not in current: continue
            point=placements.get(entry['id'])
            if not isinstance(point,list) or len(point)!=3 or any(type(v) not in (int,float) or not math.isfinite(v) for v in point):
                raise ValueError('组合位置无效')
            if not (0<=point[0]<=1000 and 0<=point[1]<=640 and .03<=point[2]<=8): raise ValueError('组合位置或比例超出范围')
            entry['placement']=point
        p['review']=dict(at=now(),baseline_revision=p['baseline_revision'],checks={},
                         note=text(data.get('note',''),'验收备注',empty=True),
                         scope='composition_layout_only',engine_integration='not_tested')
    elif action not in ('create','baseline','add','select'): raise ValueError('项目操作无效')
    p['revision']+=1;p['updated_at']=now();atomic(folder(root,pid)/'project.json',p)
    if obsolete_selection:
        for suffix in ('.png','.zip'):
            (folder(root,pid)/'selected'/(obsolete_selection+suffix)).unlink(missing_ok=True)
    return p

def context(root,data):
    c=data.get('studio_context')
    if not c: return None
    if not isinstance(c,dict): raise ValueError('项目上下文无效')
    p=load(root,c.get('project'));entry=item(p,c.get('item'))
    if c.get('baseline_revision')!=p['baseline_revision']: raise ValueError('共同基准已变化，请刷新工作台')
    return dict(project=p['id'],item=entry['id'],baseline_revision=p['baseline_revision'],baseline=p['baseline'],title=entry['title'])

def inherit(root,c,route,data):
    if not c or data.get('resume'): return
    entry=item(load(root,c['project']),c['item'])
    expected={'/api/buildings/prepare':('building',),'/api/props/generate':('prop',),
              '/api/components/generate':('component',),'/api/tasks':('character',),
              '/api/terrain/generate':('ground','road','water'),
              '/api/terrain/transition':('transition','shore')}
    if entry['kind'] not in expected.get(route,()): raise ValueError('工作台与清单类型不一致，请从对应清单项进入')
    b=c['baseline'];style='。'.join(b[k] for k in ('style','palette','lighting') if b[k])
    spatial='\n'.join(b.get(k,'') for k in ('camera_rules','orientation_rules') if b.get(k))
    if spatial and route in ('/api/buildings/prepare','/api/props/generate'):
        style+='\n视角与朝向约定：'+spatial
    c['request_snapshot']={k:data.get(k) for k in ('title','description','appearance','projection','mode')}
    if route=='/api/buildings/prepare':
        if not b['style']: raise ValueError('请先在素材项目设置共同风格')
        data['appearance']=style
        if entry.get('description','').strip():
            data['appearance']+='\n本项具体需求（材质要求优先于共同风格的默认材质；形体以框线图为准）：'+entry['description'].strip()
    elif route in ('/api/props/generate','/api/components/generate','/api/terrain/generate') and data.get('mode','ai')=='ai':
        description=data.get('description','')
        data['description']=description+'\n项目共同风格：'+style if style else description
        if len(data['description'])>2000: raise ValueError('需求与项目风格合计超过2000字，请精简')
    if route=='/api/buildings/prepare' and len(data['appearance'])>2000:
        raise ValueError('项目共同风格超过2000字，请精简风格、配色或光照描述')
    if route=='/api/props/generate' and data.get('mode')=='ai':
        if b['view']=='top_down': raise ValueError('当前物件工作台尚不支持项目的正俯视生成，请导入合适素材')
        data['projection']=b['view']
    if route=='/api/terrain/generate':
        if entry['kind']=='road' and data.get('asset_type')=='material': raise ValueError('道路清单项需要道路套件')
        if entry['kind'] in ('ground','water') and data.get('asset_type')!='material': raise ValueError('此清单项需要独立材质')
        if b['view']=='isometric_2_1' and entry['kind']=='road': raise ValueError('当前道路工作台仅支持正俯视连接块，尚不支持项目的等距道路')
        if entry['kind'] in ('ground','water'):
            data['projection']='isometric_2_1' if b['view']=='isometric_2_1' else 'top_down'
            data['tile_size']=b['cell_px']//2 if b['view']=='isometric_2_1' else b['cell_px']


def production_plan(root,p,entry):
    """Resolve an explicit single-item generation without calling an image service."""
    kind=entry['kind'];b=p['baseline']
    try:
        if kind=='building' and not entry.get('template_id'): raise ValueError('需先选择或导入建筑线稿模板')
        if kind in ('transition','shore'): raise ValueError('需先选定两份来源素材，再在工作台制作')
        if kind=='character': raise ValueError('需先准备人物模型及动作')
        if not b['style']: raise ValueError('请先填写项目共同风格')
        description=text(entry.get('description',''),'素材需求')
        data=dict(mode='ai',title=entry['title'],description=description)
        if kind=='building':
            from building_templates import load as load_template
            _,meta=load_template(root,entry['template_id'])
            if meta['view'] not in (b['view'],'custom'): raise ValueError('模板视角与项目不一致')
            route='/api/buildings/prepare'
            data.update(workflow='line_drawing',template_id=entry['template_id'])
        elif kind=='prop':
            route='/api/props/generate'
            data.update(kind='custom',size=256,collision_usage='none')
        elif kind=='component': route='/api/components/generate'
        else:
            route='/api/terrain/generate'
            data.update(asset_type='terrain' if kind=='road' else 'material',
                        material_kind='water' if kind=='water' else 'generic',
                        tile_size=b['cell_px'],road_width=.5,finish='natural',projection='top_down')
        c=dict(project=p['id'],item=entry['id'],baseline_revision=p['baseline_revision'],baseline=b,title=entry['title'])
        inherit(root,c,route,data)
        if kind=='prop':
            from static_props import validate
            validate(data)
        elif kind not in ('component','building'):
            from terrain import validate
            validate(data)
        from terrain_images import configured
        if not configured(root): raise ValueError('请先配置图片服务')
        return dict(ready=True,route=route,data=data,context=c,
                    note='默认256px、自定义物件、无碰撞；可到工作台调整' if kind=='prop' else
                         '默认道路宽度50%、自然边缘' if kind=='road' else '使用项目基准与清单需求')
    except ValueError as exc:
        return dict(ready=False,reason=str(exc))


def record_task(root,c,route,result):
    if not c or route not in ROUTES: return
    task=result.get('id') or result.get('task_id') or result.get('task')
    if not isinstance(task,str): return
    name(task);p=load(root,c['project'])
    if any(t['family']==ROUTES[route] and t['id']==task for t in p['tasks']): return
    snapshot=AssetRepository(root).scoped('.local/studio/task-context/'+ROUTES[route]+'-'+task+'.json','.local/studio/task-context')
    atomic(snapshot,c)
    p['tasks'].append(dict(id=task,family=ROUTES[route],context=c,created_at=now()))
    p['revision']+=1;p['updated_at']=now();atomic(folder(root,p['id'])/'project.json',p)

def task_state(root,p):
    result=[]
    for t in p['tasks']:
        family=t['family']
        path=(Path(root)/'.local/panel/tasks'/(t['id']+'.json') if family=='character' else
              Path(root)/'terrain-transitions'/t['id']/'manifest.json' if family=='transitions' else
              Path(root)/'.local'/family/'jobs'/t['id']/'job.json')
        j=read(path,{})
        if family=='transitions' and j.get('id')==t['id']:
            j=dict(j,status='complete',stage='过渡套件已完成',kit_id=t['id'])
        result.append(dict(**t,status=j.get('status','missing'),stage=j.get('stage',j.get('action','')),
                           error=j.get('error'),kit=j.get('kit_id',j.get('kit')),character=j.get('character')))
    return result
