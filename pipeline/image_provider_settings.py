"""Public provider choices and atomic .env selection; never returns credentials."""
import hashlib
import json
import os
from pathlib import Path
import tempfile

from asset_repository import read
from task_lock import task_lock
from terrain_images import load_config, config_ready

PROVIDERS = ('openai_compatible', 'google_cloud')


def state(root):
    config=load_config(root)
    current=config.get('STUDIO_IMAGE_PROVIDER','openai_compatible')
    choices=[]
    for provider,label,model in [('openai_compatible','兼容接口','gpt-image-2'),
                                 ('google_cloud','Google Cloud Vertex AI',config.get('STUDIO_GOOGLE_IMAGE_MODEL','gemini-2.5-flash-image'))]:
        choices.append(dict(id=provider,label=label,model=model,
                            configured=config_ready({**config,'STUDIO_IMAGE_PROVIDER':provider},root)))
    public=dict(current=current,choices=choices,environment_override='STUDIO_IMAGE_PROVIDER' in os.environ)
    public['revision']=hashlib.sha256(json.dumps(public,sort_keys=True).encode()).hexdigest()
    return public


def switch(root, data):
    if data.get('provider') not in PROVIDERS: raise ValueError('请选择支持的图片服务')
    with task_lock(root):
        public=state(root)
        if data.get('revision') != public['revision']: raise ValueError('图片服务配置已更新，请重新载入后切换')
        if public['environment_override']:
            raise ValueError('STUDIO_IMAGE_PROVIDER由启动进程的环境变量指定，请移除该环境变量并重启Studio后使用网页切换')
        # Also guard queued receipts: a task can be between submission and child startup.
        paths=list((Path(root)/'.local/panel/tasks').glob('*.json'))
        for family in ('terrain','props','components','buildings'):
            paths.extend((Path(root)/('.local/'+family+'/jobs')).glob('*/job.json'))
        if any(read(p,{}).get('status') in ('queued','running') for p in paths):
            raise ValueError('有生产任务正在运行，请结束后再切换图片服务')
        choice=next(c for c in public['choices'] if c['id']==data['provider'])
        if not choice['configured']: raise ValueError('所选图片服务尚未配置，请先在项目.env配置该服务的凭据')
        path=Path(root)/'.env'
        lines=[]
        for line in path.read_text().splitlines() if path.exists() else []:
            text=line.strip()
            if text.startswith('export '):text=text[7:].strip()
            key,sep,_=text.partition('=')
            if sep and key.strip()=='STUDIO_IMAGE_PROVIDER':continue
            lines.append(line)
        lines.append('STUDIO_IMAGE_PROVIDER='+data['provider'])
        fd,temporary=tempfile.mkstemp(prefix='.env.provider-',dir=str(Path(root)))
        try:
            with os.fdopen(fd,'w') as output:
                output.write('\n'.join(lines)+'\n');output.flush();os.fsync(output.fileno())
            os.chmod(temporary,0o600);os.replace(temporary,path)
        finally:
            if os.path.exists(temporary):os.unlink(temporary)
        return state(root)
