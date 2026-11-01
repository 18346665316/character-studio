"""Fence geometry and timber appearance compiler; no gameplay implementation.

Coordinate contract: 64px ground cell, top-left origin, y down. Suggested
collision is independent of the transparent 64x96 visual canvas.
"""
import argparse
import base64
from datetime import datetime
import hashlib
import json
from pathlib import Path
import secrets
import zipfile

from PIL import Image, ImageDraw

from asset_repository import AssetRepository, atomic, name, read
from task_lock import task_lock

CELL=64
THICKNESS=6
DIRECTIONS={'north':(1,(32,0),(0,-1)),'east':(2,(64,32),(1,0)),
            'south':(4,(32,64),(0,1)),'west':(8,(0,32),(-1,0))}
MODULES={'post':0,'end_n':1,'end_e':2,'end_s':4,'end_w':8,
         'straight_ns':5,'straight_ew':10,'corner_ne':3,'corner_es':6,
         'corner_sw':12,'corner_wn':9,'opening_ew':10}


def rectangle(x,y,width,height):
    return [[x,y],[x+width,y],[x+width,y+height],[x,y+height]]


def module_record(identity,bits):
    if identity=='opening_ew':
        polygons=[rectangle(0,29,20,6),rectangle(44,29,20,6)]
        passages=[{'id':'opening','polygon':rectangle(20,16,24,32),
                   'clear_width_px':24,'axis':'north_south','state':'permanently_open'}]
    else:
        polygons=[rectangle(29,29,6,6)]
        for direction,(bit,_,_) in DIRECTIONS.items():
            if bits&bit:
                polygons.append({'north':rectangle(29,0,6,32),'east':rectangle(32,29,32,6),
                                 'south':rectangle(29,32,6,32),'west':rectangle(0,29,32,6)}[direction])
        passages=[]
    return {'id':identity,'image':f'tiles/{identity}.png','ground_cell_px':[64,64],
            'canvas_px':[64,96],'ground_origin_px':[0,32],'anchor_px':[32,64],
            'connections':[{'direction':direction,'position_px':list(point),'normal':list(normal),
                            'width_px':THICKNESS} for direction,(bit,point,normal) in DIRECTIONS.items() if bits&bit],
            'suggested_collision':{'enabled_by_default':False,'coordinate_space':'ground_cell_px',
                                   'polygons':polygons,'purpose':'ground_blocker'},
            'passages':passages,
            'occlusion':{'sort_anchor_px':[32,64],'status':'pending_art_review',
                         'note':'纵向构件的角色遮挡须待正式外观单独验收，当前未宣称Y排序已解决。'}}


def fixture_image(record):
    """Simple raised rails, explicitly a geometry fixture rather than wood art."""
    image=Image.new('RGBA',(64,96),(0,0,0,0));draw=ImageDraw.Draw(image)
    if record['id']=='opening_ew':
        segments=[((0,32),(20,32)),((44,32),(64,32))];posts=[(17,32),(47,32)]
    else:
        posts=[(32,32)]
        segments=[((32,32),tuple(connection['position_px'])) for connection in record['connections']]
    for start,end in segments:
        for lift,color in [(8,(84,112,132,255)),(20,(108,144,169,255))]:
            a=(start[0],start[1]+32-lift);b=(end[0],end[1]+32-lift)
            draw.line([a,b],fill=color,width=4)
    for x,y in posts:
        draw.rectangle([x-3,y+32-26,x+3,y+32],fill=(55,80,99,255))
        draw.rectangle([x-3,y+32-26,x+3,y+32-23],fill=(156,185,200,255))
    return image


def assembly_layout():
    result=[{'module':'corner_es','cell':[1,1]},{'module':'corner_sw','cell':[5,1]},
            {'module':'corner_ne','cell':[1,3]},{'module':'corner_wn','cell':[5,3]}]
    for x in range(2,5):
        result.extend([{'module':'opening_ew' if x==3 else 'straight_ew','cell':[x,1]},
                       {'module':'straight_ew','cell':[x,3]}])
    for x in (1,5):result.append({'module':'straight_ns','cell':[x,2]})
    return result


