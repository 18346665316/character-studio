"""Reusable building line-art masters, independent from appearance jobs."""
from pathlib import Path
import shutil

from PIL import Image
from asset_repository import AssetRepository, atomic, read, name
import building_pipeline as bp

VIEWS = {'orthographic_three_quarter':'正面斜俯视', 'isometric_2_1':'2:1 等距地格', 'isometric_true':'等轴测（严格等角）', 'custom':'沿用原图视角'}


def folder_for(root, identity):
    return AssetRepository(root).scoped('building-templates/'+name(identity),'building-templates')


def load(root, identity):
    folder=folder_for(root,identity);meta=read(folder/'template.json',{})
    if meta.get('id') != identity or meta.get('schema') != 'studio.building-template/0.1': raise ValueError('建筑模板不存在')
    if not (folder/'outline.png').is_file() or bp.digest(folder/'outline.png') != meta.get('outline_sha256'):
        raise ValueError('模板框线图缺失或已变化')
    return folder,meta


def catalog(root):
    result=[]
    for path in (Path(root)/'building-templates').glob('*/template.json'):
        try:
            _,meta=load(root,path.parent.name);result.append(meta)
        except (ValueError,OSError):continue
    return sorted(result,key=lambda m:m['created_at'],reverse=True)


def text(value,label,maximum=60):
    if not isinstance(value,str) or not 1<=len(value.strip())<=maximum:raise ValueError(label+'需为1–'+str(maximum)+'字')
    return value.strip()


def save(root, data):
    with bp.task_lock(root):
        title=text(data.get('title'),'模板名称');view=data.get('view','isometric_2_1')
        if view not in VIEWS:raise ValueError('模板视角无效')
        provenance={}
        target=None
        if data.get('task'):
            source,job=bp.require_job(root,data['task']);bp.check_revision(job,data.get('revision'));bp.verify_inputs(source,job)
            if job.get('purpose') != 'template':raise ValueError('请选择模板生成任务')
            if job['status'] in ('queued','running'):raise ValueError('请等待模板生成结束')
            attempt=data.get('attempt')
            if attempt not in job['attempts']:raise ValueError('模板候选不存在')
            target=bp.attempt_folder(source,attempt);bp.verify_attempt(source,target,job)
            verify_candidate(source,target)
            if data.get('evidence_key')!=bp.digest(target/'checks.json'):raise ValueError('模板候选已更新，请重新检查')
            with Image.open(target/'raw.png') as image:drawing=image.convert('RGB')
            provenance=dict(kind='ai_line_drawing',task_id=job['id'],attempt_id=attempt,
                            prompt_sha256=bp.digest(target/'prompt.txt'),raw_sha256=bp.digest(target/'raw.png'))
            view=job['spec']['view']
        else:
            drawing=bp.decode_art_image(data.get('line_drawing'))
            paper=Image.new('RGBA',drawing.size,'white');paper.alpha_composite(drawing);drawing=paper.convert('RGB')
            provenance=dict(kind='uploaded_line_drawing')
        identity=bp.identity();folder=folder_for(root,identity)
        staging=Path(root)/'.local/buildings/template-staging'/identity;staging.mkdir(parents=True)
        drawing.save(staging/'outline.png')
        if target:
            for filename in ('prompt.txt','generation.json','attempt.json','checks.json'):shutil.copyfile(target/filename,staging/filename)
        meta=dict(schema='studio.building-template/0.1',id=identity,title=title,view=view,view_label=VIEWS[view],
                  created_at=bp.now(),canvas_px=list(drawing.size),outline_sha256=bp.digest(staging/'outline.png'),
                  source=provenance,review='saved_for_reuse_not_projection_measurement')
        atomic(staging/'template.json',meta);folder.parent.mkdir(parents=True,exist_ok=True);staging.rename(folder)
        if target:
            job['template_id']=identity;job['status']='complete';job['stage']='建筑模板已保存，可用于不同外观风格';job['error']=None
            job['revision']+=1;atomic(source/'job.json',job)
        return meta


def prepare(root,data):
    title=text(data.get('title'),'模板名称');description=text(data.get('description'),'建筑形体描述',2000)
    view=data.get('view','isometric_2_1')
    if view not in VIEWS or view=='custom':raise ValueError('请选择支持的模板生成视角')
    task=bp.identity();folder=bp.folder_for(root,task);folder.mkdir(parents=True)
    spec=dict(title=title,description=description,view=view)
    atomic(folder/'template-request.json',spec)
    job=dict(id=task,workflow='line_drawing',purpose='template',spec=spec,status='draft',
             stage='模板生成方案已保存',created_at=bp.now(),revision=1,current_attempt=None,attempts=[],error=None)
    job['input_sha256']=bp.input_hashes(folder);atomic(folder/'job.json',job);return job


def prompt(spec):
    view=('Use a front-facing orthographic three-quarter game view, visible roof and front wall. Front wall horizontal, door facing screen bottom, roof recedes upward, minimal side wall. Do not use symmetric isometric sides. '
          if spec['view']=='orthographic_three_quarter' else 'Use orthographic dimetric game projection aligned to a 2:1 diamond tile. '
          'The two ground directions are symmetric, with each edge running twice as far horizontally as vertically. '
          if spec['view']=='isometric_2_1' else
          'Use strict orthographic isometric projection, with all three world axes equally foreshortened. '
          'The two ground directions are symmetric and steeper than in a dimetric diamond tile view. ')
    return ('Draw ONE clean architectural line-art master of a standalone building for reuse in 2D game art production. '
            +view+'Parallel edges remain parallel, no perspective convergence. Vertical edges stay vertical. '
            'Plain white background, thin dark visible architectural outlines, no color, '
            'no painted materials, no shading, no hatching, no ground, shadows, grid, dimension annotations or labels. '
            'Whole building centered in a square canvas with 12 percent empty margins. '
            'Depict only the building: no text, numbers, angle markers, measurement arrows, axes, '
            'tile outlines, hidden edges or internal construction guides. Projection instructions describe '
            'how to draw the building; never illustrate or annotate these instructions. '
            'Draw clear connected roof, wall and opening outlines. Architectural form: '+spec['description'])


def new_attempt(folder,job,correction,mode):
    from building_candidates import new_attempt as candidate_attempt
    # Reuse lifecycle protections, but provide a separate template prompt and no source image.
    spec=job['spec'];job['spec']={**spec,'appearance':spec['description']}
    result=candidate_attempt(folder,job,correction,mode,template=True)
    result['spec']=spec;atomic(folder/'job.json',result);return result


def process(folder,target):
    with Image.open(target/'raw.png') as image:
        image.load();size=list(image.size)
        image.convert('RGB').save(target/'preview.png')
    atomic(target/'checks.json',dict(algorithm='building-template/1',canvas_px=size,
        evidence_sha256={p:bp.digest(target/p) for p in ('raw.png','preview.png')},view='requires_user_review'))


def verify_candidate(folder,target):
    report=read(target/'checks.json',{})
    if read(target/'generation.json',{}).get('sha256')!=bp.digest(target/'raw.png'):raise ValueError('模板原图回执不一致')
    if report.get('algorithm')!='building-template/1' or report.get('evidence_sha256')!={p:bp.digest(target/p) for p in ('raw.png','preview.png')}:
        raise ValueError('模板候选已变化')
    return report
