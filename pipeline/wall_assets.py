"""Line-constrained wall generation and fixed-canvas validation, using prop jobs."""
from io import BytesIO
import hashlib
import json
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw
from asset_repository import atomic
from build_courtyard_wall_templates import CANVAS, ANCHOR, LENGTH, faces, point, project, render, render_continuous


def validate_axis(axis):
    if axis not in ('a','b'): raise ValueError('院墙线框只支持 A/B 两轴直墙')
    return axis


def mask(axis,continuous=False):
    validate_axis(axis)
    image=Image.new('L',CANVAS);draw=ImageDraw.Draw(image)
    for face in (faces(axis,LENGTH)[:3] if continuous else faces(axis,LENGTH)):
        draw.polygon([(x+ANCHOR[0],y+ANCHOR[1]) for x,y in map(project,face)],fill=255)
    return image


def prompt(axis,style):
    validate_axis(axis)
    return (
        'Use case: one modular courtyard wall sprite for a 2D game. '
        'Image 1 is the exact structural line master, NOT a style reference. '
        'Paint ONLY its visible wall and pitched wall-cap surfaces. '
        'Preserve the entire square canvas and ALL normalized positions, silhouette, wall thickness, '
        'wall height, cap profile, viewing direction and both cut ends exactly. '
        'Do not crop, center, zoom, rotate, expand or move the object. '
        'Keep each end flush and open for joining an identical wall; no posts or end ornaments. '
        'No wall-cap overhang beyond either longitudinal end. '
        'This is one plain straight wall, no gate, corners, windows, buildings or vegetation. '
        'Orthographic 2:1 projection. The wall runs '+
        ('upper-left to lower-right. ' if axis=='a' else 'upper-right to lower-left. ')+
        'Subtle plaster and grey tile material, restrained variation; matching colors at both ends. '
        'Replace the line art with finished surfaces, no black technical outline. '
        'Pure flat #FF00FF background everywhere outside the exact silhouette, no cast/contact shadows, '
        'no magenta material or color spill, no ground, text, marks, rulers, labels or extra objects. '
        'Soft upper-left illumination on the wall only. Shared material direction: '+style)


def configure(folder,spec,axis):
    axis=validate_axis(axis)
    renderer=render_continuous if spec.get('wall_continuous') else render
    renderer(axis).save(folder/'inputs/reference.png')
    spec.update(wall_axis=axis,size=512,material_prompt=prompt(axis,spec['description']))
    spec['wall_reference_sha256']=hashlib.sha256((folder/'inputs/reference.png').read_bytes()).hexdigest()


