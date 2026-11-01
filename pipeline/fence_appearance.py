"""Deterministic timber surfaces on independent projected fence members.

The optional image supplies wood grain only. Geometry, direction, ground depth
layers and interfaces are constructed here; this never claims AI fence sprites.
"""
import numpy as np
from PIL import Image

SCALE=4


def procedural_timber():
    y,x=np.indices((256,256),dtype=float)
    rng=np.random.default_rng(31)
    bend=2*np.sin(y/38)+1.3*np.sin(y/17+x/45)
    grain=np.sin((x+bend)*.72)*3.8+np.sin((x+bend)*2.1)*1.6
    grain+=rng.normal(0,.7,(256,256))
    broad=4*np.sin(x/27+y/200)
    return Image.fromarray(np.clip(np.array([161,115,65])+((grain+broad)[:,:,None])*np.array([1,.8,.5]),0,255).astype('uint8'))


def segments(record):
    if record['id']=='opening_ew':
        return [((0,32),(17,32)),((47,32),(64,32))],[(17,32),(47,32)]
    return [((32,32),tuple(c['position_px'])) for c in record['connections']],[(32,32)]


def render_timber(record,texture):
    texture=np.array(texture.convert('RGB').resize((256,256),Image.Resampling.LANCZOS))
    layers={}
    def face(rect,depth,axis,brightness,cap=False):
        x0,y0,x1,y1=rect
        x0=max(0,int(round(x0*SCALE)));x1=min(64*SCALE,int(round(x1*SCALE)))
        y0=max(0,int(round(y0*SCALE)));y1=min(96*SCALE,int(round(y1*SCALE)))
        if x1<=x0 or y1<=y0:return
        layer=layers.setdefault(depth,Image.new('RGBA',(64*SCALE,96*SCALE),(0,0,0,0)))
        yy,xx=np.indices((y1-y0,x1-x0),dtype=float);xx=(xx+x0)/SCALE;yy=(yy+y0)/SCALE
        if axis=='horizontal':u=(yy*31).astype(int)%256;v=(xx*7).astype(int)%256
        elif axis=='vertical':u=(xx*31).astype(int)%256;v=(yy*7).astype(int)%256
        else:u=(xx*17).astype(int)%256;v=(yy*17).astype(int)%256
        colour=texture[v,u].astype(float)*brightness
        # A narrow edge bevel belongs to the member, never to the cell boundary.
        if cap:colour=colour*.9+np.array([12,9,4])
        rgba=np.empty((y1-y0,x1-x0,4),dtype='uint8');rgba[:,:,:3]=np.clip(colour,0,255);rgba[:,:,3]=255
        layer.paste(Image.fromarray(rgba),(x0,y0))
    beams,posts=segments(record)
    for start,end in beams:
        horizontal=start[1]==end[1]
        if horizontal:
            x0,x1=sorted((start[0],end[0]));y=32
            for z in (9,21):
                # Front and top faces share the same ground support depth.
                face((x0,y+32+2-z,x1,y+32+2-(z-4)),32,'horizontal',.74)
                face((x0,y+32-2-z,x1,y+32+2-z),32,'horizontal',1.12)
        else:
            y0,y1=sorted((start[1],end[1]));x=32
            for z in (9,21):
                # Vertical rails are sliced by ground depth, not by image Y.
                for begin in range(int(y0),int(y1),4):
                    finish=min(begin+4,y1)
                    face((x-2,begin+32-z,x+2,finish+32-z),int(finish),'vertical',1.02)
                face((x-2,y1+32-z,x+2,y1+32-(z-4)),int(y1),'vertical',.68)
    for x,y in posts:
        # Six-pixel foot agrees with suggested collision; cap overhang is visual.
        face((x-3,y+32-28,x+3,y+32),int(y)+1,'vertical',.78)
        face((x-3,y+32-31,x+3,y+32-28),int(y)+1,'cap',1.12,True)
    result=[]
    for depth,image in sorted(layers.items()):
        result.append((depth,image.resize((64,96),Image.Resampling.LANCZOS)))
    combined=Image.new('RGBA',(64,96))
    for _,image in result:combined.alpha_composite(image)
    return combined,result


def compose_layered(images,layout):
    result=Image.new('RGBA',(7*64,5*64+40),(224,231,219,255))
    draw=[]
    for placement in layout:
        x,y=placement['cell']
        for depth,image in images[placement['module']][1]:
            draw.append((y*64+depth,(x*64,y*64-32+40),image))
    for _,position,image in sorted(draw,key=lambda row:row[0]):result.alpha_composite(image,position)
    return result.convert('RGB')
