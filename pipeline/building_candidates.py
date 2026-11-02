"""Line drawing + style -> independent candidates -> manual spatial calibration.

No inferred roof, opening or footprint data is supplied to the image service.
"""
import math
from pathlib import Path
import shutil
import zipfile

from PIL import Image
from asset_repository import AssetRepository, atomic, read
from static_props import cutout, single_object
import building_pipeline as bp

WORKFLOW = 'line_drawing'
SCHEMA = 'studio.building-kit/0.2'
ALGORITHM = 'building-candidate/1'


def prepare(root, data):
    title, style = data.get('title', ''), data.get('appearance', '')
    if not isinstance(title, str) or not 1 <= len(title.strip()) <= 60: raise ValueError('建筑名称需为1–60字')
    if not isinstance(style, str) or not 1 <= len(style.strip()) <= 2000: raise ValueError('请填写1–2000字的建筑风格提示词')
    source = None
    if data.get('source_task'):
        source, parent = bp.require_job(root, data['source_task'])
        bp.check_revision(parent, data.get('source_revision')); bp.verify_inputs(source, parent)
    template_meta=None
    if data.get('template_id') and data.get('line_drawing'):raise ValueError('请选择模板或上传框线图，不能同时指定')
    if data.get('template_id'):
        from building_templates import load
        template_folder,template_meta=load(root,data['template_id'])
        with Image.open(template_folder/'outline.png') as image:drawing=image.convert('RGB')
    elif data.get('line_drawing'):
        drawing = bp.decode_art_image(data['line_drawing'])
        # Transparent line art needs a visible paper background for the provider.
        paper = Image.new('RGBA', drawing.size, 'white'); paper.alpha_composite(drawing)
        drawing = paper.convert('RGB')
    elif source and (source/'outline.png').exists():
        with Image.open(source/'outline.png') as image: drawing = image.convert('RGB')
    else: raise ValueError('请上传原始建筑框线图')
    task = bp.identity(); folder = bp.folder_for(root, task); folder.mkdir(parents=True)
    drawing.save(folder/'outline.png')
    if template_meta is None and source and not data.get('line_drawing'):template_meta=read(source/'template-source.json')
    if template_meta:atomic(folder/'template-source.json',template_meta)
    atomic(folder/'request.json', dict(title=title.strip(), appearance=style.strip(), workflow=WORKFLOW,template_id=template_meta['id'] if template_meta else None))
    job = dict(id=task, workflow=WORKFLOW, spec=dict(title=title.strip(), appearance=style.strip()),
               status='draft', stage='框线图与风格已保存，等待生成', created_at=bp.now(), revision=1,
               current_attempt=None, selected_attempt=None, attempts=[], error=None, template_id=template_meta['id'] if template_meta else None, parent_task=data.get('source_task'))
    job['input_sha256'] = bp.input_hashes(folder); atomic(folder/'job.json', job)
    return job


def prompt(style):
    return ('Render ONE finished standalone 2D game building from the supplied original line drawing. '
            'The line drawing defines the building shape, proportions, roof, openings and viewing angle. '
            'Keep its architectural layout; do not invent a different building type or add structures. '
            'Preserve each door and window in its original location, size and function: '
            'windows remain windows and doors remain doors. Do not turn upper-floor windows into doors. '
            'Ignore and remove any reference text, numbers, angle markers, dimensions, ground grids '
            'and construction guides; these are not part of the building. '
            'Replace construction lines with finished surfaces in the requested style. '
            'Keep the whole building visible with empty margins, no ground plane, scene or cast shadow. '
            'Use a perfectly flat pure magenta #FF00FF background for background removal. '
            'Every background pixel must have the same color: no gradients, texture, vignette, '
            'ground contact shadows or projected shadows. Use soft neutral lighting on the building itself; '
            'surface shading stays within its silhouette. The magenta is a background key only, '
            'not an environment: no magenta color spill, bounce light or reflections on the building. '
            'No diagram lines, text, labels, watermark or collage. '
            'Apply the following architectural art style (materials, palette and rendering): '+style)


