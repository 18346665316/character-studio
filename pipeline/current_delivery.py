"""Publish one editable result per original render and action selection."""
from hashlib import sha256
import json
from pathlib import Path
import shutil

from asset_repository import AssetRepository, atomic, name, read


def original(root, character, delivery):
    assets = AssetRepository(root)
    seen = set()
    while delivery not in seen:
        seen.add(delivery)
        path = assets.scoped(f'deliverables/{name(character)}/{name(delivery)}', f'deliverables/{character}')
        manifest = read(path/'manifest.json', {})
        if manifest.get('source', {}).get('character') != character:
            raise ValueError('原始图集不存在或人物不匹配')
        parent = manifest.get('operation', {}).get('source_delivery')
        if not parent:
            return path
        delivery = parent
    raise ValueError('图集来源循环，请重新生成成果')


def clips(manifest):
    return sorted(k.removesuffix('_spritesheet.png') for k in manifest if k.endswith('_spritesheet.png'))


def publish(root, character, stage, source):
    """Replace the current result after processing succeeds; never edit the raw input.

    The caller holds the production lock. A temporary backup exists only during
    replacement, so a failed write restores the previous result and action set.
    """
    root, stage = Path(root), Path(stage)
    base = original(root, character, source)
    manifest = read(stage/'manifest.json')
    selected = clips(manifest)
    key = sha256(json.dumps([base.name, selected]).encode()).hexdigest()[:20]
    target = base.parent/('current-'+key)
    manifest['operation'] = {'source_delivery': base.name}
    atomic(stage/'manifest.json', manifest)
    recipe_path = root/'workspaces'/name(character)/'action_set.json'
    recipe_bytes = recipe_path.read_bytes() if recipe_path.is_file() else None
    transaction = root/'.local/current-update'/name(character)/key
    transaction.mkdir(parents=True, exist_ok=True)
    backup = transaction/'previous-current'
    if backup.exists():
        raise ValueError('上一次成果替换未完成，请先恢复当前成果')
    replaced = target.exists()
    if replaced:
        target.rename(backup)
    try:
        stage.rename(target)
        recipe = read(recipe_path)
        # Existing current-result references keep working after an edit.
        if recipe and any(a.get('delivery') in (source, target.name) and a.get('clip') in selected for a in recipe['actions'].values()):
            from action_set import save
            for choice in recipe['actions'].values():
                if choice.get('delivery') in (source, target.name) and choice.get('clip') in selected:
                    choice['delivery'] = target.name
            save(root, character, recipe)
    except BaseException:
        if target.exists():
            shutil.rmtree(target)
        if replaced:
            backup.rename(target)
        if recipe_bytes is not None:
            recipe_path.write_bytes(recipe_bytes)
        raise
    shutil.rmtree(backup, ignore_errors=True)
    transaction.rmdir()
    _remove_unused_edits(root, character, base, selected, target)
    # Successful processing inputs are temporary, not another retained version.
    scratch = root/'.local/jobs'/stage.name
    report = read(scratch/'quality.json', {})
    if not report.get('summary', {}).get('failed'):
        shutil.rmtree(scratch, ignore_errors=True)
    return target


def _remove_unused_edits(root, character, base, selected, current):
    """Retire superseded edits only when no materialized source or recipe needs them."""
    manifests = {p.parent.name: read(p, {}) for p in base.parent.glob('*/manifest.json')}
    candidates = set()
    for identity, manifest in manifests.items():
        if (identity in (base.name, current.name) or manifest.get('source', {}).get('character') != character
                or not manifest.get('operation') or clips(manifest) != selected):
            continue
        try:
            if original(root, character, identity) == base:
                candidates.add(identity)
        except (ValueError, OSError):
            continue
    recipe = read(root/'workspaces'/character/'action_set.json', {})
    protected = {a.get('delivery') for a in recipe.get('actions', {}).values()}
    sequence = read(root/'workspaces'/character/'sequence.json', {})
    protected.update(segment.get('delivery') for segment in sequence.get('segments', []))
    # An edit outside this replacement group may still use an intermediate input.
    protected.update(identity for identity in manifests if identity not in candidates)
    pending = list(protected)
    while pending:
        manifest = manifests.get(pending.pop(), {})
        for field in ('source_delivery', 'timing_delivery'):
            dependency = manifest.get('operation', {}).get(field)
            if dependency and dependency not in protected:
                protected.add(dependency)
                pending.append(dependency)
    for identity in candidates - protected:
        directory = base.parent/identity
        if not directory.is_symlink():
            shutil.rmtree(directory)
