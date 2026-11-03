"""Explicit deletion of local projects and library assets, with live-reference checks."""
from hashlib import sha256
from pathlib import Path
import shutil

from asset_repository import AssetRepository, name, read
from task_lock import serialized

FOLDERS = {'terrain': 'terrain-kits', 'transition': 'terrain-transitions',
           'prop': 'prop-kits', 'component': 'component-kits',
           'building': 'building-kits', 'character': 'workspaces'}


def _path(root, relative, subtree):
    path = Path(root)/relative
    if path.is_symlink():
        raise ValueError('不能通过符号链接删除素材')
    return AssetRepository(root).scoped(relative, subtree)


def _target(root, data):
    kind, identity = data.get('kind'), name(data.get('id'))
    if kind == 'project':
        from studio_projects import load
        value = load(root, identity)
        path = _path(root, '.local/studio/projects/'+identity, '.local/studio/projects')
        return path, value['title'], [path]
    if kind == 'item':
        from studio_projects import load, item
        project = load(root, name(data.get('project')))
        entry = item(project, identity)
        path = _path(root, '.local/studio/projects/'+project['id']+'/project.json', '.local/studio/projects')
        return path, entry['title'], [path]
    if kind == 'scene':
        path = _path(root, '.local/module-scenes/'+identity+'.json', '.local/module-scenes')
        value = read(path)
        if not value:
            raise ValueError('场景不存在')
        return path, value['title'], [path]
    if kind != 'asset' or data.get('family') not in FOLDERS:
        raise ValueError('删除对象无效')
    family = data['family']; directory = FOLDERS[family]
    path = _path(root, directory+'/'+identity, directory)
    if not path.is_dir():
        raise ValueError('素材不存在或已删除')
    manifest = read(path/('character.json' if family == 'character' else 'manifest.json'), {})
    paths = [path]
    if family == 'character':
        for directory in ('deliverables', '.local/mixamo', '.local/production'):
            extra = _path(root, directory+'/'+identity, directory)
            if extra.exists(): paths.append(extra)
        progress = _path(root, '.local/progress/'+identity+'.json', '.local/progress')
        if progress.exists(): paths.append(progress)
        for directory, record in (('.local/jobs','job.json'),('.local/scene-characters','manifest.json')):
            for file in (Path(root)/directory).glob('*/'+record):
                if read(file, {}).get('character') == identity:
                    paths.append(_path(root,str(file.parent.relative_to(root)),directory))
        for file in (Path(root)/'.local/panel/tasks').glob('*.json'):
            if read(file, {}).get('character') == identity:
                paths.append(_path(root,str(file.relative_to(root)),'.local/panel/tasks'))
                log=file.with_suffix('.log')
                if log.exists(): paths.append(_path(root,str(log.relative_to(root)),'.local/panel/tasks'))
    return path, manifest.get('title') or manifest.get('display_name') or identity, paths


def references(root, family, identity):
    result = []
    from studio_projects import catalog, current_assets
    for project in catalog(root):
        current = current_assets(root, project)
        for entry in project['items'] + project.get('archived_items', []):
            selected = entry.get('asset_ref') or entry.get('selected') or {}
            live = current.get(entry['id'], {})
            if ((live.get('family') == family and live.get('id') == identity) if live else
                    (selected.get('family') == family and selected.get('asset') == identity)):
                result.append('项目「'+project['title']+'」 / '+entry['title'])
    for path in (Path(root)/'.local/module-scenes').glob('*.json'):
        scene = read(path)
        if not scene: continue
        for module in scene.get('modules', []):
            source = module.get('source', {})
            matches = source.get('family') == family and source.get('id') == identity
            if family == 'character' and source.get('family') == 'character':
                snapshot = read(Path(root)/'.local/scene-characters'/name(source.get('id'))/'manifest.json', {})
                matches = snapshot.get('character') == identity
            if matches:
                result.append('验证场景「'+scene['title']+'」 / '+module['title'])
    if family == 'terrain':
        for path in (Path(root)/'terrain-transitions').glob('*/manifest.json'):
            manifest = read(path, {})
            if any(source.get('kit') == identity for source in manifest.get('sources', [])):
                result.append('地表过渡「'+manifest.get('title',path.parent.name)+'」')
    return list(dict.fromkeys(result))


def _fingerprint(paths):
    digest = sha256()
    for path in paths:
        files = [path] + sorted(path.rglob('*')) if path.is_dir() else [path]
        for file in files:
            stat = file.lstat()
            digest.update(str((str(file),stat.st_mode,stat.st_size,stat.st_mtime_ns)).encode())
    return digest.hexdigest()


def inspect(root, data):
    _, title, paths = _target(root, data)
    refs = references(root,data['family'],data['id']) if data.get('kind') == 'asset' else []
    return {'title': title, 'references': refs, 'fingerprint': _fingerprint(paths)}


@serialized(lambda root, *args, **kwargs: root)
def delete(root, data):
    state = inspect(root, data)
    if state['references']:
        raise ValueError('正在使用，不能删除：'+'；'.join(state['references']))
    if not data.get('fingerprint') or data['fingerprint'] != state['fingerprint']:
        raise ValueError('内容已更新，请重新打开删除窗口')
    _, _, paths = _target(root, data)
    if data['kind'] == 'item':
        from studio_projects import load, change
        project = load(root, data['project'])
        change(root, {'action':'delete_item','project':project['id'],'revision':project['revision'],'item':data['id']})
    else:
        for path in paths:
            if path.is_dir(): shutil.rmtree(path)
            else: path.unlink()
    return {'deleted': True}
