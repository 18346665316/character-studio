"""Pin an adopted character action set for immutable module-scene consumption."""
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import zipfile
from PIL import Image
from asset_repository import atomic,name,read
from sprite_contract import number

def directory(root):
    return Path(root)/'.local/scene-characters'

def snapshot(root,character,scale=.65):
    from action_set import export,inspect
    from asset_repository import AssetRepository
    name(character);number(scale)
    if not .01<=scale<=100:raise ValueError('人物比例须为0.01–100')
    report=inspect(root,character)
    if not report.get('complete'):raise ValueError('人物动作集尚不能交付，请先补齐成果或修复结构错误')
    raw=export(root,character)
    with zipfile.ZipFile(BytesIO(raw)) as z:
        prefix='character_assets/'+character+'/'
        contract=json.loads(z.read(prefix+'asset.json'))
        if contract['directions']['available_views']!=['three_quarter']:
            raise ValueError('当前等距场景需要斜俯视人物成果')
        idle=contract['actions'].get('idle')
        if not idle:raise ValueError('场景人物需要待机动作')
        image=Image.open(BytesIO(z.read(prefix+idle['texture']))).convert('RGBA')
        size=idle['frame_size'];image=image.crop((0,0,size,size))
        stream=BytesIO();image.save(stream,format='PNG');png=stream.getvalue()
    # Asset/manifest contents identify the delivery; ZIP timestamps do not.
    with zipfile.ZipFile(BytesIO(raw)) as z:
        content_hash=sha256(b''.join(n.encode()+sha256(z.read(n)).digest() for n in sorted(z.namelist()))).hexdigest()
    identity=character+'-'+sha256((content_hash+str(scale)).encode()).hexdigest()[:12]
    folder=directory(root)/identity
    if folder.exists():return load(root,identity)
    folder.mkdir(parents=True)
    manifest=dict(id=identity,character=character,title=AssetRepository(root).character(character)['display_name'],
        view='isometric_2_1',source_view='three_quarter',view_policy='use_source_authored_view_without_reprojection',
        anchor=idle['anchor_px'],world_scale=scale,behavior='passable',polygons=[],layer='objects',
        entry_scene=prefix+'character.tscn',source_sha256=sha256(raw).hexdigest(),
        actions=list(contract['actions']),body_height_px=contract['coordinates']['body_height_px'],
        validation=report)
    (folder/'source.zip').write_bytes(raw);(folder/'sprite.png').write_bytes(png)
    files={'sprite.png':png,'source.zip':raw,'manifest.json':json.dumps(manifest,ensure_ascii=False).encode()}
    with zipfile.ZipFile(folder/'kit.zip','w',zipfile.ZIP_DEFLATED) as z:
        for path,content in files.items():z.writestr(path,content)
    manifest['kit_sha256']=sha256((folder/'kit.zip').read_bytes()).hexdigest()
    atomic(folder/'manifest.json',manifest)
    return load(root,identity)

def load(root,identity):
    folder=directory(root)/name(identity);m=read(folder/'manifest.json')
    if not m:raise ValueError('人物场景版本不存在')
    if sha256((folder/'kit.zip').read_bytes()).hexdigest()!=m['kit_sha256']:raise ValueError('人物包指纹不一致')
    with zipfile.ZipFile(folder/'kit.zip') as z:
        for file in ('sprite.png','source.zip'):
            if z.read(file)!=(folder/file).read_bytes():raise ValueError('人物文件与快照不一致')
        stored=json.loads(z.read('manifest.json'))
        if stored!={k:v for k,v in m.items() if k!='kit_sha256'}:raise ValueError('人物设置与快照不一致')
    return m