def whole_sprite(folder,spec,root,style_job=None):
    """Generate intact artwork; a second reference carries appearance only."""
    spec.update(wall_whole_sprite=True,wall_surface_projection=False)
    spec['material_prompt']+=' Render the ENTIRE wall as ONE cohesive hand-painted illustration. Preserve artistic outlines, curved ceramic tiles, ridge tiles, eave detailing and soft local shadows where the cap meets plaster. These are part of the artwork. No texture atlas, separate material swatches, flat polygon rendering or independently assembled surfaces. Fine warm ivory lime plaster, restrained natural texture, blue-grey fired clay tiles. Clean readable game-art shapes, delicate painted edges, no random scratch marks. '
    if spec.get('wall_continuous'):
        spec['material_prompt']=(
            'Paint Image 1 as an intact hand-painted 2D game sprite. This is a repeating MIDDLE slice of a continuous wall, not a freestanding wall. '
            'GEOMETRY: paint exactly the colored 2D panels in Image 1 at their existing positions and sizes on the unchanged square canvas. '
            'Do not extrude or redesign the panels. There are only a plaster plane, narrow eave, and tiled roof plane. There is NO end face. '
            'The two vertical boundaries are invisible cut planes through a continuing surface. They are alpha-cut edges WITHOUT ink strokes, border lines, bevels, thickness, shading or exposed cross-sections. '
            'Do not draw a vertical line at either cut. Do not add terminal tiles, ridge-end ornaments, pillars or roof overhang at the cuts. '
            'LONGITUDINAL REPEAT: the whole sprite will be copied by exactly '+str(list(project(point(spec['wall_axis'],LENGTH,0,0))))+' pixels on a 512-pixel canvas. '
            'Walls and roof must continue smoothly under this translation: same plaster color at both cuts, level continuing ridge/eave/baseline, eight identical ceramic tile repeats at matching phase. '
            'ART: cohesive painted warm ivory lime plaster, blue-grey curved clay tiles, restrained plaster grain, soft narrow shade directly under the eave, delicate dark ink only on tile details and the continuous longitudinal roof edges. '
            'Preserve the rich integrated illustration; no flat polygon rendering or separate material swatches. '
            'BACKGROUND: pure solid #FF00FF outside the exact colored panels, no ground plane, drop shadow, gradients, extra objects, lettering or labels. '
            'The reference omits end faces and vertical border strokes deliberately; keep them absent. Shared art direction: '+spec['description'])

    if style_job:
        from asset_repository import AssetRepository,name,read
        source=AssetRepository(root).scoped('.local/props/jobs/'+name(style_job),'.local/props/jobs')
        job=read(source/'job.json',{})
        if job.get('status')!='complete' or not job.get('spec',{}).get('wall_whole_sprite'):
            raise ValueError('院墙风格参考需要已完成的一体生成任务')
        raw=(source/'inputs/ground.png').read_bytes()
        digest=hashlib.sha256(raw).hexdigest()
        if read(source/'generation.json',{}).get('ground',{}).get('sha256')!=digest:
            raise ValueError('院墙风格参考与生成回执不一致')
        (folder/'inputs/wall-style.png').write_bytes(raw)
        spec.update(wall_style_job=style_job,wall_style_sha256=digest)
        spec['material_prompt']+=' Image 2 is the finished appearance reference ONLY: match its plaster, tile shapes, outline weight, palette and soft shading. Follow Image 1 for the NEW direction and composition. Do not copy the direction or silhouette of Image 2. '


def reuse_material(root,folder,spec,identity):
    from asset_repository import AssetRepository,name,read
    source=AssetRepository(root).scoped('.local/props/jobs/'+name(identity),'.local/props/jobs')
    job=read(source/'job.json',{})
    if not job.get('spec',{}).get('wall_axis'):raise ValueError('请选择院墙材质来源任务')
    raw=(source/'inputs/ground.png').read_bytes()
    receipt=read(source/'generation.json',{})
    if receipt.get('ground',{}).get('sha256')!=hashlib.sha256(raw).hexdigest():raise ValueError('院墙来源原图与回执不一致')
    (folder/'inputs/ground.png').write_bytes(raw)
    atomic(folder/'generation.json',receipt)
    spec['wall_material_job']=identity

def verify_reference(folder,spec):
    raw=(folder/'inputs/reference.png').read_bytes()
    if hashlib.sha256(raw).hexdigest()!=spec['wall_reference_sha256']:
        raise ValueError('院墙线框已变化，请重新创建制作任务')
    if spec.get('wall_style_sha256') and hashlib.sha256((folder/'inputs/wall-style.png').read_bytes()).hexdigest()!=spec['wall_style_sha256']:
        raise ValueError('院墙风格参考已变化，请重新创建制作任务')


def process(original,axis,continuous=False):
    from static_props import cutout
    validate_axis(axis)
    if original.width!=original.height:raise ValueError('院墙输出必须为正方形，不能通过裁切修正')
    sprite,background=cutout(original,adaptive_magenta=True,reserved_magenta=True)
    # Normalize the full canvas using its known scale. Never bbox-fit or recenter.
    sprite=sprite.resize(CANVAS,Image.Resampling.LANCZOS)
    expected=np.asarray(mask(axis,continuous))>0
    visible=np.asarray(sprite.getchannel('A'))>127
    union=int((expected|visible).sum());intersection=int((expected&visible).sum())
    iou=intersection/max(1,union)
    missing=int((expected&~visible).sum())/max(1,int(expected.sum()))
    excess=int((visible&~expected).sum())/max(1,int(expected.sum()))
    # Separate endpoint bands prevent a high whole-wall IoU hiding broken joints.
    endpoint_errors=[]
    for t in (0,LENGTH):
        footprint=Image.new('L',CANVAS);d=ImageDraw.Draw(footprint)
        for face in faces(axis,4):
            pts=[]
            for x,y,z in face:
                delta=point(axis,t-2,0,0)
                px,py=project((x+delta[0],y+delta[1],z))
                pts.append((px+ANCHOR[0],py+ANCHOR[1]))
            d.polygon(pts,fill=255)
        band=np.asarray(footprint)>0
        endpoint_errors.append(int(((expected^visible)&band).sum())/max(1,int((expected&band).sum())))
    report=dict(iou=round(iou,5),missing_ratio=round(missing,5),excess_ratio=round(excess,5),
                endpoint_errors=[round(v,5) for v in endpoint_errors],canvas_px=list(CANVAS),
                normalized_by='whole_canvas_uniform_scale',background=background,
                geometry_passed=iou>=.94 and missing<=.04 and excess<=.04 and max(endpoint_errors)<=.08,
                texture_seams='requires_visual_validation',occlusion='not_tested')
    return sprite,report


