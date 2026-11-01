"""Render six verified actions together, then stage an isolated 2D game."""
import json
from pathlib import Path
import shutil
import subprocess


def build():
    import studio_core as studio
    root = studio.BASE_DIR
    character = 'hunyuan-guard'
    state = json.loads((root/'.local/mixamo'/character/'state.json').read_text())
    rig_sha = state['bound_sha256']
    files = {}
    motions = ('walk','jogging','run','fast_run','standing_jump','great_sword_jump_attack')
    receipts = sorted((root/'workspaces'/character/'animations').glob('*/batch.json'),reverse=True)
    for motion in motions:
        for receipt in receipts:
            data = json.loads(receipt.read_text())
            filename = motion+'.fbx'
            if data.get('kind') == 'sequence' or data.get('rig_sha256') != rig_sha: continue
            if filename in data.get('files',{}):
                path = receipt.parent/filename
                if studio.digest(path) != data['files'][filename]: raise ValueError('源动作已变化')
                files[filename] = {'batch':receipt.parent.name,'sha256':data['files'][filename]}
                break
        else: raise ValueError('缺少本人物已验证的源动作: '+motion)
    record = {'character':character,'rig_sha256':rig_sha,'files':files}
    batch = studio.new_batch()
    directory = root/'workspaces'/character/'animations'/batch
    directory.mkdir(parents=True)
    files = {}
    for filename, origin in record['files'].items():
        path = root/'workspaces'/character/'animations'/origin['batch']/filename
        if studio.digest(path) != origin['sha256']: raise ValueError('源动作已变化')
        shutil.copy2(path,directory/filename)
        files[filename] = origin['sha256']
    (directory/'batch.json').write_text(json.dumps({'character':character,'batch':batch,'kind':'sequence',
        'rig_sha256':record['rig_sha256'],'files':files}))
    equipment = None
    for path in sorted((root/'workspaces'/character/'equipment').glob('*/equipment.json'),reverse=True):
        config = json.loads(path.read_text())
        if config.get('confirmed') and config.get('rig_sha256') == record['rig_sha256']:
            equipment = path.parent.name
            break
    delivery = studio.bake(character,batch,'three_quarter',128,4,equipment,'godot',body_height=96)
    project = root/'.local/playgrounds_2d'/character/batch
    shutil.copytree(root/'pipeline/scene_2d',project)
    assets = project/'assets'
    assets.mkdir()
    shutil.copy2(delivery/'manifest.json',assets/'manifest.json')
    for filename in files:
        name = Path(filename).stem+'_spritesheet.png'
        shutil.copy2(delivery/name,assets/name)
    (project/'source.json').write_text(json.dumps({'delivery':str(delivery),'original':record},ensure_ascii=False,indent=2))
    subprocess.run([studio.GODOT,'--headless','--editor','--path',str(project),'--import','--log-file',str(project/'import.log')],check=True,timeout=180)
    print('PLAYGROUND_2D_PROJECT='+str(project),flush=True)
    return project

if __name__ == '__main__': build()
