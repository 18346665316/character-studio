"""Explicit frame layout; padded grid cells are never animation frames."""
import math
from PIL import Image


def layout(image,frame_size,count=None):
    if type(frame_size) is not int or frame_size<=0 or image.width%frame_size or image.height%frame_size:
        raise ValueError('图集尺寸不是完整帧的整数倍')
    cols,rows=image.width//frame_size,image.height//frame_size
    if count is None:
        if rows!=1: raise ValueError('多行图集缺少明确帧数')
        count=cols
    if type(count) is not int or not 1<=count<=cols*rows or count<=(rows-1)*cols:
        raise ValueError('图集帧数与网格容量不符')
    return {'columns':cols,'rows':rows,'frame_count':count,'frame_width':frame_size,'frame_height':frame_size}


def tiles(image,frame_size,count=None):
    spec=layout(image,frame_size,count)
    for index in range(spec['frame_count']):
        x=index%spec['columns']*frame_size;y=index//spec['columns']*frame_size
        yield image.crop((x,y,x+frame_size,y+frame_size))


def blank(size,count):
    cols=min(16,count);rows=math.ceil(count/cols)
    return Image.new('RGBA',(cols*size,rows*size)),cols,rows