def whole_cutout(original):
    """Remove the reserved pink matte without unmixing painted edge colors."""
    rgba=original.convert('RGBA')
    if np.asarray(rgba.getchannel('A')).min()<255:return rgba
    pixels=np.asarray(rgba).copy();rgb=pixels[:,:,:3].astype(int)
    background=(rgb[:,:,0]-rgb[:,:,1]>35)&(rgb[:,:,2]-rgb[:,:,1]>15)
    if min(rgba.size)<=20:raise ValueError('一体墙体画布过小')
    inner=np.concatenate([background[8,8:-8],background[-9,8:-8],background[8:-8,8],background[8:-8,-9]])
    if inner.mean()<.98:raise ValueError('一体墙体未使用预留品红背景，未自动清除')
    # Providers sometimes add a narrow white canvas rim. It is background only
    # in this explicit border band; ivory plaster inside is never selected.
    border=np.zeros(background.shape,dtype=bool)
    border[:8]=True;border[-8:]=True;border[:,:8]=True;border[:,-8:]=True
    background|=border&(rgb.min(axis=2)>210)&(rgb.max(axis=2)-rgb.min(axis=2)<40)
    edge=np.concatenate([background[0],background[-1],background[:,0],background[:,-1]])
    if edge.mean()<.98:raise ValueError('一体墙体背景不是预留品红色，未自动清除')
    foreground=~background
    if foreground.sum()<100:raise ValueError('一体墙体没有可用主体')
    pixels[background]=0
    pixels[foreground,3]=255
    return Image.fromarray(pixels)


def cap_texture(sprite,bbox):
    """Rectify the sloping roof band before mapping it onto either wall axis."""
    rgb=np.asarray(sprite.convert('RGB'));alpha=np.asarray(sprite.getchannel('A'))
    neutral=(rgb.max(axis=2)-rgb.min(axis=2)<65)&(rgb.mean(axis=2)<175)&(alpha>240)
    x0,y0,x1,y1=bbox;w,h=x1-x0,y1-y0
    samples=[]
    for x in range(round(x0+.15*w),round(x0+.80*w)):
        rows=np.flatnonzero(neutral[:,x])
        if not len(rows):continue
        top=rows[0];band=rows[rows<=top+max(8,round(.17*h))]
        if len(band)>3:samples.append((x,top,band[-1]))
    if len(samples)<20:raise ValueError('瓦顶区域不足，无法保留瓦片结构')
    points=np.asarray(samples)
    upper=np.polyfit(points[:,0],points[:,1],1);lower=np.polyfit(points[:,0],points[:,2],1)
    xx=np.linspace(points[0,0],points[-1,0],256)[None,:]
    top=np.polyval(upper,xx)+2;bottom=np.polyval(lower,xx)-2
    if np.any(bottom-top<2):raise ValueError('瓦顶区域过薄，不能提取材质')
    # Leave out the fascia/plaster border below the tiles. Surface UV runs
    # from the eave toward the ridge, opposite to image Y.
    v=np.linspace(.80,.02,256)[:,None]
    # The roof cross-section also shifts horizontally in 2:1 projection.
    # Undo that shear so individual tiles retain their shape across the slope.
    shift=np.sign(upper[0])*.5*(bottom-top)*(1-v)
    yy=top+upper[0]*shift+(bottom-top)*v
    sample_x=xx+shift
    texture=rgb[np.clip(np.rint(yy).astype(int),0,sprite.height-1),np.clip(np.rint(sample_x).astype(int),0,sprite.width-1)].copy()
    # Only the longitudinal direction repeats; ridge and eave stay distinct.
    edge=(texture[:,0].astype(float)+texture[:,-1].astype(float))/2
    for i in range(12):
        weight=i/12
        for column in (i,255-i):texture[:,column]=np.rint(edge*(1-weight)+texture[:,column]*weight).astype(np.uint8)
    return Image.fromarray(texture)


