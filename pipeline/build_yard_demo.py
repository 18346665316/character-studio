"""Assemble a standalone game from immutable Studio exports; no API calls."""
from io import BytesIO
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

from game_package import build
from terrain_integrity import require
from fence_components import load_package as load_fence
from static_props import load_package as load_prop

ROOT=Path(__file__).resolve().parent.parent
TARGET=ROOT/'demo/yard'
CHARACTER='hunyuan-guard'
DELIVERY='20261101-160235-ed6aa702'
SOURCES={'terrain':('terrain-kits','20261101-192420-43363e76'),
         'water':('terrain-transitions','20261101-211802-903d2ca6'),
         'fence':('component-kits','20261101-214941-4eab1d46'),
         'rock':('prop-kits','20261101-220035-4ba65e34'),
         'crate':('prop-kits','20261101-221510-229aa2a0'),
         'bush':('prop-kits','20261101-221737-b973aa63')}


def assemble():
    records={};assets=TARGET/'assets';assets.mkdir(parents=True,exist_ok=True)
    for role,(family,identity) in SOURCES.items():
        if family in ('terrain-kits','terrain-transitions'):require(ROOT,family,identity)
        elif family=='component-kits':load_fence(ROOT,identity)
        else:load_prop(ROOT,identity)
        source=ROOT/family/identity;manifest=json.loads((source/'manifest.json').read_text())
        if role=='terrain':
            files={group['ground'] for group in manifest['variants']}
            files.update(tile['image'] for group in manifest['variants'] for tile in group['tiles'])
        elif role=='water':files={tile['image'] for tile in manifest['tiles']}
        elif role=='fence':files={layer['image'] for module in manifest['modules'] for layer in module['visual_layers']}
        else:files={'sprite.png'}
        files.add('manifest.json')
        for relative in files:
            destination=assets/'textures'/role/relative;destination.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(source/relative,destination)
        records[role]={'source':str(source.relative_to(ROOT)),
                       'zip_sha256':hashlib.sha256((source/'kit.zip').read_bytes()).hexdigest()}
    choices={role:{'delivery':DELIVERY,'clip':clip} for role,clip in
             [('idle','breathing_idle'),('walk','walking'),('run','running'),('jump','standing_jump')]}
    raw=build(ROOT,CHARACTER,choices)
    with zipfile.ZipFile(BytesIO(raw)) as bundle:
        for relative in bundle.namelist():
            if relative.startswith('character_assets/'):
                destination=assets/relative;destination.parent.mkdir(parents=True,exist_ok=True)
                destination.write_bytes(bundle.read(relative))
    records['character']={'character':CHARACTER,'delivery':DELIVERY,'selection':choices,
                          'export_sha256':hashlib.sha256(raw).hexdigest()}
    (TARGET/'sources.json').write_text(json.dumps(records,ensure_ascii=False,indent=2)+'\n')
    print('Assembled standalone demo:',TARGET)


if __name__=='__main__':assemble()
