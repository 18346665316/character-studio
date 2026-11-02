"""Google Cloud Vertex AI Gemini image adapter.

Uses service-account/ADC credentials, not the Gemini Developer API. One POST per
explicit generation; synchronous failures are never retried automatically.
"""
import base64
from io import BytesIO
import json
import re
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener

from PIL import Image

DEFAULT_MODEL = 'gemini-2.5-flash-image'
DEFAULT_LOCATION = 'us-central1'
SCOPE = 'https://www.googleapis.com/auth/cloud-platform'


def settings(config, root):
    root = Path(root)
    path = config.get('GOOGLE_APPLICATION_CREDENTIALS')
    credentials = Path(path).expanduser() if path else None
    if credentials and not credentials.is_absolute(): credentials = root/credentials
    project = config.get('GCP_PROJECT_ID') or config.get('GOOGLE_CLOUD_PROJECT')
    if credentials:
        if not credentials.is_file(): raise ValueError('Google Cloud 服务账号文件不存在')
        try:
            account = json.loads(credentials.read_text())
            if not isinstance(account, dict): raise ValueError('Google Cloud 服务账号文件无效')
            if account.get('type') != 'service_account': raise ValueError('请使用服务账号JSON，或留空凭据路径使用ADC')
            project = project or account.get('project_id')
        except (OSError, json.JSONDecodeError): raise ValueError('Google Cloud 服务账号文件无效') from None
    model = config.get('STUDIO_GOOGLE_IMAGE_MODEL', DEFAULT_MODEL)
    location = config.get('GCP_LOCATION') or config.get('GOOGLE_CLOUD_LOCATION', DEFAULT_LOCATION)
    if not isinstance(project,str) or not re.fullmatch(r'[a-z][a-z0-9-]{4,62}', project):
        raise ValueError('请配置有效的GCP_PROJECT_ID或GOOGLE_CLOUD_PROJECT')
    if not re.fullmatch(r'[a-z0-9-]+', location): raise ValueError('Google Cloud 区域无效')
    if not re.fullmatch(r'gemini-[a-z0-9.-]*image[a-z0-9.-]*', model):
        raise ValueError('请选择支持参考图输入的Gemini image模型；此适配器不使用Imagen文生图接口')
    host = 'aiplatform.googleapis.com' if location == 'global' else location+'-aiplatform.googleapis.com'
    base = f'https://{host}/v1/projects/{project}/locations/{location}/publishers/google/models/{model}'
    return dict(project=project, location=location, model=model, credentials=credentials, base=base)


class GoogleProvider:
    def __init__(self, config, root, audit_path=None):
        from terrain_images import NoRedirect
        spec = settings(config, root)
        self.base, self.model = spec['base'], spec['model']
        self.provider = 'google_cloud'; self.audit_path = Path(audit_path) if audit_path else None
        try:
            import google.auth
            from google.oauth2 import service_account
            from google.auth.transport.requests import Request as AuthRequest
        except ImportError:
            raise ValueError('Google Cloud 缺少依赖，请运行 .local/python/bin/python3 -m pip install -r pipeline/requirements-google-images.txt') from None
        try:
            if spec['credentials']:
                self.credentials = service_account.Credentials.from_service_account_file(str(spec['credentials']), scopes=[SCOPE])
            else:
                self.credentials, _ = google.auth.default(scopes=[SCOPE], quota_project_id=spec['project'])
            # Authenticate before the caller writes non-idempotent submission intent.
            self.auth_request = AuthRequest()
            self.credentials.refresh(self.auth_request)
        except Exception:
            raise ValueError('Google Cloud 认证失败，请检查服务账号或ADC凭据及网络连接') from None
        self.opener = build_opener(NoRedirect())

    def audit(self, **event):
        import time
        if not self.audit_path: return
        event['time_utc'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        try:
            with self.audit_path.open('a', encoding='utf-8') as output: output.write(json.dumps(event,ensure_ascii=False)+'\n')
        except OSError: pass

    def create(self, prompt, images):
        from terrain_images import SubmissionRejected
        parts = [{'text': prompt}]
        for path in images:
            with Image.open(path) as image:
                image.load(); stream=BytesIO();image.save(stream,format='PNG')
            parts.append({'inlineData': {'mimeType': 'image/png', 'data': base64.b64encode(stream.getvalue()).decode()}})
        payload = dict(contents=[dict(role='user',parts=parts)],
                       generationConfig=dict(responseModalities=['TEXT','IMAGE'],
                                             imageConfig=dict(aspectRatio='1:1')))
        # Token refresh is safe to retry, paid image generation is not.
        if not self.credentials.valid:
            try: self.credentials.refresh(self.auth_request)
            except Exception: raise SubmissionRejected('Google Cloud 凭据刷新失败，尚未提交生成') from None
        body = json.dumps(payload).encode()
        endpoint=self.base+':generateContent'
        event=dict(method='POST',endpoint=endpoint,payload_bytes=len(body),content_type='application/json')
        self.audit(event='request',**event)
        request=Request(endpoint, data=body, headers={'Authorization':'Bearer '+self.credentials.token,
                        'Content-Type':'application/json','Accept':'application/json'})
        try:
            with self.opener.open(request,timeout=240) as response:
                raw=response.read(32*1024*1024+1)
                if len(raw)>32*1024*1024: raise ValueError('Google Cloud 图片响应超过32MB，未自动重试')
                result=json.loads(raw)
                self.audit(event='response',http_status=response.status,
                    request_id=response.headers.get('x-request-id'),response={'model':self.model,'status':'responded'},**event)
        except HTTPError as error:
            self.audit(event='http_error',http_status=error.code,response={'model':self.model,'error':'HTTP '+str(error.code)},**event)
            # Never expose server bodies, signed credentials, input data or tokens.
            cls=SubmissionRejected if error.code in (400,401,403,404,405,413,422,429) else ValueError
            raise cls('Google Cloud 图片服务 HTTP '+str(error.code)+'；请检查模型区域、Vertex AI权限、配额和账单') from None
        except (URLError,TimeoutError,OSError):
            self.audit(event='connection_error',**event)
            raise ValueError('Google Cloud 生图连接中断，提交结果不明；不会自动重试，请先核实服务商记录') from None
        except (json.JSONDecodeError,UnicodeError):
            self.audit(event='invalid_json',**event)
            raise ValueError('Google Cloud 返回无效JSON；不会自动重试') from None
        if not isinstance(result,dict): raise ValueError('Google Cloud 响应格式无效；不会自动重试')
        for candidate in result.get('candidates') or []:
            for part in (candidate.get('content') or {}).get('parts') or []:
                inline=part.get('inlineData') or part.get('inline_data') or {}
                if not inline.get('mimeType',inline.get('mime_type','')).startswith('image/'): continue
                content=inline.get('data')
                try:
                    decoded=base64.b64decode(content,validate=True)
                    with Image.open(BytesIO(decoded)) as image: image.verify()
                except (ValueError,TypeError,OSError): raise ValueError('Google Cloud 返回的图片数据无效；不会自动重试') from None
                return {'data':[{'b64_json':content}]}
        self.audit(event='no_image',response={'model':self.model,'status':'no_image'},**event)
        raise SubmissionRejected('Google Cloud 已响应但没有图片，可能被过滤或模型不支持生图；未自动重试')

    def request(self, *args, **kwargs):
        raise ValueError('Google Cloud 同步生图接口没有可续查的异步任务；请检查原服务与回执，不会自动重新提交')
