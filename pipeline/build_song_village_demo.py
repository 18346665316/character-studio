"""Consume a Studio project release without altering its delivered images.

The Godot scene is a visual acceptance fixture: placement and uniform display
scale only. Generation, background removal and packaging belong to Studio.
"""
import argparse
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import zipfile
from asset_repository import atomic
from studio_projects import load, folder

ROOT = Path(__file__).resolve().parents[1]


def assemble(project_id):
    current = load(ROOT, project_id)
    if not current['releases']:raise ValueError('Export the Studio project first')
    release = current['releases'][-1]
    content = (folder(ROOT,project_id)/'releases'/(release['id']+'.zip')).read_bytes()
    if sha256(content).hexdigest()!=release['sha256']:raise ValueError('Release fingerprint mismatch')
    delivery=zipfile.ZipFile(BytesIO(content))
    if delivery.testzip():raise ValueError('Damaged Studio delivery')
    project=json.loads(delivery.read('project.json'))
    output = ROOT/'demo/song_village/assets'
    output.mkdir(parents=True, exist_ok=True)
    (output/'studio-delivery.zip').write_bytes(content)
    sources = {};tiles=[];objects=[]
    roles = {'farm_house':'茅顶农舍','tile_house':'江南民居',
             'tea':'村口茶棚','shop':'村中米铺','grass':'春日草地','earth':'村路夯土',
             'tree':'村边桑树','willow':'村边柳树','well':'村口石井',
             'cart':'农用木推车','paddy':'稻田小块','vegetable':'乡村菜畦',
             'basket':'竹编粮筐','jar':'储粮陶瓮','firewood':'屋旁柴堆',
             'actor':'临时验收人物'}
    for role,title in roles.items():
        entry=next((e for e in project['items'] if e['title']==title),None)
        if not entry or not entry.get('selected'):raise ValueError('Missing selection: '+title)
        selection=entry['selected']
        raw=delivery.read('assets/'+entry['id']+'.zip')
        if sha256(raw).hexdigest()!=selection['sha256']:raise ValueError('Package fingerprint mismatch')
        target=output/'packages'/entry['id']
        target.mkdir(parents=True,exist_ok=True)
        with zipfile.ZipFile(BytesIO(raw)) as archive:
            if archive.testzip():raise ValueError('Damaged Studio package')
            for name in archive.namelist():
                if role=='actor' and name.endswith('.import'):
                    continue # Godot regenerates host-specific import metadata.
                # The standalone preview project would hide this directory from
                # Godot's parent-project importer. It remains in the original ZIP.
                if role=='actor' and name=='project.godot':
                    (target/name).unlink(missing_ok=True)
                    continue
                path=target/name
                if not path.resolve().is_relative_to(target.resolve()):raise ValueError('Unsafe package path')
                if not name.endswith('/'):
                    path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(archive.read(name))
            manifest_path=('character_assets/'+selection['asset']+'/manifest.json'
                           if role=='actor' else 'manifest.json')
            manifest=json.loads(archive.read(manifest_path))
        prefix=str(target.relative_to(output))+'/'
        if role=='actor':
            sources[role]=dict(item=entry['id'],title=title,asset=selection['asset'],
                zip_sha256=selection['sha256'],
                scene=prefix+'character_assets/'+selection['asset']+'/character.tscn',
                view=manifest['view'],body_height_px=manifest['body_height_px'],
                actions=list(manifest['actions']),scale=1,
                excluded_files=['project.godot'],
                excluded_patterns=['*.import'],
                limitations='Temporary actor; Song clothing, isometric directions and manual motion review unverified')
            continue
        info=dict(item=entry['id'],title=title,asset=selection['asset'],
                  zip_sha256=selection['sha256'],anchor=selection['anchor_px'],
                  image=prefix+'sprite.png',canvas_px=selection['canvas_px'])
        if role in ('grass','earth'):
            projection=manifest['projection_spec']
            if projection['id']!='isometric_2_1' or projection['cell_px']!=[128,64]:raise ValueError('Projection mismatch')
            info['variants']=[prefix+v['image'] for v in projection['variants']]
        sources[role]=info
    for x in range(-25,26):
        for y in range(-25,26):
            role='earth' if abs(x)<=1 or abs(y)<=1 else 'grass'
            images=sources[role]['variants']
            tiles.append(dict(position=[(x-y)*64,(x+y)*32],image=images[(x*3+y*7)%len(images)]))
    def place(role,x,y,width):
        source=sources[role]
        # Display scale is explicit; image bytes and source anchors stay intact.
        objects.append(dict(name=role+str(len(objects)),role=role,image=source['image'],
                            anchor=source['anchor'],position=[x,y],scale=width/source['canvas_px'][0]))
    for role,x,y in [('farm_house',-780,-550),('tile_house',150,-700),('tile_house',950,-220),
                     ('farm_house',-1000,260),('tile_house',-100,600),('farm_house',1100,600)]:
        place(role,x,y,480)
    place('shop',240,-30,410);place('tea',-210,180,350);place('well',80,160,120)
    place('cart',410,150,150);place('basket',320,20,45)
    for base_x,base_y in [(-1500,430),(-800,1050),(1350,80)]:
        for a in range(3):
            for b in range(3):place('paddy',base_x+(a-b)*110,base_y+(a+b)*55,220)
    for i,(x,y) in enumerate([(-1650,-500),(-1150,-900),(-400,-1100),(700,-1000),(1600,-500),
                             (1650,700),(700,1050),(-1300,1000),(-1800,200),(-500,650)]):
        place('tree' if i%2 else 'willow',x,y,210)
    record=dict(schema='studio.release-consumer/1',project=project_id,release=release['id'],
                release_sha256=release['sha256'],source_revision=project['revision'],
                sources=sources,tiles=tiles,objects=objects,map_cells=51,
                processing='none; exact exported files; placement and uniform display scale only',
                road='independent earth tiles; no generated transition or road kit',
                production_ready=False,collision=False,
                viewpoints=[dict(name='全村',position=[0,0],zoom=.32),
                            dict(name='农家',position=[-780,-650],zoom=.85),
                            dict(name='井边街市',position=[100,-20],zoom=.85),
                            dict(name='瓦房',position=[950,-320],zoom=.85)])
    atomic(output/'layout.json',record)
    return record


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--project',required=True)
    result=assemble(parser.parse_args().project)
    print(json.dumps(dict(sources=len(result['sources']),objects=len(result['objects']),processing=result['processing'])))
