"""Small scene-module workspace. PNG bytes are immutable, scene edits revisioned."""
import base64
from hashlib import sha256
from io import BytesIO
import json
import math
from pathlib import Path
import secrets
import zipfile
from PIL import Image
from asset_repository import atomic, name, read
from sprite_contract import number, point, polygons, title, settings

SCHEMA = 'studio.module-scene/1'


def directory(root):
    path = Path(root)/'.local/module-scenes'
    path.mkdir(parents=True, exist_ok=True)
    return path


def load(root, identity):
    scene = read(directory(root)/(name(identity)+'.json'))
    if not scene: raise ValueError('场景不存在')
    packages={}
    for module in scene['modules']:
        module.setdefault('world_scale',1)
        module.setdefault('layer','objects')
        if module.get('source'):
            source=module['source'];key=(source['family'],source['id'],source.get('sha256'))
            if key not in packages:packages[key]=source_package(root,source)
            raw,manifest=packages[key]
            config=source_config(manifest,module['source'],root)
            if 'assembly_ports' in config:module.setdefault('assembly_ports',config['assembly_ports'])
            if any(module.get(k)!=v for k,v in config.items()):raise ValueError('场景素材设置与引用版本不一致')
            with zipfile.ZipFile(BytesIO(raw)) as archive: digest=sha256(archive.read(source_image(manifest,module['source']))).hexdigest()
            if module['image']!=digest+'.png':raise ValueError('场景图片与素材版本不一致')
    return scene


def state(root, identity=None):
    scenes = [dict(id=s['id'], title=s['title'], revision=s['revision'],
                   images=list(dict.fromkeys(m['image'] for m in s.get('modules', [])))[:4],
                   material_count=len(s.get('modules', [])),instance_count=len(s.get('instances', [])))
              for p in sorted(directory(root).glob('*.json')) if (s := read(p))]
    return dict(scenes=scenes, selected=load(root, identity) if identity else None)


def transition_tile(manifest,source):
    corners=source.get('corners',0);variant=source.get('variant',0)
    if type(corners) is not int or type(variant) is not int:
        raise ValueError('过渡块角点和变化组须为整数')
    tile=next((t for t in manifest.get('projection_spec',{}).get('tiles',[])
               if t['corners']==corners and t['variant']==variant),None)
    if not tile:raise ValueError('过渡块角点或变化组不存在')
    return tile


def source_image(manifest,source):
    if source['family']=='transition':return transition_tile(manifest,source)['image']
    if source['family']=='terrain':return manifest['projection_spec']['variants'][0]['image']
    return 'sprite.png'


def source_config(manifest,source,root=None):
    if source['family'] in ('terrain','transition'):
        variant=transition_tile(manifest,source) if source['family']=='transition' else manifest['projection_spec']['variants'][0]
        return dict(title=manifest['title'],anchor=variant['anchor_px'],
                    behavior=variant.get('behavior','passable'),polygons=variant.get('polygons',[]),
                    world_scale=1,layer='ground')
    if source['family']=='character':
        return {**{k:manifest[k] for k in ('title','anchor','behavior','polygons','world_scale','layer')},
                'character_scene':'characters/'+manifest['id']+'/'+manifest['entry_scene'],
                'character_id':manifest['character']}
    from static_props import module_settings
    extra={}
    for key in ('assembly_ports','occlusion_slices'):
        if manifest.get(key):extra[key]=manifest[key]
    if root is not None and manifest.get('courtyard_part'):
        from courtyard_expand import connection_ports
        checks=read(Path(root)/'prop-kits'/manifest['id']/'expansion-checks.json')
        extra['assembly_ports']=connection_ports(manifest['courtyard_part'],checks,manifest['provenance']['source_sha256'])
    return dict(module_settings(manifest),layer='objects',**extra,
                **({'wall_connectors':manifest['wall_connectors']} if manifest.get('wall_connectors') else {}),
                **({'corner_ports':manifest['corner_ports']} if manifest.get('corner_ports') else {}))


def source_package(root, source):
    family=source.get('family');identity=name(source.get('id'))
    if family=='terrain':
        from terrain_integrity import require
        require(root,'terrain-kits',identity)
        path=Path(root)/'terrain-kits'/identity
        manifest=read(path/'manifest.json')
        if manifest.get('view')!='isometric_2_1' or not manifest.get('projection_spec',{}).get('variants'):
            raise ValueError('地面需要已交付的2:1等距瓦片')
    elif family=='transition':
        from terrain_integrity import require
        require(root,'terrain-transitions',identity)
        path=Path(root)/'terrain-transitions'/identity
        manifest=read(path/'manifest.json')
        transition_tile(manifest,source)
    elif family=='character':
        from scene_characters import load as load_character,directory as character_directory
        manifest=load_character(root,identity);path=character_directory(root)/identity
    elif family=='prop':
        from static_props import load_package
        manifest=load_package(root,identity);path=Path(root)/'prop-kits'/identity
    else:raise ValueError('MVP目前支持独立物件和等距地面素材')
    raw=(path/'kit.zip').read_bytes()
    if source.get('sha256') and sha256(raw).hexdigest()!=source['sha256']:raise ValueError('引用的素材版本指纹不一致')
    return raw,manifest


