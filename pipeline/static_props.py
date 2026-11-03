"""Shared standalone object production, independent of maps and gameplay."""
import base64
from collections import deque
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
import math
from pathlib import Path
import secrets
import shutil
import zipfile

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from asset_repository import AssetRepository, atomic, name, read
from task_lock import task_lock
from asset_projection import ISOMETRIC, contract, validate_projection
from terrain import decode_image
from terrain_images import configured, generate_materials

KINDS={
    'rock':{'label':'石头','subject':'rock','composition':'one compact stone',
            'description':'温暖田园风2D游戏中的一块矮胖灰褐色石头，轮廓略不规则，大块面手绘，少量细小裂纹，低对比度，柔和色彩。',
            'collision_usage':'blocking','width_ratio':.55,'depth_ratio':.16,
            'hint':'石头的阻挡占地需要人工确认；默认椭圆仅是初值。'},
    'crate':{'label':'木箱','subject':'wooden crate','composition':'one closed wooden crate with visible top and front faces',
             'description':'温暖田园风2D游戏中的一个方形旧木箱，暖棕木材，简洁板缝，大块面手绘，柔和色彩，轻微磨损。',
             'collision_usage':'blocking','width_ratio':.75,'depth_ratio':.25,
             'hint':'木箱使用统一落地锚点；椭圆建议不代表箱底的精确占地，可按游戏需要另行定义。'},
    'bush':{'label':'灌木','subject':'bush','composition':'one dense rounded bush with a connected foliage silhouette, no detached leaves or open interior gaps',
            'description':'温暖田园风2D游戏中的一丛矮灌木，浓密圆润的绿色叶团，少量浅绿亮面，大块面手绘，轮廓完整，没有脱落叶片。',
            'collision_usage':'optional','width_ratio':.45,'depth_ratio':.14,
            'hint':'灌木可作装饰或阻挡；细叶和内部孔洞不能靠单色抠图可靠处理，优先导入透明PNG。'},
    'custom':{'label':'自定义物件','subject':'object described in the art direction','composition':'one complete connected standalone object',
              'description':'',
              'collision_usage':'none','width_ratio':.55,'depth_ratio':.16,
              'hint':'自定义物件默认不提供碰撞形状。透明、镂空或复杂细枝物件建议导入透明PNG。'}
}
COLLISION_USAGES=('blocking','optional','none')


def identity():
    return datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+secrets.token_hex(4)


def decode_sprite(content):
    try:
        raw=base64.b64decode(content,validate=True)
        if not raw or len(raw)>8*1024*1024: raise ValueError('物件图片需小于8MB')
        with Image.open(BytesIO(raw)) as image:
            if min(image.size)<32 or image.width*image.height>4_000_000:
                raise ValueError('物件图片至少32px，且不超过400万像素')
            image.load()
            return image.convert('RGBA')
    except (OSError,TypeError,Image.DecompressionBombError):
        raise ValueError('请选择有效的PNG / JPEG / WebP图片') from None


def validate(data):
    kind=data.get('kind','rock')
    if not isinstance(kind,str) or kind not in KINDS: raise ValueError('未知物件类型')
    title=data.get('title',KINDS[kind]['label']+'素材')
    description=data.get('description','')
    mode=data.get('mode','ai')
    size=data.get('size',256)
    if not isinstance(title,str) or not 1<=len(title.strip())<=60: raise ValueError('名称需为1–60字')
    if not isinstance(description,str) or len(description)>2000 or (mode=='ai' and not description.strip()):
        raise ValueError('AI模式请填写1–2000字的物件描述')
    if mode not in ('ai','import'): raise ValueError('请选择AI生成或导入物件')
    if type(size) is not int or size not in (128,256): raise ValueError('输出尺寸须为128或256')
    usage=data.get('collision_usage',KINDS[kind]['collision_usage'])
    if not isinstance(usage,str) or usage not in COLLISION_USAGES: raise ValueError('未知碰撞建议用途')
    projection=validate_projection(data.get('projection','orthographic_three_quarter'),'orthographic_three_quarter')
    return {'projection':projection,'title':title.strip(),'description':description.strip(),'mode':mode,'size':size,'kind':kind,'collision_usage':usage}


def prompt(description,kind='rock',projection='orthographic_three_quarter'):
    validate_projection(projection,'orthographic_three_quarter')
    profile=KINDS[kind]
    view=('2:1 dimetric game projection, camera azimuth 45 degrees and elevation 30 degrees. '
          'Visible top, left and right faces; equal left and right face widths. '
          'Ground-plane axes slope +0.5 and -0.5 in screen space (26.565 degrees to horizontal), vertical edges stay vertical. '
          'Parallel edges remain parallel, no perspective convergence. '
          if projection==ISOMETRIC else
          'Orthographic three-quarter view from above, visible top and front, no perspective convergence. ')
    composition=('one closed wooden crate with a visible diamond top and two equal side faces' if projection==ISOMETRIC and kind=='crate' else profile['composition'])
    return (f'Create exactly ONE complete standalone {profile["subject"]} sprite for a 2D game. '
            f'The AI must draw the full {profile["subject"]} silhouette and its surface, not a texture swatch. '
            +view+
            f'Centered {composition}, full silhouette within the square, 12% empty margin on every side. '
            'No other objects, no ground plane, no grass, no cast shadow, no contact shadow, no horizon. '
            'Soft upper-left lighting painted on the object only. '
            'Background must be perfectly flat solid RGB(255,0,255), hex #FF00FF, touching all four edges. '
            'Magenta and pink are reserved for background removal, including empty holes between leaves or structural openings. '
            'No magenta or pink material on the object; no reflected background color or pink contact rim. '
            'No transparency, no checkerboard, no text, no labels, no border, no collage or variants. '
            'Use the reference only for palette, brushwork and detail scale; do not copy its composition. '
            'Art direction: '+description)


