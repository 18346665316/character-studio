"""Stage an isolated Godot 4.6 consumer from three immutable Studio ZIPs.

No generated scene or image is written into the Studio source tree. --check
imports textures and runs Godot with real rendering to compare delivered pixels.
"""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import zipfile

from asset_repository import name, read
from terrain_integrity import require

ROOT=Path(__file__).resolve().parent.parent


def stage(road_kit,material_kit,water_kit,root=ROOT):
    sources={'road':('terrain-kits',name(road_kit)),
             'material':('terrain-kits',name(material_kit)),
             'water':('terrain-transitions',name(water_kit))}
    manifests={}
    for role,(subtree,identity) in sources.items():
        require(root,subtree,identity)
        m=read(root/subtree/identity/'manifest.json')
        if role=='road' and (m.get('asset_type')=='material' or not m.get('variants')):
            raise ValueError('道路验收须选择包含变化组的道路套件')
        if role=='material' and m.get('asset_type')!='material': raise ValueError('材质验收须选择独立材质')
        if role=='water' and m.get('transition_mode')!='shoreline': raise ValueError('水岸验收须选择静态水岸套件')
        manifests[role]=m
    if [source['kit'] for source in manifests['water']['sources']] != [road_kit,material_kit]:
        raise ValueError('水岸的陆地与水面来源须分别对应所选道路套件与独立材质')
    identity=datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    target=root/'.local/terrain-godot-validation'/identity
    shutil.copytree(Path(__file__).parent/'terrain_validation',target)
    provenance={}
    for role,(subtree,identity) in sources.items():
        archive=root/subtree/identity/'kit.zip'
        destination=target/'assets'/role
        destination.mkdir(parents=True)
        with zipfile.ZipFile(archive) as bundle:
            # Integrity gate has already rejected unsafe/duplicate ZIP members.
            # Only consumer files are needed; omit generation prompts and inputs.
            for member in bundle.namelist():
                if member=='manifest.json' or member=='preview.png' or member=='atlas.png' or member.startswith(('tiles/','masks/')):
                    path=destination/member
                    path.parent.mkdir(parents=True,exist_ok=True)
                    path.write_bytes(bundle.read(member))
        provenance[role]={'id':identity,'subtree':subtree,'zip_sha256':hashlib.sha256(archive.read_bytes()).hexdigest()}
    (target/'source.json').write_text(json.dumps(provenance,ensure_ascii=False,indent=2))
    for path in target.rglob('*.png'):
        relative=path.relative_to(target).as_posix()
        Path(str(path)+'.import').write_text(
            '[remap]\nimporter="texture"\ntype="CompressedTexture2D"\n'
            '[deps]\nsource_file="res://'+relative+'"\n'
            '[params]\ncompress/mode=0\nmipmaps/generate=false\n')
    return target


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--road-kit',required=True)
    parser.add_argument('--material-kit',required=True)
    parser.add_argument('--water-kit',required=True)
    parser.add_argument('--godot',default='/Applications/Godot.app/Contents/MacOS/Godot')
    parser.add_argument('--check',action='store_true')
    parser.add_argument('--open',action='store_true')
    args=parser.parse_args()
    target=stage(args.road_kit,args.material_kit,args.water_kit)
    print(target,flush=True)
    if args.check or args.open:
        with (target/'import.log').open('w') as output:
            subprocess.run([args.godot,'--headless','--path',str(target),'--editor','--import'],stdout=output,stderr=subprocess.STDOUT,check=True,timeout=120)
        import_log=(target/'import.log').read_text()
        if 'SCRIPT ERROR' in import_log or 'Parse Error' in import_log:
            raise ValueError('Godot 导入或脚本解析失败，详见 '+str(target/'import.log'))
    if args.check:
        with (target/'run.log').open('w') as output:
            subprocess.run([args.godot,'--path',str(target),'--','--qa'],stdout=output,stderr=subprocess.STDOUT,check=True,timeout=120)
        report=read(target/'qa/report.json')
        if not report or not report.get('passed'): raise ValueError('Godot 接入验收失败，详见 '+str(target/'run.log'))
        print('PASS',len(report['checks']),'checks; report:',target/'qa/report.json',flush=True)
    if args.open: subprocess.Popen([args.godot,'--path',str(target)],start_new_session=True)


if __name__=='__main__': main()
