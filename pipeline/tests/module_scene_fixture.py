"""Explicit geometry fixtures for module-scene acceptance, not generated art."""
import base64
from io import BytesIO
from PIL import Image, ImageDraw
import scene_modules as sm


def create(root):
    scene=sm.change(root,dict(action='create',title='通用模块 MVP · 几何验收'))
    def change(**data):
        nonlocal scene
        scene=sm.change(root,dict(scene=scene['id'],revision=scene['revision'],**data))
    for title,behavior,shapes in [
        ('阻挡块 · 程序样例','blocking',[[[-64,-6],[64,-6],[64,6],[-64,6]]]),
        ('开口块 · 程序样例','opening',[[[-64,-6],[-20,-6],[-20,6],[-64,6]],[[20,-6],[64,-6],[64,6],[20,6]]]),
        ('可通过块 · 程序样例','passable',[])]:
        image=Image.new('RGBA',(128,100),(0,0,0,0));draw=ImageDraw.Draw(image)
        if behavior=='passable':draw.ellipse((30,60,98,96),fill='#78a17c')
        else:
            for poly in shapes:
                left=poly[0][0]+64;right=poly[1][0]+64
                draw.rectangle((left,24,right-1,86),fill='#bda884',outline='#ede1c2',width=2)
        stream=BytesIO();image.save(stream,format='PNG')
        change(action='import',title=title,image=base64.b64encode(stream.getvalue()).decode())
        m=scene['modules'][-1]
        change(action='module',module=m['id'],title=title,anchor=[64,80],behavior=behavior,polygons=shapes)
    a,b,c=[m['id'] for m in scene['modules']]
    from static_props import annotate
    scaled=[]
    for original,factor in [(scene['modules'][0],.5),(scene['modules'][1],.25)]:
        version=annotate(root,dict(source_kit=original['source']['id'],title=original['title']+' · 缩放',
            anchor=original['anchor'],behavior=original['behavior'],polygons=original['polygons'],world_scale=factor))
        change(action='adopt',kit=version['id']);scaled.append(scene['modules'][-1]['id'])
    change(action='layout',spawn=[320,140],instances=[dict(id='wall-a',module=a,position=[0,0]),dict(id='wall-b',module=a,position=[128,0]),dict(id='opening',module=b,position=[320,0]),dict(id='decoration',module=c,position=[520,0]),dict(id='half-wall',module=scaled[0],position=[720,0]),dict(id='small-opening',module=scaled[1],position=[920,0])])
    return scene
