"""Expand a courtyard with shared opposite-wall periods and immutable corners."""
from pathlib import Path
from io import BytesIO
import json
import numpy as np
from PIL import Image,ImageDraw
from asset_repository import read,atomic
from wall_strip import validated_source

RECIPE='studio.courtyard-expand/1'
LIMITS=dict(roof_mae=18.,wall_mae=10.,outline_shift=1.,alpha_mismatch=.015)
ORIGIN=(512,300)
CASES=((1,1),(5,1),(1,5),(5,5),(9,7))


def runs(mask):
    indices=np.flatnonzero(mask)
    return [g for g in np.split(indices,np.flatnonzero(np.diff(indices)>1)+1) if len(g)>=16]


def select_axis(source,axis):
    rgba=np.asarray(source.convert('RGBA')).astype(float);cross=np.arange(-240,621)
    candidates=[]
    def sample(t,k):
        u,v=(t,k) if axis=='a' else (k,t)
        x=np.rint(ORIGIN[0]+u-v).astype(int);y=np.rint(ORIGIN[1]+(u+v)/2).astype(int)
        valid=(x>=0)&(x<source.width)&(y>=0)&(y<source.height)
        pixels=rgba[np.clip(y,0,source.height-1),np.clip(x,0,source.width-1)].copy()
        pixels[~valid]=0
        return pixels
    for length in range(32,161,2):
        starts=np.arange(96,353-length,2)
        tt=np.broadcast_to(starts,(len(cross),len(starts)))
        costs=[];differences=[];masks=[]
        for offset in (-1,0,1):
            left=sample(tt+offset,cross[:,None]);right=sample(tt+length+offset,cross[:,None])
            la=left[:,:,3]>127;ra=right[:,:,3]>127
            diff=np.abs(left[:,:,:3]-right[:,:,:3]).mean(2)
            costs.append(np.where(la&ra,diff,0)+np.where(la!=ra,1000.,0))
            differences.append(diff);masks.append((la,ra))
        cost=np.mean(costs,0);dp=cost[0].copy();links=np.zeros(cost.shape,dtype=int)
        for row in range(1,len(cross)):
            previous=np.stack([np.r_[np.inf,dp[:-1]]+2,dp,np.r_[dp[1:],np.inf]+2])
            links[row]=np.arange(len(starts))+previous.argmin(0)-1
            dp=cost[row]+previous.min(0)
        column=int(dp.argmin());indices=[]
        for row in range(len(cross)-1,-1,-1):
            indices.append(column);column=links[row,column]
        indices=np.asarray(indices[::-1]);rows=np.arange(len(cross))
        left,right=masks[1];la=left[rows,indices];ra=right[rows,indices]
        lr,rr=runs(la),runs(ra)
        if len(lr)!=2 or len(rr)!=2:continue
        metrics=dict(outline_shift=float(max(abs(int(a[j])-int(b[j])) for a,b in zip(lr,rr) for j in (0,-1))),
                     alpha_mismatch=float(np.mean([np.mean(a[rows,indices]!=b[rows,indices]) for a,b in masks])))
        bands=[]
        for a,b in zip(lr,rr):
            top=min(a[0],b[0]);bottom=max(a[-1],b[-1]);split=top+.45*(bottom-top)
            band={}
            for role,region in [('roof',(rows>=top)&(rows<split)),('wall',(rows>=split)&(rows<=bottom))]:
                values=[]
                for (left,right),diff in zip(masks,differences):
                    common=left[rows,indices]&right[rows,indices]&region
                    values.extend(diff[rows,indices][common].tolist())
                band[role+'_mae']=float(np.mean(values)) if values else 255.
            bands.append(band)
        for role in ('roof_mae','wall_mae'):metrics[role]=max(b[role] for b in bands)
        passed=all(metrics[k]<=v for k,v in LIMITS.items())
        candidates.append(dict(length=length,path=starts[indices].tolist(),**metrics,bands=bands,
            passed=passed,score=sum(metrics[k]/LIMITS[k] for k in LIMITS)))
    if not candidates:raise ValueError(axis.upper()+'方向没有可同时测量的两面相对墙')
    candidates.sort(key=lambda c:(not c['passed'],c['score'],-c['length']))
    return dict(axis=axis,cross=cross.tolist(),candidate_count=len(candidates),selected=candidates[0])


