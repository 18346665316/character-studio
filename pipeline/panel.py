"""Loopback-only Studio control panel. Jobs reuse the production pipeline."""
import argparse
import base64
from datetime import datetime, timezone
import fcntl
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import json
import mimetypes
import os
from pathlib import Path
import secrets
import subprocess
import threading
from urllib.parse import parse_qs, unquote, urlparse, quote
import zipfile

from PIL import Image

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC = Path(__file__).parent / 'panel_ui'
ACTIONS = {'reconstruct', 'prepare', 'rig', 'download', 'review', 'bake', 'equipment', 'weapon'}
LABELS = {'reconstruct': '原画重建与贴图', 'prepare': '贴图准备', 'rig': 'Mixamo 人工绑定',
          'download': '动作下载', 'review': '动作检查画面', 'bake': '图集与 GIF 输出', 'equipment': '武器握持标注', 'weapon':'独立武器重建'}


def now():
    return datetime.now(timezone.utc).isoformat()


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


class Panel:
    def __init__(self, root=BASE_DIR):
        self.root = Path(root).resolve()
        self.storage = self.root / '.local/panel'
        self.tasks_dir = self.storage / 'tasks'
        self.tasks_dir.mkdir(parents=True, exist_ok=True)
        self.token = secrets.token_urlsafe(32)
        self.mutex = threading.RLock()
        self.hash_cache = {}
        self.children = []

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
        if path.suffix.lower() not in ('.png', '.jpg', '.jpeg', '.webp', '.gif', '.glb', '.fbx', '.zip', '.json') or not path.is_file():
            raise ValueError('文件不存在或不可预览')
        return path

    def worker_lock(self):
        fd = os.open(self.storage / 'worker.lock', os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            return None
        return fd

    def jobs(self):
        jobs = []
        # Poll/reap only our own child handles; workers keep running if HTTP exits.
        self.children[:] = [p for p in self.children if p.poll() is None]
        for path in self.tasks_dir.glob('*.json'):
            job = read(path)
            if job:
                jobs.append(job)
        fd = self.worker_lock()
        if fd is not None:
            try:
                for job in jobs:
                    if job['status'] in ('queued', 'running'):
                        job.update(status='interrupted', error='任务进程已结束且未写入完成记录，可重试当前步骤。', finished_at=now())
                        atomic(self.tasks_dir / (job['id'] + '.json'), job)
            finally:
                os.close(fd)
        return sorted(jobs, key=lambda j:j['created_at'], reverse=True)[:60]

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
        state = read(self.root / '.local/mixamo' / character / 'state.json', {'status':'unbound'})
        rig_ready = False
        if prepared and state.get('status') == 'ready' and state.get('human_reviewed'):
            try:
                bound = self.scoped(str(Path(state['bound_model']).relative_to(self.root)), f'workspaces/{character}/rig')
                upload = ws / 'models/prepared' / prepared['id'] / 'mixamo.zip'
                rig_ready = bound.is_file() and self.digest(bound) == state['bound_sha256'] and self.digest(upload) == state['source_sha256']
            except (ValueError, KeyError, OSError):
                pass
        batches = []
        for receipt in files('animations/*/batch.json'):
            info = read(receipt, {})
            if info.get('character') != character or info.get('batch') != receipt.parent.name:
                continue
            request=read(receipt.parent/'request.json',{})
            titles={a.lower().replace(' ','_')+'.fbx':a for a in request.get('names',[]) if isinstance(a,str)}
            batches.append({'titles':titles,'id':receipt.parent.name, 'fingerprint': self.digest(receipt),
                            'files': list(info.get('files', {})), 'hashes': info.get('files', {}),
                            'current_rig': rig_ready and info.get('rig_sha256') == state.get('bound_sha256')})
        reviews = []
        for spec in files('reviews/*/viewer/review.json'):
            info = read(spec, {})
            captures = spec.parent / 'captures'
            report = spec.parent / 'character-report.json'
            if report.is_file():
                reviews.append({'id':spec.parent.parent.name, 'batch':info.get('batch'),
                                'files':info.get('files'),
                                'images':[{'name':p.stem, 'url':self.asset(p)} for p in sorted(captures.glob('*.png'))],
                                'report':self.asset(report)})
        deliveries = []
        for manifest in sorted((self.root / 'deliverables' / character).glob('*/manifest.json'),
                               key=lambda p:p.stat().st_mtime, reverse=True):
            info = read(manifest, {})
            if info.get('source', {}).get('character') != character:
                continue
            deliveries.append({'id':manifest.parent.name, 'batch':info.get('source', {}).get('batch'),
                               'manifest':self.asset(manifest), 'equipment':info.get('equipment'), 'settings':info.get('pixel_style', {}),
                               'clips':[{'name':p.stem.replace('_preview',''), 'gif':self.asset(p),
                                         'sheet':self.asset(p.with_name(p.name.replace('_preview.gif','_spritesheet.png'))),
                                         'info':info.get(p.name.replace('_preview.gif','_spritesheet.png'),{})}
                                        for p in sorted(manifest.parent.glob('*_preview.gif'))],
                               'export':'/api/export?character='+character+'&delivery='+manifest.parent.name})
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
            equipment.append({'id':config_path.parent.name, 'batch':config['batch'], 'compatible_batches':compatible, 'bone':config['bone'],
                              'weapon':config['weapon'], 'weapon_name':config.get('weapon_name','标准单手剑'), 'scale':config['weapon_scale'],
                              'config':self.asset(config_path), 'preview':self.asset(config_path.parent/'review.png')})
        approvals = read(ws / 'panel_approvals.json', {})
        model_ok = bool(prepared and approvals.get('model', {}).get('fingerprint') == prepared['fingerprint'])
        profile=read(ws/'character.json',{})
        return {'id':character, 'display_name':profile.get('display_name',character), 'inputs':inputs, 'has_model':model.is_file(), 'prepared':prepared,
                'rig':{'status':state.get('status'), 'ready':bool(rig_ready), 'error':state.get('error')}, 'batches':batches,
                'equipment':equipment, 'reviews':reviews[:12], 'deliveries':deliveries[:12], 'approvals':approvals,
                'model_approved':model_ok,
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

    def upload(self, data):
        character_id=data.get('character') or ('character-'+secrets.token_hex(5))
        character = name(character_id)
        display_name=data.get('display_name',character)
        if not isinstance(display_name,str) or not 1<=len(display_name.strip())<=60:
            raise ValueError('角色名称需为1–60个字符')
        try:
            content = base64.b64decode(data.get('content', ''), validate=True)
        except (ValueError, TypeError):
            raise ValueError('图片内容无效')
        if not content or len(content) > 12 * 1024 * 1024:
            raise ValueError('图片大小需小于 12 MB')
        try:
            with Image.open(BytesIO(content)) as image:
                if image.width * image.height > 20_000_000 or min(image.size) < 64:
                    raise ValueError('图片须至少64像素，且不超过2000万像素')
                image.load()
                converted = image.convert('RGBA')
        except (OSError, Image.DecompressionBombError):
            raise ValueError('请选择有效的 PNG、JPEG 或 WebP 图片')
        ws = self.root / 'workspaces' / character
        if ws.is_symlink():
            raise ValueError('非法角色目录')
        path = self.scoped(f'workspaces/{character}/inputs/upload-{secrets.token_hex(6)}/original.png', f'workspaces/{character}')
        path.parent.mkdir(parents=True, exist_ok=False)
        converted.save(path)
        profile=ws/'character.json'
        if not profile.exists():
            atomic(profile,{'display_name':display_name.strip()})
        return {'character': character, 'image':str(path.relative_to(self.root))}

    def upload_weapon(self,data):
        display=data.get('name','')
        if not isinstance(display,str) or not 1<=len(display.strip())<=60:
            raise ValueError('武器名称需为1–60个字符')
        try:
            content=base64.b64decode(data.get('content',''),validate=True)
            if not content or len(content)>12*1024*1024: raise ValueError('图片需小于12MB')
            with Image.open(BytesIO(content)) as image:
                if min(image.size)<64 or image.width*image.height>20_000_000: raise ValueError('图片尺寸无效')
                image.load();converted=image.convert('RGB')
        except (OSError,TypeError,Image.DecompressionBombError):
            raise ValueError('请选择有效武器图片')
        identity='input-'+secrets.token_hex(6)
        path=self.scoped(f'.local/weapon-inputs/{identity}/original.png','.local/weapon-inputs')
        path.parent.mkdir(parents=True);converted.save(path)
        return {'image':str(path.relative_to(self.root)),'name':display.strip()}

    def validate_task(self, character, action, params):
        c = self.character(character)
        if action not in ACTIONS or not isinstance(params, dict):
            raise ValueError('不支持的操作')
        clean = {}
        if action == 'weapon':
            path=self.scoped(params.get('image'),'.local/weapon-inputs')
            if not path.is_file() or path.name!='original.png': raise ValueError('请先导入武器原画')
            display=params.get('name','')
            if not isinstance(display,str) or not 1<=len(display.strip())<=60: raise ValueError('武器名称无效')
            clean.update(image=str(path.relative_to(self.root)),name=display.strip())
        if action == 'reconstruct':
            path = self.scoped(params.get('image'), f'workspaces/{character}/inputs')
            if not path.is_file() or path.suffix.lower() not in ('.png', '.jpg', '.jpeg', '.webp'):
                raise ValueError('请先上传原画')
            clean['image'] = str(path.relative_to(self.root))
        if action == 'prepare' and not c['has_model']:
            raise ValueError('请先生成模型')
        if action == 'rig' and not c['model_approved']:
            raise ValueError('请先检查并确认当前模型')
        if action == 'download':
            if not c['rig']['ready']:
                if c['rig']['status']=='needs_review':
                    raise ValueError((c['rig']['error'] or 'Mixamo 人物需要复核')+'。请先在“人工绑定”恢复本角色，再创建新下载任务。')
                raise ValueError('请先完成人工绑定')
            actions = params.get('actions')
            if not isinstance(actions, list) or not 1 <= len(actions) <= 12:
                raise ValueError('请选择 1–12 个动作')
            import re
            if any(not isinstance(a,str) or len(a)>60 or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9 _-]*',a) for a in actions):
                raise ValueError('动作名只接受英文、数字、空格、下划线和短横线')
            keys = [a.lower().replace(' ', '_') for a in actions]
            if len(set(keys)) != len(keys):
                raise ValueError('动作名重复')
            clean['actions'] = actions
        if action in ('review', 'bake', 'equipment'):
            batch = name(params.get('batch'))
            match = next((b for b in c['batches'] if b['id'] == batch), None)
            if not match:
                raise ValueError('请先选择完整动作批次')
            clean['batch'] = batch
            if action == 'equipment':
                if not match['current_rig']:
                    raise ValueError('请选择当前已验收绑定的动作批次')
                if params.get('weapon_id'):
                    if params.get('equipment_id'): raise ValueError('新建武器与编辑装备不能同时选择')
                    from weapon_assets import load as load_weapon
                    clean['weapon_id']=name(params['weapon_id'])
                    load_weapon(self.root,clean['weapon_id'],confirmed=True)
                if params.get('equipment_id'):
                    from equipment import load as load_equipment
                    clean['equipment_id'] = name(params['equipment_id'])
                    load_equipment(self.root, character, batch, clean['equipment_id'])
            if action == 'bake':
                approval = c['approvals'].get('motions', {}).get(batch, {})
                if approval.get('fingerprint') != match['fingerprint'] and not all(
                        c['approvals'].get('animations',{}).get(batch,{}).get(file,{}).get('fingerprint')==match['fingerprint']
                        for file in match['files']):
                    raise ValueError('请先检查并确认该批次动作')
                if params.get('equipment_id'):
                    from equipment import load as load_equipment
                    clean['equipment_id'] = name(params['equipment_id'])
                    load_equipment(self.root, character, batch, clean['equipment_id'])
                clean['view'] = params.get('view', 'three_quarter')
                clean['frame_size'] = params.get('frame_size', 64)
                clean['supersample'] = params.get('supersample', 4)
                if clean['view'] not in ('front','side','three_quarter') or clean['frame_size'] not in (64,128) or clean['supersample'] not in (1,2,4):
                    raise ValueError('无效的图集参数')
        return clean

    def start(self, data):
        with self.mutex:
            character = name(data.get('character'))
            retry_id = data.get('retry')
            old = None
            if retry_id:
                old = read(self.tasks_dir / (name(retry_id)+'.json'))
                if not old or old['character'] != character or old['status'] not in ('failed','interrupted'):
                    raise ValueError('只能重试本角色失败或中断的任务')
                action, params = old['action'], old['params']
            else:
                action, params = data.get('action'), data.get('params', {})
            clean = self.validate_task(character, action, params)
            fd = self.worker_lock()
            if fd is None:
                raise ValueError('已有任务在运行，请等待完成后再操作')
            try:
                task_id = old['id'] if old else datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+secrets.token_hex(4)
                path = self.tasks_dir / (task_id+'.json')
                job = old or {'id':task_id, 'character':character, 'action':action,
                              'created_at':now(), 'outputs':{}, 'attempts':0}
                job.update(params=clean, status='queued', error=None, attempts=job['attempts']+1)
                atomic(path, job)
                log = (self.tasks_dir / (task_id+'.log')).open('ab')
                try:
                    child = subprocess.Popen([str(self.root/'.local/python/bin/python3'),
                                              str(self.root/'pipeline/panel_worker.py'), str(path), str(fd)],
                                             cwd=self.root, stdout=log, stderr=subprocess.STDOUT,
                                             env={**os.environ,'PYTHONUNBUFFERED':'1'},
                                             pass_fds=(fd,), start_new_session=True)
                    self.children.append(child)
                except BaseException as exc:
                    job.update(status='failed', error=str(exc))
                    atomic(path,job)
                    raise
                finally:
                    log.close()
                return job
            finally:
                os.close(fd)

    def approve(self, data):
        with self.mutex:
            if any(j['status'] in ('queued','running') for j in self.jobs()):
                raise ValueError('请等待当前任务结束后再验收')
            character = name(data.get('character'))
            c = self.character(character)
            path = self.root/'workspaces'/character/'panel_approvals.json'
            record = read(path, {})
            if data.get('kind') == 'model':
                prepared = c['prepared']
                if not prepared or data.get('fingerprint') != prepared['fingerprint']:
                    raise ValueError('模型版本已变化，请刷新后重新检查')
                record['model'] = {'fingerprint':prepared['fingerprint'], 'approved_at':now()}
            elif data.get('kind') in ('motion','animation'):
                batch = name(data.get('batch'))
                match = next((b for b in c['batches'] if b['id']==batch),None)
                if not match or data.get('fingerprint') != match['fingerprint']:
                    raise ValueError('动作批次已变化，请刷新后重新检查')
                receipt = read(self.root/'workspaces'/character/'animations'/batch/'batch.json',{})
                if not any(r['batch']==batch and r['files']==receipt.get('files') for r in c['reviews']):
                    raise ValueError('请先为该批次生成动作检查画面')
                if data.get('kind')=='animation':
                    file=data.get('file')
                    if file not in match['files']:
                        raise ValueError('动画不属于此来源')
                    stem=Path(file).stem
                    review=next((r for r in c['reviews'] if r['batch']==batch and r['files']==receipt.get('files')),None)
                    if not any(i['name'].startswith(stem+'_') for i in review['images']):
                        raise ValueError('请先生成此动画的姿态检查画面')
                    record.setdefault('animations',{}).setdefault(batch,{})[file]={'fingerprint':match['fingerprint'],'approved_at':now()}
                else:
                    record.setdefault('motions',{})[batch] = {'fingerprint':match['fingerprint'], 'approved_at':now()}
            else:
                raise ValueError('无效的验收类型')
            atomic(path,record)
            return {'ok':True}

    def export(self, character, delivery):
        character, delivery = name(character), name(delivery)
        directory = self.scoped(f'deliverables/{character}/{delivery}', f'deliverables/{character}')
        manifest = read(directory/'manifest.json',{})
        if manifest.get('source',{}).get('character') != character:
            raise ValueError('交付目录无有效清单')
        buffer = BytesIO()
        with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED) as archive:
            for path in directory.iterdir():
                if path.is_file() and not path.is_symlink() and path.suffix in ('.png','.gif','.json'):
                    archive.write(path,path.name)
        return buffer.getvalue()


def handler(panel):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def trusted(self, mutation=False):
            host = self.headers.get('Host','')
            allowed = (f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}')
            if host not in allowed:
                return False
            if mutation:
                if self.headers.get('X-Studio-Token') != panel.token:
                    return False
                origin = self.headers.get('Origin')
                if origin and origin != 'http://'+host:
                    return False
            return True

        def respond(self, body, kind='application/json; charset=utf-8', code=200):
            if not isinstance(body,bytes):
                body = json.dumps(body,ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header('Content-Type',kind)
            self.send_header('Content-Length',str(len(body)))
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('X-Frame-Options','DENY')
            self.send_header('Content-Security-Policy',"default-src 'self'; img-src 'self' blob:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if not self.trusted():
                return self.respond({'error':'仅允许本机访问'},code=403)
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)
            try:
                if parsed.path in ('/','/app.js','/style.css'):
                    file = STATIC / ('index.html' if parsed.path=='/' else parsed.path[1:])
                    return self.respond(file.read_bytes(),mimetypes.guess_type(file.name)[0]+'; charset=utf-8')
                if parsed.path == '/api/state':
                    with panel.mutex:
                        result = {'api_version':5,'token':panel.token,'characters':panel.catalog(),'jobs':panel.jobs()}
                        from weapon_assets import catalog as weapon_catalog
                        result['weapons']=[{**w,'front':panel.asset(panel.root/'weapons'/w['id']/'front.png'),'contact':panel.asset(panel.root/'weapons'/w['id']/'contact.png')} for w in weapon_catalog(panel.root)]
                        if query.get('character'):
                            result['selected'] = panel.character(query['character'][0])
                            from workflow import guidance
                            result['selected']['guidance']=guidance(result['selected'],result['jobs'])
                    return self.respond(result)
                if parsed.path == '/api/log':
                    task = name(query.get('task',[''])[0])
                    if not (panel.tasks_dir/(task+'.json')).is_file():
                        raise ValueError('任务不存在')
                    path = panel.tasks_dir/(task+'.log')
                    if path.exists():
                        with path.open('rb') as log:
                            log.seek(max(0,path.stat().st_size-24000))
                            content = log.read().decode('utf-8',errors='replace')
                    else:
                        content = ''
                    return self.respond({'text':content})
                if parsed.path.startswith('/asset/'):
                    path = panel.asset_path(unquote(parsed.path[len('/asset/'):]))
                    return self.respond(path.read_bytes(),mimetypes.guess_type(path.name)[0] or 'application/octet-stream')
                if parsed.path == '/api/export':
                    content = panel.export(query.get('character',[''])[0],query.get('delivery',[''])[0])
                    return self.respond(content,'application/zip')
                return self.respond({'error':'页面不存在'},code=404)
            except (ValueError,KeyError,OSError) as exc:
                return self.respond({'error':str(exc)},code=400)

        def do_POST(self):
            if not self.trusted(mutation=True):
                return self.respond({'error':'请求校验失败，请刷新页面'},code=403)
            try:
                size = int(self.headers.get('Content-Length','0'))
                if not 0 < size <= 18*1024*1024:
                    raise ValueError('请求为空或超过上传限制')
                if self.headers.get('Content-Type','').split(';')[0] != 'application/json':
                    raise ValueError('需要 JSON 请求')
                data = json.loads(self.rfile.read(size))
                if not isinstance(data,dict):
                    raise ValueError('无效的请求结构')
                with panel.mutex:
                    route = urlparse(self.path).path
                    if route == '/api/upload':
                        result = panel.upload(data)
                    elif route == '/api/weapon/upload':
                        result=panel.upload_weapon(data)
                    elif route == '/api/weapon/calibrate':
                        if any(j['status'] in ('queued','running') for j in panel.jobs()):
                            raise ValueError('请等待当前任务完成后再确认武器')
                        from weapon_assets import calibrate
                        result=calibrate(panel.root,name(data.get('weapon')),data.get('length'),data.get('grip'))
                    elif route == '/api/tasks':
                        result = panel.start(data)
                    elif route == '/api/approve':
                        result = panel.approve(data)
                    else:
                        return self.respond({'error':'接口不存在'},code=404)
                return self.respond(result)
            except (ValueError,KeyError,OSError,TypeError) as exc:
                return self.respond({'error':str(exc)},code=400)
    return Handler


def serve(port=0):
    panel = Panel()
    server = ThreadingHTTPServer(('127.0.0.1',port),handler(panel))
    server.daemon_threads = True
    url = f'http://127.0.0.1:{server.server_port}/'
    atomic(panel.storage/'server.json',{'url':url,'pid':os.getpid()})
    print(f'Studio 人物工作台：{url}',flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port',type=int,default=0)
    serve(parser.parse_args().port)
