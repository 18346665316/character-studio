"""Find a translated pair of pixel cuts; never blend, warp or repaint pixels."""
import numpy as np
from PIL import Image

RECIPE='studio.wall-path/1'
LIMITS=dict(roof_mae=18.,wall_mae=10.,outline_shift=1.,alpha_mismatch=.015)


def select(source,origin,axis='a'):
    if axis not in ('a','b'):raise ValueError('Unknown wall axis')
    rgba=np.asarray(source.convert('RGBA')).astype(float)
    ks=np.arange(-240,121);sign=1 if axis=='a' else -1
    candidates=[]
    for length in range(96,193,2):
        ts=np.arange(128,513-length,2)
        xx=np.broadcast_to(ts,(len(ks),len(ts)))
        costs=[];masks=[];differences=[]
        for offset in (-1,0,1):
            x=xx+offset;y=np.rint(origin[1]+x/2+ks[:,None]).astype(int)
            a=rgba[y,origin[0]+sign*x]
            b=rgba[y+length//2,origin[0]+sign*(x+length)]
            la=a[:,:,3]>127;ra=b[:,:,3]>127;common=la&ra
            diff=np.abs(a[:,:,:3]-b[:,:,:3]).mean(2)
            costs.append(np.where(common,diff,0)+np.where(la!=ra,500.,0))
            masks.append((la,ra));differences.append(diff)
        coverage=masks[1][0]|masks[1][1]
        rows=np.flatnonzero(coverage.any(1))
        if not len(rows) or rows[0]==0 or rows[-1]==len(ks)-1:continue
        top,bottom=rows[0],rows[-1]
        roof_boundary=ks[top]+(ks[bottom]-ks[top])*.45
        cost=np.mean(costs,axis=0)
        dp=cost[0].copy();links=np.zeros(cost.shape,dtype=int)
        for row in range(1,len(ks)):
            previous=np.stack([np.r_[np.inf,dp[:-1]]+2,dp,np.r_[dp[1:],np.inf]+2])
            choice=previous.argmin(0)
            links[row]=np.arange(len(ts))+choice-1
            dp=cost[row]+previous.min(0)
        j=int(dp.argmin());indices=[]
        for row in range(len(ks)-1,-1,-1):
            indices.append(j);j=links[row,j]
        indices=np.asarray(indices[::-1]);path=ts[indices];r=np.arange(len(ks))
        if int(path.max()-path.min())+length>248:continue
        metrics={};valid=True
        for role,region in [('roof',ks<roof_boundary),('wall',ks>=roof_boundary)]:
            samples=[]
            for (la,ra),diff in zip(masks,differences):
                common=(la[r,indices]&ra[r,indices])&region
                samples.extend(diff[r,indices][common].tolist())
            if len(samples)<30:valid=False;break
            metrics[role+'_mae']=float(np.mean(samples))
        if not valid:continue
        la,ra=masks[1];left=la[r,indices];right=ra[r,indices]
        li=np.flatnonzero(left);ri=np.flatnonzero(right)
        if not len(li) or not len(ri):continue
        metrics['outline_shift']=float(max(abs(int(li[0])-int(ri[0])),abs(int(li[-1])-int(ri[-1]))))
        metrics['alpha_mismatch']=float(np.mean([np.mean(a[r,indices]!=b[r,indices]) for a,b in masks]))
        passed=all(metrics[key]<=value for key,value in LIMITS.items())
        candidates.append(dict(length=length,start=int(path.min()),path=path.tolist(),
            **metrics,passed=passed,score=sum(metrics[key]/LIMITS[key] for key in LIMITS)))
    if not candidates:raise ValueError('长墙没有完整可切割的中段')
    candidates.sort(key=lambda c:(not c['passed'],c['score'],-c['length']))
    return dict(recipe=RECIPE,limits=LIMITS.copy(),candidate_count=len(candidates),
        selected=candidates[0],passed=candidates[0]['passed'],path_k=ks.tolist(),
        scope='Three-pixel boundary appearance and contour only; not physics or corners.')


def cut(source,origin,axis,selection,count=1):
    from build_courtyard_wall_templates import ANCHOR,CANVAS
    c=selection['selected'];length=c['length'];start=c['start'];sign=1 if axis=='a' else -1
    rgba=np.asarray(source.convert('RGBA'))
    yy,xx=np.indices(rgba.shape[:2],dtype=float)
    t=sign*(xx-origin[0]);k=yy-origin[1]-.5*t
    boundary=np.interp(k,selection['path_k'],c['path'])
    labels=np.floor((t-boundary)/length).astype(int)
    expected=np.zeros_like(rgba);sprites=[];offsets=[]
    for index in range(count):
        region=np.zeros_like(rgba);owned=(labels==index)&(rgba[:,:,3]>0)
        region[owned]=rgba[owned];expected[owned]=rgba[owned]
        offset=(origin[0]+sign*(start+index*length)-ANCHOR[0],origin[1]+(start+index*length)//2-ANCHOR[1])
        sprite=Image.new('RGBA',CANVAS);sprite.paste(Image.fromarray(region),(-offset[0],-offset[1]))
        restored=Image.new('RGBA',source.size);restored.paste(sprite,offset)
        if not np.array_equal(np.asarray(restored),region):raise ValueError('切片超出统一画布，未缩放原图')
        if not owned.any():raise ValueError('切片为空')
        sprites.append(sprite);offsets.append(list(offset))
    return sprites,Image.fromarray(expected),dict(method='translated_pixel_path_partition',axis=axis,
        start=start,length=length,count=count,anchor_px=list(ANCHOR),source_offsets_px=offsets,
        repeat_offset_px=[sign*length,length//2],reconstruction_pixel_errors=0,
        processing='source pixels and integer translations only; no blending, warping or repainting')