def partition(source,axes):
    pixels=np.asarray(source.convert('RGBA'));yy,xx=np.indices(pixels.shape[:2],dtype=float)
    u=(xx-ORIGIN[0])/2+yy-ORIGIN[1];v=-(xx-ORIGIN[0])/2+yy-ORIGIN[1]
    labels=[]
    for axis,t,k in [('a',u,v),('b',v,u)]:
        r=axes[axis];c=r['selected'];boundary=np.interp(k,r['cross'],c['path'])
        labels.append(np.clip(np.floor((t-boundary)/c['length'])+1,0,2).astype(int))
    a,b=labels;visible=pixels[:,:,3]>0
    if ((a==1)&(b==1)&visible).any():raise ValueError('两组重复切口相交在墙体上，不能独立扩建')
    parts=[];rebuilt=np.zeros_like(pixels)
    names={(0,0):'后角',(2,0):'右角',(2,2):'前角',(0,2):'左角',
           (1,0):'右后直墙',(1,2):'左前直墙',(0,1):'左后直墙',(2,1):'右前直墙'}
    for (ai,bi),title in names.items():
        owned=(a==ai)&(b==bi)&visible
        if not owned.any():raise ValueError('扩建分区缺失：'+title)
        region=np.zeros_like(pixels);region[owned]=pixels[owned];rebuilt[owned]=pixels[owned]
        # All parts keep the source canvas; ground anchors place them exactly.
        foot=[ORIGIN[0]+(ai-bi)*192,ORIGIN[1]+(ai+bi)*96]
        parts.append(dict(a=ai,b=bi,title=title,sprite=Image.fromarray(region),foot=foot))
    if not np.array_equal(rebuilt,pixels):raise ValueError('扩建切片丢失来源像素')
    return parts


