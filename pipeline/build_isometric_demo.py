"""Build an isolated projection acceptance scene, without paid requests.

With --rock/--crate use real Studio isometric packages. Without them create
explicit procedural fixtures for engineering verification, never AI artwork.
"""
import argparse
import base64
from io import BytesIO
import json
from pathlib import Path
import shutil

from asset_repository import atomic
from asset_projection import ISOMETRIC
from static_props import package, validate, load_package
from terrain import prepare, execute
from terrain_integrity import require
from PIL import Image,ImageDraw

ROOT=Path(__file__).resolve().parent.parent
TARGET=ROOT/'demo/isometric'


def fixture(kind):
    image=Image.new('RGBA',(256,256));d=ImageDraw.Draw(image)
    if kind=='crate':
        d.polygon([(48,112),(128,72),(208,112),(128,152)],fill='#c9a270')
        d.polygon([(48,112),(128,152),(128,232),(48,192)],fill='#986943')
        d.polygon([(128,152),(208,112),(208,192),(128,232)],fill='#71513b')
        d.line([(48,112),(128,152),(208,112)],fill='#4e4136',width=3)
    else:
        d.polygon([(43,165),(74,125),(132,109),(195,142),(214,184),(148,228),(65,204)],fill='#777f87')
        d.polygon([(43,165),(74,125),(132,109),(164,158),(105,183)],fill='#a2abb0')
        d.polygon([(164,158),(195,142),(214,184),(148,228),(105,183)],fill='#5d6871')
    return image


def assemble(ground,rock=None,crate=None):
    source=ROOT/'terrain-kits'/ground
    require(ROOT,'terrain-kits',ground)
    original=Image.open(source/'inputs/ground.png').convert('RGB')
    stream=BytesIO();original.save(stream,format='PNG')
    job=prepare(ROOT,{'title':'等距草地 · 复用已有纹理','description':'复用已有草地纹理，程序导出2:1菱形，不新增AI调用。',
                      'asset_type':'material','material_kind':'grass','mode':'import','projection':ISOMETRIC,
                      'ground':base64.b64encode(stream.getvalue()).decode(),'tile_size':64,'finish':'natural'})
    execute(ROOT,job['id']);require(ROOT,'terrain-kits',job['id'])
    assets=TARGET/'assets';(assets/'textures').mkdir(parents=True,exist_ok=True)
    records={'ground':{'package':job['id'],'texture_source':ground,'new_ai_calls':0}}
    ground_folder=ROOT/'terrain-kits'/job['id']
    ground_manifest=json.loads((ground_folder/'manifest.json').read_text())
    for index,item in enumerate(ground_manifest['projection_spec']['variants']):
        shutil.copyfile(ground_folder/item['image'],assets/'textures'/f'ground_{index}.png')
    records['objects']={}
    for kind,identity in [('rock',rock),('crate',crate)]:
        if identity:
            manifest=load_package(ROOT,identity)
            if manifest['view']!=ISOMETRIC or manifest['asset_kind']!=kind:
                raise ValueError('Demo物件须为对应类型的等距包：'+kind)
            folder=ROOT/'prop-kits'/identity
        else:
            folder=package(ROOT,fixture(kind),validate({'mode':'import','kind':kind,'title':'程序几何验证样本 · 非AI素材','projection':ISOMETRIC}),
                           provenance={'art_source':'procedural_projection_fixture','purpose':'engineering_verification_only'})
            identity=folder.name;manifest=load_package(ROOT,identity)
        shutil.copyfile(folder/'sprite.png',assets/'textures'/f'{kind}.png')
        atomic(assets/f'{kind}.json',manifest)
        records['objects'][kind]={'package':identity,'source':manifest['provenance']['art_source'],
                                  'fixture':manifest['provenance']['art_source']=='procedural_projection_fixture'}
    atomic(assets/'sources.json',records)
    return records


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ground',default='20261101-192420-43363e76')
    parser.add_argument('--rock');parser.add_argument('--crate')
    args=parser.parse_args();print(json.dumps(assemble(args.ground,args.rock,args.crate),ensure_ascii=False,indent=2))
