"""Experimental corner-based two-material terrain kit. No image API calls.

Each grid vertex stores a material, and four shared vertices select one of 16
tiles. This is a corner Wang set, not the existing four-exit road convention.
"""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import secrets
import zipfile

import numpy as np
from PIL import Image, ImageFilter

from asset_repository import AssetRepository, atomic, name, read
from task_lock import task_lock
from terrain import variant_at
from terrain_integrity import inspect, require


def mask(size, bits, ground, variant):
    y,x=np.meshgrid(np.linspace(0,1,size),np.linspace(0,1,size),indexing='ij')
    nw,ne,se,sw=[float(bool(bits&bit)) for bit in (1,2,4,8)]
    field=nw*(1-x)*(1-y)+ne*x*(1-y)+se*x*y+sw*(1-x)*y
    fade=np.clip(np.minimum.reduce([x,y,1-x,1-y])/.16,0,1)
    # Shared edge samples never depend on the tile's other corners or variant.
    gray=ground.convert('L')
    detail=(np.array(gray,dtype=float)-np.array(gray.filter(ImageFilter.GaussianBlur(2)),dtype=float))/255
    irregular=(.025*np.sin(29*x+7*y+variant)*np.sin(25*y-9*x)
               +.014*np.sin(71*x+19*y)+detail*.35)*fade
    # Resolve diagonal saddles consistently: sand joins through the centre.
    if bits in (5,10): field+=.075*fade
    alpha=np.clip(.5+(field-.5+irregular)/.12,0,1)
    return Image.fromarray(np.rint(alpha*255).astype('uint8'))


def validate_edges(tiles):
    worst,pairs=0,0
    arrays=[[np.array(t,dtype=np.int16) for t in group] for group in tiles]
    for va in arrays:
        for vb in arrays:
            for a in range(16):
                for b in range(16):
                    horizontal=(bool(a&2)==bool(b&1) and bool(a&4)==bool(b&8))
                    vertical=(bool(a&8)==bool(b&1) and bool(a&4)==bool(b&2))
                    for matches,ea,eb in [(horizontal,va[a][:,-1],vb[b][:,0]),
                                          (vertical,va[a][-1],vb[b][0])]:
                        if matches:
                            pairs+=1;worst=max(worst,int(np.abs(ea-eb).max()))
    return {'passed':worst==0,'matching_edge_pairs':pairs,'max_channel_difference':worst}


def shoreline_tile(base, water, coverage):
    """Static shallow-water and damp-bank bands from shared corner coverage.

    Pointwise operations preserve the shared edge samples and pure source tiles.
    No directional shadow: every bank orientation uses the same material rule.
    """
    a=np.array(coverage,dtype=float)[:,:,None]/255
    land=np.array(base,dtype=float)
    wet=np.clip(1-abs(a-.24)/.24,0,1)*.22
    land=land*(1-wet)
    surface=np.array(water,dtype=float)
    shallow=np.clip(1-abs(a-.58)/.42,0,1)*.32
    # A little bank colour under the water conveys a visible shallow bottom.
    bottom=np.clip(np.array(base,dtype=float)*.55+np.array([95,88,60]),0,255)
    surface=surface*(1-shallow)+bottom*shallow
    pixels=surface*a+land*(1-a)
    return Image.fromarray(np.clip(np.rint(pixels),0,255).astype('uint8'))


def pond_vertices(width=16,height=10):
    y,x=np.indices((height+1,width+1),dtype=float)
    water=((x-9)/5.6)**2+((y-4.8)/3.6)**2<1
    water[((x-10)/1.25)**2+((y-4.5)/1.2)**2<1]=False
    water[((x-2.3)/1.5)**2+((y-7.5)/1.5)**2<1]=True
    return water.astype(int).tolist()


def example_vertices(width=16,height=10):
    y,x=np.indices((height+1,width+1),dtype=float)
    # Coastline, a grass island in the desert, and a small sand patch in grass.
    coast=7.5+1.3*np.sin(y*.65)+.65*np.sin(y*1.7)
    sand=x>coast
    sand[((x-12.5)/1.9)**2+((y-5)/2.1)**2<1]=False
    sand[((x-3)/1.5)**2+((y-7)/1.5)**2<1]=True
    return sand.astype(int).tolist()


