"""Studio image-provider adapter for the user's asynchronous compatible API.

Remote task IDs are saved before polling, allowing continuation without paying
for a second generation. Credentials stay in the worker environment.
"""
import base64
import json
import os
import re
from pathlib import Path
import secrets
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse, quote
from urllib.request import Request, build_opener, HTTPRedirectHandler

from terrain import decode_image, digest
from asset_repository import atomic, read

DEFAULT_BASE = 'https://api.kbsfdxc.net/v1'


def load_config(root=None):
    """Read settings fresh without mutating the environment inherited by workers.

    Explicit process variables override .env; file changes and deletion are
    reflected on the next read. No shell interpolation is performed.
    """
    path = (Path(root) if root else Path(__file__).resolve().parent.parent)/'.env'
    allowed = {'STUDIO_IMAGE_API_KEY', 'OPENAI_API_KEY', 'STUDIO_IMAGE_BASE_URL'}
    result={}
    for line in (path.read_text().splitlines() if path.is_file() else []):
        line = line.strip()
        if line.startswith('export '): line = line[7:].strip()
        key, sep, value = line.partition('=')
        if sep and key.strip() in allowed:
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ('\"', "'"):
                value = value[1:-1]
            if value: result[key.strip()]=value
    result.update({key:os.environ[key] for key in allowed if key in os.environ})
    return result


def configured(root=None):
    config=load_config(root)
    return bool(config.get('STUDIO_IMAGE_API_KEY') or config.get('OPENAI_API_KEY'))


def prompts(description):
    shared = (
        'Create ONE production material texture for a top-down 2D game. '
        'Square canvas, strictly orthographic overhead view, full-bleed surface texture. '
        'The uploaded reference, if present, is for palette, mark-making and visual style only; '
        'do not reproduce its scene or objects. '
        f'Art direction from the user: {description}\n'
        'Use flat diffuse lighting without cast shadows, perspective, horizon or vignette. '
        'Keep small details at a consistent scale. Aim for seamless repetition on both axes. '
        'No text, labels, grid, frames, watermark, characters, buildings, props or composed scene. '
        'Fill the whole image with a single opaque material, not a tileset or contact sheet.\n'
    )
    return {
        'ground': shared + 'Subject: the GROUND material described by the user (grass by default). '
                  'No road, paths, borders, flowers or prominent isolated motifs.',
        'road': shared + 'Subject: only the ROAD SURFACE material described by the user '
                '(compacted earth by default). Fill the canvas with the material. '
                'Do not draw a road shape or its edges; a compiler will add the shape. '
                'The last supplied image is the chosen ground texture: match its art style, '
                'detail scale and lighting, while keeping the road material distinct. '
                'No grass borders, intersections, road markings or scenic composition.',
    }


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class SubmissionRejected(ValueError):
    """A definite HTTP rejection before a remote task was accepted."""


