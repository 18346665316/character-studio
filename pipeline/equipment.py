"""Versioned one-hand annotations, pinned to a character and verified rig; batches retain review provenance."""
import json
import math
from pathlib import Path
import shutil
import numpy as np


def validate(config):
    if not ((config.get('schema')==1 and config.get('weapon')=='studio_sword_v1') or (config.get('schema')==2 and config.get('weapon')=='asset')):
        raise ValueError('不支持的装备配置版本')
    if config.get('schema')==2:
        import re
        if not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}',str(config.get('weapon_asset',''))) or not re.fullmatch(r'[a-f0-9]{64}',str(config.get('weapon_model_sha256',''))):
            raise ValueError('武器资产来源无效')
        length=config.get('weapon_length')
        if isinstance(length,bool) or not isinstance(length,(int,float)) or not math.isfinite(length) or not .1<=length<=2:
            raise ValueError('武器长度无效')
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
    if np.max(np.abs(config['weapon_points']))>(4 if config.get('schema')==2 else 2):
        raise ValueError('武器标注超出标准剑范围')
    if config.get('confirmed') is not True:
        raise ValueError('装备尚未经过人工预览确认')
    return config


def load(root, character, batch, equipment_id):
    import studio_core as studio
    studio.slug(character)
    if batch is not None: studio.slug(batch)
    studio.slug(equipment_id)
    directory=root/'workspaces'/character/'equipment'/equipment_id
    if directory.is_symlink() or not directory.resolve().is_relative_to((root/'workspaces'/character/'equipment').resolve()):
        raise ValueError('非法装备路径')
    config=validate(json.loads((directory/'equipment.json').read_text()))
    if config.get('character')!=character or not config.get('rig_sha256'):
        raise ValueError('装备配置与人物或绑定版本不匹配，请重新检查挂点')
    if batch is not None:
        receipt=json.loads((root/'workspaces'/character/'animations'/batch/'batch.json').read_text())
        if (not receipt.get('rig_sha256') or config['rig_sha256']!=receipt['rig_sha256']
                or receipt.get('character',character)!=character or receipt.get('batch',batch)!=batch):
            raise ValueError('装备配置与人物或绑定版本不匹配，请重新检查挂点')
    if config.get('schema')==2:
        from weapon_assets import digest
        model=directory/'weapon.glb'
        if model.is_symlink() or not model.is_file() or digest(model)!=config['weapon_model_sha256']:
            raise ValueError('装备的武器模型快照缺失或已变化')
    return config


def edit(character,batch,equipment_id=None,weapon_id=None):
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
    if weapon_id and equipment_id:
        raise ValueError('编辑已有装备时不能替换武器来源，请新建装备')
    if weapon_id:
        from weapon_assets import load as load_weapon, asset_dir
        asset=load_weapon(root,weapon_id,confirmed=True)
        length=asset['length_meters']; grip=np.asarray(asset['grip'])*length
        config.update(schema=2,weapon='asset',weapon_asset=weapon_id,weapon_name=asset['name'],
                      weapon_model_sha256=asset['model_sha256'],weapon_length=length,
                      weapon_points=[grip.tolist(),(grip+np.array([0,.6*length,0])).tolist(),(grip+np.array([.1*length,0,0])).tolist()])
        shutil.copy2(asset_dir(root,weapon_id)/'model.glb',directory/'weapon.glb')
    elif config.get('schema')==2:
        shutil.copy2(root/'workspaces'/character/'equipment'/equipment_id/'weapon.glb',directory/'weapon.glb')
    config.update(character=character,batch=batch,files=receipt['files'],rig_sha256=binding['bound_sha256'],confirmed=False)
    output=directory/'equipment.json'
    # Editor writes only on explicit confirmation; closing the window is a failed task.
    review(character,batch,equipment_editor={'draft':config,'output':str(output),'screenshot':str(directory/'review.png'),'model':str(directory/'weapon.glb') if config.get('schema')==2 else None})
    if not output.is_file():
        raise ValueError('装备标注未保存；关闭窗口不会自动确认')
    result=validate(json.loads(output.read_text()))
    if any(result.get(k)!=config.get(k) for k in ('character','batch','files','rig_sha256','schema','weapon','weapon_asset','weapon_model_sha256','weapon_length','weapon_points')):
        raise ValueError('标注期间来源版本发生变化')
    if equipment_id:
        from equipment_usage import load as load_usage
        from weapon_assets import digest
        usage=load_usage(root,character,equipment_id)
        usage['equipment_sha256']=digest(output)
        (directory/'usage.json').write_text(json.dumps(usage,ensure_ascii=False,indent=2)+'\n')
    studio.progress_update(character,'review','装备标注已确认并保存，可选择该配置烘焙图集',status='waiting',batch=batch,output=str(directory))
    return directory


def copy_runtime(root,project):
    shutil.copy2(root/'pipeline/equipment/runtime.gd',project/'equipment_runtime.gd')


def stage_model(config, source, project):
    """A project-local immutable model snapshot shared by viewer and baker."""
    if config.get('schema')!=2: return
    from weapon_assets import digest
    source=Path(source)
    if source.is_symlink() or digest(source)!=config['weapon_model_sha256']:
        raise ValueError('武器快照校验失败')
    shutil.copy2(source,project/'weapon.glb')
    if digest(project/'weapon.glb')!=config['weapon_model_sha256']:
        raise ValueError('复制期间武器模型发生变化')