def render(tiles,vertices,size):
    h,w=len(vertices)-1,len(vertices[0])-1
    result=Image.new('RGB',(w*size,h*size))
    for y in range(h):
        for x in range(w):
            bits=(vertices[y][x]+vertices[y][x+1]*2+
                  vertices[y+1][x+1]*4+vertices[y+1][x]*8)
            result.paste(tiles[variant_at(x,y,len(tiles))][bits],(x*size,y*size))
    return result


def catalog(root):
    assets=AssetRepository(root)
    result=[]
    for path in sorted((assets.root/'terrain-transitions').glob('*/manifest.json'),reverse=True):
        if path.parent.is_symlink(): continue
        item=read(path)
        if item and item.get('schema')=='studio.terrain-transition/0.1':
            item['integrity']=inspect(root,'terrain-transitions',path.parent.name)
            result.append(item)
    return result


def build(root,grass_kit,sand_kit,size=64,title='草地与沙地共存实验',interactive=True,mode='surface'):
    if mode not in ('surface','shoreline'): raise ValueError('过渡类型须为普通地表或水岸')
    if type(size) is not int or size not in (32,64,128): raise ValueError('尺寸须为32/64/128')
    if not isinstance(title,str) or not 1<=len(title.strip())<=60: raise ValueError('名称需为1–60字')
    if grass_kit==sand_kit: raise ValueError('请选择两个不同的地表套件')
    assets=AssetRepository(root)
    with task_lock(root):
        inputs=[];sources=[]
        for kit in (grass_kit,sand_kit):
            kit=name(kit)
            require(root,'terrain-kits',kit)
            manifest_path=assets.scoped(f'terrain-kits/{kit}/manifest.json',f'terrain-kits/{kit}')
            manifest=read(manifest_path)
            path=assets.scoped(f'terrain-kits/{kit}/inputs/ground.png',f'terrain-kits/{kit}')
            if not manifest or not path.is_file(): raise ValueError('来源套件缺少地面材质')
            if manifest.get('tile_size')!=size:
                raise ValueError('过渡尺寸须与两个来源套件一致；请先重新制作相同尺寸的地表套件')
            sha=hashlib.sha256(path.read_bytes()).hexdigest()
            if sha!=manifest.get('source_sha256',{}).get('ground.png'): raise ValueError('来源材质已变化')
            groups=manifest.get('variants') or [{'ground':manifest['ground']}]
            delivered=[];fingerprints=[]
            for group in groups:
                relative=group['ground']
                ground_path=assets.scoped(f'terrain-kits/{kit}/{relative}',f'terrain-kits/{kit}')
                with Image.open(ground_path) as image:
                    if image.size!=(size,size): raise ValueError('来源成品地表尺寸与清单不一致')
                    delivered.append(image.convert('RGB'))
                fingerprints.append({'source':relative,'sha256':hashlib.sha256(ground_path.read_bytes()).hexdigest()})
            inputs.append(delivered)
            sources.append({'kit':kit,'sha256':sha,'source':'inputs/ground.png',
                            'finish':manifest.get('finish','classic'),'ground_variants':fingerprints})
        identity=datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+secrets.token_hex(4)
        destination=assets.scoped('terrain-transitions/'+identity,'terrain-transitions')
        folder=assets.scoped('.local/terrain-transition-builds/'+identity,'.local/terrain-transition-builds')
        folder.mkdir(parents=True)
        (folder/'inputs').mkdir();(folder/'tiles').mkdir()
        if mode=='shoreline': (folder/'masks').mkdir()
        for role,images in zip(('base','overlay'),inputs):
            for index,image in enumerate(images): image.save(folder/'inputs'/f'{role}_v{index}.png')
        grass,sand=inputs
        count=max(len(grass),len(sand))
        if count%len(grass) or count%len(sand): raise ValueError('来源变化组数量不兼容')
        atlas=Image.new('RGB',(size*4,size*4*count))
        tiles=[];entries=[]
        for v in range(count):
            base,overlay=grass[v%len(grass)],sand[v%len(sand)]
            group=[]
            for bits in range(16):
                coverage=mask(size,bits,base,v)
                tile=(shoreline_tile(base,overlay,coverage) if mode=='shoreline'
                      else Image.composite(overlay,base,coverage))
                path=f'tiles/terrain_{bits:02d}_v{v}.png';tile.save(folder/path)
                cell=[bits%4,v*4+bits//4];atlas.paste(tile,(cell[0]*size,cell[1]*size))
                group.append(tile);entries.append({'corners':bits,'variant':v,'atlas_cell':cell,'image':path})
                if mode=='shoreline':
                    relative=f'masks/water_{bits:02d}_v{v}.png'
                    coverage.save(folder/relative)
                    entries[-1]['water_mask']=relative
            tiles.append(group)
        report=validate_edges(tiles)
        if not report['passed']: raise ValueError('地形边缘检查失败')
        vertices=pond_vertices() if mode=='shoreline' else example_vertices()
        atlas.save(folder/'atlas.png');render(tiles,vertices,size).save(folder/'preview.png')
        atomic(folder/'manifest.json',{'schema':'studio.terrain-transition/0.1','id':identity,
            'title':title.strip(),'tile_size':size,'sources':sources,'ai_calls':0,
            'transition_mode':mode,
            'asset_family':'water' if mode=='shoreline' else 'surface',
            'asset_role':'shoreline_kit' if mode=='shoreline' else 'surface_transition',
            'corners':{'northwest':1,'northeast':2,'southeast':4,'southwest':8},
            'material_bits':{'0':'base','1':'overlay'},'diagonal_policy':'overlay_connected',
            'variants':count,'source_policy':'delivered_ground_exact','tiles':entries,'example_vertices':vertices,'validation':report,
            'art_review':'pending','limitations':['共用边缘仍有重复痕迹','二值顶点模型，不能表示任意宽度的微小地形',
                '斜向相对角同为第二地表时，中心优先连第二地表；不是47块地形集或道路位掩码']})
        (folder/'INTEGRATION.md').write_text(
            '# 双地表过渡套件\n\n每个网格顶点存0（第一个来源地表）或1（第二个来源地表）。每格取四角：'
            '左上×1＋右上×2＋右下×4＋左下×8，选择对应corners编号。'
            '同一顶点必须在相邻格共享。变化组数量见清单，可任意搭配；纯地表像素与来源成品一致。'
            '两对角为第二地表时中心连第二地表。不要按道路出口位掩码解释本套素材。\n\n'
            'preview.png仅为固定验收样例，展示大面积交界、岛及独立地表斑块。'
            '单组来源搭配多组来源时，单组按组号取模复用。来源成品及各自指纹记录在 sources[].ground_variants。'
            '本次复用已有成品地表，无新增AI调用。\n',encoding='utf-8')
        if mode=='shoreline':
            with (folder/'INTEGRATION.md').open('a',encoding='utf-8') as output:
                output.write('\n## 静态水岸\n\n第一来源为陆地，第二来源为水面。程序在边界生成湿岸和浅水带，'
                             '纯陆地和纯水块保留来源像素。masks/ 为各块水面覆盖率（0=陆，255=水），'
                             '用于后续水面效果；它不是深度、碰撞或可行走数据。preview.png 为固定池塘、岛与小水洼样例。'
                             '当前只交付静态素材，没有水流、波纹动画、倒影或物理效果。\n')
        if interactive: (folder/'index.html').write_text(HTML,encoding='utf-8')
        manifest=read(folder/'manifest.json')
        if mode=='shoreline':
            manifest['water']={'animated':False,'land_source':0,'water_source':1,
                               'mask_channel':'L','mask_range':[0,255],
                               'shoreline_profile':'damp_bank_shallow_bottom_v1'}
            manifest['limitations'].append('静态水面，无波纹动画、水流、倒影或碰撞数据')
        manifest['files_sha256']={str(p.relative_to(folder)):hashlib.sha256(p.read_bytes()).hexdigest()
                                  for p in sorted(folder.rglob('*')) if p.is_file() and p.name!='manifest.json'}
        atomic(folder/'manifest.json',manifest)
        with zipfile.ZipFile(folder/'kit.zip','w',zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(folder.rglob('*')):
                if path.is_file() and path.name!='kit.zip': archive.write(path,str(path.relative_to(folder)))
        destination.parent.mkdir(parents=True,exist_ok=True)
        folder.rename(destination)
        return destination


HTML='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Studio · 草地与沙地共存实验</title><style>
body{margin:0;background:#f4f5f2;color:#25362e;font:14px/1.7 system-ui}main{max-width:1100px;margin:28px auto;padding:0 20px}h1{font-size:26px;margin:10px 0}p{color:#68786c}button,a,select{font:inherit;padding:8px 12px;border:1px solid #d0d9cd;border-radius:6px;background:white;color:inherit}header{display:flex;gap:12px;align-items:center;flex-wrap:wrap}.stage{overflow:auto;background:white;padding:14px;border:1px solid #dfe5df;border-radius:10px;margin:20px 0}canvas{width:100%;height:auto;display:block;image-rendering:pixelated;touch-action:none}a{text-decoration:none}#tiles{width:256px;height:auto;image-rendering:pixelated}#status{font-size:12px}</style>
<main><header><a href="http://127.0.0.1:61922/terrain.html">← 地面与道路工作台</a><span>GAME ASSET STUDIO / EXPERIMENT</span></header>
<h1>草地与沙地共存</h1><p>已有 AI 材质 + 程序过渡 · 不新增 AI 调用。点击或拖动改变最近的地表顶点，相邻格同步更新。</p>
<header><label>笔刷 <select id="brush"><option value="1">沙地</option><option value="0">草地</option></select></label><button id="reset">示例布局</button><button id="grass">全部草地</button><button id="sand">全部沙地</button><a href="kit.zip" download>下载实验套件</a></header>
<div class="stage"><canvas id="map" aria-label="草沙交界绘制预览"></canvas></div><p id="status">正在加载…</p><details><summary>查看64个过渡块</summary><img id="tiles" src="atlas.png" alt="四组16种角点组合"></details></main>
<script>
let manifest,vertices,atlas;const canvas=document.querySelector('#map'),ctx=canvas.getContext('2d');
function variant(x,y){let v=(Math.imul(x,374761393)^Math.imul(y,668265263)^17)>>>0;v=Math.imul(v^(v>>>13),1274126177)>>>0;return ((v^(v>>>16))>>>0)%manifest.variants;}
function draw(){const s=manifest.tile_size,h=vertices.length-1,w=vertices[0].length-1;canvas.width=w*s;canvas.height=h*s;ctx.imageSmoothingEnabled=false;for(let y=0;y<h;y++)for(let x=0;x<w;x++){const b=vertices[y][x]+vertices[y][x+1]*2+vertices[y+1][x+1]*4+vertices[y+1][x]*8;const tile=manifest.tiles[variant(x,y)*16+b];ctx.drawImage(atlas,tile.atlas_cell[0]*s,tile.atlas_cell[1]*s,s,s,x*s,y*s,s,s);}}
function paint(e){if(!manifest)return;const r=canvas.getBoundingClientRect(),h=vertices.length-1,w=vertices[0].length-1;const x=Math.max(0,Math.min(w,Math.round((e.clientX-r.left)/r.width*w))),y=Math.max(0,Math.min(h,Math.round((e.clientY-r.top)/r.height*h)));vertices[y][x]=Number(document.querySelector('#brush').value);draw();}
let down=false;canvas.onpointerdown=e=>{down=true;canvas.setPointerCapture(e.pointerId);paint(e)};canvas.onpointermove=e=>{if(down)paint(e)};canvas.onpointerup=canvas.onpointercancel=()=>down=false;
document.querySelector('#reset').onclick=()=>{if(manifest){vertices=structuredClone(manifest.example_vertices);draw()}};for(const [id,value]of [['grass',0],['sand',1]])document.querySelector('#'+id).onclick=()=>{if(vertices){vertices=vertices.map(row=>row.map(()=>value));draw()}};
(async()=>{try{manifest=await(await fetch('manifest.json')).json();atlas=new Image();atlas.src='atlas.png';await atlas.decode();vertices=structuredClone(manifest.example_vertices);draw();document.querySelector('#status').textContent=manifest.validation.matching_edge_pairs+' 对合法连接边缘通过 · 最大通道差 '+manifest.validation.max_channel_difference+' · 待美术复核。对角相遇时沙地优先连接。'}catch(e){document.querySelector('#status').textContent=e.message}})();
</script></html>'''


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--grass-kit',required=True);parser.add_argument('--sand-kit',required=True)
    parser.add_argument('--tile-size',type=int,default=64)
    args=parser.parse_args()
    print(build(Path(__file__).resolve().parent.parent,args.grass_kit,args.sand_kit,args.tile_size))