def validation_cases(modules):
    cases=[]
    def add(label,placements,start,motion,blocked,radius=4):
        cases.append(dict(id=label,placements=placements,start=start,motion=motion,
                          expect_blocked=blocked,radius_px=radius))
    for sign in (-1,1):
        add('ew_both_sides_'+str(sign),[['straight_ew',[0,0]]],[32,32+sign*24],[0,-sign*48],True)
        add('ns_both_sides_'+str(sign),[['straight_ns',[0,0]]],[32+sign*24,32],[-sign*48,0],True)
        add('opening_pass_'+str(sign),[['opening_ew',[0,0]]],[32,32+sign*24],[0,-sign*48],False)
    for x in (10,54):add('opening_posts_'+str(x),[['opening_ew',[0,0]]],[x,8],[0,48],True)
    add('opening_large_actor_blocked',[['opening_ew',[0,0]]],[32,8],[0,48],True,14)
    add('end_no_full_canvas_collision',[['end_n',[0,0]]],[8,48],[48,0],False)
    add('post_local_footprint',[['post',[0,0]]],[8,48],[48,0],False)
    # Probe every connected pair at its shared port, across the barrier.
    for a in modules:
        for b in modules:
            for direction,(_,point,normal) in DIRECTIONS.items():
                opposite={'north':'south','east':'west','south':'north','west':'east'}[direction]
                if not any(c['direction']==direction for c in a['connections']):continue
                if not any(c['direction']==opposite for c in b['connections']):continue
                offset=[normal[0]*64,normal[1]*64]
                start=[point[0]-24 if normal[1] else point[0],point[1]-24 if normal[0] else point[1]]
                motion=[48 if normal[1] else 0,48 if normal[0] else 0]
                add('joint_'+a['id']+'_'+direction+'_'+b['id'],[[a['id'],[0,0]],[b['id'],offset]],start,motion,True)
    return cases


def validate_geometry(modules):
    checks=[]
    for module in modules:
        if module['anchor_px']!=[module['ground_origin_px'][0]+32,module['ground_origin_px'][1]+32]:
            raise ValueError('落地锚点与地面原点不一致')
        for polygon in module['suggested_collision']['polygons']:
            if len(polygon)!=4 or not all(0<=x<=64 and 0<=y<=64 for x,y in polygon):
                raise ValueError('碰撞多边形超出地面单元')
            if not (polygon[1][0]>polygon[0][0] and polygon[2][1]>polygon[1][1]):
                raise ValueError('碰撞多边形面积无效')
        for port in module['connections']:
            if port['position_px']!=list(DIRECTIONS[port['direction']][1]): raise ValueError('接口位置不一致')
        checks.append({'module':module['id'],'passed':True,'scope':'anchor, polygon bounds and interface positions'})
    return checks


def load_package(root,identity):
    try:
        return _load_package(root,identity)
    except (OSError,KeyError,TypeError,zipfile.BadZipFile,UnicodeError) as error:
        raise ValueError('构件包缺失或损坏：'+str(error)) from None


def _load_package(root,identity):
    assets=AssetRepository(root)
    source=assets.scoped('component-kits/'+name(identity),'component-kits')
    archive=assets.scoped('component-kits/'+identity+'/kit.zip','component-kits/'+identity)
    manifest=read(source/'manifest.json')
    if not isinstance(manifest,dict) or manifest.get('schema')!='studio.connected-components/0.1': raise ValueError('无效连接构件清单')
    expected=manifest.get('files_sha256',{})
    required={'physics_cases.json','preview.png','atlas.png','INTEGRATION.md'}|{m['image'] for m in manifest['modules']}
    required.update(layer['image'] for module in manifest['modules'] for layer in module.get('visual_layers',[]))
    if manifest.get('material_source'):required.add(manifest['material_source']['image'])
    if not required.issubset(expected): raise ValueError('构件清单缺少必需资源指纹')
    with zipfile.ZipFile(archive) as bundle:
        names=bundle.namelist()
        if len(names)!=len(set(names)): raise ValueError('ZIP包含重复文件')
        if set(names)!=set(expected)|{'manifest.json'}: raise ValueError('ZIP资源清单不匹配')
        if json.loads(bundle.read('manifest.json'))!=manifest: raise ValueError('ZIP与磁盘清单不一致')
        content={}
        for relative,digest in expected.items():
            file=assets.scoped('component-kits/'+identity+'/'+relative,'component-kits/'+identity)
            raw=bundle.read(relative)
            if hashlib.sha256(raw).hexdigest()!=digest or file.read_bytes()!=raw: raise ValueError('构件文件指纹不一致：'+relative)
            content[relative]=raw
    return manifest,content


def catalog(root):
    result=[]
    for path in sorted((Path(root)/'component-kits').glob('*/manifest.json'),reverse=True):
        if path.parent.is_symlink():continue
        manifest=read(path)
        if not isinstance(manifest,dict):continue
        try:
            load_package(root,path.parent.name)
            manifest['integrity']={'passed':True,'errors':[]}
        except (ValueError,OSError,KeyError,zipfile.BadZipFile) as error:
            manifest['integrity']={'passed':False,'errors':[str(error)]}
        result.append(manifest)
    return result