def pin(root, scene, manifest, module_id=None, family='prop',selectors=None):
    old=next((m for m in scene['modules'] if m['id']==module_id),None)
    if module_id and not old:raise ValueError('替换的模块不存在')
    if not old and len(scene['modules'])>=100:raise ValueError('最多100个模块')
    path=Path(root)/({'terrain':'terrain-kits','transition':'terrain-transitions','character':'.local/scene-characters'}.get(family,'prop-kits'))/manifest['id']
    raw=(path/'kit.zip').read_bytes()
    source=dict(family=family,id=manifest['id'],sha256=sha256(raw).hexdigest())
    if family=='transition':source.update(corners=(selectors or {}).get('corners',0),variant=(selectors or {}).get('variant',0))
    _,verified=source_package(root,source)
    with zipfile.ZipFile(BytesIO(raw)) as archive:image=archive.read(source_image(verified,source))
    digest=sha256(image).hexdigest();images=directory(root)/'images';images.mkdir(exist_ok=True)
    (images/(digest+'.png')).write_bytes(image)
    module=dict(id=module_id or secrets.token_hex(8),source=source,image=digest+'.png',
                canvas_px=list(Image.open(BytesIO(image)).size),version=(old['version']+1 if old else 1),**source_config(verified,source,root))
    if old:scene['modules'][scene['modules'].index(old)]=module
    else:scene['modules'].append(module)
    return module


def library(root):
    from static_props import catalog
    props=[dict(family='prop',id=m['id'],title=m['title'],view=m['view'],canvas_px=m['canvas_px'],
                 parent=m.get('provenance',{}).get('parent_kit'),image='/prop-asset/'+m['id']+'/sprite.png',
                 href='/props.html?kit='+m['id'])
            for m in catalog(root)['kits'] if m.get('integrity',{}).get('passed')]
    terrain=[]
    for path in sorted((Path(root)/'terrain-kits').glob('*/manifest.json'),reverse=True):
        try:
            _,m=source_package(root,dict(family='terrain',id=path.parent.name))
            terrain.append(dict(family='terrain',id=m['id'],title=m['title'],view=m['view'],canvas_px=m['projection_spec']['cell_px'],
                image='/terrain-asset/'+m['id']+'/'+source_image(m,dict(family='terrain')),href='/terrain.html?kit='+m['id']))
        except (ValueError,KeyError,OSError):continue
    buildings=[]
    from building_pipeline import load_package as load_building
    for path in sorted((Path(root)/'building-kits').glob('*/manifest.json'),reverse=True):
        try:
            m=load_building(root,path.parent.name)
            buildings.append(dict(family='building',id=m['id'],title=m['title'],view='isometric_2_1',canvas_px=[512,512],
                image='/building-asset/'+m['id']+'/sprite.png',href='/buildings.html?kit='+m['id']))
        except (ValueError,KeyError,OSError):continue
    characters=[]
    from action_set import inspect as inspect_character
    from asset_repository import AssetRepository
    for c in AssetRepository(root).catalog():
        if inspect_character(root,c['id']).get('complete'):
            characters.append(dict(family='character',id=c['id'],title=c['display_name'],
                view='isometric_2_1',canvas_px=[120,120],image=None,
                href='/characters.html?character='+c['id']))
    return props+terrain+buildings+characters


