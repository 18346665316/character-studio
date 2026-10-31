"""Local Mixamo handoff state; no credentials in workspace receipts."""
import hashlib
import json
from pathlib import Path
import re
import tempfile
import os

BASE_DIR = Path(__file__).resolve().parent.parent


def character_name(value):
    if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]*', value):
        raise ValueError('Invalid character name')
    return value


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def state_path(character):
    return BASE_DIR / '.local/mixamo' / character_name(character) / 'state.json'


def read_state(character):
    path = state_path(character)
    return json.loads(path.read_text()) if path.exists() else {'character': character, 'status': 'unbound'}


def write_state(character, status, **fields):
    path = state_path(character)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {'character': character, 'status': status, **fields}
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.state-', suffix='.json')
    with os.fdopen(fd, 'w') as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    os.replace(temporary, path)
    return data


class MeshIdentityError(ValueError):
    """Downloaded cloud character differs from the reviewed local reference."""


def cloud_recoverable(state):
    if state.get('status')!='needs_review' or not state.get('human_reviewed'):
        return False
    if state.get('cloud_recovery') is False:
        return False
    return state.get('cloud_recovery') is True or any(text in (state.get('error') or '') for text in ('网格面数与角色不符','默认人偶'))


def require_ready(character, model=None, allow_cloud_recovery=False):
    state = read_state(character)
    if (state.get('status') != 'ready' and not (allow_cloud_recovery and cloud_recoverable(state))) or not state.get('human_reviewed'):
        if state.get('status')=='needs_review':
            raise ValueError((state.get('error') or 'Mixamo 云端人物需要复核')+'。请在“人工绑定”恢复并确认本角色；本地模型和已有动作仍保留。')
        raise ValueError(f'角色尚未完成人工绑定验收（{state.get("status")}），请运行 ./studio rig --character {character}')
    bound = Path(state['bound_model'])
    if not bound.is_file() or file_hash(bound) != state['bound_sha256']:
        raise ValueError('绑定模型缺失或已变更，请重新绑定验收')
    source = Path(model) if model else Path(state['source_model'])
    if not source.is_file() or file_hash(source) != state['source_sha256']:
        raise ValueError('源模型已变更，请重新绑定验收')
    return state


def check_mesh_identity(info, reference):
    if info.get('skeleton_bones', 0) < 1 or info.get('skinned_meshes', 0) < 1:
        raise MeshIdentityError('下载文件没有蒙皮网格和骨骼')
    names = set(info.get('mesh_names', []))
    if {'Beta_Joints', 'Beta_Surface'} & names and not ({'Beta_Joints', 'Beta_Surface'} & set(reference.get('mesh_names', []))):
        raise MeshIdentityError('下载文件是 Mixamo 默认人偶，拒绝登记为此角色')
    if reference.get('textured_surfaces', 0) > 0 and info.get('textured_surfaces', 0) < 1:
        raise MeshIdentityError('角色贴图在 Mixamo 往返中丢失，请检查 OBJ/MTL/PNG 上传包')
    expected = reference.get('triangles', 0)
    actual = info.get('triangles', 0)
    if expected < 1 or abs(actual - expected) > max(4, expected * 0.05):
        raise MeshIdentityError(f'下载网格面数与角色不符（角色 {expected}，下载 {actual}）')


def check_bound_skeleton(info, reference):
    expected=reference.get('bone_names')
    if expected and info.get('bone_names')!=expected:
        raise MeshIdentityError('下载骨骼结构与已验收绑定不符')


def check_motion(info):
    if not any(a.get('changing_tracks', 0) > 0 for a in info.get('animations', [])):
        raise ValueError('下载文件没有有效动态轨道，拒绝作为动作使用')
