"""Fixed-size closed courtyard: generate once, partition without changing pixels."""
from pathlib import Path
from io import BytesIO
import hashlib
import json
import numpy as np
from PIL import Image,ImageDraw
from asset_repository import read,atomic
from build_courtyard_wall_templates import faces,project
from wall_strip import validated_source

LENGTH=384
ORIGIN=(512,300)
NODES=[('后角',(512,300)),('右后墙',(704,396)),('右角',(896,492)),('右前墙',(704,588)),
       ('前角',(512,684)),('左前墙',(320,588)),('左角',(128,492)),('左后墙',(320,396))]


def reference():
    image=Image.new('RGB',(1024,1024),'#ff00ff');draw=ImageDraw.Draw(image)
    for axis,origin in [('a',ORIGIN),('b',ORIGIN),('a',(128,492)),('b',(896,492))]:
        for face,color in zip(faces(axis,LENGTH),('#e7e0cf','#adb9bd','#c3ced0','#d2cbbb')):
            points=[(project(v)[0]+origin[0],project(v)[1]+origin[1]) for v in face]
            draw.polygon(points,fill=color);draw.line(points+[points[0]],fill='#354440',width=2)
    return image


def configure_job(folder,spec):
    reference().save(folder/'inputs/reference.png')
    spec.update(courtyard_ring_build=True,size=1024,asset_type='material',
        wall_reference_sha256=hashlib.sha256((folder/'inputs/reference.png').read_bytes()).hexdigest(),
        material_prompt=(
        'Create ONE complete CLOSED square courtyard perimeter wall sprite using Image 1 as the exact layout. '
        '1024x1024 unchanged canvas. Orthographic 2:1 game projection. Four equal straight walls, FOUR joined '
        'ninety-degree corners, a diamond-shaped empty courtyard hole in the middle. '
        'Ground corners exactly at (512,300), (896,492), (512,684), (128,492). '
        'Keep reference wall height, width, thickness and parallel roof lines. All walls share the same plaster '
        'and curved grey-green clay tiles, with continuous roof corners. Warm ivory plaster, soft eave shadows, '
        'fine dark outlines, restrained hand-painted weathering, clear tile volume. '
        'The near two walls occlude the bottom edge of the empty courtyard naturally. '
        'No building, house, separate roof covering the courtyard, gate, doors, windows, pillars, trees, people, '
        'floor, ground, cast shadow, extra partitions, extra branches, text or border. '
        'Pure flat RGB(255,0,255) outside AND inside the courtyard. The middle must be an empty magenta hole, '
        'not a ground surface. Keep the entire wall ring inside the canvas. Art direction: '+spec['description']))


def partition(source):
    pixels=np.asarray(source.convert('RGBA'));visible=pixels[:,:,3]>0
    if visible[450,512]:raise ValueError('院心被填满，未生成空院墙环')
    mask=Image.fromarray(np.where(visible,255,0).astype(np.uint8)).copy()
    ImageDraw.floodfill(mask,(512,450),128)
    hole=np.asarray(mask)==128
    if hole[0].any() or hole[-1].any() or hole[:,0].any() or hole[:,-1].any():
        raise ValueError('院墙未闭合，院心与外部连通；未发布')
    if hole.sum()<12000:raise ValueError('院墙内空区域过小，未通过闭合院墙检查')
    # Voronoi partition near the projected wall mid-height. This is a fixed-size
    # reconstruction kit, not a promise that its pieces can repeat independently.
    yy,xx=np.indices(visible.shape,dtype=float)
    distances=np.stack([((xx-x)/2)**2+(yy+54-y)**2 for _,(x,y) in NODES])
    labels=distances.argmin(0);parts=[];rebuilt=np.zeros_like(pixels);counts=np.zeros(visible.shape,dtype=int)
    for index,(title,foot) in enumerate(NODES):
        owned=visible&(labels==index)
        if owned.sum()<100:raise ValueError('院墙区域缺失：'+title)
        region=np.zeros_like(pixels);region[owned]=pixels[owned]
        offset=(foot[0]-384,foot[1]-400)
        sprite=Image.new('RGBA',(768,768));sprite.paste(Image.fromarray(region),(-offset[0],-offset[1]))
        restored=Image.new('RGBA',source.size);restored.paste(sprite,offset)
        if not np.array_equal(np.asarray(restored),region):raise ValueError('院墙切片超出画布：'+title)
        rebuilt[owned]=np.asarray(restored)[owned];counts+=owned
        parts.append(dict(title=title,sprite=sprite,foot=list(foot),offset=list(offset)))
    if not np.array_equal(rebuilt,pixels) or counts[visible].min()!=1 or counts.max()!=1:
        raise ValueError('院墙切片未能逐像素重建原图')
    return parts,dict(recipe='studio.courtyard-ring/1',closed=True,interior_transparent_pixels=int(hole.sum()),
        reconstruction_pixel_errors=0,overlapping_pixels=0,
        scope='fixed-size ring reconstruction only; not independent repeats, physics, gate or occlusion certification',
        parts=[{k:v for k,v in part.items() if k!='sprite'} for part in parts])