def new_attempt(folder, job, correction, mode, template=False):
    if correction or mode != 'fresh': raise ValueError('此流程复用框线图与风格重新生成；修改风格请另存生成方案')
    if job['status'] not in ('draft', 'waiting_review', 'failed', 'complete'): raise ValueError('请等待当前生成结束')
    previous = job.get('current_attempt')
    if previous:
        receipt = read(bp.attempt_folder(folder, previous)/'generation.json', {})
        if receipt.get('submission_uncertain'): raise ValueError('提交结果不明，请先核实原任务，禁止重复付费')
        if receipt.get('remote_id') and receipt.get('status') not in ('completed', 'failed'):
            raise ValueError('原任务尚未结束，请继续查询')
    attempt = bp.identity(); target = bp.attempt_folder(folder, attempt); target.mkdir(parents=True)
    if template:
        from building_templates import prompt as template_prompt
        generation_prompt=template_prompt(job['spec'])
    else:generation_prompt=prompt(job['spec']['appearance'])
    (target/'prompt.txt').write_text(generation_prompt, encoding='utf-8')
    atomic(target/'attempt.json', dict(id=attempt, parent_attempt=previous, workflow=WORKFLOW,
        mode='fresh', prompt_sha256=bp.digest(target/'prompt.txt'), inputs_sha256=job['input_sha256'],
        image_roles=[] if template else [dict(path='outline.png', role='building_line_drawing', sha256=bp.digest(folder/'outline.png'))],
        created_at=bp.now()))
    job.update(current_attempt=attempt, execution_mode='submit', status='queued', stage='等待生成新候选', error=None,
               revision=job['revision']+1)
    job['attempts'].append(attempt); atomic(folder/'job.json', job)
    return job


def evidence(folder, target):
    return {p: bp.digest(target/p) for p in ('raw.png', 'sprite.png', 'preview.png')}


def process(folder, target):
    with Image.open(target/'raw.png') as image: sprite, method = cutout(image, adaptive_magenta=True)
    connectivity = single_object(sprite)
    # Keep the provider's full canvas. Candidate comparison never bbox-fits each image.
    sprite.save(target/'sprite.png'); width, height = sprite.size
    preview = Image.new('RGB', (width*2, height))
    for i, color in enumerate(('#edf0e9', '#34404b')):
        panel = Image.new('RGBA', sprite.size, color); panel.alpha_composite(sprite)
        preview.paste(panel.convert('RGB'), (i*width, 0))
    preview.save(target/'preview.png')
    atomic(target/'checks.json', dict(algorithm=ALGORITHM, evidence_sha256=evidence(folder, target),
        canvas_px=list(sprite.size), background=method, connectivity=connectivity,
        structure_conformity='not_automatically_verified', art_review='user_selection_required'))


def verify_evidence(folder, target):
    report = read(target/'checks.json', {})
    receipt = read(target/'generation.json', {})
    if receipt.get('sha256') != bp.digest(target/'raw.png'): raise ValueError('候选原图与回执不一致')
    if report.get('algorithm') != ALGORITHM or report.get('evidence_sha256') != evidence(folder, target):
        raise ValueError('候选文件已变化，请重新检查')
    return report


def select(root, data):
    with bp.task_lock(root):
        folder, job = bp.require_job(root, data.get('task')); bp.check_revision(job, data.get('revision'))
        if job.get('workflow') != WORKFLOW or job.get('purpose') == 'template': raise ValueError('请选择建筑外观候选，线框母版请保存为模板')
        if job['status'] in ('queued', 'running'): raise ValueError('请等待当前生成结束后再选用')
        bp.verify_inputs(folder, job)
        attempt = data.get('attempt')
        if attempt not in job['attempts']: raise ValueError('候选不存在')
        target = bp.attempt_folder(folder, attempt); bp.verify_attempt(folder, target, job)
        verify_evidence(folder, target)
        job.update(selected_attempt=attempt, revision=job['revision']+1)
        atomic(folder/'job.json', job); return job


