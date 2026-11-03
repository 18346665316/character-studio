"""Cut unchanged pixels from a single painted wall using shared cross-sections."""
from pathlib import Path
import hashlib
import json
from io import BytesIO
import numpy as np
from PIL import Image,ImageDraw
from build_courtyard_wall_templates import LENGTH, ANCHOR, CANVAS, render

SOURCE_CANVAS = (1024,1024)
SOURCE_ORIGIN = (160,400)


def source_origin(axis):
    if axis not in ('a','b'):raise ValueError('Unknown wall axis')
    return SOURCE_ORIGIN if axis=='a' else (864,400)


def reference(axis='a'):
    return render(axis,LENGTH*5,source_origin(axis),SOURCE_CANVAS)


def prompt(style,axis='a'):
    return (
        'Create one intact hand-painted 2D game sprite of the LONG straight courtyard wall in Image 1. '
        'Paint the reference at exactly its existing position and scale on the unchanged 1024x1024 canvas. '+
        ('Orthographic 2:1 projection: the wall runs upper left to lower right at slope +0.5, verticals stay vertical. ' if axis=='a' else
         'Orthographic 2:1 projection: the wall runs upper right to lower left at slope -0.5, verticals stay vertical. ')+
        'This is ONE continuous wall FIVE standard spans long. Keep the entire middle uninterrupted: '
        'no pillars, dividing lines, joints, corner turns, gate, windows or breaks along its length. '
        'The two OUTERMOST ends may have normal finished end faces and roof terminations. '
        'The middle will be sliced into modules: keep wall height, plaster value, tile size, roof cross-section '
        'and lighting consistent along the whole length. Regular repeating curved grey-blue clay tiles and ridge tiles, '
        'a clean warm ivory plaster face, restrained fine hand-painted texture, soft eave shadow. '
        'Preserve a cohesive painted illustration with natural tile volume and delicate outlines. '
        'No broad left-to-right color gradient, random scratch marks or large isolated stains. '
        'Keep the reference geometry, no perspective convergence, thickened wall or roof enlargement. '
        'Pure flat #FF00FF background, no ground, cast shadow, border, text, labels, ruler, marks, '
        'collage, separate material samples or multiple objects. Art direction: '+style)