def prepare(root,data):
    spec=validate(data)
    if data.get('wall_axis'):
        from wall_assets import validate_axis
        validate_axis(data['wall_axis'])
        if spec['mode']!='ai' or spec['projection']!='isometric_2_1':raise ValueError('院墙线框需要 AI 模式及2:1等距投影')
    if spec['mode']=='ai' and not configured(root): raise ValueError('请先在项目.env配置图片服务密钥')
    image=decode_sprite(data.get('image')) if spec['mode']=='import' else None
    reference=decode_image(data['reference']) if data.get('reference') else None
    job_id=identity()
    folder=AssetRepository(root).scoped('.local/props/jobs/'+job_id,'.local/props/jobs')
    (folder/'inputs').mkdir(parents=True)
    if image is not None: image.save(folder/'inputs/original.png')
    if reference is not None: reference.save(folder/'inputs/reference.png')
    spec.update(asset_type='material',material_prompt=prompt(spec['description'],spec['kind'],spec['projection']) if spec['mode']=='ai' else '')
    if data.get('wall_corner_build'):
        if spec['mode']!='ai' or spec['projection']!='isometric_2_1':raise ValueError('转角墙需要 AI 模式及2:1等距投影')
        from wall_corner import configure_job
        configure_job(folder,spec)
    if data.get('wall_axis'):
        if data.get('wall_strip_build'):
            from wall_strip import configure_job
            configure_job(folder,spec,data['wall_axis'])
        else:
            from wall_assets import configure
            spec['wall_continuous']=bool(data.get('wall_continuous'))
            configure(folder,spec,data['wall_axis'])
            spec['wall_surface_projection']=bool(data.get('wall_surface_projection'))
            if data.get('wall_whole_sprite'):
                from wall_assets import whole_sprite
                whole_sprite(folder,spec,root,data.get('wall_style_job'))
            if data.get('wall_material_job'):
                if spec.get('wall_whole_sprite'):raise ValueError('一体墙体需独立生成，不能复用材质图片')
                from wall_assets import reuse_material
                reuse_material(root,folder,spec,data['wall_material_job'])
    job={'id':job_id,'status':'queued','stage':'等待制作物件','error':None,'spec':spec,
         'created_at':datetime.now(timezone.utc).isoformat()}
    atomic(folder/'job.json',job)
    return job


def reserved_magenta_mask(rgb,key):
    rgb=np.asarray(rgb).astype(np.int16)
    red=rgb[:,:,0]-rgb[:,:,1];blue=rgb[:,:,2]-rgb[:,:,1]
    key_ratio=float(key[0]-key[1])/max(1,float(key[2]-key[1]))
    ratio=red/np.maximum(blue,1)
    return (red>20)&(blue>15)&(ratio>=key_ratio*.65)&(ratio<=key_ratio*1.65)


