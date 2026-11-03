"""One generated L wall, split into a corner and two unchanged repeat arms."""
from pathlib import Path
from io import BytesIO
import hashlib
import json
import numpy as np
from PIL import Image,ImageDraw
from asset_repository import read,atomic
from build_courtyard_wall_templates import faces,project
from wall_strip import validated_source
from wall_seam import select,cut

ORIGIN=(512,360)
ARM_LENGTH=352


def reference():
    image=Image.new('RGB',(1024,1024),'#ff00ff');draw=ImageDraw.Draw(image)
    for axis in ('a','b'):
        for face,color in zip(faces(axis,ARM_LENGTH),('#e7e0cf','#adb9bd','#c3ced0','#d2cbbb')):
            pts=[(project(v)[0]+ORIGIN[0],project(v)[1]+ORIGIN[1]) for v in face]
            draw.polygon(pts,fill=color);draw.line(pts+[pts[0]],fill='#354440',width=2)
    return image


def configure_job(folder,spec):
    reference().save(folder/'inputs/reference.png')
    spec.update(wall_corner_build=True,size=1024,asset_type='material',
        wall_reference_sha256=hashlib.sha256((folder/'inputs/reference.png').read_bytes()).hexdigest(),material_prompt=(
        'Create ONE connected L-shaped courtyard wall game sprite, using Image 1 as the exact structure. '
        '1024x1024 canvas unchanged. Orthographic 2:1 projection: a single corner at (512,360), '
        'two equal long straight arms extending down-right and down-left with slopes +0.5 and -0.5. '
        'The two walls meet at a ninety-degree ground-plane corner, with one continuous correctly joined tiled roof. '
        'Keep reference position, wall thickness and height. No third arm, gate, columns, detached parts or perspective convergence. '
        'Hand-painted game illustration: warm ivory plaster, grey-green curved clay tiles, fine dark outlines, '
        'restrained weathering, soft eave shadow. Consistent tile size and plaster value along each arm. '
        'Do not add pillars or cross-lines in the middle of the arms; the arms will be cut into repeat modules. '
        'Flat solid RGB(255,0,255) background touching every canvas edge. No ground, cast shadow, text, border or labels. '
        'Art direction: '+spec['description']))


def partition(source):
    results={axis:select(source,ORIGIN,axis,stop=ARM_LENGTH-16) for axis in ('a','b')}
    for axis,r in results.items():
        if not r['passed']:
            c=r['selected']
            raise ValueError('%s轴未找到可重复接口：瓦顶 %.1f/18，墙面 %.1f/10，轮廓 %.0f/1px；未发布转角套件。'%(axis.upper(),c['roof_mae'],c['wall_mae'],c['outline_shift']))
    pixels=np.asarray(source);yy,xx=np.indices(pixels.shape[:2],dtype=float)
    owned=pixels[:,:,3]>0;parts={};reports={}
    for axis,r in results.items():
        t=(xx-ORIGIN[0])*(1 if axis=='a' else -1);k=yy-ORIGIN[1]-.5*t
        boundary=np.interp(k,r['path_k'],r['selected']['path'])
        owned&=t<boundary
        sprites,_,report=cut(source,ORIGIN,axis,r)
        parts[axis]=sprites[0];reports[axis]=report
    corner=np.zeros_like(pixels);corner[owned]=pixels[owned]
    anchor=(384,400);offset=(ORIGIN[0]-anchor[0],ORIGIN[1]-anchor[1])
    sprite=Image.new('RGBA',(768,768));sprite.paste(Image.fromarray(corner),(-offset[0],-offset[1]))
    restored=Image.new('RGBA',source.size);restored.paste(sprite,offset)
    if not np.array_equal(np.asarray(restored),corner):raise ValueError('转角超出画布，未缩放原图')
    # Reconstruct all retained pixels in the original coordinate system.
    rebuilt=np.asarray(restored).copy();count=(rebuilt[:,:,3]>0).astype(int)
    for axis in ('a','b'):
        region=Image.new('RGBA',source.size);region.paste(parts[axis],reports[axis]['source_offsets_px'][0])
        p=np.asarray(region);visible=p[:,:,3]>0;count+=visible;rebuilt[visible]=p[visible]
    visible=count>0
    if count.max()>1 or not np.array_equal(rebuilt[visible],pixels[visible]):raise ValueError('转角接口像素分区验证失败')
    parts['corner']=sprite
    return parts,dict(recipe='studio.wall-corner/1',origin=list(ORIGIN),arms=results,
        cuts=reports,reconstruction_pixel_errors=0,overlapping_source_pixels=0)


def build_job(root,folder,spec):
    from static_props import _publish_annotation,load_package
    folder=Path(folder);source,digest=validated_source(folder)
    parts,report=partition(source);atomic(folder/'corner-checks.json',report)
    published=read(folder/'corner-published.json',{})
    for role in ('a','b','corner'):
        if role in published:
            load_package(root,published[role]);continue
        sprite=parts[role];stream=BytesIO();sprite.save(stream,'PNG')
        files={'sprite.png':stream.getvalue(),'cutout.png':stream.getvalue(),
            'inputs/original.png':(folder/'inputs/ground.png').read_bytes(),
            'inputs/reference.png':(folder/'inputs/reference.png').read_bytes(),
            'generation.json':(folder/'generation.json').read_bytes(),
            'production.json':json.dumps(spec).encode(),'prompt.txt':spec['material_prompt'].encode(),
            'corner-checks.json':json.dumps(report).encode()}
        manifest=dict(schema='studio.static-prop/0.1',asset_family='static_prop',asset_kind='custom',view='isometric_2_1',
            canvas_px=list(sprite.size),image='sprite.png',
            provenance=dict(art_source='ai_corner_wall_slice',source_sha256=digest,role=role),
            processing=dict(method='shared_source_corner_partition',recipe=report['recipe']),
            limitations=['Experimental: collision, occlusion and additional corner orientations are untested.'])
        if role!='corner':
            step=report['cuts'][role]['repeat_offset_px']
            manifest['wall_connectors']=dict(schema='studio.wall-connectors/1',axis=role,start=[0,0],end=step,repeat_offset_px=step)
        else:
            manifest['corner_ports']={axis:[(1 if axis=='a' else -1)*report['cuts'][axis]['start'],report['cuts'][axis]['start']//2] for axis in ('a','b')}
        config=dict(title=spec['title']+' · '+('转角' if role=='corner' else role.upper()+'轴直墙'),
            anchor=[384,400] if role=='corner' else [256,280],world_scale=1,behavior='passable',polygons=[])
        manifest=_publish_annotation(root,files,manifest,config)
        published[role]=manifest['id'];atomic(folder/'corner-published.json',published)
    return load_package(root,published['corner'])
