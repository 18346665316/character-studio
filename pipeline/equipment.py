"""Versioned one-hand annotations, pinned to a verified rig and animation batch."""
import json
import math
from pathlib import Path
import shutil
import numpy as np


def validate(config):
    if config.get('schema') != 1 or config.get('weapon') != 'studio_sword_v1':
        raise ValueError('不支持的装备配置版本')
    if config.get('bone') not in ('mixamorig_RightHand','mixamorig_LeftHand'):
        raise ValueError('仅支持左右手的单手挂接')
    for field in ('hand_points','weapon_points'):
        try:
            points=np.asarray(config[field],dtype=float)
        except (ValueError,KeyError,TypeError):
            raise ValueError('标注点格式错误')
        if points.shape!=(3,3) or not np.isfinite(points).all():
            raise ValueError('每组需要三个有限的三维点')
        a,b=points[1]-points[0],points[2]-points[0]
        if min(np.linalg.norm(a),np.linalg.norm(b))<1e-6 or np.linalg.norm(np.cross(a,b))<np.linalg.norm(a)*np.linalg.norm(b)*0.1:
            raise ValueError('标注方向不能重合或接近共线')
    for field,low,high in [('weapon_scale',0.2,2),('source_units_per_meter',1e-5,1e5)]:
        value=config.get(field)
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not low<=value<=high:
            raise ValueError('装备尺寸或模型单位无效')
    # Avoid a valid-looking annotation sending a weapon arbitrarily far away.
    if np.max(np.abs(config['hand_points']))/config['source_units_per_meter']>0.5:
        raise ValueError('手部标注超出合理范围')
    if np.max(np.abs(config['weapon_points']))>2:
        raise ValueError('武器标注超出标准剑范围')
    if config.get('confirmed') is not True:
        raise ValueError('装备尚未经过人工预览确认')
    return config


def load(root, character, batch, equipment_id):
    import studio_core as studio
    studio.slug(equipment_id)
    directory=root/'workspaces'/character/'equipment'/equipment_id
    if directory.is_symlink() or not directory.resolve().is_relative_to((root/'workspaces'/character/'equipment').resolve()):
        raise ValueError('非法装备路径')
    config=validate(json.loads((directory/'equipment.json').read_text()))
    receipt=json.loads((root/'workspaces'/character/'animations'/batch/'batch.json').read_text())
    if (config.get('character')!=character or config.get('batch')!=batch or config.get('files')!=receipt.get('files')
            or not receipt.get('rig_sha256') or config.get('rig_sha256')!=receipt['rig_sha256']):
        raise ValueError('装备配置与人物、动作或绑定版本不匹配，请重新标注确认')
    return config


def edit(character,batch,equipment_id=None):
    import studio_core as studio
    from mixamo_state import require_ready
    from review_character import review
    root=studio.BASE_DIR
    binding=require_ready(character,studio.model_path(character))
    receipt=json.loads((root/'workspaces'/character/'animations'/batch/'batch.json').read_text())
    if receipt.get('rig_sha256')!=binding['bound_sha256']:
        raise ValueError('此动作批次不属于当前绑定版本，请选择当前绑定的动作')
    identity=studio.new_batch()
    directory=root/'workspaces'/character/'equipment'/identity
    directory.mkdir(parents=True)
    config=load(root,character,batch,equipment_id).copy() if equipment_id else {
        'schema':1,'weapon':'studio_sword_v1','bone':'mixamorig_RightHand',
        'hand_points':[],'weapon_points':[[0,0,0],[0,0.7,0],[0.1,0,0]],
        'weapon_scale':1.0,'source_units_per_meter':1.0}
    config.update(character=character,batch=batch,files=receipt['files'],rig_sha256=binding['bound_sha256'],confirmed=False)
    output=directory/'equipment.json'
    # Editor writes only on explicit confirmation; closing the window is a failed task.
    review(character,batch,equipment_editor={'draft':config,'output':str(output),'screenshot':str(directory/'review.png')})
    if not output.is_file():
        raise ValueError('装备标注未保存；关闭窗口不会自动确认')
    result=validate(json.loads(output.read_text()))
    if any(result.get(k)!=config.get(k) for k in ('character','batch','files','rig_sha256')):
        raise ValueError('标注期间来源版本发生变化')
    studio.progress_update(character,'review','装备标注已确认并保存，可选择该配置烘焙图集',status='waiting',batch=batch,output=str(directory))
    return directory


def copy_runtime(root,project):
    shutil.copy2(root/'pipeline/equipment/runtime.gd',project/'equipment_runtime.gd')