def build_fixed_job(root,folder,spec):
    from static_props import _publish_annotation,load_package
    folder=Path(folder);source,digest=validated_source(folder)
    parts,checks=partition(source);atomic(folder/'ring-checks.json',checks)
    published=read(folder/'ring-published.json',{})
    all_parts=parts+[dict(title='完整院墙',sprite=source,foot=[512,684])]
    for index,part in enumerate(all_parts):
        key=str(index)
        if key in published:
            load_package(root,published[key]);continue
        stream=BytesIO();part['sprite'].save(stream,'PNG');whole=index==8
        files={'sprite.png':stream.getvalue(),'cutout.png':stream.getvalue(),
            'inputs/original.png':(folder/'inputs/ground.png').read_bytes(),
            'inputs/reference.png':(folder/'inputs/reference.png').read_bytes(),
            'generation.json':(folder/'generation.json').read_bytes(),
            'production.json':json.dumps(spec).encode(),'prompt.txt':spec['material_prompt'].encode(),
            'ring-checks.json':json.dumps(checks).encode()}
        manifest=dict(schema='studio.static-prop/0.1',asset_family='static_prop',asset_kind='custom',view='isometric_2_1',
            canvas_px=list(part['sprite'].size),image='sprite.png',
            provenance=dict(art_source='ai_courtyard_ring',source_sha256=digest,part=index),
            processing=dict(method='fixed_ring_pixel_partition',recipe=checks['recipe']),
            assembly_parts=[published[str(i)] for i in range(8)] if whole else [],
            limitations=[checks['scope']])
        manifest=_publish_annotation(root,files,manifest,dict(title=spec['title']+' · '+part['title'],
            anchor=[512,684] if whole else [384,400],world_scale=1,behavior='passable',polygons=[]))
        published[key]=manifest['id'];atomic(folder/'ring-published.json',published)
    source.save(folder/'ring-preview.png')
    return load_package(root,published['8'])


def build_job(root,folder,spec):
    from courtyard_expand import build_job as expand
    return expand(root,folder,spec)


def reuse_source(root,folder,spec,identity):
    """Explicitly reprocess a verified Studio ring source without another AI call."""
    import shutil
    from asset_repository import AssetRepository,name
    old=AssetRepository(root).scoped('.local/props/jobs/'+name(identity),'.local/props/jobs')
    prior=read(old/'job.json',{}).get('spec',{})
    if not prior.get('courtyard_ring_build'):raise ValueError('只能复用 Studio 院墙来源任务')
    validated_source(old)
    if (folder/'inputs/reference.png').read_bytes()!=(old/'inputs/reference.png').read_bytes():raise ValueError('院墙参考已变化，不能复用旧图')
    shutil.copyfile(old/'inputs/ground.png',folder/'inputs/ground.png')
    shutil.copyfile(old/'generation.json',folder/'generation.json')
    spec['courtyard_source_job']=identity


def create_validation_scene(root,folder):
    """Explicit validation action; reuse the saved scene without overwriting edits."""
    import scene_modules as scenes
    from task_lock import task_lock
    folder=Path(folder)
    if (folder/'expansion-published.json').is_file():
        from courtyard_expand import create_scenes
        return create_scenes(root,folder)[3]
    with task_lock(root):
        receipt=read(folder/'ring-scene.json',{})
        if receipt:return scenes.load(root,receipt['scene'])
        ids=read(folder/'ring-published.json',{})
        if set(ids)!=set(map(str,range(9))):raise ValueError('院墙尚未完成，不能创建验证场景')
        checks=read(folder/'ring-checks.json')
        scene=scenes.change(root,dict(action='create',title='四合院 · 新院墙闭合验证'))
        instances=[]
        for index,part in enumerate(checks['parts']):
            scene=scenes.change(root,dict(action='adopt',scene=scene['id'],revision=scene['revision'],kit=ids[str(index)]))
            instances.append(dict(id='ring-'+str(index),module=scene['modules'][-1]['id'],
                position=[part['foot'][0]-ORIGIN[0],part['foot'][1]-ORIGIN[1]]))
        scene=scenes.change(root,dict(action='layout',scene=scene['id'],revision=scene['revision'],instances=instances,spawn=[0,192]))
        atomic(folder/'ring-scene.json',dict(scene=scene['id']))
        return scene
