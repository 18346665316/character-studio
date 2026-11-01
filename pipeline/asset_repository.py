"""Filesystem asset storage and character read models, independent of HTTP."""
import hashlib
import json
import os
from pathlib import Path
import secrets
from urllib.parse import quote

def name(value):
    import re
    if not isinstance(value, str) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}', value):
        raise ValueError('名称限 1–80 个字母、数字、下划线或短横线')
    return value


def read(path, fallback=None):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return fallback


def atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + secrets.token_hex(4) + '.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    os.replace(temp, path)


class AssetRepository:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.hash_cache = {}

    def scoped(self, relative, subtree=None):
        if not isinstance(relative, str):
            raise ValueError('非法资产路径')
        candidate = self.root / relative
        # Reject symlink components before resolving the requested boundary too.
        try:
            components = candidate.relative_to(self.root).parts
        except ValueError:
            raise ValueError('资产路径越界')
        current = self.root
        for part in components:
            current = current / part
            if current.is_symlink():
                raise ValueError('不允许通过符号链接访问资产')
        path = candidate.resolve()
        boundary = (self.root / subtree).resolve() if subtree else self.root
        if not path.is_relative_to(boundary) or path == boundary:
            raise ValueError('资产路径越界')
        return path

    def digest(self, path):
        stat = path.stat()
        key = (str(path), stat.st_mtime_ns, stat.st_size)
        if key not in self.hash_cache:
            if len(self.hash_cache) > 500:
                self.hash_cache.clear()
            self.hash_cache[key] = hashlib.sha256(path.read_bytes()).hexdigest()
        return self.hash_cache[key]

    def game_clip(self, directory, info):
        if not info:return None
        return {'sheet':self.asset(directory/info['sheet']), 'gif':self.asset(directory/info['gif']),
                'spriteframes':self.asset(directory/info['spriteframes']), 'info':info}

    def asset(self, path):
        return '/asset/' + quote(str(path.relative_to(self.root)), safe='/') if path.is_file() else None

    def asset_path(self, relative):
        # Expose only character production assets, never .local, credentials, code,
        # arbitrary files or a symlink outside its original character subtree.
        parts = Path(relative).parts
        if len(parts)==3 and parts[0]=='weapons':
            from weapon_assets import load as load_weapon, asset_dir
            load_weapon(self.root,parts[1])
            if parts[2] not in ('front.png','contact.png','model.glb','original.png','processed.png'):
                raise ValueError('禁止访问此武器文件')
            return self.scoped(relative,'weapons/'+parts[1])
        if len(parts) < 4 or parts[0] not in ('workspaces', 'deliverables'):
            raise ValueError('禁止访问此文件')
        name(parts[1])
        if parts[0] == 'workspaces' and parts[2] not in ('inputs', 'models', 'rig', 'animations', 'reviews', 'equipment'):
            raise ValueError('禁止访问此工作区目录')
        if parts[0] == 'deliverables':
            name(parts[2])
        path = self.scoped(relative, '/'.join(parts[:3]))
        if path.suffix.lower() not in ('.png', '.jpg', '.jpeg', '.webp', '.gif', '.glb', '.fbx', '.zip', '.json', '.tres') or not path.is_file():
            raise ValueError('文件不存在或不可预览')
        return path

    def binding(self, character, prepared):
        ws = self.root / 'workspaces' / name(character)
        state = read(self.root / '.local/mixamo' / character / 'state.json', {'status':'unbound'})
        rig_ready = False
        from mixamo_state import cloud_recoverable
        recovery_available=cloud_recoverable(state)
        if prepared and (state.get('status') == 'ready' or recovery_available) and state.get('human_reviewed'):
            try:
                bound = self.scoped(str(Path(state['bound_model']).relative_to(self.root)), f'workspaces/{character}/rig')
                upload = ws / 'models/prepared' / prepared['id'] / 'mixamo.zip'
                rig_ready = bound.is_file() and self.digest(bound) == state['bound_sha256'] and self.digest(upload) == state['source_sha256']
            except (ValueError, KeyError, OSError):
                pass
        return state, rig_ready, recovery_available

    def sequence_inputs(self, character):
        """Only binding and published source references needed by arrangement planning."""
        character = name(character)
        ws = self.root / 'workspaces' / character
        if not ws.is_dir() or ws.is_symlink():
            raise ValueError('角色不存在')
        model = ws / 'models' / (character + '.obj')
        prepared = None
        for path in sorted(ws.glob('models/prepared/*/prepare.json'), key=lambda p:p.stat().st_mtime, reverse=True):
            if model.is_file() and read(path, {}).get('source_sha256') == self.digest(model):
                prepared = {'id':path.parent.name}
                break
        state, ready, _ = self.binding(character, prepared)
        deliveries = []
        for path in (self.root / 'deliverables' / character).glob('*/manifest.json'):
            data = read(path, {})
            if data.get('source', {}).get('character') != character or data.get('source', {}).get('kind') == 'sequence':
                continue
            deliveries.append({'id':path.parent.name, 'batch':data['source'].get('batch'),
                               'clips':[{'name':p.name.removesuffix('_spritesheet.png')}
                                        for p in path.parent.glob('*_spritesheet.png') if p.name in data]})
        return {'rig':{'ready':bool(ready)}, 'deliveries':deliveries}

    def character(self, character):
        character = name(character)
        ws = self.root / 'workspaces' / character
        if not ws.is_dir() or ws.is_symlink():
            raise ValueError('角色不存在')
        relative = lambda p: str(p.relative_to(self.root))
        files = lambda pattern: sorted(ws.glob(pattern), key=lambda p:p.stat().st_mtime, reverse=True)
        inputs = [{'path': relative(p), 'url': self.asset(p), 'name': p.name} for p in sorted(ws.glob('inputs/*/*'), key=lambda p:p.parent.stat().st_mtime, reverse=True)
                  if p.suffix.lower() in ('.png', '.jpg', '.jpeg', '.webp') and not p.is_symlink()][:20]
        model = ws / 'models' / (character + '.obj')
        prepared = None
        for path in files('models/prepared/*/prepare.json'):
            info = read(path, {})
            if model.is_file() and info.get('source_sha256') == self.digest(model):
                prepared = {'id': path.parent.name, 'fingerprint': self.digest(path), 'info': info,
                            'contact': self.asset(path.parent / 'previews/contact_sheet.png'),
                            'glb': self.asset(path.parent / 'preview.glb')}
                break
        optimizations=[]
        for report_path in files('models/optimizations/*/report.json'):
            report=read(report_path,{})
            if model.is_file() and report.get('source_sha256')==self.digest(model):
                optimizations.append({'id':report_path.parent.name,'report':report,'comparison':self.asset(report_path.parent/'comparison.png'),
                                      'report_url':self.asset(report_path),'pixel_comparisons':{str(size):self.asset(report_path.parent/f'comparison_{size}.png') for size in (64,128)},
                                      'variants':[{'id':v['id'],'triangles':v['triangles'],'glb':self.asset(report_path.parent/v['id']/'preview.glb')} for v in report.get('variants',[]) if v['id']!='original']})
        state, rig_ready, recovery_available = self.binding(character, prepared)
        batches = []
        for receipt in files('animations/*/batch.json'):
            info = read(receipt, {})
            if info.get('kind')=='sequence' or info.get('character') != character or info.get('batch') != receipt.parent.name:
                continue
            request=read(receipt.parent/'request.json',{})
            titles={a.lower().replace(' ','_')+'.fbx':a for a in request.get('names',[]) if isinstance(a,str)}
            batches.append({'action_roles':info.get('action_roles',{}),'loop_intent':info.get('loop_intent',{}),'preset':info.get('preset'),'titles':titles,'id':receipt.parent.name, 'fingerprint': self.digest(receipt),
                            'files': list(info.get('files', {})), 'hashes': info.get('files', {}),
                            'current_rig': rig_ready and info.get('rig_sha256') == state.get('bound_sha256')})
        from motion_heading import records as heading_records
        for batch_info in batches:
            batch_info['headings'] = heading_records(self.root, character, batch_info['hashes'])
        sequence_preview = read(self.scoped(f'workspaces/{character}/sequence_preview.json', f'workspaces/{character}'), None)
        if sequence_preview and sequence_preview.get('heading_sources'):
            sequence_preview['heading_stale'] = sequence_preview.get('headings') != heading_records(self.root, character, sequence_preview['heading_sources'])
        reviews = []
        for spec in files('reviews/*/viewer/review.json'):
            info = read(spec, {})
            captures = spec.parent / 'captures'
            report = spec.parent / 'character-report.json'
            if report.is_file():
                reviews.append({'id':spec.parent.parent.name, 'batch':info.get('batch'),
                                'files':info.get('files'), 'headings':info.get('headings',{}),
                                'images':[{'name':p.stem, 'url':self.asset(p)} for p in sorted(captures.glob('*.png'))],
                                'report':self.asset(report)})
        deliveries = []
        for manifest in sorted((self.root / 'deliverables' / character).glob('*/manifest.json'),
                               key=lambda p:p.stat().st_mtime, reverse=True):
            info = read(manifest, {})
            if info.get('source', {}).get('character') != character:
                continue
            current_headings = heading_records(self.root, character, info.get('source',{}).get('files',{}))
            heading_stale = any(abs(float(info.get(Path(f).stem+'_spritesheet.png',{}).get('heading',{}).get('degrees',0)) - float(value.get('degrees',0))) > 0.001 for f,value in current_headings.items())
            deliveries.append({'id':manifest.parent.name, 'batch':info.get('source', {}).get('batch'),
                               'color_processing':info.get('color_processing'),'heading_stale':heading_stale, 'operation':info.get('operation'), 'renderer':info.get('renderer','godot'), 'kind':info.get('source',{}).get('kind'),
                               'quality_report':info.get('quality_report'), 'manifest':self.asset(manifest), 'equipment':info.get('equipment'), 'settings':info.get('pixel_style', {}),
                               'clips':[{'name':p.stem.replace('_preview',''), 'gif':self.asset(p),
                                         'sheet':self.asset(p.with_name(p.name.replace('_preview.gif','_spritesheet.png'))),
                                         'info':info.get(p.name.replace('_preview.gif','_spritesheet.png'),{}),
                                         'comparison':self.game_clip(manifest.parent,info.get(p.name.replace('_preview.gif','_spritesheet.png'),{}).get('color_comparison')),
                                         'game':self.game_clip(manifest.parent,info.get(p.name.replace('_preview.gif','_spritesheet.png'),{}).get('game'))}
                                        for p in sorted(manifest.parent.glob('*_preview.gif'))],
                               'export':'/api/export?character='+character+'&delivery='+manifest.parent.name})
        if sequence_preview and any(d['id'] == sequence_preview.get('delivery') and d.get('heading_stale') for d in deliveries):
            sequence_preview['heading_stale'] = True
        equipment = []
        from equipment import load as load_equipment
        for config_path in files('equipment/*/equipment.json'):
            config = read(config_path, {})
            try:
                load_equipment(self.root, character, None, config_path.parent.name)
            except (ValueError, OSError, TypeError, KeyError):
                continue
            compatible=[]
            for batch in batches:
                try:
                    load_equipment(self.root,character,batch['id'],config_path.parent.name)
                    compatible.append(batch['id'])
                except (ValueError,OSError,TypeError,KeyError):
                    continue
            from equipment_usage import load as load_usage
            try: usage=load_usage(self.root,character,config_path.parent.name)
            except (ValueError,OSError,TypeError,KeyError): usage=None
            equipment.append({'usage':usage,'id':config_path.parent.name, 'batch':config['batch'], 'compatible_batches':compatible, 'bone':config['bone'],
                              'weapon':config['weapon'], 'weapon_name':config.get('weapon_name','标准单手剑'), 'scale':config['weapon_scale'],
                              'config':self.asset(config_path), 'preview':self.asset(config_path.parent/'review.png')})
        approvals = read(ws / 'panel_approvals.json', {})
        model_ok = bool(prepared and approvals.get('model', {}).get('fingerprint') == prepared['fingerprint'])
        profile=read(ws/'character.json',{})
        return {'id':character, 'display_name':profile.get('display_name',character), 'inputs':inputs, 'has_model':model.is_file(), 'prepared':prepared,
                'rig':{'status':state.get('status'), 'ready':bool(rig_ready), 'recovery_available':bool(rig_ready and recovery_available), 'error':state.get('error')}, 'batches':batches,
                'equipment':equipment, 'reviews':reviews[:12], 'deliveries':deliveries, 'approvals':approvals,
                'sequence_preview':sequence_preview,
                'sequence':read(self.scoped(f'workspaces/{character}/sequence.json',f'workspaces/{character}'), None),
                'model_approved':model_ok, 'optimizations':optimizations,
                'progress':read(self.root / '.local/progress' / (character+'.json'))}

    def catalog(self):
        return [{'id':p.name, 'display_name':read(p/'character.json',{}).get('display_name',p.name)} for p in sorted((self.root / 'workspaces').glob('*'))
                if p.is_dir() and not p.is_symlink() and self._valid(p.name)]

    @staticmethod
    def _valid(value):
        try:
            name(value)
            return True
        except ValueError:
            return False
