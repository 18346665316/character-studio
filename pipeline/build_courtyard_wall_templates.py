"""Deterministic two-axis wall line masters; no image service or asset publishing."""
import argparse
import json
from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
LENGTH, THICKNESS, HEIGHT, CAP_RISE = 128, 16, 96, 12
CANVAS = (512, 512)
ANCHOR = (256, 280)


def project(p):
    x, y, z = p
    return (x-y, (x+y)/2-z)


def point(axis, t, q, z):
    return (t, q, z) if axis == 'a' else (q, t, z)


def section(axis, t):
    # Roof terminates flush at longitudinal interfaces: no end overhang or posts.
    return [point(axis,t,q,z) for q,z in [(-8,0),(8,0),(8,96),(8,100),(0,108),(-8,100),(-8,96)]]


def faces(axis, length):
    start,end=section(axis,0),section(axis,length)
    # Camera looks from positive X/Y. Draw the visible longitudinal face, roof,
    # then positive-axis end. No hidden edges in the image-edit reference.
    wall=[start[1],end[1],end[2],start[2]]
    rim=[start[2],end[2],end[3],start[3]]
    roof=[start[3],end[3],end[4],start[4]]
    return [wall,rim,roof,end]


def render(axis, length=LENGTH, origin=ANCHOR, canvas=CANVAS):
    factor=3
    image=Image.new('RGB',(canvas[0]*factor,canvas[1]*factor),'white')
    draw=ImageDraw.Draw(image)
    for face in faces(axis,length):
        points=[((project(v)[0]+origin[0])*factor,(project(v)[1]+origin[1])*factor) for v in face]
        draw.polygon(points,fill='white')
        draw.line(points+[points[0]],fill='#26332e',width=2*factor,joint='curve')
    return image.resize(canvas,Image.Resampling.LANCZOS)


def render_continuous(axis, length=LENGTH, origin=ANCHOR, canvas=CANVAS):
    """Open repeat boundaries: no end face or cross-section outline to copy."""
    if axis not in ('a','b'):raise ValueError('Unknown wall axis')
    factor=3
    image=Image.new('RGB',(canvas[0]*factor,canvas[1]*factor),'white')
    draw=ImageDraw.Draw(image)
    def pixel(v):
        x,y=project(v)
        return ((x+origin[0])*factor,(y+origin[1])*factor)
    for face,color in zip(faces(axis,length)[:3],('#e7e0cf','#adb9bd','#c3ced0')):
        draw.polygon([pixel(v) for v in face],fill=color)
    start,end=section(axis,0),section(axis,length)
    for index in (1,2,3,4):
        draw.line([pixel(start[index]),pixel(end[index])],fill='#354440',width=factor)
    return image.resize(canvas,Image.Resampling.LANCZOS)


def build(output):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    spec=dict(schema='studio.wall-line-master/1',projection='orthographic_2_1',
              length=LENGTH,thickness=THICKNESS,wall_height=HEIGHT,cap_rise=CAP_RISE,
              canvas_px=list(CANVAS),anchor_px=list(ANCHOR),modules={})
    for axis in ('a','b'):
        render(axis).save(output/('wall-'+axis+'-outline.png'))
        render_continuous(axis).save(output/('wall-'+axis+'-continuous.png'))
        start,end=section(axis,0),section(axis,LENGTH)
        delta=project(point(axis,LENGTH,0,0))
        # Compare every interface vertex in 3D and in image coordinates,
        # including both faces of the wall and the full cap profile.
        for n in (1,2):
            for left,right in zip(section(axis,LENGTH*(n-1)),section(axis,LENGTH*n)):
                translated=tuple(left[i]+point(axis,LENGTH,0,0)[i] for i in range(3))
                assert translated==right
                assert tuple(project(left)[i]+delta[i] for i in range(2))==project(right)
        spec['modules'][axis]=dict(outline='wall-'+axis+'-outline.png',
            repeat_offset_px=list(delta),start_section_px=[list(project(v)) for v in start],
            end_section_px=[list(project(v)) for v in end],
            connectors=dict(start=[0,0],end=list(delta)))
    # Render a continuous extrusion, then mark the exact two interfaces.
    # This checks geometry only; it does not certify AI-generated material seams.
    sample=Image.new('RGB',(1100,690),'#f1f4ef');draw=ImageDraw.Draw(sample)
    for axis,origin,label in [('a',(90,245),'A  |  step (+128, +64)'),('b',(1000,245),'B  |  step (-128, +64)')]:
        art=render(axis,LENGTH*3,origin,(1100,690))
        mask=art.convert('L').point(lambda v:255 if v<245 else 0)
        sample.paste(art,(0,0),mask)
        draw=ImageDraw.Draw(sample)
        draw.text((origin[0] if axis=='a' else origin[0]-330,75),label,fill='#26332e')
        for n in (1,2):
            edge=[project(v) for v in section(axis,LENGTH*n)]
            points=[(p[0]+origin[0],p[1]+origin[1]) for p in edge]
            draw.line(points+[points[0]],fill='#cf663e',width=2)
        draw.text((origin[0] if axis=='a' else origin[0]-330,480),'3 modules / 2 shared interfaces',fill='#526359')
    draw.text((50,580),'Geometry only: identical cross-sections; no AI textures, no collision or occlusion certification.',fill='#526359')
    sample.save(output/'three-segment-check.png')
    spec['verification']=dict(interface_vertices_matched=28,segments_per_axis=3,
        geometry='exact translated cross-sections',appearance='not_generated',
        corners='not_defined',collision='not_tested',occlusion='not_tested')
    (output/'wall-spec.json').write_text(json.dumps(spec,ensure_ascii=False,indent=2)+'\n')
    return output


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=ROOT/'docs/assets/courtyard-walls')
    print(build(parser.parse_args().output))
