"""Run real Godot collision checks against an isolated exported fence fixture ZIP."""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile

from asset_repository import AssetRepository, name, read

ROOT=Path(__file__).resolve().parent.parent


def stage(root,identity):
    from fence_components import load_package
    assets=AssetRepository(root)
    manifest,content=load_package(root,identity)
    source=assets.scoped('component-kits/'+name(identity),'component-kits')
    archive=source/'kit.zip'
    target=assets.scoped('.local/fence-godot-validation/'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'),'.local/fence-godot-validation')
    (target/'assets').mkdir(parents=True)
    for relative,raw in content.items():
        path=target/'assets'/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
    (target/'assets/manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
    (target/'project.godot').write_text('config_version=5\n[application]\nconfig/name="Fence collision fixture validation"\n[physics]\ncommon/physics_ticks_per_second=60\n')
    (target/'source.json').write_text(json.dumps({'kit':identity,'zip_sha256':hashlib.sha256(archive.read_bytes()).hexdigest()}))
    return target


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kit',required=True)
    parser.add_argument('--godot',default='/Applications/Godot.app/Contents/MacOS/Godot')
    parser.add_argument('--visual',action='store_true',help='Also verify layered visuals using a real graphics renderer')
    args=parser.parse_args()
    folder=stage(ROOT,args.kit)
    print(folder,flush=True)
    with (folder/'run.log').open('w') as log:
        subprocess.run([args.godot,'--headless','--path',str(folder),'--script',str(ROOT/'pipeline/tests/fence_component_integration.gd')],
                       stdout=log,stderr=subprocess.STDOUT,check=True,timeout=120)
    report=read(folder/'qa/physics_report.json')
    if not report or not report.get('passed'): raise ValueError('围栏物理验收失败：'+str(folder/'run.log'))
    report['zip_sha256']=read(folder/'source.json')['zip_sha256']
    (folder/'qa/physics_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    if args.visual:
        with (folder/'visual.log').open('w') as log:
            subprocess.run([args.godot,'--path',str(folder),'--script',str(ROOT/'pipeline/tests/fence_visual_integration.gd')],stdout=log,stderr=subprocess.STDOUT,check=True,timeout=120)
        visual=read(folder/'qa/visual_report.json')
        if not visual or not visual.get('passed'):raise ValueError('围栏分层遮挡验收失败：'+str(folder/'visual.log'))
        visual['zip_sha256']=report['zip_sha256']
        (folder/'qa/visual_report.json').write_text(json.dumps(visual,ensure_ascii=False,indent=2))
        print('VISUAL PASS',len(visual['checks']),'checks',folder/'qa/visual_report.json')
    print('PASS',len(report['checks']),'checks',folder/'qa/physics_report.json')


if __name__=='__main__': main()