def change(root, data):
    action=data.get('action')
    if action=='create':
        identity=secrets.token_hex(8)
        scene=dict(schema=SCHEMA,id=identity,title=title(data.get('title')),revision=0,
                   projection='isometric_2_1',grid_px=[128,64],modules=[],instances=[],spawn=[0,150])
    else:
        scene=load(root,data.get('scene'))
        if type(data.get('revision')) is not int or data['revision']!=scene['revision']:
            raise ValueError('场景已更新，请刷新后重试')
    if action=='import':
        if len(scene['modules'])>=100: raise ValueError('最多100个模块')
        from static_props import import_exact
        manifest=import_exact(root,dict(data,projection=scene['projection']))
        pin(root,scene,manifest)
    elif action=='adopt':
        family=data.get('family','prop')
        if family=='building':
            from static_props import from_building
            manifest=from_building(root,dict(kit=data.get('kit'),projection=scene['projection']))
            family='prop'
        elif family=='character':
            from scene_characters import snapshot
            manifest=snapshot(root,name(data.get('kit')),data.get('world_scale',.65))
        else:manifest=None
        selectors={k:data.get(k,0) for k in ('corners','variant')} if family=='transition' else {}
        _,manifest=source_package(root,dict(family=family,id=manifest['id'] if manifest else name(data.get('kit')),**selectors))
        if manifest.get('view')!=scene['projection']:raise ValueError('素材投影与场景不一致；请选择同一视角的物件')
        existing=next((m for m in scene['modules'] if m.get('source',{}).get('id')==manifest['id'] and m.get('source',{}).get('family')==family and all(m['source'].get(k)==v for k,v in selectors.items())),None)
        if existing and not data.get('module'):return scene
        pin(root,scene,manifest,data.get('module'),family,selectors)
    elif action=='module':
        config=settings(data)
        module=next((m for m in scene['modules'] if m['id']==data.get('module')),None)
        if not module:raise ValueError('模块不存在')
        if module.get('source',{}).get('family')=='character':raise ValueError('人物引用固定版本的动作包，请在人物工作台制作版本后重新采用')
        if module.get('source',{}).get('family') in ('terrain','transition'):raise ValueError('地面使用素材包的固定地格设置，请在地面工作台调整')
        from static_props import annotate,import_exact
        if not module.get('source'):
            # Promote legacy scene-local PNGs once; future edits use the library.
            manifest=import_exact(root,dict(title=module['title'],image=base64.b64encode(image_bytes(root,module['image'])).decode(),projection=scene['projection']))
            source_id=manifest['id']
        else:source_id=module['source']['id']
        manifest=annotate(root,dict(config,source_kit=source_id))
        pin(root,scene,manifest,module['id'])
    elif action=='layout':
        values=data.get('instances')
        if not isinstance(values,list) or len(values)>2000: raise ValueError('场景最多2000个实例')
        ids=set();known={m['id'] for m in scene['modules']};instances=[]
        for v in values:
            identity=name(v.get('id'))
            if identity in ids or v.get('module') not in known: raise ValueError('实例重复或模块不存在')
            ids.add(identity)
            instances.append(dict(id=identity,module=v['module'],position=point(v.get('position'))))
        scene.update(instances=instances,spawn=point(data.get('spawn')))
    elif action!='create': raise ValueError('未知操作')
    scene['revision']+=1
    atomic(directory(root)/(scene['id']+'.json'),scene)
    return scene


def image_bytes(root, filename):
    if len(filename)!=68 or not filename.endswith('.png') or any(c not in '0123456789abcdef' for c in filename[:-4]):
        raise ValueError('图片名称无效')
    raw=(directory(root)/'images'/filename).read_bytes()
    if sha256(raw).hexdigest()!=filename[:-4]: raise ValueError('图片指纹不一致')
    return raw


def export(root, identity):
    scene=load(root,identity)
    output=BytesIO()
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('scene.json',json.dumps(scene,ensure_ascii=False,indent=2))
        for image in {m['image'] for m in scene['modules']}:
            z.writestr('images/'+image,image_bytes(root,image))
        sources={m['source']['id']:m['source'] for m in scene['modules'] if m.get('source')}
        for asset,source in sources.items():
            raw,manifest=source_package(root,source);z.writestr('assets/'+asset+'.zip',raw)
            if source['family']=='character':
                with zipfile.ZipFile(BytesIO(raw)) as wrapper:
                    original=wrapper.read('source.zip')
                z.writestr('assets/'+asset+'-actions.zip',original)
                with zipfile.ZipFile(BytesIO(original)) as package:
                    for filename in package.namelist():
                        if not filename.startswith('character_assets/'):continue
                        if '..' in Path(filename).parts:raise ValueError('人物包路径无效')
                        z.writestr('characters/'+asset+'/'+filename,package.read(filename))
        templates=Path(__file__).parent/'module_scene_runtime'
        for filename in ('project.godot','main.tscn','scene.gd'):
            z.writestr(filename,(templates/filename).read_bytes())
        z.writestr('README.txt','Studio 模块场景 MVP。Godot 4 打开 project.godot；WASD移动，C显示碰撞。\n图片为引用素材版本的原始PNG；坐标为屏幕像素、Y向下，锚点为图像像素，碰撞点相对锚点。\n普通素材脚底Y排序；带occlusion_slices的墙体按局部墙脚分段排序。测试角色半径8px，无导航或多层高度。\n素材编辑另存库版本并更新当前场景引用；其他场景保持原引用。交付包含引用素材原包与布局。\n')
    return output.getvalue()