def cutout(image, *, adaptive_magenta=False, reserved_magenta=False):
    """Keep supplied alpha, or remove border-connected magenta / near-white.

    Background removal requires foreground/background color separation. It is not
    semantic segmentation and must reject ordinary opaque scene backgrounds.
    """
    image=image.convert('RGBA')
    alpha=np.asarray(image.getchannel('A'))
    if alpha.min()<255:
        if not np.any(alpha>16): raise ValueError('物件图片完全透明')
        if np.any(alpha[0]>16) or np.any(alpha[-1]>16) or np.any(alpha[:,0]>16) or np.any(alpha[:,-1]>16):
            raise ValueError('物件接触画布边缘，可能被裁断，请补充透明留白后导入')
        return image,{'method':'preserve_supplied_alpha','art_review':'pending'}
    rgb=np.asarray(image.convert('RGB')).astype(np.int16)
    h,w=rgb.shape[:2]
    edges=np.concatenate((rgb[0],rgb[-1],rgb[:,0],rgb[:,-1]))
    white_key=np.median(edges,axis=0)
    white=bool(np.min(white_key)>=245 and np.max(white_key)-np.min(white_key)<=5
               and np.mean(np.max(np.abs(edges-white_key),axis=1)<=8)>=.98)
    key=white_key if white else np.array([255,0,255])
    tolerance=12 if white else 55
    sampled=False
    keyed_frame=False
    if adaptive_magenta and not white:
        # Some generators render the chroma key as muted pink. Accept only a
        # uniform magenta-family border, never an arbitrary scene background.
        sample_key=white_key
        sample_edges=edges
        # A generator may add a one-pixel dark pink canvas rim. Require a
        # uniform inner safety band before treating that rim as background.
        if min(h,w)>16:
            inner=np.concatenate((rgb[1:4,4:-4].reshape(-1,3),rgb[-4:-1,4:-4].reshape(-1,3),
                                  rgb[4:-4,1:4].reshape(-1,3),rgb[4:-4,-4:-1].reshape(-1,3)))
            inner_key=np.median(inner,axis=0)
            pink_edges=(edges[:,0]-edges[:,1]>20)&(edges[:,2]-edges[:,1]>15)
            if (np.mean(np.max(np.abs(inner-inner_key),axis=1)<=16)>=.98
                    and np.mean(pink_edges)>=.98):
                sample_key=inner_key;sample_edges=inner;keyed_frame=True
        deviation=np.max(np.abs(sample_edges-sample_key),axis=1)
        if (sample_key[0]-sample_key[1]>45 and sample_key[2]-sample_key[1]>35
                and np.mean(deviation<=16)>=.98):
            key=sample_key
            tolerance=16
            sampled=True
    distance=np.max(np.abs(rgb-key),axis=2)
    border=np.concatenate((distance[0],distance[-1],distance[:,0],distance[:,-1]))
    if not (sampled and keyed_frame) and np.mean(border<=tolerance)<.98:
        raise ValueError('背景未识别为近纯白或纯品红；请导入透明PNG，或使用四边留白的单色背景图')
    candidate=distance<=tolerance
    if sampled and keyed_frame:
        candidate[0,:]=True;candidate[-1,:]=True;candidate[:,0]=True;candidate[:,-1]=True
    removed=np.zeros((h,w),dtype=bool)
    queue=deque()
    for y,x in [(0,x) for x in range(w)]+[(h-1,x) for x in range(w)]+[(y,0) for y in range(h)]+[(y,w-1) for y in range(h)]:
        if candidate[y,x] and not removed[y,x]: removed[y,x]=True;queue.append((y,x))
    while queue:
        y,x=queue.popleft()
        for ny,nx in ((y-1,x),(y+1,x),(y,x-1),(y,x+1)):
            if 0<=ny<h and 0<=nx<w and candidate[ny,nx] and not removed[ny,nx]:
                removed[ny,nx]=True;queue.append((ny,nx))
    reserved_count=0
    enclosed_count=0
    if reserved_magenta and not white:
        # Only AI production reserves this color family for the background.
        # Match chroma direction, allowing darker spill but excluding green/brown/blue.
        chroma=reserved_magenta_mask(rgb,key)
        extra=chroma & ~removed
        reserved_count=int(extra.sum())
        if reserved_count>max(1,int((~removed).sum()))*.20:
            raise ValueError('品红清理涉及超过20%的主体区域，可能误删主体；请重新生成不含品红材质的物件')
        enclosed_count=int((extra & ~np.asarray(Image.fromarray(removed.astype('uint8')*255).filter(ImageFilter.MaxFilter(7))).astype(bool)).sum())
        removed |= chroma
    # Decontaminate the boundary of external background and cleaned internal holes.

    dilated=np.asarray(Image.fromarray(removed.astype('uint8')*255).filter(ImageFilter.MaxFilter(7)))>0
    ring=dilated & ~removed
    foreground=rgb.astype(float)/255
    coverage=np.ones((h,w),dtype=float)
    if white or sampled:
        # Infer foreground color from the nearest interior pixel, then unmix
        # the sampled matte only in the boundary ring, preserving interiors.
        stable=np.asarray(Image.fromarray((~removed).astype('uint8')*255).filter(ImageFilter.MinFilter(7)))>0
        stable &= distance>36
        yy,xx=np.nonzero(ring)
        found=np.zeros(len(yy),dtype=bool)
        sample=foreground[yy,xx].copy()
        offsets=sorted(((dy,dx) for dy in range(-8,9) for dx in range(-8,9)),key=lambda p:p[0]*p[0]+p[1]*p[1])
        for dy,dx in offsets:
            sy=np.clip(yy+dy,0,h-1);sx=np.clip(xx+dx,0,w-1)
            use=~found & stable[sy,sx]
            sample[use]=foreground[sy[use],sx[use]];found[use]=True
            if found.all(): break
        background=key/255
        delta=sample-background
        a=np.sum((foreground[yy,xx]-background)*delta,axis=1)/np.maximum(np.sum(delta*delta,axis=1),.0001)
        coverage[yy[found],xx[found]]=np.clip(a[found],0,1)
    else:
        chroma=np.clip((np.minimum(rgb[:,:,0],rgb[:,:,2])-rgb[:,:,1])/255,0,1)
        coverage[ring]=1-chroma[ring]
    coverage[removed]=0
    corrected=(foreground-(1-coverage[:,:,None])*(key/255))/np.maximum(coverage[:,:,None],.001)
    rgba=np.dstack((np.clip(corrected*255,0,255).astype('uint8'),np.round(coverage*255).astype('uint8')))
    rgba[removed]=0
    result=Image.fromarray(rgba,'RGBA')
    bbox=result.getchannel('A').point(lambda v:255 if v>16 else 0).getbbox()
    fraction=np.mean(coverage>.1)
    if not bbox or not .01<fraction<.85: raise ValueError('未识别到合理大小的单个物件，请检查原图')
    if min(bbox[0],bbox[1],w-bbox[2],h-bbox[3])<3: raise ValueError('物件接近画布边缘，可能被裁断')
    return result,{'method':('border_connected_near_white_key' if white else
                             'border_connected_sampled_magenta_key' if sampled else 'border_connected_magenta_key'),
                   'reserved_magenta_cleanup':bool(reserved_magenta and not white),
                   'reserved_color_removed_px':reserved_count,'enclosed_or_deep_spill_px':enclosed_count,
                   'semantic_removal_verified':False,
                   'key_rgb':key.tolist(),'removed_fraction':round(float(removed.mean()),4),
                   'edge_color_correction':'3px_boundary_only','art_review':'pending',
                   'limitations':'未做语义分割。AI品红背景模式会清除匹配的封闭孔洞与残色，主体不得含品红材质；仍需检查误删、细枝和透明边缘。导入模式保留内部颜色。'}