def slice_middle(source,origin=SOURCE_ORIGIN,start=LENGTH,count=3,length=LENGTH,axis='a'):
    """Partition roof and wall at common t planes. Half-open ownership, no blend."""
    if axis not in ('a','b'):raise ValueError('Unknown wall axis')
    if count<1 or length<1 or length%2 or start%2:raise ValueError('Cut distances must preserve integer 2:1 translations')
    rgba=source.convert('RGBA');pixels=np.asarray(rgba)
    yy,xx=np.indices((rgba.height,rgba.width),dtype=float)
    sx=xx-origin[0] if axis=='a' else origin[0]-xx
    sy=yy-origin[1]
    # On the visible wall q=8. On the pitched roof q varies from ridge 0
    # to eave 8, with z=108-q; k=screen_y-screen_x/2=2*q-108.
    q=np.clip((sy-.5*sx+108)/2,0,8)
    longitudinal=sx+q
    labels=np.floor((longitudinal-start)/length).astype(int)
    selected=(labels>=0)&(labels<count)&(pixels[:,:,3]>0)
    expected=np.zeros_like(pixels);expected[selected]=pixels[selected]
    restored=Image.new('RGBA',rgba.size)
    sprites=[];offsets=[]
    for index in range(count):
        t=start+index*length
        offset=(round(origin[0]+(t if axis=='a' else -t)-ANCHOR[0]),round(origin[1]+t/2-ANCHOR[1]))
        owned=(labels==index)&(pixels[:,:,3]>0)
        region=np.zeros_like(pixels);region[owned]=pixels[owned]
        image=Image.fromarray(region)
        sprite=Image.new('RGBA',CANVAS);sprite.paste(image,(-offset[0],-offset[1]))
        # Any visible source pixel lost outside the common output canvas is an
        # error, not permission to fit, resize or repair the generated artwork.
        restored_region=Image.new('RGBA',rgba.size);restored_region.paste(sprite,offset)
        if not np.array_equal(np.asarray(restored_region),region):raise ValueError('切片超出统一画布；未缩放或挪动原图')
        restored.alpha_composite(sprite,offset)
        sprites.append(sprite);offsets.append(list(offset))
    if not selected.any() or any(not s.getchannel('A').getbbox() for s in sprites):raise ValueError('中间墙段为空，未按参考位置生成')
    if not np.array_equal(np.asarray(restored),expected):raise ValueError('切片无法逐像素还原来源')
    return sprites,Image.fromarray(expected),dict(
        method='half_open_cross_section_pixel_partition',axis=axis,
        source_canvas_px=list(rgba.size),source_origin_px=list(origin),start=start,length=length,
        count=count,canvas_px=list(CANVAS),anchor_px=list(ANCHOR),source_offsets_px=offsets,
        repeat_offset_px=[length if axis=='a' else -length,length//2],
        reconstruction_pixel_errors=0,appearance='requires_visual_validation',
        processing='pixel_selection_and_integer_translation_only; no resize, repaint, blending or repair')


def board(sprites):
    image=Image.new('RGBA',(640,1050),'#e1e5dd')
    draw=ImageDraw.Draw(image)
    for row,indices in enumerate((range(3),(1,1,1),(2,0,1))):
        draw.text((30,12+row*320),('1 / original order','2 / repeat the SAME middle slice','3 / mixed order')[row],fill='#34443e')
        for column,index in enumerate(indices):
            image.alpha_composite(sprites[index],(110+column*128-ANCHOR[0],190+row*320+column*64-ANCHOR[1]))
    return image.convert('RGB')


def validated_source(folder):
    from asset_repository import read
    from wall_assets import whole_cutout
    folder=Path(folder);receipt=read(folder/'generation.json',{}).get('ground',{})
    original=folder/'inputs/ground.png';reference_file=folder/'inputs/reference.png'
    digest=hashlib.sha256(original.read_bytes()).hexdigest()
    if receipt.get('sha256')!=digest:raise ValueError('长墙原图与生成回执不一致')
    if receipt.get('reference_sha256',{}).get('reference.png')!=hashlib.sha256(reference_file.read_bytes()).hexdigest():
        raise ValueError('长墙参考图与生成回执不一致')
    with Image.open(original) as image:
        if image.size!=SOURCE_CANVAS:raise ValueError('长墙画布与参考不一致，未自动缩放')
        source=whole_cutout(image)
    return source,digest


def analyze(folder):
    from asset_repository import atomic
    folder=Path(folder);source,digest=validated_source(folder)
    sprites,expected,report=slice_middle(source)
    report['source_sha256']=digest
    source.save(folder/'source-cutout.png');expected.save(folder/'middle.png')
    for index,sprite in enumerate(sprites):sprite.save(folder/('slice-'+str(index)+'.png'))
    board(sprites).save(folder/'join-board.png');atomic(folder/'slice-checks.json',report)
    return sprites,report


def configure_job(folder,spec,axis):
    source_origin(axis)
    reference(axis).save(folder/'inputs/reference.png')
    spec.update(wall_axis=axis,wall_strip_build=True,size=512,asset_type='material',
                material_prompt=prompt(spec['description'],axis),
                wall_reference_sha256=hashlib.sha256((folder/'inputs/reference.png').read_bytes()).hexdigest())


def build_job(root,folder,spec):
    """Worker production path: select, gate, slice, then publish one repeat."""
    from asset_repository import atomic
    from static_props import _publish_annotation
    from wall_repeat import select
    folder=Path(folder);axis=spec['wall_axis'];origin=source_origin(axis)
    source,digest=validated_source(folder)
    try:
        search=select(source,origin,axis)
    except ValueError as error:
        search=dict(passed=False,error=str(error))
    if not search['passed']:
        from wall_seam import select as select_path
        straight=search
        search=select_path(source,origin,axis)
        search['straight_cut_result']=straight
    atomic(folder/'repeat-checks.json',search)
    if not search['passed']:
        c=search['selected']
        raise ValueError('长墙切割后边界差异仍过大（瓦顶 %.1f/18，墙面 %.1f/10，轮廓 %.0f/1px）；当前素材保留。'%(c['roof_mae'],c['wall_mae'],c['outline_shift']))
    selected=search['selected']
    if search['recipe']=='studio.wall-path/1':
        from wall_seam import cut as cut_path
        sprites,_,cut=cut_path(source,origin,axis,search)
    else:
        sprites,_,cut=slice_middle(source,origin=origin,start=selected['start'],count=1,length=selected['length'],axis=axis)
    sprite=sprites[0];sprite.save(folder/'wall-preview.png')
    stream=BytesIO();sprite.save(stream,'PNG')
    preview=Image.new('RGBA',(1024,640),'#e1e5dd')
    step=cut['repeat_offset_px']
    for index in range(3):
        x=200 if axis=='a' else 824
        preview.alpha_composite(sprite,(x+index*step[0]-ANCHOR[0],260+index*step[1]-ANCHOR[1]))
    preview_stream=BytesIO();preview.convert('RGB').save(preview_stream,'PNG')
    connectors=dict(schema='studio.wall-connectors/1',axis=axis,start=[0,0],end=cut['repeat_offset_px'],repeat_offset_px=cut['repeat_offset_px'])
    files={'sprite.png':stream.getvalue(),'cutout.png':stream.getvalue(),
        'inputs/original.png':(folder/'inputs/ground.png').read_bytes(),
        'inputs/reference.png':(folder/'inputs/reference.png').read_bytes(),
        'generation.json':(folder/'generation.json').read_bytes(),
        'repeat-checks.json':json.dumps(search).encode(),'slice.json':json.dumps(cut).encode(),
        'repeat-preview.png':preview_stream.getvalue(),
        'wall-connectors.json':json.dumps(connectors).encode(),
        'production.json':json.dumps(spec).encode(),'prompt.txt':spec['material_prompt'].encode()}
    manifest=dict(schema='studio.static-prop/0.1',asset_family='static_prop',asset_kind='custom',view='isometric_2_1',
        canvas_px=list(CANVAS),image='sprite.png',wall_connectors=connectors,
        provenance=dict(art_source='ai_long_wall_repeat',this_build='program_selected_unchanged_source_pixels',source_sha256=digest),
        processing=dict(method='automatic_wall_repeat',recipe=search['recipe'],boundary_checks=selected),
        limitations=['Boundary checks passed; collision, corners and occlusion are not validated.'])
    config=dict(title=spec['title'],anchor=list(ANCHOR),world_scale=1,behavior='passable',polygons=[])
    return _publish_annotation(root,files,manifest,config)


def publish_trial(root,folder,scene_id=None):
    """Publish the three unretouched samples in an optional comparison scene."""
    from asset_repository import read,atomic
    from static_props import _publish_annotation
    from task_lock import task_lock
    import scene_modules as scenes
    folder=Path(folder)
    with task_lock(root):
        sprites,report=analyze(folder)
        existing=read(folder/'published.json',{})
        if existing:
            if existing.get('source_sha256')!=report['source_sha256']:raise ValueError('已发布试验的来源发生变化')
            scenes.load(root,existing['scene'])
            return existing
        scene=scenes.load(root,scene_id) if scene_id else None
        if scene and (scene['modules'] or scene['instances']):raise ValueError('试验场景已有内容，未覆盖')
        production=read(folder/'production.json');kits=[]
        for index,sprite in enumerate(sprites):
            stream=BytesIO();sprite.save(stream,'PNG')
            files={'sprite.png':stream.getvalue(),'cutout.png':stream.getvalue(),
                'inputs/original.png':(folder/'inputs/ground.png').read_bytes(),
                'inputs/reference.png':(folder/'inputs/reference.png').read_bytes(),
                'generation.json':(folder/'generation.json').read_bytes(),
                'slice.json':json.dumps(dict(report,slice_index=index)).encode(),
                'production.json':json.dumps(dict(production,slice_index=index,source_job=folder.name)).encode(),
                'prompt.txt':production['material_prompt'].encode()}
            manifest=dict(schema='studio.static-prop/0.1',asset_family='static_prop',asset_kind='custom',
                view='isometric_2_1',canvas_px=list(CANVAS),image='sprite.png',
                provenance=dict(art_source='ai_long_wall_slice',source_job=folder.name,slice_index=index,this_build='unchanged_source_pixels'),
                processing=dict(method='cross_section_pixel_partition',reconstruction_pixel_errors=0),
                limitations=['Original order restores source. Repeated and mixed slices need visual validation; no collision validation.'])
            config=dict(title='长墙中段 '+str(index+1),anchor=list(ANCHOR),world_scale=1,behavior='passable',polygons=[])
            kits.append(_publish_annotation(root,files,manifest,config)['id'])
        if scene is None:scene=scenes.change(root,dict(action='create',title='院落 · 长墙切片验证'))
        for kit in kits:scene=scenes.change(root,dict(action='adopt',scene=scene['id'],revision=scene['revision'],kit=kit))
        instances=[]
        for row,indices in enumerate(((0,1,2),(1,1,1),(2,0,1))):
            for column,index in enumerate(indices):
                instances.append(dict(id='strip-%s-%s'%(row,column),module=scene['modules'][index]['id'],
                    position=[-250+128*column,-350+320*row+64*column]))
        scene=scenes.change(root,dict(action='layout',scene=scene['id'],revision=scene['revision'],instances=instances,spawn=[280,400]))
        result=dict(scene=scene['id'],kits=kits,source_sha256=report['source_sha256'])
        atomic(folder/'published.json',result)
        return result


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description='Slice and compare a generated wall-strip job; no image-service requests')
    parser.add_argument('folder',type=Path)
    parser.add_argument('--publish-root',type=Path,help='Also register samples and create their comparison scene')
    args=parser.parse_args();_,report=analyze(args.folder)
    print(report)
    if args.publish_root:print(publish_trial(args.publish_root,args.folder))
