"""Persistent AI surface jobs for the procedural fence compiler."""
from datetime import datetime, timezone
from pathlib import Path
import secrets

from asset_repository import AssetRepository, atomic, read, name
from task_lock import task_lock
from terrain import decode_image
from terrain_images import configured, generate_materials
from fence_components import build, load_package


def prepare(root, data):
    description=data.get('description')
    if not isinstance(description,str) or not 1<=len(description.strip())<=2000:
        raise ValueError('请填写1–2000字的木材描述')
    if not configured(root): raise ValueError('请先在项目.env配置图片服务密钥')
    reference=decode_image(data['reference']) if data.get('reference') else None
    identity=datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+secrets.token_hex(4)
    folder=AssetRepository(root).scoped('.local/components/jobs/'+identity,'.local/components/jobs')
    (folder/'inputs').mkdir(parents=True)
    if reference: reference.save(folder/'inputs/reference.png')
    prompt=('Create one opaque wood surface texture for a stylized 2D game fence. '
            'Fill the entire square with continuous fine vertical wood grain. '
            'Flat frontal view, even diffuse light, no perspective, no shadows, '
            'no plank gaps, no fence, no objects, no text or border. '
            'If a reference is supplied, use its palette and rendering style only. '
            'The program will construct fence posts and rails from this material. '
            'Art direction: '+description.strip())
    job={'id':identity,'status':'queued','stage':'等待生成木纹','error':None,
         'created_at':datetime.now(timezone.utc).isoformat(),
         'spec':{'asset_type':'material','description':description.strip(),'material_prompt':prompt}}
    atomic(folder/'job.json',job)
    return job


def catalog(root):
    jobs=[read(p) for p in (Path(root)/'.local/components/jobs').glob('*/job.json')]
    return sorted((j for j in jobs if j),key=lambda j:j['created_at'],reverse=True)[:60]


def execute(root, identity):
    folder=AssetRepository(root).scoped('.local/components/jobs/'+name(identity),'.local/components/jobs')
    with task_lock(root):
        job=read(folder/'job.json')
        def progress(stage):
            job.update(status='running',stage=stage.replace('地面','木纹'),error=None)
            atomic(folder/'job.json',job)
        try:
            destination=Path(root)/'component-kits'/identity
            if destination.exists():
                load_package(root,identity)
            else:
                progress('准备生成木纹')
                generate_materials(folder,job['spec'],progress)
                progress('程序制作围栏构件')
                build(root,appearance='timber',wood_image=folder/'inputs/ground.png',source_job=folder)
            job.update(status='complete',stage='围栏套件已完成',kit_id=identity,error=None)
        except Exception as error:
            job.update(status='failed',stage='任务失败',error=str(error))
        atomic(folder/'job.json',job)


if __name__=='__main__':
    import sys
    root=Path(__file__).resolve().parent.parent
    with task_lock(root,inherited_fd=int(sys.argv[2])):
        execute(root,sys.argv[1])