def number(value,default,low,high,label):
    if value is None: return default
    if type(value) not in (int,float) or not math.isfinite(value) or not low<=value<=high:
        raise ValueError(label+'超出有效范围')
    return round(value,2)


def single_object(image):
    """Reject multiple large detached silhouettes; this is not semantic recognition."""
    alpha=image.getchannel('A').copy();alpha.thumbnail((512,512),Image.Resampling.NEAREST)
    mask=np.asarray(alpha)>16
    # Bridge tiny antialias gaps without merging clearly separated objects.
    mask=np.asarray(Image.fromarray(mask.astype('uint8')*255).filter(ImageFilter.MaxFilter(3)))>0
    visited=np.zeros(mask.shape,dtype=bool);h,w=mask.shape;sizes=[]
    for y,x in zip(*np.nonzero(mask)):
        if visited[y,x]: continue
        visited[y,x]=True;queue=deque([(y,x)]);count=0
        while queue:
            cy,cx=queue.popleft();count+=1
            for ny,nx in ((cy-1,cx),(cy+1,cx),(cy,cx-1),(cy,cx+1)):
                if 0<=ny<h and 0<=nx<w and mask[ny,nx] and not visited[ny,nx]:
                    visited[ny,nx]=True;queue.append((ny,nx))
        sizes.append(count)
    sizes.sort(reverse=True)
    if not sizes: raise ValueError('未识别到物件')
    major=sum(count>=max(8,sizes[0]*.015) for count in sizes)
    if major>1: raise ValueError('发现多个明显分离的前景区域，请每次只提供一个完整物件；分离配件请先合成或分别生产')
    return {'method':'connected_silhouette_check','major_regions':major,'minor_regions':len(sizes)-major,
            'semantic_single_object':'not_verified'}