def finite(value, low, high, label):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(label+'超出范围')
    return float(value)


def calibration(data, size):
    if not isinstance(data, dict): raise ValueError('请完成占地与锚点标定')
    width, height = size
    def point(value):
        if not isinstance(value, list) or len(value) != 2: raise ValueError('标定点坐标无效')
        return [finite(value[0], 0, width, '横坐标'), finite(value[1], 0, height, '纵坐标')]
    anchor = point(data.get('anchor_px'))
    polygon = data.get('footprint_polygon_px')
    if not isinstance(polygon, list) or not 3 <= len(polygon) <= 24: raise ValueError('请标记3–24个占地轮廓顶点')
    polygon = [point(p) for p in polygon]
    def cross(a,b,c): return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
    def intersects(a,b,c,d):
        eps=1e-6
        def on(p,q,r): return abs(cross(p,q,r)) < eps and min(p[0],q[0])-eps <= r[0] <= max(p[0],q[0])+eps and min(p[1],q[1])-eps <= r[1] <= max(p[1],q[1])+eps
        return (cross(a,b,c)*cross(a,b,d)<0 and cross(c,d,a)*cross(c,d,b)<0) or any((on(a,b,c),on(a,b,d),on(c,d,a),on(c,d,b)))
    for i,a in enumerate(polygon):
        b=polygon[(i+1)%len(polygon)]
        if a==b: raise ValueError('占地顶点不能重复')
        for j in range(i+1,len(polygon)):
            if j==i+1 or (i==0 and j==len(polygon)-1): continue
            if intersects(a,b,polygon[j],polygon[(j+1)%len(polygon)]): raise ValueError('占地轮廓不能交叉')
    area=abs(sum(p[0]*polygon[(i+1)%len(polygon)][1]-p[1]*polygon[(i+1)%len(polygon)][0] for i,p in enumerate(polygon)))/2
    if area < 4: raise ValueError('占地轮廓面积过小')
    output_width=data.get('output_width_px',512)
    if type(output_width) is not int or not 64 <= output_width <= 2048: raise ValueError('成品画布宽度须为64–2048整数')
    if round(height*output_width/width)>2048: raise ValueError('成品画布高度超过2048px，请减小宽度')
    cell=data.get('cell_px',128)
    if type(cell) is not int or cell not in (64,128): raise ValueError('地格宽度须为64或128')
    entrance=point(data['entrance_px']) if data.get('entrance_px') is not None else None
    return dict(source_canvas_px=list(size), anchor_px=anchor, footprint_polygon_px=polygon,
                entrance_px=entrance, output_width_px=output_width, cell_px=cell,
                coordinate_space='original_generated_image_pixels', source='user_calibrated')


