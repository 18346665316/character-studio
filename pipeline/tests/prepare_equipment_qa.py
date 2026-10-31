"""Create an isolated editor QA project; never register test annotations as user-approved assets."""
from pathlib import Path
import shutil
import json

ROOT=Path(__file__).resolve().parents[2]

def prepare():
    project=ROOT/'.local/jobs/equipment-qa/viewer'
    source=ROOT/'workspaces/martial_arts_boy/reviews/20261030-215429-2e218e9c/viewer'
    if not project.exists():
        shutil.copytree(source,project,ignore=shutil.ignore_patterns('.godot','captures'))
    for file in ['review.gd','review.tscn','project.godot']:
        shutil.copy2(ROOT/'pipeline/character_preview'/file,project/file)
    shutil.copy2(ROOT/'pipeline/equipment/runtime.gd',project/'equipment_runtime.gd')
    shutil.copy2(ROOT/'pipeline/equipment/editor.gd',project/'equipment_editor.gd')
    shutil.copy2(ROOT/'pipeline/equipment/handles.gd',project/'equipment_handles.gd')
    shutil.copy2(ROOT/'pipeline/tests/equipment_editor_qa.gd',project/'qa.gd')
    shutil.copy2(ROOT/'pipeline/tests/equipment_controls_qa.gd',project/'controls_qa.gd')
    spec=json.loads((project/'review.json').read_text())
    spec['equipment_draft']={'schema':1,'weapon':'studio_sword_v1','bone':'mixamorig_RightHand','hand_points':[],
        'weapon_points':[[0,0,0],[0,.7,0],[.1,0,0]],'weapon_scale':1,'source_units_per_meter':1,'confirmed':False,
        'character':spec['character'],'batch':spec['batch'],'files':spec['files'],
        'rig_sha256':json.loads((ROOT/'.local/mixamo/martial_arts_boy/state.json').read_text())['bound_sha256']}
    spec['equipment_output']=str(project.parent/'qa-equipment.json')
    spec['equipment_screenshot']=str(project.parent/'qa-editor.png')
    (project/'review.json').write_text(json.dumps(spec))
    print(project)

if __name__=='__main__':
    prepare()