def package(root,original,spec,package_id=None,source=None,provenance=None,settings=None):
    """Stage immutable exports, including inputs and provider receipts."""
    with task_lock(root):
        assets=AssetRepository(root);package_id=name(package_id or identity())
        target=assets.scoped('prop-kits/'+package_id,'prop-kits')
        if target.exists():
            load_package(root,package_id)
            return target
        sprite,processing=cutout(original,adaptive_magenta=spec.get('mode')=='ai',reserved_magenta=spec.get('mode')=='ai')
        processing['single_object']=single_object(sprite)
        bbox=sprite.getchannel('A').getbbox()
        crop=sprite.crop(bbox)
        size=spec['size'];padding=size//16
        factor=(size-padding*2)/max(crop.size)
        dimensions=tuple(max(1,round(v*factor)) for v in crop.size)
        crop=crop.resize(dimensions,Image.Resampling.LANCZOS)
        canvas=Image.new('RGBA',(size,size))
        offset=((size-dimensions[0])//2,size-padding-dimensions[1])
        canvas.paste(crop,offset)
        if processing.get('reserved_magenta_cleanup'):
            # Resampling/unmatting can mix foreground colors back into the key range.
            pixels=np.array(canvas)
            spill=reserved_magenta_mask(pixels[:,:,:3],processing['key_rgb']) & (pixels[:,:,3]>0)
            visible_spill=int((spill & (pixels[:,:,3]>16)).sum())
            if visible_spill>max(8,int((pixels[:,:,3]>16).sum())*.02):
                raise ValueError('缩放后仍有较多品红残色，请重新生成不含品红材质的物件')
            pixels[spill]=0
            canvas=Image.fromarray(pixels,'RGBA')
            processing['resampled_spill_removed_px']=int(spill.sum())
            processing['output_visible_reserved_pixels']=0
        settings=settings or {}
        projection=validate_projection(spec.get('projection','orthographic_three_quarter'),'orthographic_three_quarter')
        isometric=projection==ISOMETRIC
        anchor=[number(settings.get('anchor_x'),size/2,0,size-1,'锚点X'),
                number(settings.get('anchor_y'),size-padding-1,0,size-1,'锚点Y')]
        kind=spec.get('kind','rock');profile=KINDS[kind]
        usage=settings.get('collision_usage',spec.get('collision_usage',profile['collision_usage']))
        if not isinstance(usage,str) or usage not in COLLISION_USAGES: raise ValueError('未知碰撞建议用途')
        width=number(settings.get('collision_width'),max(1,round(dimensions[0]*profile['width_ratio'],2)),1,size,'碰撞宽度')
        depth=number(settings.get('collision_depth'),max(1,round(dimensions[1]*profile['depth_ratio'],2)),1,size,'碰撞深度')
        if isometric:
            depth=number(settings.get('collision_depth'),round(width/2,2),1,size,'碰撞深度')
            anchor[1]=number(settings.get('anchor_y'),round(size-padding-width/4,2),0,size-1,'锚点Y')
        # Legacy foot anchor sits at ellipse bottom; dimetric anchor estimates ground center.
        polygon=[[round(math.cos(i*math.pi/8)*width/2,2),round(-depth/2+math.sin(i*math.pi/8)*depth/2,2)] for i in range(16)]
        if isometric:
            polygon=([[0,-depth/2],[width/2,0],[0,depth/2],[-width/2,0]] if kind=='crate' else
                     [[round(math.cos(i*math.pi/8)*width/2,2),round(math.sin(i*math.pi/8)*depth/2,2)] for i in range(16)])
        staging=assets.scoped('.local/prop-builds/'+package_id,'.local/prop-builds')
        if staging.exists(): shutil.rmtree(staging)
        (staging/'inputs').mkdir(parents=True)
        if source and (source/'inputs/original.png').is_file():
            shutil.copyfile(source/'inputs/original.png',staging/'inputs/original.png')
        else:
            original.save(staging/'inputs/original.png')
        canvas.save(staging/'sprite.png')
        sprite.save(staging/'cutout.png')
        for relative in ('generation.json','inputs/reference.png'):
            if source and (source/relative).is_file():
                shutil.copyfile(source/relative,staging/relative)
        atomic(staging/'production.json',spec)
        (staging/'prompt.txt').write_text(spec.get('material_prompt',''),encoding='utf-8')
        preview=Image.new('RGB',(size*3,size),(239,239,235))
        for index,color in enumerate(((237,235,225),(54,63,74),(116,139,99))):
            panel=Image.new('RGB',(size,size),color)
            if index==0:
                draw=ImageDraw.Draw(panel)
                for y in range(0,size,16):
                    for x in range(0,size,16):
                        if (x//16+y//16)%2: draw.rectangle((x,y,x+15,y+15),fill=(208,210,206))
            panel.paste(canvas,(0,0),canvas);preview.paste(panel,(index*size,0))
        preview.save(staging/'preview.png')
        overlay=preview.crop((size,0,size*2,size));draw=ImageDraw.Draw(overlay)
        projected=[(anchor[0]+x,anchor[1]+y) for x,y in polygon]
        if usage!='none': draw.line(projected+[projected[0]],fill=(255,145,61),width=2)
        x,y=anchor;draw.line((x-6,y,x+6,y),fill=(45,224,226),width=2);draw.line((x,y-6,x,y+6),fill=(45,224,226),width=2)
        overlay.save(staging/'anchor_collision.png')
        origin=provenance or {'art_source':'ai_complete_object' if spec['mode']=='ai' else 'external_complete_object'}
        manifest={'schema':'studio.static-prop/0.1','id':package_id,'title':spec['title'],'asset_family':'static_prop',
                  'asset_kind':kind,'production_ready':False,'provenance':origin,'canvas_px':[size,size],
                  'image':'sprite.png','anchor_px':anchor,'sprite_offset_px':[-anchor[0],-anchor[1]],
                  'view':projection,'processing':processing,
                  'normalization':{'source_bbox_px':list(bbox),'content_px':list(dimensions),'offset_px':list(offset),
                                   'scale_factor':factor,'world_scale':'caller_defined'},
                  'suggested_collision':{'enabled_by_default':False,'suggestions_only':True,
                       'coordinate_space':'anchor_local_px','polygon':polygon if usage!='none' else [],'width_px':width,'depth_px':depth,'usage':usage,
                       'layers_and_masks':'caller_defined','source':'editable_ellipse_heuristic_not_semantic'},
                  'validation':{'art':'pending','transparent_edges':'pending_visual_review','anchor':'pending_manual_review',
                                'engine_physics':'not_tested','occlusion':'not_tested'},
                  'limitations':['只生产单个物件候选；连通区域检查不等于语义识别，不检查视角和风格是否符合游戏',
                                 '锚点与碰撞为可调整建议，不是AI识别的实际接触面','没有导航、交互、地图或游戏行为']}
        if isometric:
            manifest['projection']={**contract(),'artwork_transform':'none',
                'anchor_role':'suggested_ground_footprint_center_and_y_sort_origin',
                'suggested_footprint':{'width_px':round(dimensions[0]*profile['width_ratio'],2),
                    'depth_px':round(dimensions[0]*profile['width_ratio']/2,2),'review':'pending_manual_review'},
                'import_contract':'caller_declares_projection_not_automatically_verified'}
            manifest['suggested_collision']['source']='editable_ground_footprint_heuristic_not_semantic'
        (staging/'INTEGRATION.md').write_text(
            '# 独立物件素材候选\n\n使用sprite.png（透明RGBA）。Sprite2D.centered=false，offset=sprite_offset_px；'
            '节点position是游戏中落脚点。PNG像素尺寸不代表世界单位。\n\n'
            '建议碰撞点相对锚点，Y向下，默认不启用；usage为blocking（阻挡候选）、optional（按游戏选择）或none（不提供形状）。游戏自行选择层与掩码，按实际物件调整落脚点与碰撞。'
            '不可用整张图片轮廓替代落地占用范围。本包不提供物理、导航或角色遮挡已通过的保证。\n\n'
            'preview.png是三种固定底色的边缘检查图；anchor_collision.png青色十字是锚点，橙色是建议碰撞。'
            'cutout.png保留裁切前抠图，inputs/original.png保留解码后原始图。原始提示词与参考图（如有）一并交付。'
            '导入图保留内部颜色，只从边界连通区域移除背景。AI品红背景物件自动清理匹配的封闭孔洞及残色，主体不得使用品红材质；未做语义识别，仍需检查误删、细枝、内部孔洞和透明边缘。\n',encoding='utf-8')
        if isometric:
            with (staging/'INTEGRATION.md').open('a',encoding='utf-8') as guide:
                guide.write('\n等距规格为2:1斜二测，参考地格128×64，基向量(64,32)、(-64,32)。物件保持原始造型，程序不旋转或压扁图片。'
                            '锚点初值为估算占地中心，Y排序使用该节点位置；请人工核对真实底面。'
                            '投影标签是请求/导入声明，尚未自动验证绘图角度。碰撞和美术验收仍待确认。\n')
        manifest['files_sha256']={str(p.relative_to(staging)):hashlib.sha256(p.read_bytes()).hexdigest()
                                  for p in staging.rglob('*') if p.is_file()}
        atomic(staging/'manifest.json',manifest)
        with zipfile.ZipFile(staging/'kit.zip','w',zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(staging.rglob('*')):
                if path.is_file() and path.name!='kit.zip': archive.write(path,str(path.relative_to(staging)))
        target.parent.mkdir(parents=True,exist_ok=True);staging.rename(target)
        return target


def load_package(root,package_id):
    try:
        assets=AssetRepository(root);package_id=name(package_id)
        folder=assets.scoped('prop-kits/'+package_id,'prop-kits');manifest=read(folder/'manifest.json')
        if not isinstance(manifest,dict) or manifest.get('schema')!='studio.static-prop/0.1' or manifest.get('id')!=package_id:
            raise ValueError('无效物件清单')
        expected=manifest['files_sha256']
        if not {'sprite.png','cutout.png','inputs/original.png','preview.png','anchor_collision.png','production.json','prompt.txt','INTEGRATION.md'}.issubset(expected):
            raise ValueError('物件清单缺少必要文件')
        if manifest.get('provenance',{}).get('art_source')=='ai_complete_object':
            if 'generation.json' not in expected: raise ValueError('AI物件缺少生成记录')
            receipt=read(folder/'generation.json',{})
            if receipt.get('ground',{}).get('sha256')!=expected['inputs/original.png']:
                raise ValueError('AI原图与生成记录指纹不一致')
        with zipfile.ZipFile(folder/'kit.zip') as archive:
            files=archive.namelist()
            if len(files)!=len(set(files)) or set(files)!=set(expected)|{'manifest.json'}:
                raise ValueError('ZIP文件清单不匹配')
            if json.loads(archive.read('manifest.json'))!=manifest: raise ValueError('ZIP与磁盘清单不一致')
            for relative,digest in expected.items():
                file=assets.scoped('prop-kits/'+package_id+'/'+relative,'prop-kits/'+package_id)
                raw=archive.read(relative)
                if hashlib.sha256(raw).hexdigest()!=digest or raw!=file.read_bytes(): raise ValueError('物件文件指纹不一致：'+relative)
        return manifest
    except (OSError,TypeError,KeyError,zipfile.BadZipFile,UnicodeError) as error:
        raise ValueError('物件包缺失或损坏：'+str(error)) from None


def catalog(root):
    kits=[]
    for path in sorted((Path(root)/'prop-kits').glob('*/manifest.json'),reverse=True):
        if path.parent.is_symlink(): continue
        manifest=read(path)
        if not isinstance(manifest,dict): continue
        try:
            load_package(root,path.parent.name);manifest['integrity']={'passed':True}
        except ValueError as error: manifest['integrity']={'passed':False,'error':str(error)}
        kits.append(manifest)
    jobs=[]
    for path in (Path(root)/'.local/props/jobs').glob('*/job.json'):
        job=read(path)
        if job:
            job['original_available']=(path.parent/'inputs/original.png').is_file()
            jobs.append(job)
    return {'kits':kits,'jobs':sorted((j for j in jobs if j),key=lambda j:j['created_at'],reverse=True)[:60]}


def remake(root,data):
    with task_lock(root):
        source_id=name(data.get('source_kit'));manifest=load_package(root,source_id)
        if manifest.get('module_settings') and not data.get('transparency_only'):
            raise ValueError('此素材使用多区域设置，请通过统一素材设置另存版本')
        if data.get('transparency_only') and manifest['provenance'].get('art_source')!='ai_complete_object':
            raise ValueError('仅支持重新处理Studio生成的AI物件；导入图片保留原处理规则')
        folder=AssetRepository(root).scoped('prop-kits/'+source_id,'prop-kits')
        spec=read(folder/'production.json')
        with Image.open(folder/'inputs/original.png') as image: original=image.convert('RGBA')
        settings={'anchor_x':data.get('anchor_x',manifest['anchor_px'][0]),
                  'anchor_y':data.get('anchor_y',manifest['anchor_px'][1]),
                  'collision_width':data.get('collision_width',manifest['suggested_collision']['width_px']),
                  'collision_depth':data.get('collision_depth',manifest['suggested_collision']['depth_px']),
                  'collision_usage':data.get('collision_usage',manifest['suggested_collision'].get('usage',KINDS[manifest.get('asset_kind','rock')]['collision_usage']))}
        return package(root,original,spec,source=folder,settings=settings,
                       provenance={**manifest['provenance'],'parent_kit':source_id,'this_build':'reuse_no_ai_call'})


def execute(root,job_id):
    folder=AssetRepository(root).scoped('.local/props/jobs/'+name(job_id),'.local/props/jobs')
    with task_lock(root):
        job=read(folder/'job.json')
        def progress(stage):
            job.update(status='running',stage=stage.replace('地面材质','完整物件'),error=None)
            atomic(folder/'job.json',job)
        try:
            published=job.get('kit_id',job_id)
            target=Path(root)/'prop-kits'/published
            if target.exists(): load_package(root,published)
            else:
                if job['spec'].get('wall_axis') or job['spec'].get('wall_corner_build'):
                    from wall_assets import verify_reference
                    verify_reference(folder,job['spec'])
                progress('准备物件原图')
                if job['spec']['mode']=='ai':
                    generated=folder/'inputs/ground.png'
                    receipt=read(folder/'generation.json',{}).get('ground',{})
                    if not generated.is_file() or hashlib.sha256(generated.read_bytes()).hexdigest()!=receipt.get('sha256'):
                        generate_materials(folder,job['spec'],progress)
                    else:
                        progress('复用已生成的完整物件原图')
                    shutil.copyfile(generated,folder/'inputs/original.png')
                progress('透明背景处理与素材导出')
                if job['spec'].get('wall_corner_build'):
                    progress('切分转角与两轴直墙并验证接口')
                    from wall_corner import build_job
                    manifest=build_job(root,folder,job['spec'])
                    job['kit_id']=manifest['id']
                elif job['spec'].get('wall_strip_build'):
                    progress('自动选择切点并验证重复拼接')
                    from wall_strip import build_job
                    manifest=build_job(root,folder,job['spec'])
                    job['kit_id']=manifest['id']
                elif job['spec'].get('wall_axis'):
                    from wall_assets import publish
                    manifest=publish(root,folder,job['spec'])
                    job['kit_id']=manifest['id']
                else:
                    with Image.open(folder/'inputs/original.png') as image:
                        package(root,image.convert('RGBA'),job['spec'],job_id,source=folder)
            job.update(status='complete',stage='物件素材已完成',kit_id=job.get('kit_id',job_id),error=None)
        except Exception as error:
            job.update(status='failed',stage='制作失败',error=str(error))
        atomic(folder/'job.json',job)




def module_settings(manifest):
    """One adapter for legacy prop packages and current annotation versions."""
    from sprite_contract import settings
    if manifest.get('module_settings'):
        return settings(manifest['module_settings'])
    suggestion=manifest['suggested_collision']
    shapes=suggestion.get('polygons')
    if shapes is None: shapes=[suggestion['polygon']] if suggestion.get('polygon') else []
    # Optional legacy footprints remain opt-in, as stated in their source contract.
    blocking=suggestion.get('usage')=='blocking' and bool(shapes)
    return settings(dict(title=manifest['title'],anchor=manifest['anchor_px'],
                         behavior='blocking' if blocking else 'passable',polygons=shapes if blocking else []))


def _publish_annotation(root, files, manifest, config):
    """Publish an immutable prop version without touching its raster art."""
    package_id=identity();manifest=json.loads(json.dumps(manifest))
    manifest.update(id=package_id,title=config['title'],created_at=datetime.now(timezone.utc).isoformat(),
        anchor_px=config['anchor'],sprite_offset_px=[-v for v in config['anchor']],module_settings=config,
        production_ready=False)
    manifest['display_spec']=dict(world_scale=config['world_scale'],
        canvas_world_units=[v*config['world_scale'] for v in manifest['canvas_px']],
        reference_cell_units=[128,64],units='screen_world_units',transform='uniform_scale_about_anchor')
    shapes=config['polygons'];points=[p for poly in shapes for p in poly]
    width=max(p[0] for p in points)-min(p[0] for p in points) if points else 1
    depth=max(p[1] for p in points)-min(p[1] for p in points) if points else 1
    manifest['suggested_collision']=dict(enabled_by_default=False,suggestions_only=True,
        coordinate_space='anchor_local_px',polygons=shapes,polygon=shapes[0] if len(shapes)==1 else [],
        width_px=width,depth_px=depth,usage='none' if not shapes else 'blocking',
        source='manual_convex_regions',layers_and_masks='caller_defined',
        note='polygons is authoritative; polygon is populated only for a single region')
    manifest['validation']=dict(art='pending',anchor='manual_annotation',engine_physics='not_tested',occlusion='not_tested')
    with Image.open(BytesIO(files['sprite.png'])) as im:
        rgba=im.convert('RGBA');w,h=rgba.size
    preview=Image.new('RGB',(w*3,h))
    for i,color in enumerate(('#e3e6dc','#34443e','#8a9a82')):
        layer=Image.new('RGB',(w,h),color);layer.paste(rgba,(0,0),rgba);preview.paste(layer,(i*w,0))
    stream=BytesIO();preview.save(stream,format='PNG');files['preview.png']=stream.getvalue()
    overlay=Image.new('RGB',(w,h),'#34443e');overlay.paste(rgba,(0,0),rgba);draw=ImageDraw.Draw(overlay)
    x,y=config['anchor']
    for poly in shapes:
        p=[(a+x,b+y) for a,b in poly];draw.line(p+[p[0]],fill='#ff9a7c',width=2)
    draw.line([(x-6,y),(x+6,y)],fill='#7affa4',width=2);draw.line([(x,y-6),(x,y+6)],fill='#7affa4',width=2)
    stream=BytesIO();overlay.save(stream,format='PNG');files['anchor_collision.png']=stream.getvalue()
    files['module-settings.json']=json.dumps(config,ensure_ascii=False,indent=2).encode()
    files['INTEGRATION.md']=('# Sprite settings\n\nAnchor: image pixels; collision polygons: anchor-local screen pixels, Y down.\n'
        'module_settings.world_scale (default 1) converts image pixels to scene units. Multiply image dimensions, anchor offsets and collision vertices by the SAME scalar; instance positions remain world units. Never resample the original PNG.\n'
        'module_settings / module-settings.json and suggested_collision.polygons describe all convex regions.\n'
        'For openings, keep the gap between polygons. Do not fill it with a bounding box.\n'
        'These are manual annotations, not verified physics or occlusion. Original raster art is unchanged.\n').encode()
    manifest['files_sha256']={k:hashlib.sha256(v).hexdigest() for k,v in files.items()}
    raw=json.dumps(manifest,ensure_ascii=False,indent=2).encode()
    staging=AssetRepository(root).scoped('.local/prop-builds/'+package_id,'.local/prop-builds');staging.mkdir(parents=True)
    try:
        for relative,content in files.items():
            file=staging/relative;file.parent.mkdir(parents=True,exist_ok=True);file.write_bytes(content)
        (staging/'manifest.json').write_bytes(raw)
        with zipfile.ZipFile(staging/'kit.zip','w',zipfile.ZIP_DEFLATED) as archive:
            for relative,content in files.items():archive.writestr(relative,content)
            archive.writestr('manifest.json',raw)
        target=Path(root)/'prop-kits'/package_id;target.parent.mkdir(parents=True,exist_ok=True);staging.rename(target)
    except Exception:
        shutil.rmtree(staging,ignore_errors=True);raise
    return manifest


def annotate(root,data):
    from sprite_contract import settings
    config=settings(data)
    with task_lock(root):
        source_id=name(data.get('source_kit'));manifest=load_package(root,source_id)
        if data.get('source_sha256') and hashlib.sha256((Path(root)/'prop-kits'/source_id/'kit.zip').read_bytes()).hexdigest()!=data['source_sha256']:
            raise ValueError('素材来源已变化，请重新载入')
        with zipfile.ZipFile(Path(root)/'prop-kits'/source_id/'kit.zip') as archive:
            files={n:archive.read(n) for n in manifest['files_sha256']}
        if manifest.get('wall_connectors'):
            old_anchor=module_settings(manifest)['anchor']
            connectors=manifest['wall_connectors']
            for endpoint in ('start','end'):
                connectors[endpoint]=[n+old_anchor[i]-config['anchor'][i] for i,n in enumerate(connectors[endpoint])]
            files['wall-connectors.json']=json.dumps(connectors).encode()
        manifest['provenance']={**manifest.get('provenance',{}),'parent_kit':source_id,'this_build':'annotation_no_ai_no_raster_change'}
        return _publish_annotation(root,files,manifest,config)


def from_building(root,data):
    """Register an immutable building delivery in the shared sprite editor.

    The original building ZIP travels inside the derived library version. Art is
    unchanged; view is a caller-declared scene compatibility choice.
    """
    from building_pipeline import load_package as load_building
    with task_lock(root):
        original=load_building(root,name(data.get('kit')))
        path=Path(root)/'building-kits'/original['id']
        integration=read(path/'integration.json')
        with Image.open(path/'sprite.png') as image:size=list(image.size)
        raw=(path/'sprite.png').read_bytes();source=(path/'kit.zip').read_bytes()
        from sprite_contract import settings
        config=settings(dict(title=original['title'],anchor=integration['anchor_px'],behavior='passable',polygons=[]))
        files={'sprite.png':raw,'cutout.png':raw,'inputs/original.png':raw,'inputs/source-building.zip':source,
            'production.json':json.dumps(dict(mode='building_delivery_adapter',source=original['id'])).encode(),'prompt.txt':b''}
        manifest=dict(schema='studio.static-prop/0.1',asset_family='static_prop',asset_kind='custom',
            view=validate_projection(data.get('projection',ISOMETRIC),'orthographic_three_quarter'),canvas_px=size,
            provenance=dict(art_source='studio_building_delivery',parent_building=original['id'],
                source_building_sha256=hashlib.sha256(source).hexdigest(),this_build='building_adapter_no_raster_change'),
            processing=dict(method='building_delivery_adapter'),normalization={},limitations=['Building projection needs visual review; no collision inferred.'])
        return _publish_annotation(root,files,manifest,config)


def import_exact(root,data):
    """Common library import for already prepared transparent game sprites."""
    from sprite_contract import settings
    raw=base64.b64decode(data.get('image','').split(',')[-1],validate=True)
    if not raw or len(raw)>8*1024*1024:raise ValueError('PNG需小于8MB')
    with Image.open(BytesIO(raw)) as image:
        if image.format!='PNG' or image.mode not in ('RGBA','LA') or max(image.size)>2048:
            raise ValueError('请导入不超过2048px的透明PNG')
        image.load()
        if image.getchannel('A').getextrema()[0]==255:raise ValueError('PNG需要包含透明背景')
        size=list(image.size)
    config=settings(dict(title=data.get('title'),anchor=[size[0]/2,size[1]],behavior='passable',polygons=[]))
    view=validate_projection(data.get('projection',ISOMETRIC),'orthographic_three_quarter')
    files={k:raw for k in ('sprite.png','cutout.png','inputs/original.png')}
    spec=dict(title=config['title'],mode='import',kind='custom',size=size[0],projection=view,description='',collision_usage='none')
    files.update({'production.json':json.dumps(spec).encode(),'prompt.txt':b''})
    manifest=dict(schema='studio.static-prop/0.1',asset_family='static_prop',asset_kind='custom',view=view,
        provenance={'art_source':'external_complete_object','this_build':'exact_png_import_no_raster_change'},canvas_px=size,
        image='sprite.png',processing={'method':'exact_png_import'},normalization={'world_scale':'caller_defined'},limitations=[])
    with task_lock(root):return _publish_annotation(root,files,manifest,config)


if __name__=='__main__':
    import sys
    root=Path(__file__).resolve().parent.parent
    with task_lock(root,inherited_fd=int(sys.argv[2])): execute(root,sys.argv[1])
