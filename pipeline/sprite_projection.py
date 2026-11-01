"""Fixed reference-body pixel density, independent of action and weapon bounds."""
import math
from pathlib import Path

BODY_HEIGHTS = (48,64,96,128)


def plan(measured, body_height, supersample, reference_sha256):
    if type(body_height) is not int or body_height not in BODY_HEIGHTS:
        raise ValueError('人物高度应为 48、64、96 或 128 像素')
    if type(supersample) is not int or supersample not in (1,2,4):
        raise ValueError('无效的超采样倍率')
    height = measured['reference_height']
    values = [height,*measured['screen_min'],*measured['screen_max'],*measured['reference_origin']]
    if any(not isinstance(v,(float,int)) or not math.isfinite(v) for v in values) or height<=0:
        raise ValueError('无效的角色测量范围')
    density = body_height / height
    lo,hi=measured['screen_min'],measured['screen_max']
    origin=measured['reference_origin']
    angle={'front':0,'side':math.pi/2,'three_quarter':math.pi/4}[measured['view']]
    right=(math.cos(angle),0,-math.sin(angle))
    anchor_x=origin[0]*right[0]+origin[2]*right[2]
    # Include the stable feet origin even when every selected pose is airborne.
    low=[min(lo[0],anchor_x),min(lo[1],origin[1])]
    high=[max(hi[0],anchor_x),max(hi[1],origin[1]+height)]
    center=[round((low[i]+high[i])*0.5*density)/density for i in range(2)]
    half=max(max(center[i]-low[i],high[i]-center[i]) for i in range(2))
    size=math.ceil(half*density+4)*2
    if size>1024: raise ValueError('动作位移过大，画布超过 1024px；请使用原地动作或缩短动作')
    if size*supersample*16 > 16384:
        raise ValueError('超采样图集超过纹理尺寸限制，请降低超采样倍率或人物像素高度')
    camera_center=[right[0]*center[0],center[1],right[2]*center[0]]
    return {'schema':1,'policy':'reference_body_height_v1','body_height_px':body_height,
            'reference_height':height,'reference_sha256':reference_sha256,
            'pixels_per_source_unit':density,'frame_size':size,'render_size':size*supersample,
            'camera_size':size/density,'camera_center':camera_center,'view':measured['view'],
            'anchor_px':[(anchor_x-center[0])*density+size/2,(center[1]-origin[1])*density+size/2],
            'reference_origin':origin,'supersample':supersample}


def stage_reference(root, character, receipt, project, digest):
    import json,shutil
    state=json.loads((root/'.local/mixamo'/character/'state.json').read_text())
    sha=receipt.get('rig_sha256')
    source=Path(state.get('bound_model',''))
    rig_directory=(root/'workspaces'/character/'rig').resolve()
    if not sha or state.get('bound_sha256')!=sha or not source.is_file() or not source.resolve().is_relative_to(rig_directory) or digest(source)!=sha:
        raise ValueError('标准站姿绑定文件缺失或与动作绑定不一致，请恢复本人物绑定')
    shutil.copy2(source,project/'reference.fbx')
    if digest(project/'reference.fbx')!=sha: raise ValueError('标准站姿文件在复制期间已变化')
    return sha
