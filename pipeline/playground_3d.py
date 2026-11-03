"""Stage an isolated playable 3D scene from verified motions sharing one rig."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess


def build(character, batch):
    import studio_core as studio
    from review_character import verified_batch
    character, batch = studio.slug(character), studio.slug(batch)
    base = studio.BASE_DIR/'workspaces'/character/'animations'
    base_receipt = json.loads((base/batch/'batch.json').read_text())
    rig = base_receipt['rig_sha256']
    required = ['walk.fbx','jogging.fbx','run.fbx','fast_run.fbx','standing_jump.fbx','great_sword_jump_attack.fbx']
    chosen = {}
    for path in sorted(base.glob('*/batch.json')):
        receipt = json.loads(path.read_text())
        if receipt.get('rig_sha256') == rig and receipt.get('kind') != 'sequence':
            for filename in required:
                if filename in receipt.get('files',{}): chosen[filename] = path.parent.name
    if set(chosen) != set(required):
        raise ValueError('缺少游戏动作：' + '、'.join(set(required)-set(chosen)))
    verified = {}
    for source_batch in sorted(set(chosen.values())):
        verified[source_batch] = verified_batch(studio.BASE_DIR,character,source_batch,studio.digest)
    from mixamo_state import check_mesh_identity
    reference = verified[chosen['walk.fbx']][2]['walk.fbx']
    for filename, source_batch in chosen.items():
        info = verified[source_batch][2][filename]
        check_mesh_identity(info, reference)
        if info['bone_names'] != reference['bone_names']: raise ValueError('动作骨架不一致')
    job_id = studio.new_batch()
    project = studio.BASE_DIR/'.local/playgrounds'/character/job_id
    shutil.copytree(studio.BASE_DIR/'pipeline/scene_3d',project)
    assets = project/'assets'
    assets.mkdir()
    provenance = {}
    for filename, source_batch in chosen.items():
        receipt, files, inspection = verified[source_batch]
        shutil.copy2(files[filename],assets/filename)
        if studio.digest(assets/filename) != receipt['files'][filename]:
            raise ValueError('场景准备期间动作源文件已变化')
        provenance[filename] = {'batch':source_batch,'sha256':receipt['files'][filename]}
    from equipment import load as load_equipment, copy_runtime, stage_model
    equipment = None
    for path in sorted((studio.BASE_DIR/'workspaces'/character/'equipment').glob('*/equipment.json'), reverse=True):
        config = json.loads(path.read_text())
        if config.get('rig_sha256') == rig and config.get('confirmed'):
            equipment = load_equipment(studio.BASE_DIR,character,batch,path.parent.name)
            copy_runtime(studio.BASE_DIR, project)
            stage_model(equipment,path.parent/'weapon.glb',project)
            (project/'equipment.json').write_text(json.dumps(equipment))
            break
    (project/'source.json').write_text(json.dumps({'character':character,'rig_sha256':rig,'files':provenance,
        'triangles':reference['triangles'],'heading':'original source preserved','equipment':equipment,
        'root_motion':'controller owns horizontal travel; authored hip elevation drives physical jumps; rotations preserved',
        'idle':'freeze walk first pose; no dedicated idle clip available'},ensure_ascii=False,indent=2))
    from animation_import import prepare as prepare_animation_import
    prepare_animation_import(project)
    subprocess.run([studio.GODOT,'--headless','--editor','--path',str(project),'--import',
                    '--log-file',str(project/'import-engine.log')],check=True,timeout=180)
    print(project,flush=True)
    return project


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--character',default='hunyuan-guard')
    parser.add_argument('--batch',default='20261031-213354-14e10a81')
    parser.add_argument('--open',action='store_true')
    args=parser.parse_args()
    project=build(args.character,args.batch)
    if args.open:
        import studio_core as studio
        subprocess.Popen([studio.GODOT,'--path',str(project),'--log-file',str(project/'game-engine.log')])
