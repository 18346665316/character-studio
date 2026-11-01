"""Deterministic shared-palette fitting and alpha-preserving mapping."""
import numpy as np
from PIL import Image
from sheet_layout import tiles


def make_palette(sheets,metadata,colors):
    if colors not in (32,64,128):raise ValueError('Supports 32, 64 or 128 colors')
    samples=[]
    for path in sheets:
        info=metadata[path.name]
        with Image.open(path) as image:
            frames=list(tiles(image.convert('RGBA'),info['frame_width'],info['frame_count']))
        indices=np.linspace(0,len(frames)-1,min(16,len(frames)),dtype=int)
        for index in indices:
            rgba=np.asarray(frames[index]);pixels=rgba[rgba[:,:,3]>=128,:3]
            if len(pixels): samples.append(pixels[np.linspace(0,len(pixels)-1,min(512,len(pixels)),dtype=int)])
    if not samples:raise ValueError('No visible foreground')
    # Each action contributes a similar number of frames, avoiding long-clip bias.
    sample=np.concatenate(samples)
    quantized=Image.fromarray(sample.reshape(-1,1,3)).quantize(colors=colors,method=Image.Quantize.MEDIANCUT)
    return np.asarray(quantized.getpalette(),dtype=np.uint8).reshape(-1,3)[:colors]


def apply_palette(source,destination,palette):
    with Image.open(source) as image:rgba=np.array(image.convert('RGBA'))
    mask=rgba[:,:,3]>0;pixels=rgba[mask,:3]
    unique,inverse=np.unique(pixels,axis=0,return_inverse=True)
    mapped=np.empty_like(unique)
    for start in range(0,len(unique),8192):
        chunk=unique[start:start+8192].astype(np.int32)
        distances=((chunk[:,None,:]-palette.astype(np.int32)[None,:,:])**2).sum(axis=2)
        mapped[start:start+len(chunk)]=palette[distances.argmin(axis=1)]
    rgba[mask,:3]=mapped[inverse]
    Image.fromarray(rgba).save(destination)
    return {'foreground_pixels':int(mask.sum()),'mean_rgb_error':float(np.abs(pixels.astype(float)-mapped[inverse]).mean())}