def material_textures(original):
    """Sample appearance only. Provider silhouette is never used as geometry."""
    from static_props import cutout
    from PIL import ImageFilter
    sprite,_=cutout(original.convert('RGBA'),adaptive_magenta=True,reserved_magenta=True)
    bbox=sprite.getchannel('A').getbbox()
    if not bbox:raise ValueError('原图没有可提取的墙体材质')
    x0,y0,x1,y1=bbox;w,h=x1-x0,y1-y0
    result={}
    result['cap']=cap_texture(sprite,bbox)
    # Conservative interior plaster swatch. Missing pixels use the median,
    # never background color. Both axes share the same textures.
    for role,rect in [('plaster',(.28,.49,.60,.69))]:
        box=(round(x0+rect[0]*w),round(y0+rect[1]*h),round(x0+rect[2]*w),round(y0+rect[3]*h))
        patch=sprite.crop(box);rgb=np.array(patch.convert('RGB'));valid=np.array(patch.getchannel('A'))>240
        valid&=(rgb.mean(axis=2)>100)
        if valid.sum()<20:raise ValueError('缺少可用的'+role+'材质采样，不能编译院墙')
        median=np.median(rgb[valid],axis=0).astype(np.uint8);rgb[~valid]=median
        texture=Image.fromarray(rgb).resize((128,128),Image.Resampling.LANCZOS).filter(ImageFilter.GaussianBlur(.6))
        # Mirror each swatch into a periodic material. Opposite edges match,
        # eliminating a value discontinuity at the fixed wall repeat interval.
        periodic=Image.new('RGB',(256,256));periodic.paste(texture,(0,0));periodic.paste(texture.transpose(Image.Transpose.FLIP_LEFT_RIGHT),(128,0))
        periodic.paste(periodic.crop((0,0,256,128)).transpose(Image.Transpose.FLIP_TOP_BOTTOM),(0,128))
        result[role]=periodic
    return result


def compile_surfaces(textures,axis):
    """Rasterize fixed quads; longitudinal UVs repeat exactly once per wall."""
    validate_axis(axis)
    image=Image.new('RGBA',CANVAS)
    for index,face in enumerate(faces(axis,LENGTH)):
        # End face has seven profile vertices; it is a separate deterministic fill.
        if index==3:
            draw=ImageDraw.Draw(image)
            for role,indices in [('plaster',(0,1,2,6)),('cap',(6,2,3,4,5))]:
                color=tuple(np.asarray(textures[role]).mean(axis=(0,1)).astype(int))+(255,)
                draw.polygon([(x+ANCHOR[0],y+ANCHOR[1]) for x,y in map(project,[face[i] for i in indices])],fill=color)
            continue
        vertices=[(x+ANCHOR[0],y+ANCHOR[1]) for x,y in map(project,face)]
        p0,p1,_,p3=vertices
        matrix=np.array([[p1[0]-p0[0],p3[0]-p0[0]],[p1[1]-p0[1],p3[1]-p0[1]]],dtype=float)
        inv=np.linalg.inv(matrix)
        yy,xx=np.indices((CANVAS[1],CANVAS[0]),dtype=float);dx=(xx-p0[0]).ravel();dy=(yy-p0[1]).ravel()
        uv=np.stack([inv[0,0]*dx+inv[0,1]*dy,inv[1,0]*dx+inv[1,1]*dy])
        texture=np.asarray(textures['plaster' if index==0 else 'cap'])
        if index==1:
            # A thin fascia cannot carry the whole roof pattern a second time.
            texture=np.broadcast_to(texture[:24].mean(axis=0).astype(np.uint8)[None,:,:],texture.shape)
        tx=np.clip(np.rint(uv[0]*255).astype(int),0,255);ty=np.clip(np.rint(uv[1]*255).astype(int),0,255)
        layer=Image.fromarray(texture[ty,tx].reshape((512,512,3)))
        coverage=Image.new('L',CANVAS);ImageDraw.Draw(coverage).polygon(vertices,fill=255)
        image.paste(layer,(0,0),coverage)
    # Filling exact polygon coverage preserves all specified endpoints. No image
    # bbox normalization, hand correction or silhouette from the provider is used.
    return image

