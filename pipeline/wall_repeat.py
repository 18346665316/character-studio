"""Deterministic cut selection. Measurements never modify source pixels."""
import numpy as np
from PIL import Image

RECIPE='studio.wall-repeat/1'
# RGB differences are measured on the common visible pixels, in 0..255 units.
LIMITS=dict(roof_mae=18.,wall_mae=10.,outline_shift=1.,alpha_mismatch=.015,shape_offset=8.)


def profiles(source,origin,axis='a'):
    rgba=np.asarray(source.convert('RGBA'))
    t=np.arange(641,dtype=float)
    k=np.arange(-180,41,dtype=float)
    q=np.clip((k+108)/2,0,8)
    sx=t[None,:]-q[:,None]
    xx=origin[0]+(sx if axis=='a' else -sx)
    yy=origin[1]+.5*sx+k[:,None]
    x=np.rint(xx).astype(int);y=np.rint(yy).astype(int)
    if x.min()<0 or y.min()<0 or x.max()>=source.width or y.max()>=source.height:raise ValueError('长墙参考截面超出来源画布')
    return rgba[y,x].transpose(1,0,2),k


def measure(profile,k,start,length):
    offsets=np.arange(-4,5)
    left=profile[start+offsets].astype(float)
    right=profile[start+length+offsets].astype(float)
    la=left[:,:,3]>127;ra=right[:,:,3]>127
    common=la&ra
    if common.sum()<700:return None
    values={}
    for role,rows in [('roof',k<-84),('wall',k>=-84)]:
        valid=common&rows[None,:]
        if valid.sum()<50:return None
        values[role+'_mae']=float(np.abs(left[:,:,:3]-right[:,:,:3])[valid].mean())
    shift=[];shape_offset=[]
    for l,r in zip(la,ra):
        li=np.flatnonzero(l);ri=np.flatnonzero(r)
        if not len(li) or not len(ri):return None
        if li[0]==0 or ri[0]==0 or li[-1]==len(k)-1 or ri[-1]==len(k)-1:return None
        shift.extend([abs(int(li[0])-int(ri[0])),abs(int(li[-1])-int(ri[-1]))])
        for indices in (li,ri):shape_offset.extend([abs(float(k[indices[0]])+108),abs(float(k[indices[-1]])-8)])
    values.update(outline_shift=float(max(shift)),alpha_mismatch=float((la!=ra).mean()),shape_offset=max(shape_offset))
    values['score']=sum(values[key]/LIMITS[key] for key in LIMITS)
    values['passed']=all(values[key]<=LIMITS[key] for key in LIMITS)
    return values


def select(source,origin,axis='a'):
    if axis not in ('a','b'):raise ValueError('Unknown wall axis')
    profile,k=profiles(source,origin,axis)
    candidates=[]
    # Leave both outer spans out; use only integer 2:1 translations. One selected
    # length applies to every placement, never per-instance offsets.
    for length in range(96,193,2):
        for start in range(128,513-length,2):
            metrics=measure(profile,k,start,length)
            if metrics:candidates.append(dict(start=start,length=length,**metrics))
    if not candidates:raise ValueError('长墙中间没有完整可测量的墙体截面')
    candidates.sort(key=lambda c:(not c['passed'],c['score'],-c['length'],c['start']))
    best=candidates[0]
    return dict(recipe=RECIPE,limits=LIMITS.copy(),candidate_count=len(candidates),selected=best,
                baseline=measure(profile,k,256,128),passed=best['passed'],
                scope='boundary appearance and contour only; not physics, corners or lighting certification')
