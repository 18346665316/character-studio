"""Weapon presentation settings, independent of immutable grip annotations.
Action overrides are keyed by source content hash, never by a display title.
"""
import hashlib
import json
import math
from pathlib import Path

STATES=('hand','back','waist','hidden')
DEFAULT_MOUNTS={
    'back':{'bone':'mixamorig_Spine2','position':[0,0,-.12],'rotation':[0,0,-20]},
    'waist':{'bone':'mixamorig_Hips','position':[.18,0,-.05],'rotation':[180,0,-15]},
}


def validate(data):
    if not isinstance(data,dict) or data.get('schema')!=1 or data.get('default') not in STATES:
        raise ValueError('武器持用设置无效')
    mounts=data.get('mounts')
    if not isinstance(mounts,dict) or set(mounts)!=set(DEFAULT_MOUNTS): raise ValueError('缺少收纳挂点')
    for state,mount in mounts.items():
        if not isinstance(mount,dict) or mount.get('bone')!=DEFAULT_MOUNTS[state]['bone']: raise ValueError('收纳骨骼无效')
        for key,limit in [('position',.6),('rotation',180)]:
            values=mount.get(key)
            if not isinstance(values,list) or len(values)!=3 or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or abs(v)>limit for v in values):
                raise ValueError('收纳位置需在 ±0.6 米内，角度需在 ±180 度内')
    actions=data.get('actions')
    if not isinstance(actions,dict) or len(actions)>500: raise ValueError('动作持用设置无效')
    for sha,action in actions.items():
        if not isinstance(sha,str) or len(sha)!=64 or any(c not in '0123456789abcdef' for c in sha): raise ValueError('动作来源无效')
        validate_action(action)
    return data


def validate_action(action):
    if not isinstance(action,dict) or action.get('initial') not in (*STATES,'inherit'): raise ValueError('动作初始状态无效')
    events=action.get('events')
    if not isinstance(events,list) or len(events)>16: raise ValueError('每个动作最多设置16次切换')
    previous=-1
    for event in events:
        if not isinstance(event,dict) or event.get('state') not in STATES: raise ValueError('切换状态无效')
        phase=event.get('at')
        if isinstance(phase,bool) or not isinstance(phase,(int,float)) or not math.isfinite(phase) or not 0<phase<1 or phase<=previous:
            raise ValueError('切换位置需按顺序填写在动作的0%与100%之间，不能重复')
        previous=phase
    return action


def load(root,character,equipment_id):
    from equipment import load as load_equipment
    from weapon_assets import digest
    config=load_equipment(root,character,None,equipment_id)
    directory=Path(root)/'workspaces'/character/'equipment'/equipment_id
    pin=digest(directory/'equipment.json')
    path=directory/'usage.json'
    if path.is_symlink(): raise ValueError('非法持用配置路径')
    if path.exists():
        data=validate(json.loads(path.read_text()))
        if data.get('equipment_sha256')!=pin or data.get('rig_sha256')!=config['rig_sha256']:
            raise ValueError('持用设置与装备或绑定版本不匹配')
        return data
    return {'schema':1,'equipment_sha256':pin,'rig_sha256':config['rig_sha256'],
            'default':'hand','mounts':json.loads(json.dumps(DEFAULT_MOUNTS)),'actions':{}}


def fingerprint(data):
    return hashlib.sha256(json.dumps(data,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def save(root,character,equipment_id,default,mounts,batch=None,file=None,action=None):
    from equipment import load as load_equipment
    from weapon_assets import digest
    from panel import atomic
    data=load(root,character,equipment_id)
    data.update(default=default,mounts=mounts)
    if batch is not None:
        from mixamo_state import character_name
        character_name(batch)
        load_equipment(root,character,batch,equipment_id)
        receipt_path=Path(root)/'workspaces'/character/'animations'/batch/'batch.json'
        receipt=json.loads(receipt_path.read_text())
        if not isinstance(file,str) or Path(file).name!=file or file not in receipt['files']: raise ValueError('请选择此来源内的动作')
        sha=receipt['files'][file]
        source=receipt_path.parent/file
        if source.is_symlink() or digest(source)!=sha: raise ValueError('动作文件已变化')
        validate_action(action)
        if action=={'initial':'inherit','events':[]}: data['actions'].pop(sha,None)
        else: data['actions'][sha]=action
    validate(data)
    path=Path(root)/'workspaces'/character/'equipment'/equipment_id/'usage.json'
    atomic(path,data)
    return data


def recipe(data,files):
    return {'schema':1,'default':data['default'],'mounts':data['mounts'],
            'clips':{Path(name).stem:data['actions'].get(sha,{'initial':'inherit','events':[]}) for name,sha in files.items()}}
