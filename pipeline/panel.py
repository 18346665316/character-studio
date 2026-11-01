"""Loopback-only Studio control panel. Jobs reuse the production pipeline."""
import argparse
import base64
from datetime import datetime, timezone
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
from asset_repository import AssetRepository, name, read, atomic
from task_lock import acquire, serialized, TaskBusyError

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC = Path(__file__).parent / 'panel_ui'
ACTIONS = {'import_model','optimize', 'adopt_model', 'reconstruct', 'prepare', 'rig', 'download', 'review', 'bake', 'equipment', 'weapon', 'sequence', 'compact', 'palette', 'produce'}
LABELS = {'reconstruct': '原画重建与贴图', 'prepare': '贴图准备', 'rig': 'Mixamo 人工绑定',
          'import_model':'导入外部模型','optimize':'模型减面对比', 'adopt_model':'采用优化模型', 'download': '动作下载', 'review': '动作检查画面', 'bake': '图集与 GIF 输出', 'equipment': '武器握持标注', 'weapon':'独立武器重建', 'sequence':'编排统一渲染', 'compact':'图集精简','palette':'颜色简化','produce':'整套动作生产'}


def now():
    return datetime.now(timezone.utc).isoformat()


class Panel(AssetRepository):
    def __init__(self, root=BASE_DIR):
        super().__init__(root)
        self.storage = self.root / '.local/panel'
        self.tasks_dir = self.storage / 'tasks'
        self.tasks_dir.mkdir(parents=True, exist_ok=True)
        self.token = secrets.token_urlsafe(32)
        self.mutex = threading.RLock()
        self.children = []

    def worker_lock(self):
        return acquire(self.root)

    def recover_jobs(self):
        """Reconcile abandoned receipts only while holding the execution lease."""
        fd = self.worker_lock()
        if fd is None:
            return
        try:
            # Read after taking the lease; a just-finished worker may have updated it.
            for path in self.tasks_dir.glob('*.json'):
                job = read(path)
                if job and job['status'] in ('queued', 'running'):
                    job.update(status='interrupted', error='任务进程已结束且未写入完成记录，可重试当前步骤。', finished_at=now())
                    atomic(path, job)
            for path in (self.root/'.local/terrain/jobs').glob('*/job.json'):
                job = read(path)
                if job and job['status'] in ('queued', 'running'):
                    job.update(status='failed', stage='任务进程已结束，可继续任务',
                               error='任务中断；继续时复用已保存的远程图片任务和材质。')
                    atomic(path, job)
        finally:
            os.close(fd)

    def start_terrain(self, data):
        from terrain import prepare
        fd = self.worker_lock()
        if fd is None:
            raise TaskBusyError('已有生产任务运行，请完成后再生成套件')
        try:
            if data.get('resume'):
                identity = name(data['resume'])
                path = self.scoped('.local/terrain/jobs/'+identity+'/job.json', '.local/terrain')
                job = read(path)
                if not job or job['status'] != 'failed':
                    raise ValueError('仅能继续已中断或失败的任务')
                job.update(status='queued', error=None, stage='等待继续任务')
                atomic(path, job)
            else:
                job = prepare(self.root, data)
                identity = job['id']
                path = self.scoped('.local/terrain/jobs/'+identity+'/job.json', '.local/terrain')
            try:
                with (path.parent/'worker.log').open('ab') as log:
                    child = subprocess.Popen(
                        [str(self.root/'.local/python/bin/python3'), str(self.root/'pipeline/terrain_worker.py'),
                         identity, str(fd)], cwd=self.root, stdout=log, stderr=subprocess.STDOUT,
                        env={**os.environ, 'PYTHONUNBUFFERED':'1'}, pass_fds=(fd,), start_new_session=True)
                    self.children.append(child)
            except OSError:
                job.update(status='failed', error='无法启动素材生成进程', stage='启动失败')
                atomic(path, job)
                raise
            return job
        finally:
            os.close(fd)

    def jobs(self):
        """Read task history without changing task receipts."""
        self.children[:] = [p for p in self.children if p.poll() is None]
        jobs = [job for path in self.tasks_dir.glob('*.json') if (job := read(path))]
        return sorted(jobs, key=lambda j:j['created_at'], reverse=True)[:60]

    def upload_model(self,data):
        from import_model import validate_glb
        display=data.get('display_name','')
        if not isinstance(display,str) or not 1<=len(display.strip())<=60:raise ValueError('人物名称需为1–60个字符')
        try:content=base64.b64decode(data.get('content',''),validate=True)
        except (ValueError,TypeError):raise ValueError('模型内容无效')
        if not content or len(content)>100*1024*1024:raise ValueError('GLB 须小于100MB')
        validate_glb(content)
        up=data.get('up','Y');yaw=data.get('yaw',0)
        if up not in ('Y','-Y','Z','-Z','X','-X') or type(yaw) is not int or yaw not in (0,90,180,270):raise ValueError('模型朝向设置无效')
        character='character-'+secrets.token_hex(5)
        ws=self.root/'workspaces'/character
        source=ws/'model_inputs/original.glb';source.parent.mkdir(parents=True);source.write_bytes(content)
        atomic(ws/'character.json',{'display_name':display.strip(),'origin':'import_glb'})
        return {'character':character,'source':str(source.relative_to(self.root)),'up':up,'yaw':yaw}

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
        if action == 'produce':
            from production import plan
            return plan(self,character,params)
        if action == 'sequence':
            from sequence_render import make_plan
            plan=make_plan(self,character,params.get('recipe',{}))
            if params.get('plan') and params['plan']!=plan:
                raise ValueError('编排来源或武器设置已变化，请新建预览任务')
            clean={'recipe':plan['recipe'],'plan':plan}
        if action == 'palette':
            from palette_delivery import plan
            clean=plan(self.root,character,params)
            if params.get('manifest_sha256') and clean!=params: raise ValueError('颜色处理来源已变化，请新建任务')
        if action == 'compact':
            from compact_delivery import plan
            clean=plan(self.root,character,params.get('delivery'),params.get('clips'),params.get('profile','balanced'))
            if params.get('manifest_sha256') and clean!=params:
                raise ValueError('原图集已变化，请重新创建精简任务')
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
        if action == 'import_model':
            source=self.scoped(params.get('source'),f'workspaces/{character}/model_inputs')
            if not source.is_file() or source.suffix!='.glb':raise ValueError('请先上传 GLB 模型')
            if c['has_model']:raise ValueError('此人物已导入模型，不能覆盖')
            up=params.get('up','Y');yaw=params.get('yaw',0)
            if up not in ('Y','-Y','Z','-Z','X','-X') or type(yaw) is not int or yaw not in (0,90,180,270):raise ValueError('模型朝向设置无效')
            clean={'source':str(source.relative_to(self.root)),'up':up,'yaw':yaw}
        if action == 'optimize':
            if not c['prepared']:raise ValueError('请先准备带贴图模型')
            clean={'prepared':c['prepared']['id'],'fingerprint':c['prepared']['fingerprint']}
            if params.get('fingerprint') and params['fingerprint']!=clean['fingerprint']:raise ValueError('当前模型已变化')
        if action == 'adopt_model':
            experiment=name(params.get('experiment'));variant=name(params.get('variant'))
            match=next((o for o in c['optimizations'] if o['id']==experiment),None)
            if not match or variant not in [v['id'] for v in match['variants']]:raise ValueError('优化候选已失效')
            clean={'experiment':experiment,'variant':variant}
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
            from action_presets import validate_metadata
            clean.update(validate_metadata(actions,params))
        if action in ('review', 'bake', 'equipment'):
            batch = name(params.get('batch'))
            match = next((b for b in c['batches'] if b['id'] == batch), None)
            if not match:
                raise ValueError('请先选择完整动作批次')
            clean['batch'] = batch
            if action == 'review' and params.get('heading_file'):
                if params['heading_file'] not in match['files']: raise ValueError('请选择本批次内的动作')
                clean['heading_file'] = params['heading_file']
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
                chosen=params.get('files',match['files'])
                if not isinstance(chosen,list) or not chosen or any(not isinstance(f,str) or f not in match['files'] for f in chosen) or len(set(chosen))!=len(chosen):
                    raise ValueError('请选择此来源内的有效动作')
                clean['files']=chosen
                approval = c['approvals'].get('motions', {}).get(batch, {})
                if approval.get('fingerprint') != match['fingerprint'] and not all(
                        c['approvals'].get('animations',{}).get(batch,{}).get(file,{}).get('fingerprint')==match['fingerprint']
                        for file in chosen):
                    raise ValueError('请先检查并确认所选动作')
                if params.get('equipment_id'):
                    from equipment import load as load_equipment
                    clean['equipment_id'] = name(params['equipment_id'])
                    load_equipment(self.root, character, batch, clean['equipment_id'])
                    from equipment_usage import load as load_usage, fingerprint
                    pin=fingerprint(load_usage(self.root,character,clean['equipment_id']))
                    if params.get('equipment_usage_sha256') and params['equipment_usage_sha256']!=pin:
                        raise ValueError('武器持用设置已变化，请创建新的导出任务')
                    clean['equipment_usage_sha256']=pin
                clean['renderer'] = params.get('renderer','godot')
                if clean['renderer'] not in ('godot','blender'):
                    raise ValueError('未知渲染后端')
                clean['view'] = params.get('view', 'three_quarter')
                body_height = params.get('body_height', None if 'frame_size' in params else 96)
                if body_height is not None:
                    if type(body_height) is not int or body_height not in (48,64,96,128): raise ValueError('无效的人物像素高度')
                    clean['body_height'] = body_height
                clean['frame_size'] = params.get('frame_size', 64)
                clean['supersample'] = params.get('supersample', 4)
                if clean['view'] not in ('front','side','three_quarter') or clean['frame_size'] not in (64,128) or clean['supersample'] not in (1,2,4):
                    raise ValueError('无效的图集参数')
        return clean

    def start(self, data):
        with self.mutex:
            character = name(data.get('character'))
            fd = self.worker_lock()
            if fd is None:
                raise TaskBusyError('已有任务在运行，请等待完成后再操作')
            try:
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

    @serialized(lambda self, *args, **kwargs: self.root)
    def approve(self, data):
        with self.mutex:
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

    @serialized(lambda self, *args, **kwargs: self.root)
    def save_sequence(self, data):
        character = name(data.get('character'))
        c = self.character(character)
        title, loop, segments = data.get('title'), data.get('loop'), data.get('segments')
        if not isinstance(title,str) or not 1 <= len(title.strip()) <= 60 or type(loop) is not bool:
            raise ValueError('编排名称需为 1–60 字，循环需为布尔值')
        if not isinstance(segments,list) or len(segments)>64:
            raise ValueError('编排最多包含 64 个片段')
        available={(d['id'],clip['name']):clip for d in c['deliveries'] for clip in d['clips'] if clip['sheet']}
        clean=[]
        for segment in segments:
            if not isinstance(segment,dict):
                raise ValueError('无效的编排片段')
            delivery, clip = segment.get('delivery'), segment.get('clip')
            repeat, speed = segment.get('repeat'), segment.get('speed')
            if not isinstance(delivery,str) or not isinstance(clip,str) or (delivery,clip) not in available:
                raise ValueError('编排引用的动画图集不存在或不属于此人物')
            if type(repeat) is not int or not 1<=repeat<=20 or type(speed) not in (int,float) or not .25<=speed<=4:
                raise ValueError('重复次数限 1–20，片段速度限 0.25–4')
            info=available[(delivery,clip)]['info']
            if not all(isinstance(info.get(k),(int,float)) and info[k]>0 for k in ('frame_count','frame_width','frame_height')):
                raise ValueError('图集缺少有效帧信息，请重新渲染')
            clean.append({'delivery':delivery,'clip':clip,'repeat':repeat,'speed':speed})
        record={'title':title.strip(),'loop':loop,'segments':clean}
        if data.get('renderSettings') is not None:
            from sequence_render import settings
            record['renderSettings']=settings(data['renderSettings'])
        atomic(self.scoped(f'workspaces/{character}/sequence.json',f'workspaces/{character}'),record)
        return {'ok':True,'sequence':record}

    def export(self, character, delivery, clip=None, variant=None):
        character, delivery = name(character), name(delivery)
        directory = self.scoped(f'deliverables/{character}/{delivery}', f'deliverables/{character}')
        manifest = read(directory/'manifest.json',{})
        if manifest.get('source',{}).get('character') != character:
            raise ValueError('交付目录无有效清单')
        if variant is not None:
            if variant not in ('game','source','comparison'): raise ValueError('未知导出版本')
            name(clip)
            info=manifest.get(clip+'_spritesheet.png')
            if not info or (variant=='game' and not info.get('game')) or (variant=='comparison' and not info.get('color_comparison')): raise ValueError('版本不存在')
            folder=directory/variant if variant in ('game','comparison') else directory
            names=[clip+'_spritesheet.png',clip+'_preview.gif',clip+'_render.json']
            if variant in ('game','comparison'): names.append(clip+'.tres')
            buffer=BytesIO()
            with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED) as archive:
                for filename in names:
                    path=self.scoped(str((folder/filename).relative_to(self.root)),f'deliverables/{character}/{delivery}')
                    if path.is_file(): archive.write(path,filename)
            return buffer.getvalue()
        buffer = BytesIO()
        with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED) as archive:
            for path in directory.rglob('*'):
                if path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(directory.resolve()) and path.suffix in ('.png','.gif','.json','.tres'):
                    archive.write(path,str(path.relative_to(directory)))
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
                if parsed.path in ('/','/app.js','/sequence.js','/workspace.js','/style.css',
                                   '/terrain.html','/terrain.js','/terrain.css',
                                   '/transition.html','/transition.js'):
                    file = STATIC / ('index.html' if parsed.path=='/' else parsed.path[1:])
                    return self.respond(file.read_bytes(),mimetypes.guess_type(file.name)[0]+'; charset=utf-8')
                if parsed.path == '/api/terrain/state':
                    from terrain import catalog
                    from terrain_images import configured, load_config, DEFAULT_BASE
                    with panel.mutex:
                        panel.recover_jobs()
                        result = catalog(panel.root)
                        from terrain_transition import catalog as transition_catalog
                        result['transitions']=transition_catalog(panel.root)
                    result.update(token=panel.token, image_api_configured=configured(panel.root),
                                  image_base_url=load_config(panel.root).get('STUDIO_IMAGE_BASE_URL', DEFAULT_BASE))
                    return self.respond(result)
                if parsed.path.startswith('/terrain-asset/'):
                    relative = unquote(parsed.path[len('/terrain-asset/'):])
                    parts = relative.split('/')
                    if len(parts) != 2 or parts[1] not in ('atlas.png','ground_material.png','road_material.png','preview.png','kit.zip'):
                        raise ValueError('无效套件资源')
                    path = panel.scoped('terrain-kits/'+name(parts[0])+'/'+parts[1], 'terrain-kits')
                    if parts[1]=='kit.zip':
                        from terrain_integrity import require
                        require(panel.root,'terrain-kits',parts[0])
                    return self.respond(path.read_bytes(), mimetypes.guess_type(path.name)[0] or 'application/octet-stream')
                if parsed.path.startswith('/transition-asset/'):
                    parts=unquote(parsed.path[len('/transition-asset/'):]).split('/')
                    if len(parts)!=2 or parts[1] not in ('preview.png','atlas.png','kit.zip'):
                        raise ValueError('无效过渡套件资源')
                    path=panel.scoped('terrain-transitions/'+name(parts[0])+'/'+parts[1], 'terrain-transitions')
                    if parts[1]=='kit.zip':
                        from terrain_integrity import require
                        require(panel.root,'terrain-transitions',parts[0])
                    return self.respond(path.read_bytes(),mimetypes.guess_type(path.name)[0] or 'application/octet-stream')
                if parsed.path == '/api/state':
                    with panel.mutex:
                        panel.recover_jobs()
                        from action_presets import PRESETS
                        result = {'action_presets':PRESETS,'api_version':24,'token':panel.token,'characters':panel.catalog(),'jobs':panel.jobs()}
                        from weapon_assets import catalog as weapon_catalog
                        from palette_delivery import catalog as palette_catalog
                        result['palettes']=palette_catalog(panel.root)
                        result['weapons']=[{**w,'front':panel.asset(panel.root/'weapons'/w['id']/'front.png'),'contact':panel.asset(panel.root/'weapons'/w['id']/'contact.png')} for w in weapon_catalog(panel.root)]
                        if query.get('character'):
                            result['selected'] = panel.character(query['character'][0])
                            from action_set import load as load_set, inspect as inspect_set
                            result['selected']['action_set']=load_set(panel.root,query['character'][0])
                            result['selected']['action_set_validation']=inspect_set(panel.root,query['character'][0])
                            result['selected']['production']=read(panel.root/'workspaces'/query['character'][0]/'production.json',None)
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
                if parsed.path == '/api/action-set/export':
                    from action_set import export as export_set
                    return self.respond(export_set(panel.root,query.get('character',[''])[0]),'application/zip')
                if parsed.path == '/api/game-package':
                    from game_package import build
                    choices=query.get('selections',['{}'])[0]
                    if len(choices)>4096: raise ValueError('动作选择过长')
                    content=build(panel.root,query.get('character',[''])[0],json.loads(choices),query.get('variant',['game'])[0],report_only=query.get('inspect')==['1'])
                    return self.respond(content) if isinstance(content,dict) else self.respond(content,'application/zip')
                if parsed.path == '/api/export':
                    content = panel.export(query.get('character',[''])[0],query.get('delivery',[''])[0],query.get('clip',[None])[0],query.get('variant',[None])[0])
                    return self.respond(content,'application/zip')
                return self.respond({'error':'页面不存在'},code=404)
            except (ValueError,KeyError,OSError) as exc:
                return self.respond({'error':str(exc)},code=400)

        def do_POST(self):
            if not self.trusted(mutation=True):
                return self.respond({'error':'请求校验失败，请刷新页面'},code=403)
            try:
                size = int(self.headers.get('Content-Length','0'))
                limit = 140*1024*1024 if urlparse(self.path).path=='/api/model/upload' else (34*1024*1024 if urlparse(self.path).path=='/api/terrain/generate' else 18*1024*1024)
                if not 0 < size <= limit:
                    raise ValueError('请求为空或超过上传限制')
                if self.headers.get('Content-Type','').split(';')[0] != 'application/json':
                    raise ValueError('需要 JSON 请求')
                data = json.loads(self.rfile.read(size))
                if not isinstance(data,dict):
                    raise ValueError('无效的请求结构')
                with panel.mutex:
                    route = urlparse(self.path).path
                    if route == '/api/terrain/transition':
                        from terrain_transition import build
                        folder=build(panel.root,data.get('base_kit'),data.get('overlay_kit'),
                                     data.get('tile_size',64),data.get('title'),interactive=False)
                        result=read(folder/'manifest.json')
                    elif route == '/api/terrain/generate':
                        result = panel.start_terrain(data)
                    elif route == '/api/model/upload':
                        result=panel.upload_model(data)
                    elif route == '/api/upload':
                        result = panel.upload(data)
                    elif route == '/api/weapon/upload':
                        result=panel.upload_weapon(data)
                    elif route == '/api/weapon/calibrate':
                        from weapon_assets import calibrate
                        result=calibrate(panel.root,name(data.get('weapon')),data.get('length'),data.get('grip'))
                    elif route == '/api/equipment/usage':
                        from equipment_usage import save as save_usage
                        result=save_usage(panel.root,name(data.get('character')),name(data.get('equipment')),data.get('default'),data.get('mounts'),data.get('batch'),data.get('file'),data.get('action'))
                    elif route == '/api/action-set':
                        from action_set import save as save_set
                        result=save_set(panel.root,name(data.get('character')),data)
                    elif route == '/api/sequence':
                        result = panel.save_sequence(data)
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