def placements(parts,lengths,copies):
    if len(copies)!=2 or any(type(n) is not int or not 1<=n<=20 for n in copies):raise ValueError('扩建重复数须为1–20的整数')
    result=[]
    for index,part in enumerate(parts):
        aa=range(copies[0]) if part['a']==1 else [0 if part['a']==0 else copies[0]-1]
        bb=range(copies[1]) if part['b']==1 else [0 if part['b']==0 else copies[1]-1]
        for a in aa:
            for b in bb:
                result.append(dict(part=index,shift=[a*lengths[0]-b*lengths[1],(a*lengths[0]+b*lengths[1])//2]))
    return result


def assemble(parts,lengths,copies):
    layout=placements(parts,lengths,copies)
    left=min(v['shift'][0] for v in layout);top=min(v['shift'][1] for v in layout)
    right=max(v['shift'][0]+parts[v['part']]['sprite'].width for v in layout)
    bottom=max(v['shift'][1]+parts[v['part']]['sprite'].height for v in layout)
    result=Image.new('RGBA',(right-left,bottom-top));counts=np.zeros((bottom-top,right-left),dtype=np.uint8)
    for value in layout:
        sprite=parts[value['part']]['sprite'];x=value['shift'][0]-left;y=value['shift'][1]-top
        result.alpha_composite(sprite,(x,y))
        counts[y:y+sprite.height,x:x+sprite.width]+=(np.asarray(sprite)[:,:,3]>0)
    return result,dict(layout=layout,origin=[left,top],overlapping_pixels=int((counts>1).sum()))


def check_closed(image):
    alpha=np.asarray(image)[:,:,3]>0
    mask=Image.fromarray(np.where(alpha,255,0).astype(np.uint8)).copy()
    # Exterior flood fill counts every enclosed empty region, including seam holes.
    ImageDraw.floodfill(mask,(0,0),128)
    holes=np.asarray(mask)==0;areas=[]
    while holes.any():
        y,x=np.argwhere(holes)[0];component=Image.fromarray(np.where(holes,0,255).astype(np.uint8)).copy()
        ImageDraw.floodfill(component,(int(x),int(y)),128)
        filled=np.asarray(component)==128;areas.append(int(filled.sum()));holes[filled]=False
        if len(areas)>100:break
    major=[n for n in areas if n>=12000]
    return dict(closed=len(major)==1,interior_pixels=max(areas,default=0),other_enclosed_pixels=sum(areas)-max(areas,default=0))


def analyze(source):
    axes={axis:select_axis(source,axis) for axis in ('a','b')}
    for axis,r in axes.items():
        if not r['selected']['passed']:
            c=r['selected'];raise ValueError('%s方向相对墙没有共同重复接口：瓦顶 %.1f/18，墙面 %.1f/10，轮廓 %.0f/1px'%(axis.upper(),c['roof_mae'],c['wall_mae'],c['outline_shift']))
    parts=partition(source,axes);lengths=[axes[a]['selected']['length'] for a in ('a','b')]
    results=[]
    for copies in CASES:
        image,report=assemble(parts,lengths,copies);closure=check_closed(image)
        if not closure['closed'] or report['overlapping_pixels']:raise ValueError('扩建 %s 后未闭合或像素重叠，未发布'%str(copies))
        if results and closure['other_enclosed_pixels']>results[0]['other_enclosed_pixels']:
            raise ValueError('扩建产生了额外的内部透明孔，未发布')
        results.append(dict(copies=list(copies),instances=len(report['layout']),**closure,overlapping_pixels=0))
    return parts,dict(recipe=RECIPE,limits=LIMITS.copy(),axes=axes,lengths=lengths,cases=results,
        reconstruction_pixel_errors=0,scope='four fixed corners, matched opposite-wall repeats; no gate, collision or character occlusion validation')


def build_job(root,folder,spec):
    from static_props import _publish_annotation,load_package
    folder=Path(folder);source,digest=validated_source(folder)
    parts,checks=analyze(source);atomic(folder/'expansion-checks.json',checks)
    published=read(folder/'expansion-published.json',{})
    for index,part in enumerate(parts+[dict(title='可扩建院墙套件',sprite=source,foot=[512,684])]):
        key=str(index)
        if key in published:
            load_package(root,published[key]);continue
        stream=BytesIO();part['sprite'].save(stream,'PNG')
        files={'sprite.png':stream.getvalue(),'cutout.png':stream.getvalue(),
            'inputs/original.png':(folder/'inputs/ground.png').read_bytes(),
            'inputs/reference.png':(folder/'inputs/reference.png').read_bytes(),
            'generation.json':(folder/'generation.json').read_bytes(),
            'production.json':json.dumps(spec).encode(),'prompt.txt':spec['material_prompt'].encode(),
            'expansion-checks.json':json.dumps(checks).encode()}
        manifest=dict(schema='studio.static-prop/0.1',asset_family='static_prop',asset_kind='custom',view='isometric_2_1',
            canvas_px=list(part['sprite'].size),image='sprite.png',
            provenance=dict(art_source='ai_courtyard_expansion',source_sha256=digest,part=index),
            processing=dict(method='opposite_wall_repeat_partition',recipe=RECIPE),
            assembly_parts=[published[str(i)] for i in range(8)] if index==8 else [],limitations=[checks['scope']])
        if index<8:manifest['courtyard_part']=dict(a=part['a'],b=part['b'],foot=part['foot'],lengths=checks['lengths'])
        manifest=_publish_annotation(root,files,manifest,dict(title=spec['title']+' · '+part['title'],anchor=part['foot'],world_scale=1,behavior='passable',polygons=[]))
        published[key]=manifest['id'];atomic(folder/'expansion-published.json',published)
    return load_package(root,published['8'])


def create_scenes(root,folder):
    import scene_modules as scenes
    from task_lock import task_lock
    folder=Path(folder)
    with task_lock(root):
        existing=read(folder/'expansion-scenes.json',{})
        if existing:return [scenes.load(root,identity) for identity in existing['scenes']]
        ids=read(folder/'expansion-published.json');checks=read(folder/'expansion-checks.json')
        from static_props import load_package
        parts=[load_package(root,ids[str(i)])['courtyard_part'] for i in range(8)]
        result=[]
        for copies,title in [((1,1),'基准'),((5,1),'只加长'),((1,5),'只加宽'),((5,5),'双向扩建'),((9,7),'大幅扩建')]:
            s=scenes.change(root,dict(action='create',title='四合院 · '+title+' · %s×%s'%copies))
            for i in range(8):s=scenes.change(root,dict(action='adopt',scene=s['id'],revision=s['revision'],kit=ids[str(i)]))
            layout=placements(parts,checks['lengths'],copies)
            instances=[dict(id='repeat-'+str(i),module=s['modules'][v['part']]['id'],position=[parts[v['part']]['foot'][d]-ORIGIN[d]+v['shift'][d] for d in range(2)]) for i,v in enumerate(layout)]
            s=scenes.change(root,dict(action='layout',scene=s['id'],revision=s['revision'],instances=instances,
                spawn=[((copies[0]-1)*checks['lengths'][0]-(copies[1]-1)*checks['lengths'][1])//2,192+((copies[0]-1)*checks['lengths'][0]+(copies[1]-1)*checks['lengths'][1])//4]))
            result.append(s)
        atomic(folder/'expansion-scenes.json',dict(scenes=[s['id'] for s in result]))
        return result
