"""Bounded, frame-hold compression of final pixel frames; no interpolation or retiming."""
import math
from pathlib import Path
import numpy as np
from PIL import Image
from sheet_layout import blank, tiles

POLICY = {'version': 'pixel_hold_v1', 'silhouette_error': .035,
          'color_error': .025, 'local_error': .18, 'max_hold_seconds': .2}


def error(reference, candidate):
    """Compare against the retained frame, preventing accumulated small-step drift.

    Foreground normalization prevents empty backgrounds hiding character changes;
    local 4x4 blocks also protect small moving features such as a weapon tip.
    """
    a=np.asarray(reference,dtype=np.float32)/255
    b=np.asarray(candidate,dtype=np.float32)/255
    union=(a[:,:,3]>.5)|(b[:,:,3]>.5)
    if not union.any():return (0.,0.,0.)
    silhouette=float(np.count_nonzero((a[:,:,3]>.5)^(b[:,:,3]>.5))/union.sum())
    delta=np.abs(a[:,:,:3]*a[:,:,3:4]-b[:,:,:3]*b[:,:,3:4]).mean(axis=2)
    color=float(delta[union].mean())
    # Fixed pixel neighborhoods, rather than a whole-frame average.
    h,w=delta.shape
    padded=np.pad(delta,((0,(-h)%4),(0,(-w)%4)))
    local=float(padded.reshape(padded.shape[0]//4,4,padded.shape[1]//4,4).mean(axis=(1,3)).max())
    return silhouette,color,local


PRESETS = {"smooth":24, "balanced":15, "compact":12}


def compact(sheet, destination, timing, protected=(), profile=None):
    size=timing['frame_width'];count=timing['frame_count'];duration=timing['duration_seconds']
    if count<1 or not math.isfinite(duration) or duration<=0:raise ValueError('Invalid animation timing')
    with Image.open(sheet) as source:frames=list(tiles(source.convert('RGBA'),size,count))
    if profile is not None and profile not in PRESETS: raise ValueError('未知精简程度')
    protected=set(protected)|{0,count-1}
    candidates=set(range(count))
    if profile is not None:
        # Keep source frames and exact original timestamps; never interpolate or retime.
        target=min(count,max(1,math.ceil(duration*PRESETS[profile]-1e-8)))
        candidates={min(count-1,int(i*count/target)) for i in range(target)}|protected
    kept=[0];peak=[0.,0.,0.];step=duration/count
    for i in range(1,count):
        if i not in candidates:
            peak=[max(a,b) for a,b in zip(peak,error(frames[kept[-1]],frames[i]))]
            continue
        measured=error(frames[kept[-1]],frames[i])
        limits=(POLICY['silhouette_error'],POLICY['color_error'],POLICY['local_error'])
        if i in protected or (i-kept[-1]+1)*step>POLICY['max_hold_seconds']+1e-8 or any(e>limit for e,limit in zip(measured,limits)):
            kept.append(i)
        else:peak=[max(a,b) for a,b in zip(peak,measured)]
    ends=kept[1:]+[count]
    durations=[(end-start)*step for start,end in zip(kept,ends)]
    image,cols,rows=blank(size,len(kept))
    for i,index in enumerate(kept):image.paste(frames[index],(i%cols*size,i//cols*size))
    destination=Path(destination);destination.parent.mkdir(parents=True,exist_ok=True);image.save(destination)
    return {**timing,'frame_count':len(kept),'columns':cols,'rows':rows,
            'fps':len(kept)/duration,'timing_mode':'variable','frame_durations_seconds':durations,
            'source_frame_indices':kept,'source_frame_count':count,
            'compression':{'profile':profile or 'lossless_hold','target_fps':PRESETS.get(profile),'source_bytes':Path(sheet).stat().st_size,'output_bytes':destination.stat().st_size,'policy':POLICY.copy(),'removed_frames':count-len(kept),
                           'retained_ratio':len(kept)/count,'max_held_error':dict(zip(('silhouette','color','local'),peak)),
                           'note':'Cadence reduction with original timestamps; visual review required.' if profile else 'Raster error bounds only; no cycle extraction or artistic guarantee.'}}


def write_spriteframes(path, sheet_name, timing):
    """Godot uses speed=1 and each frame's duration in seconds. Loop is opt-in."""
    count=timing['frame_count'];size=timing['frame_width'];cols=timing['columns']
    lines=[f'[gd_resource type="SpriteFrames" load_steps={count+2} format=3]',
           f'[ext_resource type="Texture2D" path="{sheet_name}" id="1"]']
    for i in range(count):
        lines += [f'[sub_resource type="AtlasTexture" id="Frame_{i}"]','atlas = ExtResource("1")',
                  f'region = Rect2({i%cols*size}, {i//cols*size}, {size}, {size})']
    entries=[f'{{"duration": {seconds:.12f}, "texture": SubResource("Frame_{i}")}}' for i,seconds in enumerate(timing['frame_durations_seconds'])]
    lines += ['[resource]','animations = [{"frames": ['+',\n'.join(entries)+'], "loop": false, "name": &"default", "speed": 1.0}]']
    Path(path).write_text('\n\n'.join(lines)+'\n')