class Provider:
    def __init__(self, audit_path=None):
        self.audit_path = Path(audit_path) if audit_path else None
        config=load_config()
        self.base = config.get('STUDIO_IMAGE_BASE_URL', DEFAULT_BASE).rstrip('/')
        parsed = urlparse(self.base)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError('STUDIO_IMAGE_BASE_URL 须为不含凭据的 HTTPS API 地址')
        self.key = config.get('STUDIO_IMAGE_API_KEY') or config.get('OPENAI_API_KEY')
        if not self.key:
            raise ValueError('未配置图像 API Key，请设置环境变量后重启 Studio')
        self.opener = build_opener(NoRedirect())

    def error_detail(self, exc):
        """Read a bounded JSON error, retaining only safe diagnostic fields."""
        try:
            raw=exc.read(16*1024+1)
            if len(raw)>16*1024: return {'message':'错误响应超过16KB，未保留正文'}
            result=json.loads(raw)
            value=result.get('error',result) if isinstance(result,dict) else None
            if isinstance(value,str): value={'message':value}
            if not isinstance(value,dict): return {}
            detail={}
            for key in ('type','code','message'):
                text=value.get(key)
                if not isinstance(text,(str,int)) or isinstance(text,bool): continue
                text=str(text).replace(self.key,'[REDACTED]')
                text=re.sub(r'Bearer\s+[^\s"\']+','Bearer [REDACTED]',text,flags=re.I)
                text=re.sub(r'(?i)(api[_-]?key\s*[:=]\s*)[^\s,;]+',r'\1[REDACTED]',text)
                text=re.sub(r'[A-Za-z0-9+/=_-]{128,}','[LONG DATA REDACTED]',text)
                detail[key]=text[:512]
            return detail
        except (OSError,ValueError,UnicodeError):
            return {}

    def audit(self, **event):
        """Local transport evidence only: never record credentials or image bytes."""
        if not self.audit_path: return
        event['time_utc']=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())
        raw=json.dumps(event,ensure_ascii=False,default=str).replace(self.key,'[REDACTED]')
        raw=re.sub(r'Bearer\s+[^\s"\\]+','Bearer [REDACTED]',raw,flags=re.I)
        try:
            with self.audit_path.open('a',encoding='utf-8') as output: output.write(raw+'\n')
        except OSError:
            # Logging must not turn an accepted submission into an uncertain one.
            pass

    def request(self, suffix, payload=None, kind='application/json', binary=False):
        url = self.base + suffix
        origin = urlparse(self.base).netloc
        for _ in range(5):
            headers = {'Accept': 'image/*' if binary else 'application/json',
                       'User-Agent': 'Mozilla/5.0 (compatible; GameAssetStudio/1.0)'}
            if urlparse(url).netloc == origin:
                headers['Authorization'] = 'Bearer ' + self.key
            if payload is not None:
                headers['Content-Type'] = kind
            req = Request(url, data=payload, headers=headers)
            endpoint=urlparse(url)
            evidence={'method':req.get_method(),'endpoint':endpoint.scheme+'://'+endpoint.netloc+endpoint.path,
                      'payload_bytes':len(payload) if payload is not None else 0,'content_type':kind if payload is not None else None}
            self.audit(event='request',**evidence)
            try:
                with self.opener.open(req, timeout=90) as response:
                    body = response.read(32*1024*1024+1)
                    if len(body) > 32*1024*1024:
                        raise ValueError('图片服务响应超过 32MB')
                    result=body if binary else json.loads(body)
                    summary=({k:result[k] for k in ('id','status','operation','model','error') if k in result}
                             if isinstance(result,dict) else {})
                    self.audit(event='response',http_status=response.status,response=summary,
                               request_id=response.headers.get('x-request-id') or response.headers.get('request-id'),**evidence)
                    return result
            except HTTPError as exc:
                detail={} if exc.code in (301,302,303,307,308) else self.error_detail(exc)
                self.audit(event='http_error',http_status=exc.code,
                           response={'error':detail},
                           request_id=exc.headers.get('x-request-id') or exc.headers.get('request-id'),**evidence)
                if binary and exc.code in (301, 302, 303, 307, 308):
                    from urllib.parse import urljoin
                    target = urljoin(url, exc.headers.get('Location', ''))
                    parsed = urlparse(target)
                    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
                        raise ValueError('图片下载重定向地址无效') from None
                    url = target
                    continue
                error = SubmissionRejected if exc.code in (400, 401, 403, 404, 405, 413, 422, 429) else ValueError
                reason=detail.get('message') or detail.get('code') or detail.get('type')
                raise error(f'图片服务 HTTP {exc.code}'+('：'+reason if reason else '，请检查额度、凭据或稍后继续任务')) from None
            except (URLError, TimeoutError, OSError):
                self.audit(event='connection_error',**evidence)
                raise ValueError('图片服务连接中断；已记录的远程任务可继续查询') from None
            except (json.JSONDecodeError, UnicodeError):
                self.audit(event='invalid_json',**evidence)
                raise ValueError('图片服务未返回有效 JSON') from None
        raise ValueError('图片下载重定向次数过多')

    def create(self, prompt, images):
        fields = {'model': 'gpt-image-2', 'prompt': prompt, 'size': '1024x1024',
                  'quality': 'high', 'response_format': 'b64_json', 'n': 1, 'async': True}
        if not images:
            return self.request('/images/generations', json.dumps(fields).encode())
        boundary = 'studio-' + secrets.token_hex(16)
        parts = []
        for key, value in fields.items():
            value = str(value).lower() if isinstance(value, bool) else str(value)
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode())
        for image in images:
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="image[]"; filename="{image.name}"\r\nContent-Type: image/png\r\n\r\n'.encode())
            parts.append(image.read_bytes() + b'\r\n')
        parts.append(f'--{boundary}--\r\n'.encode())
        return self.request('/images/edits', b''.join(parts), f'multipart/form-data; boundary={boundary}')