def publish(root,folder,spec):
    from static_props import _publish_annotation
    verify_reference(folder,spec)
    axis=spec['wall_axis']
    with Image.open(folder/'inputs/original.png') as original:
        sprite,report=process(whole_cutout(original) if spec.get('wall_whole_sprite') else original.convert('RGBA'),axis,spec.get('wall_continuous',False))
        if spec.get('wall_surface_projection'):
            textures=material_textures(original)
            sprite=compile_surfaces(textures,axis)
            report=dict(source_geometry=report,geometry_passed=True,method='ai_material_on_fixed_geometry',
                        texture_seams='periodic_material_edges; visual_validation_required',occlusion='not_tested')
            for role,texture in textures.items():texture.save(folder/('wall-'+role+'-material.png'))
    sprite.save(folder/'wall-preview.png');atomic(folder/'wall-checks.json',report)
    whole=spec.get('wall_whole_sprite',False)
    if not report['geometry_passed'] and (not whole or spec.get('wall_continuous')):
        raise ValueError('院墙外观偏离线框：轮廓重合 %.1f%%，端面偏差 %s；未发布，不会改动当前素材。' %
                         (report['iou']*100,report['endpoint_errors']))
    delta=list(project(point(axis,LENGTH,0,0)))
    ground=[project(point(axis,t,q,0)) for t,q in [(0,-8),(LENGTH,-8),(LENGTH,8),(0,8)]]
    config=dict(title=spec['title'],anchor=list(ANCHOR),world_scale=1,behavior='blocking',polygons=[[list(v) for v in ground]])
    stream=BytesIO();sprite.save(stream,'PNG')
    connectors=dict(schema='studio.wall-connectors/1',axis=axis,start=[0,0],end=delta,repeat_offset_px=delta)
    if whole:
        if not sprite.getchannel('A').getbbox():raise ValueError('一体墙体抠图为空')
        report['method']='whole_ai_sprite_background_removal_only'
        # Appearance previews must never advertise unverified endpoints or physics.
        config.update(behavior='passable',polygons=[])
        if not report['geometry_passed']:connectors=None
        atomic(folder/'wall-checks.json',report)
    files={'sprite.png':stream.getvalue(),'cutout.png':stream.getvalue(),
           'inputs/original.png':(folder/'inputs/original.png').read_bytes(),
           'inputs/line-master.png':(folder/'inputs/reference.png').read_bytes(),
           'wall-checks.json':json.dumps(report).encode(),'wall-connectors.json':json.dumps(connectors).encode(),
           'production.json':json.dumps(spec).encode(),'prompt.txt':spec['material_prompt'].encode()}
    for role in ('plaster','cap'):
        path=folder/('wall-'+role+'-material.png')
        if spec.get('wall_surface_projection') and path.exists():files['inputs/'+path.name]=path.read_bytes()
    if (folder/'generation.json').exists():files['generation.json']=(folder/'generation.json').read_bytes()
    if spec.get('wall_style_sha256'):files['inputs/style-reference.png']=(folder/'inputs/wall-style.png').read_bytes()
    manifest=dict(schema='studio.static-prop/0.1',asset_family='static_prop',asset_kind='custom',view='isometric_2_1',
        provenance=dict(art_source='ai_whole_wall' if whole else 'ai_surface_sampling' if spec.get('wall_surface_projection') else 'ai_line_constrained_wall',this_build='full_canvas_normalization_no_bbox_fit' if whole else 'fixed_geometry_surface_projection' if spec.get('wall_surface_projection') else 'full_canvas_normalization_no_bbox_fit'),
        canvas_px=list(CANVAS),image='sprite.png',wall_connectors=connectors,
        processing=dict(method='wall_line_constrained',geometry=report),
        normalization=dict(method='whole_canvas_uniform_scale'),limitations=['Texture joins and occlusion need visual validation.'])
    return _publish_annotation(root,files,manifest,config)
