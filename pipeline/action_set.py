"""A character's adopted action set; candidates remain immutable deliveries."""
import json
from datetime import datetime, timezone
from asset_repository import AssetRepository, atomic, name, read
from game_package import build
from task_lock import serialized


def path(root, character):
    return AssetRepository(root).scoped(f'workspaces/{name(character)}/action_set.json', f'workspaces/{character}')


def load(root, character):
    return read(path(root, character), None)


def clean(data):
    title = data.get('title', '角色动作集')
    actions = data.get('actions')
    if not isinstance(title, str) or not 1 <= len(title.strip()) <= 60:
        raise ValueError('动作集名称需为1–60个字符')
    if not isinstance(actions, dict) or not 1 <= len(actions) <= 32:
        raise ValueError('动作集需包含1–32个动作槽位')
    result = {}
    for role, choice in actions.items():
        name(role)
        if not isinstance(choice, dict): raise ValueError('动作设置无效')
        loop, reviewed = choice.get('loop', False), choice.get('reviewed', False)
        if type(loop) is not bool or type(reviewed) is not bool:
            raise ValueError('循环与验收设置须为布尔值')
        entry = {'loop': loop, 'reviewed': reviewed}
        if choice.get('delivery') or choice.get('clip'):
            entry.update(delivery=name(choice.get('delivery')), clip=name(choice.get('clip')), variant=choice.get('variant', 'game'))
            if entry['variant'] not in ('game', 'source'): raise ValueError('未知图集版本')
        result[role] = entry
    return {'schema': 'character_studio.action_set/1.0', 'title': title.strip(), 'actions': result}


def source(root, character, choice):
    assets = AssetRepository(root)
    base = f'deliverables/{name(character)}/{name(choice["delivery"])}'
    manifest = assets.scoped(base+'/manifest.json', f'deliverables/{character}')
    data = json.loads(manifest.read_text())
    if data.get('source', {}).get('character') != character: raise ValueError('图集人物不匹配')
    if data.get('source', {}).get('kind') == 'sequence': raise ValueError('请采用独立动作成果，编排预览不能作为动作来源')
    clip = name(choice['clip'])
    info = data.get(clip+'_spritesheet.png', {})
    if choice['variant'] == 'game': info = info.get('game', {})
    if not info: raise ValueError('所选图集版本不存在')
    from motion_heading import records as heading_records
    headings = heading_records(root, character, data.get('source', {}).get('files', {}))
    for file, value in headings.items():
        if file.rsplit('/', 1)[-1].removesuffix('.fbx') == clip and abs(float(info.get('heading', {}).get('degrees', 0))-float(value.get('degrees', 0))) > .001:
            raise ValueError('动作朝向设置已变化，请重新渲染')
    sheet = assets.scoped(base+('/game/' if choice['variant']=='game' else '/')+clip+'_spritesheet.png', f'deliverables/{character}')
    fingerprint = {'manifest': assets.digest(manifest), 'sheet': assets.digest(sheet)}
    if data.get('color_processing'):
        palette = assets.scoped(base+'/palette.json', f'deliverables/{character}')
        colors = json.loads(palette.read_text()).get('rgb')
        if not isinstance(colors, list) or not colors: raise ValueError('缺少有效调色板')
        fingerprint['palette'] = assets.digest(palette)
    return data, info, fingerprint


def inspect(root, character, recipe=None):
    recipe = recipe if recipe is not None else load(root, character)
    if not recipe: return {'status':'draft', 'errors':[], 'warnings':[], 'actions':{}, 'complete':False}
    errors, warnings, rows, choices = [], [], {}, {}
    colors, equipment = {}, {}
    for role, choice in recipe['actions'].items():
        issues = []
        if not choice.get('delivery'):
            issues.append('尚未选择成果')
        else:
            try:
                data, info, fingerprint = source(root, character, choice)
                if choice.get('fingerprint') != fingerprint: issues.append('来源已变化，请重新选择并保存')
                # The existing exporter validates actual atlas capacity, timing and provenance.
                build(root, character, {role:choice}, report_only=True, action_set=True)
                colors[role] = data.get('color_processing', {}).get('palette_sha256') if data.get('color_processing') else 'original'
                if data.get('color_processing'):
                    palette = AssetRepository(root).scoped(f'deliverables/{character}/{choice["delivery"]}/palette.json', f'deliverables/{character}')
                    colors[role] = json.dumps(read(palette, {}).get('rgb'), sort_keys=True)
                equipment[role] = (data.get('equipment') or {}).get('id')
                choices[role] = choice
                if not choice.get('reviewed'): warnings.append(f'{role}：尚未人工验收动作与循环效果')
                rows[role] = {'frame_count':info['frame_count'], 'duration_seconds':info['duration_seconds'], 'body_height_px':info.get('body_height_px'), 'anchor_px':info.get('anchor_px')}
            except (ValueError, OSError, KeyError, TypeError) as exc:
                issues.append(str(exc))
        rows.setdefault(role, {})['errors'] = issues
        errors.extend(f'{role}：{issue}' for issue in issues)
    if len(set(colors.values())) > 1: errors.append('动作配色不一致：请采用同一份共享调色板，或统一保留原色')
    if len(set(equipment.values())) > 1: warnings.append('动作间装备不同，请确认属于预期的持用切换')
    if choices:
        try:
            report = build(root, character, choices, report_only=True, action_set=True)
            warnings.extend(report['warnings'])
        except (ValueError, OSError, KeyError, TypeError) as exc: errors.append(str(exc))
    return {'status':'blocked' if errors else 'review' if warnings else 'ready', 'complete':not errors, 'errors':errors, 'warnings':list(dict.fromkeys(warnings)), 'actions':rows}


@serialized(lambda root, *args, **kwargs: root)
def save(root, character, data):
    target = path(root, character)
    if not target.parent.is_dir(): raise ValueError('人物不存在')
    previous = load(root, character) or {}
    if data.get('revision', 0) != previous.get('revision', 0):
        raise ValueError('动作集已在其他页面更新，请刷新后重试')
    recipe = clean(data)
    for role, choice in recipe['actions'].items():
        if choice.get('delivery'):
            _, _, choice['fingerprint'] = source(root, character, choice)
            old = previous.get('actions', {}).get(role, {})
            # A changed source or playback policy must be reviewed again.
            if old and any(old.get(k) != choice.get(k) for k in ('delivery','clip','variant','loop','fingerprint')):
                choice['reviewed'] = False
    recipe.update(character=character, revision=previous.get('revision', 0)+1, updated_at=datetime.now(timezone.utc).isoformat())
    atomic(target, recipe)
    return {'recipe':recipe, 'validation':inspect(root, character, recipe)}


def export(root, character):
    recipe = load(root, character)
    report = inspect(root, character, recipe)
    if not recipe or not report['complete']: raise ValueError('动作集尚不能交付：'+'；'.join(report['errors'] or ['请先保存动作集']))
    import io, zipfile
    content = build(root, character, recipe['actions'], action_set=True)
    stream = io.BytesIO(content)
    with zipfile.ZipFile(stream, 'a', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f'character_assets/{character}/action_set.json', json.dumps({'recipe':recipe, 'validation':report}, ensure_ascii=False, indent=2))
    return stream.getvalue()