def generate_materials(folder, spec, progress):
    provider = Provider(folder/'http.jsonl')
    receipt = read(folder/'generation.json', {})
    prompt_set = prompts(spec['description'])
    if spec.get('asset_type')=='material':
        prompt_set['ground']=prompt_set['ground'].replace(' (grass by default)','')
        if spec.get('material_prompt'):
            prompt_set['ground'] = spec['material_prompt']
    for role in (('ground',) if spec.get('asset_type')=='material' else ('ground','road')):
        target = folder/'inputs'/f'{role}.png'
        record = receipt.setdefault(role, {'prompt': prompt_set[role], 'model': 'gpt-image-2',
                                          'base_url': provider.base})
        if record['base_url'] != provider.base:
            raise ValueError('图片服务地址已变化，请恢复原地址后继续，或创建新任务')
        if target.is_file() and record.get('sha256') == digest(target):
            progress('复用已生成的' + ('地面' if role == 'ground' else '道路') + '材质')
            continue
        if record.get('submission_uncertain'):
            raise ValueError('上次提交未收到任务 ID，服务端可能已扣费。请在服务商后台确认后新建任务，避免自动重复提交')
        if record.get('remote_status') == 'failed':
            # Re-entered by an explicit continuation; never retry indefinitely
            # within a worker. Keep all failed IDs for provider/account auditing.
            record.setdefault('failed_attempts', []).append({'remote_id':record['remote_id'], 'status':'failed'})
            record.pop('remote_id')
            record.pop('remote_status')
            atomic(folder/'generation.json', receipt)
        progress('AI 正在生成' + ('地面' if role == 'ground' else '道路') + '材质')
        if not record.get('remote_id'):
            references = [folder/'inputs/reference.png'] if (folder/'inputs/reference.png').exists() else []
            if role == 'road': references.append(folder/'inputs/ground.png')
            record['reference_sha256'] = {p.name: digest(p) for p in references}
            # Persist intent before the non-idempotent network request.
            record['submission_uncertain'] = True
            atomic(folder/'generation.json', receipt)
            try:
                response = provider.create(record['prompt'], references)
            except SubmissionRejected:
                record.pop('submission_uncertain', None)
                atomic(folder/'generation.json', receipt)
                raise
            if response.get('id'):
                record['remote_id'] = str(response['id'])
                record.pop('submission_uncertain', None)
                atomic(folder/'generation.json', receipt)
            elif response.get('data'):
                # Some compatible providers finish immediately despite async=true.
                image = decode_image(response['data'][0].get('b64_json'))
                image.save(target)
                record['sha256'] = digest(target)
                record.pop('submission_uncertain', None)
                atomic(folder/'generation.json', receipt)
                continue
            else:
                raise ValueError('图片服务未返回任务 ID；请确认服务商后台的任务状态')
        remote = quote(record['remote_id'], safe='')
        deadline = time.monotonic() + 1200
        while time.monotonic() < deadline:
            response = provider.request('/images/' + remote)
            status = response.get('status')
            if status == 'completed':
                raw = provider.request('/images/' + remote + '/content', binary=True)
                # Normalize provider PNG/JPEG content to our opaque PNG inputs.
                image = decode_image(base64.b64encode(raw).decode())
                image.save(target)
                record['sha256'] = digest(target)
                atomic(folder/'generation.json', receipt)
                break
            if status == 'failed':
                record['remote_status'] = 'failed'
                atomic(folder/'generation.json', receipt)
                raise ValueError('图片接口返回任务失败（'+record['remote_id']+'）；尚不能确认请求是否到达生图服务。'
                                 '请求记录见任务目录 http.jsonl。继续任务会重新提交失败的材质，可能产生费用；已成功材质将复用')
            if status not in ('pending', 'queued', 'running', 'processing'):
                raise ValueError('图片服务返回未知任务状态，请检查服务商后台')
            time.sleep(3)
        else:
            raise ValueError('等待图片生成超过 20 分钟，可继续任务查询原任务')
