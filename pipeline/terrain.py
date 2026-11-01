"""Deterministic top-down ground / four-way road kit compiler."""
import base64
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
from pathlib import Path
import secrets
import shutil
import zipfile

import numpy as np
from PIL import Image, ImageFilter

from asset_repository import AssetRepository, atomic, name, read
from task_lock import task_lock

DEFAULT_DESCRIPTION = '手绘游戏素材，浅绿色草地，浅褐色泥土路，少量细碎石，柔和色彩。'
DIRECTIONS = [('north', 1, 0, -1), ('east', 2, 1, 0),
              ('south', 4, 0, 1), ('west', 8, -1, 0)]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def decode_image(content):
    try:
        raw = base64.b64decode(content, validate=True)
        if not raw or len(raw) > 8 * 1024 * 1024:
            raise ValueError('每张图片需小于 8 MB')
        with Image.open(BytesIO(raw)) as image:
            if min(image.size) < 32 or image.width * image.height > 16_000_000:
                raise ValueError('图片需至少 32px，且不超过 1600 万像素')
            image.load()
            rgba = image.convert('RGBA')
            if rgba.getchannel('A').getextrema() != (255, 255):
                raise ValueError('材质和参考图须为不透明图片，请先合成背景')
            return rgba.convert('RGB')
    except (OSError, TypeError, Image.DecompressionBombError):
        raise ValueError('请选择有效的 PNG / JPEG / WebP 图片') from None


def validate(data):
    title, description = data.get('title'), data.get('description')
    if not isinstance(title, str) or not 1 <= len(title.strip()) <= 60:
        raise ValueError('套件名称需为 1–60 字')
    if not isinstance(description, str) or not 1 <= len(description.strip()) <= 2000:
        raise ValueError('请填写 1–2000 字的素材描述')
    size, width = data.get('tile_size', 64), data.get('road_width', 0.5)
    if type(size) is not int or size not in (32, 64, 128):
        raise ValueError('格子尺寸须为 32 / 64 / 128')
    if type(width) not in (int, float) or not 0.25 <= width <= 0.65:
        raise ValueError('道路宽度须为格子的 25%–65%')
    mode = data.get('mode', 'ai')
    if mode not in ('ai', 'import', 'demo', 'reuse'):
        raise ValueError('未知素材来源')
    finish = data.get('finish', 'natural')
    if finish not in ('natural', 'classic'):
        raise ValueError('未知素材处理方案')
    asset_type=data.get('asset_type','terrain')
    if asset_type not in ('terrain','material'): raise ValueError('未知素材类型')
    material_kind=data.get('material_kind','generic')
    if material_kind not in ('generic','grass','sand','water','stone'): raise ValueError('未知材质分类')
    return dict(asset_type=asset_type, material_kind=material_kind, title=title.strip(), description=description.strip(), tile_size=size,
                road_width=width, mode=mode, view='top_down', seed=17, finish=finish)


