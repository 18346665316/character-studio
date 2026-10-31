"""Batch palette and tile-local coverage/outline for legacy strips and explicit grids."""
import numpy as np
from PIL import Image
from scipy.ndimage import binary_dilation
from sheet_layout import layout,tiles


def finish_batch(sheets,colors=64,frame_size=128,layouts=None):
    resized=[];specs=[]
    for path in sheets:
        with Image.open(path) as source:
            image=source.convert('RGBA')
        meta=(layouts or {}).get(path.name,{})
        source_size=meta.get('frame_width',image.height)
        spec=layout(image,source_size,meta.get('frame_count'))
        if frame_size>source_size:raise ValueError('Invalid source tile size or requested upscale')
        target=Image.new('RGBA',(spec['columns']*frame_size,spec['rows']*frame_size))
        for i,tile in enumerate(tiles(image,source_size,spec['frame_count'])):
            target.paste(tile.resize((frame_size,frame_size),Image.Resampling.BOX),((i%spec['columns'])*frame_size,(i//spec['columns'])*frame_size))
        resized.append(target);specs.append(spec)
    samples=[]
    for image,spec in zip(resized,specs):
        for tile in tiles(image,frame_size,spec['frame_count']):
            pixels=np.asarray(tile);rgb=pixels[pixels[:,:,3]>=128,:3]
            if len(rgb):samples.append(rgb[::max(1,len(rgb)//512)])
    if not samples:raise ValueError('No foreground colors to create a palette')
    pixels=np.concatenate(samples)
    pixels=pixels[::max(1,len(pixels)//120000)]
    palette=Image.fromarray(pixels.reshape((-1,1,3)),'RGB').quantize(colors=colors,method=Image.Quantize.MEDIANCUT)
    for path,image,spec in zip(sheets,resized,specs):
        output=Image.new('RGBA',image.size)
        for i,tile in enumerate(tiles(image,frame_size,spec['frame_count'])):
            original=np.array(tile);mask=original[:,:,3]>=128;outline=binary_dilation(mask)&~mask
            rgb=np.array(tile.convert('RGB').quantize(palette=palette,dither=Image.Dither.NONE).convert('RGB'))
            result=np.zeros_like(original);result[mask,:3]=rgb[mask];result[mask,3]=255;result[outline]=(25,29,32,255)
            output.paste(Image.fromarray(result,'RGBA'),((i%spec['columns'])*frame_size,(i//spec['columns'])*frame_size))
        output.save(path)
    return {'palette_colors':colors,'outline_pixels':1,'dither':False,'palette_scope':'whole_batch','alpha_threshold':128,'frame_size':frame_size,'coverage_filter':'premultiplied_rgba_box','outline_stage':'after_resize'}