def build(root,appearance="fixture",wood_image=None,source_job=None):
    if appearance not in ("fixture","timber"): raise ValueError("未知围栏外观模式")
    if wood_image and appearance!="timber": raise ValueError("木纹输入仅用于木围栏模式")
    assets=AssetRepository(root)
    with task_lock(root):
        identity=name(source_job.name) if source_job else datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+secrets.token_hex(4)
        if source_job and (Path(root)/'component-kits'/identity).exists():
            load_package(root,identity)
            return Path(root)/'component-kits'/identity
        folder=assets.scoped('.local/fence-builds/'+identity,'.local/fence-builds')
        if source_job and folder.exists():
            import shutil
            shutil.rmtree(folder)
        (folder/'tiles').mkdir(parents=True)
        modules=[module_record(identity,bits) for identity,bits in MODULES.items()]
        records={record['id']:record for record in modules}
        visuals={}
        art_source='procedural_geometry_fixture'
        if appearance=='timber':
            from fence_appearance import procedural_timber,render_timber
            if wood_image:
                from terrain import decode_image
                texture=wood_image.copy().convert('RGB') if isinstance(wood_image,Image.Image) else decode_image(base64.b64encode(Path(wood_image).read_bytes()).decode())
                art_source='external_wood_texture_program_geometry'
                if source_job: art_source='ai_wood_texture_program_geometry'
            else:
                texture=procedural_timber()
                art_source='procedural_wood_texture_program_geometry'
            (folder/'inputs').mkdir();texture.save(folder/'inputs/wood.png')
            texture.resize((256,256)).save(folder/'wood_material.png')
            (folder/'layers').mkdir()
            for record in modules:
                image,layers=render_timber(record,texture)
                visuals[record['id']]=(image,layers)
                record['visual_layers']=[]
                for depth,layer in layers:
                    relative=f"layers/{record['id']}_depth_{depth:02d}.png"
                    layer.save(folder/relative)
                    record['visual_layers'].append({'image':relative,'sort_position_px':[32,depth],
                        'image_offset_px':[-32,-32-depth],'coordinate_space':'ground_cell_px'})
                record['occlusion']={'strategy':'shared_parent_y_sort_ground_depth_slices',
                    'status':'pending_engine_check','art_review':'pending',
                    'note':'每个深度层必须作为公共Y排序节点的直接子项，图片左上角仍位于格子原点减ground_origin_px。'}
        else:
            visuals={record['id']:(fixture_image(record),[]) for record in modules}
        atlas=Image.new('RGBA',(64*6,96*2),(0,0,0,0))
        preview=Image.new('RGB',(6*128,2*160+60),(239,242,239));draw=ImageDraw.Draw(preview)
        draw.text((16,12),'TIMBER CANDIDATE / '+art_source if appearance=='timber' else 'GEOMETRY FIXTURE - NOT AI ART / COLLISION OVERLAY',fill=(35,51,64))
        for index,record in enumerate(modules):
            image=visuals[record['id']][0];image.save(folder/record['image'])
            record['atlas_cell']=[index%6,index//6]
            atlas.paste(image,(index%6*64,index//6*96))
            origin=(index%6*128+32,index//6*160+40)
            preview.paste(image,origin,image)
            for polygon in record['suggested_collision']['polygons']:
                projected=[(origin[0]+x,origin[1]+32+y) for x,y in polygon]
                draw.line(projected+[projected[0]],fill=(209,81,49),width=1)
            for passage in record['passages']:
                draw.rectangle([origin[0]+20,origin[1]+48,origin[0]+44,origin[1]+80],outline=(30,160,100),width=1)
            draw.text((origin[0]-22,origin[1]+102),record['id'],fill=(35,51,64))
        atlas.save(folder/'atlas.png');preview.save(folder/'preview.png')
        assembled=Image.new('RGB',(7*64,5*64+40),(225,231,224))
        for placement in sorted(assembly_layout(),key=lambda p:(p['cell'][1],p['cell'][0])):
            image=visuals[placement['module']][0]
            assembled.paste(image,(placement['cell'][0]*64,placement['cell'][1]*64-32+40),image)
        ImageDraw.Draw(assembled).text((12,10),'GEOMETRY FIXTURE / FIXED ASSEMBLY',fill=(35,51,64))
        if appearance=='timber':
            from fence_appearance import compose_layered
            assembled=compose_layered(visuals,assembly_layout())
            ImageDraw.Draw(assembled).text((12,10),'TIMBER CANDIDATE / FIXED ASSEMBLY',fill=(35,51,64))
        assembled.save(folder/'assembly.png')
        overlay=assembled.copy();draw_overlay=ImageDraw.Draw(overlay)
        for placement in assembly_layout():
            x,y=placement['cell']
            for polygon in records[placement['module']]['suggested_collision']['polygons']:
                points=[(x*64+px,y*64+py+40) for px,py in polygon]
                draw_overlay.line(points+[points[0]],fill=(213,65,36),width=2)
        overlay.save(folder/'assembly_collision.png')
        manifest={'schema':'studio.connected-components/0.1','id':identity,
                  'title':'木围栏外观候选' if appearance=='timber' else '围栏连接与碰撞几何原型','asset_family':'connected_component',
                  'asset_role':'fence_kit_candidate' if appearance=='timber' else 'fence_geometry_fixture','production_ready':False,
                  'art_source':art_source,'ai_calls':0,'view':'orthographic_three_quarter',
                  'coordinate_system':{'units':'pixels','origin':'ground_cell_top_left','x':'right','y':'down'},
                  'modules':modules,'atlas_cell_px':[64,96],
                  'fixed_assembly':assembly_layout(),
                  'validation':{'geometry':validate_geometry(modules),'engine_physics':'pending','art':'pending','occlusion':'pending'},
                  'physics':{'suggestions_only':True,'enabled_by_default':False,
                             'layers_and_masks':'caller_defined','recommended_actor_radius_px':4},
                  'limitations':['木纹来源和程序构件记录在art_source；美术尚未验收' if appearance=='timber' else '程序几何样例，不是正式木围栏美术','门洞为永久开口，不包含门扇与开关逻辑',
                                 '没有T形或十字模块','角色遮挡需正式外观后另行验收']}
        if appearance=='timber':
            manifest['material_source']={'image':'inputs/wood.png','sha256':hashlib.sha256((folder/'inputs/wood.png').read_bytes()).hexdigest(),'role':'surface_grain_only'}
        if source_job:
            import shutil
            receipt=read(source_job/'generation.json')
            atomic(folder/'generation.json',receipt)
            atomic(folder/'production.json',read(source_job/'job.json')['spec'])
            if (source_job/'inputs/reference.png').is_file():
                shutil.copyfile(source_job/'inputs/reference.png',folder/'inputs/reference.png')
            manifest.pop('ai_calls',None)
            manifest['generation_receipt']='generation.json'
            manifest['source_job']=identity
        atomic(folder/'manifest.json',manifest)
        atomic(folder/'physics_cases.json',{'actor_shape':'CircleShape2D','default_radius_px':4,
                                           'cases':validation_cases(modules)})
        (folder/'INTEGRATION.md').write_text('# 围栏几何原型（非正式美术）\n\n'
            '图像左上角放在地面格子原点减ground_origin_px；anchor_px为图像中的落地排序锚点。'
            '碰撞多边形使用地面格子坐标，不是图像坐标；接入可选择完全不创建阻挡。'
            '碰撞层和掩码由游戏定义。门洞是永久开口，不包含门扇、导航或交互。'
            '未提供完成的遮挡方案，不自动用整张图片透明轮廓生成碰撞。\n\n'
            'physics_cases.json为独立引擎验收用例，不是游戏逻辑。engine_physics为pending直到外部验收，'
            '不修改已发布包来伪造通过状态。\n',encoding='utf-8')
        if appearance=='timber':
            with (folder/'INTEGRATION.md').open('a',encoding='utf-8') as output:
                output.write('\n## 木围栏外观与深度层\n\n本包为外观候选，非正式验收美术。art_source明确标记AI木纹、程序木纹或外部木纹；程序生成构件几何，不宣称AI直接生成整套围栏。\n'
                    'visual_layers须与角色落脚节点一起作为公共y_sort_enabled父节点的直接子项；不能把整个纵向构件当作单一排序精灵。'
                    '每层节点position为格子原点加sort_position_px；Sprite2D.centered=false，offset=image_offset_px。'
                    '组合预览全局按地面深度排序。建议碰撞仍独立放在地面坐标，且默认不启用。\n')
        manifest['files_sha256']={str(p.relative_to(folder)):hashlib.sha256(p.read_bytes()).hexdigest()
                                  for p in folder.rglob('*') if p.is_file() and p.name!='manifest.json'}
        atomic(folder/'manifest.json',manifest)
        with zipfile.ZipFile(folder/'kit.zip','w',zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(folder.rglob('*')):
                if path.is_file() and path.name!='kit.zip':archive.write(path,str(path.relative_to(folder)))
        target=assets.scoped('component-kits/'+identity,'component-kits')
        target.parent.mkdir(parents=True,exist_ok=True);folder.rename(target)
        return target


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--appearance',choices=['fixture','timber'],default='fixture')
    parser.add_argument('--wood-image',type=Path)
    args=parser.parse_args()
    print(build(Path(__file__).resolve().parent.parent,args.appearance,args.wood_image))