def periodic(image, size):
    """Repair a narrow edge band, preserving the interior; opposite pixels match."""
    a = np.array(image.resize((size, size), Image.Resampling.LANCZOS), dtype=float)
    band = max(2, size // 8)
    for axis in (1, 0):
        b = np.swapaxes(a, 0, axis)
        target = (b[0] + b[-1]) / 2
        left, right = target - b[0], target - b[-1]
        for i in range(band):
            weight = (1 - i / band) ** 2
            b[i] += left * weight
            b[-1-i] += right * weight
    return Image.fromarray(np.clip(np.rint(a), 0, 255).astype('uint8'))


def demo_material(size, color, seed):
    """Explicitly labelled procedural fixture, never an AI-generated asset."""
    rng = np.random.default_rng(seed)
    noise = np.zeros((size, size))
    for resolution, amplitude in ((4, 9), (16, 5), (size, 3)):
        coarse = Image.fromarray(rng.integers(0, 256, (resolution, resolution), dtype='uint8'))
        noise += (np.array(coarse.resize((size, size), Image.Resampling.BICUBIC)) / 255 - .5) * amplitude
    a = np.clip(np.array(color)[None, None, :] + noise[:, :, None], 0, 255).astype('uint8')
    return Image.fromarray(a)


def road_mask(size, bits, width):
    # Endpoint-inclusive samples make every exit share an identical cross-section.
    y, x = np.meshgrid(np.linspace(-.5, .5, size), np.linspace(-.5, .5, size), indexing='ij')
    radius = width / 2
    distance = np.hypot(x, y) - radius
    for _, bit, dx, dy in DIRECTIONS:
        if bits & bit:
            along, across = x * dx + y * dy, -x * dy + y * dx
            rectangle = np.maximum(abs(across) - radius, -along)
            distance = np.minimum(distance, rectangle)
    # Edge irregularity fades out before tile boundaries so exits remain invariant.
    fade = np.clip((.5 - np.maximum(abs(x), abs(y))) / .18, 0, 1)
    wobble = .012 * np.sin(23*x + 8*y) * np.sin(19*y - 4*x) * fade
    coverage = np.clip(.5 - (distance + wobble) * size / 1.5, 0, 1)
    return Image.fromarray(np.rint(coverage * 255).astype('uint8'))


def material_variants(image, size, count=4):
    """Use local 256px patches instead of squeezing a whole 1024px texture.

    All variants share a blended boundary ring, allowing independent cell choice.
    """
    image = image.convert('RGB')
    span = min(256, image.width, image.height)
    locations = [(0.2, .2), (.8, .2), (.2, .8), (.8, .8)]
    patches = []
    for px, py in locations[:count]:
        x = round((image.width-span)*px); y = round((image.height-span)*py)
        patch=image.crop((x,y,x+span,y+span)).resize((size,size),Image.Resampling.LANCZOS)
        pixels=np.array(patch,dtype=float)
        broad=np.array(patch.filter(ImageFilter.GaussianBlur(size/8)),dtype=float)
        # Reduce the broad light/dark islands that reveal repeated tiles.
        patches.append(np.clip(pixels-.6*(broad-broad.mean(axis=(0,1))),0,255))
    target = np.mean([p.mean(axis=(0,1)) for p in patches],axis=0)
    patches = [np.clip(p + target-p.mean(axis=(0,1)),0,255) for p in patches]
    shared = np.array(periodic(Image.fromarray(patches[0].astype('uint8')),size),dtype=float)
    yy, xx = np.indices((size,size))
    edge = np.minimum.reduce([xx,yy,size-1-xx,size-1-yy])
    blend = np.clip(edge/max(3,size*.12),0,1)
    blend = (blend*blend*(3-2*blend))[:,:,None]
    return [Image.fromarray(np.rint(shared*(1-blend)+p*blend).astype('uint8')) for p in patches]


def natural_mask(size, bits, width, ground, variant):
    y,x=np.meshgrid(np.linspace(-.5,.5,size),np.linspace(-.5,.5,size),indexing='ij')
    radius=width/2
    distance=np.hypot(x,y)-radius
    for _,bit,dx,dy in DIRECTIONS:
        if bits&bit:
            along,across=x*dx+y*dy,-x*dy+y*dx
            arm=np.maximum(abs(across)-radius,-along)
            # A smooth union softens the internal corners of bends and junctions.
            h=np.clip(1-abs(distance-arm)/.08,0,1)
            distance=np.minimum(distance,arm)-h*h*.08/4
    fade=np.clip((.5-np.maximum(abs(x),abs(y)))/.14,0,1)
    gray=ground.convert('L')
    detail=(np.array(gray,dtype=float)-np.array(gray.filter(ImageFilter.GaussianBlur(2)),dtype=float))/18
    waviness=(np.sin(17*x+9*y+variant)*np.sin(21*y-5*x-variant)*1.3
              + np.sin(47*x+13*y)*.4 + detail*.9)
    transition=max(2,size*.075)
    alpha=np.clip(.5-(distance*size+waviness*fade)/transition,0,1)
    return Image.fromarray(np.rint(alpha*255).astype('uint8'))


def variant_at(x, y, count, seed=17):
    value=((x*374761393)^(y*668265263)^seed)&0xffffffff
    value=((value^(value>>13))*1274126177)&0xffffffff
    return (value^(value>>16))%count


def seam_report(tiles):
    arrays = [np.array(tile, dtype=np.int16) for tile in tiles]
    errors = []
    for a in range(16):
        for b in range(16):
            if bool(a & 2) == bool(b & 8):
                errors.append(int(np.abs(arrays[a][:, -1] - arrays[b][:, 0]).max()))
            if bool(a & 4) == bool(b & 1):
                errors.append(int(np.abs(arrays[a][-1] - arrays[b][0]).max()))
    return {'matching_edge_pairs': len(errors), 'max_channel_difference': max(errors),
            'passed': max(errors) == 0,
            'scope': '连接边缘像素一致；不代表风格、美术、纹理重复与边缘过渡已验收。'}


def sample_grid():
    grid = [[False] * 12 for _ in range(9)]
    for x in range(2, 10):
        grid[2][x] = grid[6][x] = True
    for y in range(2, 7):
        grid[y][2] = grid[y][9] = grid[y][6] = True
    for x in range(0, 12):
        grid[4][x] = True
    grid[0][6] = grid[1][6] = grid[8][4] = True
    return grid


def render_grid(ground, tiles, grid, variants=None):
    size = ground.width
    result = Image.new('RGB', (len(grid[0])*size, len(grid)*size))
    for y, row in enumerate(grid):
        for x, occupied in enumerate(row):
            bits = 0
            if occupied:
                for _, bit, dx, dy in DIRECTIONS:
                    nx, ny = x+dx, y+dy
                    if 0 <= ny < len(grid) and 0 <= nx < len(row) and grid[ny][nx]:
                        bits |= bit
            cell_ground,cell_tiles=(variants[variant_at(x,y,len(variants))] if variants else (ground,tiles))
            result.paste(cell_tiles[bits] if occupied else cell_ground, (x*size, y*size))
    return result



def compile_material(folder,spec,identity):
    size=spec['tile_size']
    with Image.open(folder/'inputs/ground.png') as source:
        images=material_variants(source,size) if spec.get('finish')=='natural' else [periodic(source.convert('RGB'),size)]
    (folder/'tiles').mkdir(exist_ok=True)
    atlas=Image.new('RGB',(size*len(images),size))
    preview=Image.new('RGB',(size*12,size*9))
    variants=[]
    for index,image in enumerate(images):
        relative='tiles/ground'+(f'_v{index}' if index else '')+'.png'
        image.save(folder/relative);atlas.paste(image,(size*index,0))
        variants.append({'id':index,'ground':relative,'ground_cell':[index,0],'tiles':[]})
    for y in range(9):
        for x in range(12): preview.paste(images[variant_at(x,y,len(images))],(x*size,y*size))
    worst=0;pairs=0
    for a in images:
        for b in images:
            aa,bb=np.array(a,dtype=np.int16),np.array(b,dtype=np.int16)
            for left,right in [(aa[:,-1],bb[:,0]),(aa[-1],bb[0])]:
                worst=max(worst,int(np.abs(left-right).max()));pairs+=1
    if worst: raise ValueError('材质边缘检查失败')
    atlas.save(folder/'atlas.png');preview.save(folder/'preview.png');images[0].save(folder/'ground_material.png')
    manifest={'schema':'studio.terrain-kit/1.1','id':identity or folder.name,**spec,
        'source_sha256':{p.name:digest(p) for p in (folder/'inputs').glob('*.png')},
        'ground':variants[0]['ground'],'ground_cell':[0,0],'variants':variants,'tiles':[],
        'variant_rule':'coordinate_hash_v1','variant_seed':17,'atlas':'atlas.png',
        'validation':{'passed':True,'matching_edge_pairs':pairs,'max_channel_difference':0},
        'art_review':'pending','limitations':['变化块共用边缘，仍需复核纹理重复和风格；不包含道路或动画。']}
    (folder/'INTEGRATION.md').write_text('# 独立材质素材\n\n按 manifest.json 的 variants[].ground 或 ground_cell 读取变化块。所有变化块可相邻使用。'
        '可作为地表过渡或静态水岸的来源。没有道路块、动画、碰撞或深度数据。边缘检查不代表美术验收。\n',encoding='utf-8')
    manifest['files_sha256']={str(p.relative_to(folder)):digest(p) for p in folder.rglob('*') if p.is_file() and p.name not in ('manifest.json','kit.zip')}
    atomic(folder/'manifest.json',manifest)
    with zipfile.ZipFile(folder/'kit.zip','w',zipfile.ZIP_DEFLATED) as archive:
        for p in sorted(folder.rglob('*')):
            if p.is_file() and p.name!='kit.zip': archive.write(p,str(p.relative_to(folder)))
    return manifest


def compile_kit(folder, spec, identity=None):
    if spec.get('asset_type')=='material': return compile_material(folder,spec,identity)
    size = spec['tile_size']
    natural = spec.get('finish') == 'natural'
    materials, choices = {}, {}
    sampling = {'method':'whole_image'}
    for role in ('ground', 'road'):
        with Image.open(folder/'inputs'/f'{role}.png') as image:
            choices[role] = material_variants(image,size) if natural else [periodic(image.convert('RGB'),size)]
            materials[role] = choices[role][0]
            if natural:
                sampling[role]={'crop_span_px':min(256,*image.size)}
                sampling['method']='local_patches'
    ground, road = materials['ground'], materials['road']
    for role, image in materials.items():
        image.save(folder/f'{role}_material.png')
    (folder/'tiles').mkdir(exist_ok=True)
    (folder/'overlays').mkdir(exist_ok=True)
    count=len(choices['ground'])
    atlas = Image.new('RGBA',(size*4,size*(count*4+1)))
    compiled, variant_entries = [], []
    for variant in range(count):
        cell_ground,cell_road=choices['ground'][variant],choices['road'][variant]
        suffix='' if variant==0 else f'_v{variant}'
        tiles,entries=[],[]
        for bits in range(16):
            mask=(natural_mask(size,bits,spec['road_width'],cell_ground,variant) if natural
                  else road_mask(size,bits,spec['road_width']))
            tile=Image.composite(cell_road,cell_ground,mask)
            tile_path=f'tiles/road_{bits:02d}{suffix}.png'
            overlay_path=f'overlays/road_{bits:02d}{suffix}.png'
            tile.save(folder/tile_path)
            overlay=cell_road.convert('RGBA');overlay.putalpha(mask);overlay.save(folder/overlay_path)
            cell=[bits%4,variant*4+bits//4]
            atlas.paste(tile,(cell[0]*size,cell[1]*size))
            tiles.append(tile)
            entries.append({'id':bits,'connections':[key for key,bit,_,_ in DIRECTIONS if bits&bit],
                            'atlas_cell':cell,'image':tile_path,'overlay':overlay_path})
        ground_cell=[variant,count*4]
        atlas.paste(cell_ground,(ground_cell[0]*size,ground_cell[1]*size))
        cell_ground.save(folder/f'tiles/ground{suffix}.png')
        compiled.append((cell_ground,tiles))
        variant_entries.append({'id':variant,'ground_cell':ground_cell,'tiles':entries,
                                'ground':f'tiles/ground{suffix}.png'})
    tiles=compiled[0][1];entries=variant_entries[0]['tiles']
    atlas.save(folder/'atlas.png')
    render_grid(ground,tiles,sample_grid(),compiled).save(folder/'preview.png')
    report = seam_report(tiles)
    # Check each variant against every other variant, not just against itself.
    worst=0;pairs=0
    for _,left_tiles in compiled:
        for _,right_tiles in compiled:
            for a in range(16):
                for b in range(16):
                    a_img=np.array(left_tiles[a],dtype=np.int16)
                    b_img=np.array(right_tiles[b],dtype=np.int16)
                    for match,edge_a,edge_b in [
                        (bool(a&2)==bool(b&8),a_img[:,-1],b_img[:,0]),
                        (bool(a&4)==bool(b&1),a_img[-1],b_img[0])]:
                        if match:
                            pairs+=1;worst=max(worst,int(np.abs(edge_a-edge_b).max()))
    report.update(matching_edge_pairs=pairs,max_channel_difference=worst,passed=worst==0)
    if not report['passed']:
        raise ValueError('道路连接边缘检查失败，未发布套件')
    sources = {p.name: digest(p) for p in sorted((folder/'inputs').glob('*.png'))}
    manifest = {'schema': 'studio.terrain-kit/1.1', 'id': identity or folder.name, **spec,
                'created_at': datetime.now(timezone.utc).isoformat(),
                'source_sha256': sources, 'atlas': 'atlas.png', 'ground': 'tiles/ground.png',
                'ground_cell': variant_entries[0]['ground_cell'],
                'variants':variant_entries,'variant_rule':'coordinate_hash_v1','variant_seed':17,
                'material_sampling':sampling,
                'directions': {'north': 1, 'east': 2, 'south': 4, 'west': 8},
                'tiles': entries, 'validation': report, 'art_review': 'pending',
                'limitations': ['固定正俯视、固定宽度、四方向道路；不支持任意宽度地形过渡。',
                                '使用边缘修复和遮罩合成；复杂材质方向、纹理尺度及过渡美术须人工复核。',
                                '变化块共用边缘带，不能彻底消除大面积重复；尚未与人物同屏验收。']}
    (folder/'INTEGRATION.md').write_text(
        '# 地面与道路套件\n\n格子尺寸见 manifest.json。所有图片以 1 倍像素和最近邻过滤显示。\n\n'
        '道路占据格子时，按北=1、东=2、南=4、西=8计算相邻道路位掩码，选择 road_00 至 road_15。'
        '没有道路的格子使用 ground.png。road_00 是孤立道路块，不是草地。\n\n'
        'tiles/ 为已合成地面的道路块；overlays/ 为透明道路层，适用于同一套地面材质。'
        'atlas.png 为4列；按 manifest.json 的 ground_cell 和 tiles[].atlas_cell 获取资源。'
        '有 variants 时，先为每格选择一个变体，再从该变体的 tiles 和 ground_cell 获取资源。'
        '所有变体之间可连接。也可使用固定种子随机选择并保存每格变体。'
        '复现预览的 coordinate_hash_v1 规则如下（Python，整数格坐标）：\n\n'
        '```python\ndef variant_at(x, y, count, seed=17):\n'
        '    v = ((x * 374761393) ^ (y * 668265263) ^ seed) & 0xffffffff\n'
        '    v = ((v ^ (v >> 13)) * 1274126177) & 0xffffffff\n'
        '    return (v ^ (v >> 16)) % count\n```\n\n'
        '边缘像素检查不等于美术验收。碰撞、导航和地形规则由接入游戏决定。\n', encoding='utf-8')
    manifest['files_sha256'] = {str(p.relative_to(folder)): digest(p)
                               for p in sorted(folder.rglob('*'))
                               if p.is_file() and p.name not in ('manifest.json','kit.zip')}
    atomic(folder/'manifest.json', manifest)
    with zipfile.ZipFile(folder/'kit.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(folder.rglob('*')):
            if path.is_file() and path.name != 'kit.zip':
                archive.write(path, str(path.relative_to(folder)))
    return manifest


def prepare(root, data):
    assets = AssetRepository(root)
    spec = validate(data)
    if spec['mode'] == 'ai':
        from terrain_images import configured
        if not configured(root):
            raise ValueError('启动 Studio 前请配置 STUDIO_IMAGE_API_KEY 或 OPENAI_API_KEY，勿将密钥填入描述')
    images = {}
    parent_generation=None
    if spec['mode']=='reuse':
        source_id=name(data.get('source_kit'))
        source=assets.scoped('terrain-kits/'+source_id,'terrain-kits')
        manifest=read(source/'manifest.json')
        if not manifest: raise ValueError('来源套件不存在')
        for role in ('ground','road','reference'):
            source_path=assets.scoped('terrain-kits/'+source_id+'/inputs/'+role+'.png','terrain-kits/'+source_id)
            expected=manifest.get('source_sha256',{}).get(role+'.png')
            if role=='reference' and not expected: continue
            if role=='road' and manifest.get('asset_type')=='material': continue
            if not source_path.is_file() or digest(source_path)!=expected:
                raise ValueError('来源材质发生变化，不能复用')
            with Image.open(source_path) as image: images[role]=image.convert('RGB')
        generation=source/'generation.json'
        if generation.is_file(): parent_generation=read(generation)
        spec['source_kit']=source_id
        spec['asset_type']=manifest.get('asset_type','terrain')
        spec['material_kind']=manifest.get('material_kind','generic')
    if data.get('reference'):
        images['reference'] = decode_image(data['reference'])
    if spec['mode'] == 'import':
        for role in (('ground',) if spec['asset_type']=='material' else ('ground','road')):
            images[role] = decode_image(data.get(role))
    elif spec['mode'] == 'demo':
        images = {'ground': demo_material(256, (112, 139, 75), 17),
                  'road': demo_material(256, (172, 143, 101), 23), **images}
    if spec['asset_type']=='material': images.pop('road',None)
    identity = datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + secrets.token_hex(4)
    folder = assets.scoped('.local/terrain/jobs/'+identity, '.local/terrain')
    (folder/'inputs').mkdir(parents=True)
    for role, image in images.items():
        image.save(folder/'inputs'/f'{role}.png')
    if parent_generation: atomic(folder/'generation.json',parent_generation)
    job = {'id': identity, 'status': 'queued', 'stage': '等待处理', 'spec': spec,
           'created_at': datetime.now(timezone.utc).isoformat(), 'error': None}
    atomic(folder/'job.json', job)
    return job


def execute(root, identity):
    assets = AssetRepository(root)
    folder = assets.scoped('.local/terrain/jobs/'+name(identity), '.local/terrain')
    job = read(folder/'job.json')
    if not job:
        raise ValueError('任务不存在')
    def persist():
        atomic(folder/'job.json', job)
    try:
        with task_lock(root):
            destination = assets.scoped('terrain-kits/'+identity, 'terrain-kits')
            if destination.exists():
                from terrain_integrity import require
                require(root,'terrain-kits',identity)
                manifest = read(destination/'manifest.json', {})
                valid = (manifest.get('id') == identity and
                         all(manifest.get(k) == v for k, v in job['spec'].items()) and
                         bool(manifest.get('files_sha256')))
                for relative, expected in manifest.get('files_sha256', {}).items():
                    path = assets.scoped('terrain-kits/'+identity+'/'+relative, 'terrain-kits/'+identity)
                    valid = valid and path.is_file() and digest(path) == expected
                if not valid: raise ValueError('已有套件文件发生变化，不能覆盖；请创建新任务')
                job.update(status='complete', stage='套件已生成，等待美术复核', kit=identity, error=None)
                persist()
                return
            job.update(status='running', error=None); persist()
            if job['spec']['mode'] == 'ai':
                from terrain_images import generate_materials
                def progress(stage):
                    job['stage'] = stage; persist()
                generate_materials(folder, job['spec'], progress)
            job['stage'] = '制作连接块与检查拼接'; persist()
            # Compile separately: never publish a partially written delivery.
            staging = folder/'build'
            if staging.exists(): shutil.rmtree(staging)
            (staging/'inputs').mkdir(parents=True)
            for path in (folder/'inputs').glob('*.png'):
                shutil.copy2(path, staging/'inputs'/path.name)
            if (folder/'generation.json').exists():
                shutil.copy2(folder/'generation.json', staging/'generation.json')
            compile_kit(staging, job['spec'], identity)
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists(): raise ValueError('套件已存在，不能覆盖')
            staging.rename(destination)
            job.update(status='complete', stage='套件已生成，等待美术复核', kit=identity)
            persist()
    except Exception as exc:
        job.update(status='failed', stage='生成中断，可继续任务', error=str(exc))
        persist()


def catalog(root):
    assets = AssetRepository(root)
    kits = []
    for path in sorted((assets.root/'terrain-kits').glob('*/manifest.json'), reverse=True):
        value = read(path)
        if value:
            from terrain_integrity import inspect
            value['integrity']=inspect(root,'terrain-kits',path.parent.name)
            kits.append(value)
    jobs = [read(path) for path in sorted((assets.root/'.local/terrain/jobs').glob('*/job.json'), reverse=True)]
    return {'kits': kits, 'jobs': [j for j in jobs if j][:30]}