def save(root, data):
    with bp.task_lock(root):
        folder,job=bp.require_job(root,data.get('task'));bp.check_revision(job,data.get('revision'));bp.verify_inputs(folder,job)
        if job.get('workflow') != WORKFLOW or job.get('purpose') == 'template': raise ValueError('此保存入口只支持建筑外观候选')
        if job['status'] in ('queued','running'): raise ValueError('请等待当前生成结束')
        attempt=data.get('attempt')
        if attempt not in job['attempts'] or attempt != job.get('selected_attempt'): raise ValueError('请先选定候选')
        target=bp.attempt_folder(folder,attempt);bp.verify_attempt(folder,target,job);report=verify_evidence(folder,target)
        if data.get('evidence_key') != bp.digest(target/'checks.json'): raise ValueError('候选已更新，请重新载入后标定')
        with Image.open(target/'sprite.png') as image:
            spec=calibration(data.get('calibration'),image.size)
            scale=spec['output_width_px']/image.width
            sprite=image.resize((spec['output_width_px'],round(image.height*scale)),Image.Resampling.LANCZOS)
        # Every saved calibration is a new immutable asset, even when the candidate is reused.
        kit=job['id']+'-'+bp.identity().split('-')[-1]
        final=AssetRepository(root).scoped('building-kits/'+kit,'building-kits')
        staging=folder/('publish-'+kit);(staging/'inputs').mkdir(parents=True)
        sprite.save(staging/'sprite.png')
        preview=Image.new('RGB',(sprite.width*2,sprite.height))
        for i,color in enumerate(('#edf0e9','#34404b')):
            panel=Image.new('RGBA',sprite.size,color);panel.alpha_composite(sprite);preview.paste(panel.convert('RGB'),(i*sprite.width,0))
        preview.save(staging/'preview.png')
        scaled=lambda p:[round(p[0]*scale,4),round(p[1]*scale,4)]
        anchor=scaled(spec['anchor_px']);poly=[scaled(p) for p in spec['footprint_polygon_px']]
        relative=[[round(p[0]-anchor[0],4),round(p[1]-anchor[1],4)] for p in poly]
        integration=dict(anchor_px=anchor,sprite_offset_px=[-v for v in anchor],footprint_polygon=relative,
            units='pixels_relative_to_ground_anchor_x_right_y_down', cell_px=spec['cell_px'],
            entrance_px=scaled(spec['entrance_px']) if spec['entrance_px'] else None,
            entrance_coordinate_space='output_image_pixels',
            collision=dict(enabled_by_default=False,proposal='user_calibrated_footprint'),
            view='from_line_drawing_not_automatically_verified', visual_layers='single_sprite',
            occlusion='not_tested',game_integration='not_tested')
        atomic(staging/'calibration.json',spec);atomic(staging/'integration.json',integration)
        atomic(staging/'selection.json',dict(attempt_id=attempt,selected_at=bp.now(),evidence=report,
            calibration_sha256=bp.digest(staging/'calibration.json'),meaning='user_selected_candidate_not_engine_acceptance'))
        for source,dest in [(folder/'outline.png','inputs/outline.png'),(folder/'request.json','request.json'),
            (target/'raw.png','inputs/raw.png'),(target/'sprite.png','inputs/sprite.png'),(target/'preview.png','inputs/preview.png'),
            (target/'attempt.json','attempt.json'),(target/'prompt.txt','prompt.txt'),
            (target/'generation.json','generation.json'),(target/'checks.json','checks.json')]:shutil.copyfile(source,staging/dest)
        if (folder/'template-source.json').exists():shutil.copyfile(folder/'template-source.json',staging/'template-source.json')
        (staging/'INTEGRATION.md').write_text('# Building candidate\n\nGeometry and view come from the input line drawing.\n'
            'Use sprite_offset_px and the recorded cell_px. Calibration points use original-image pixels; integration uses output pixels.\n'
            'Footprint is manually marked, not inferred. Collision is OFF by default.\n'
            'Entrance is an optional scene-transition marker. Character scale and occlusion require game testing.\n',encoding='utf-8')
        manifest=dict(schema=SCHEMA,id=kit,title=job['spec']['title'],created_at=bp.now(),asset_family='building',
            workflow=WORKFLOW,source_evidence_base='inputs',task_id=job['id'],attempt_id=attempt,view='from_line_drawing',
            production_ready=False,human_review='candidate_selected',game_integration='not_tested',
            files_sha256={str(p.relative_to(staging)):bp.digest(p) for p in sorted(staging.rglob('*')) if p.is_file()})
        atomic(staging/'manifest.json',manifest)
        with zipfile.ZipFile(staging/'kit.zip','w',zipfile.ZIP_DEFLATED) as archive:
            for p in sorted(staging.rglob('*')):
                if p.is_file() and p.name!='kit.zip':archive.write(p,str(p.relative_to(staging)))
        final.parent.mkdir(parents=True,exist_ok=True);staging.rename(final);bp.load_package(root,kit)
        job.update(status='complete',error=None,stage='建筑素材已保存，游戏接入待验证',kit_id=kit,revision=job['revision']+1)
        job.setdefault('saved_kits',[]).append(kit);atomic(folder/'job.json',job)
        return manifest
