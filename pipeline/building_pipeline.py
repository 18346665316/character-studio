"""Persistent building production with shared image-service recovery and package checks.

The main workflow uses line drawings and style prompts; structured references
remain available as an auxiliary workflow.

Uses the project's image provider. Explicit retries create new attempts; resume
only queries an existing remote ID. No import-time network or UI dependencies.
"""
import argparse
import base64
from datetime import datetime, timezone
from io import BytesIO
import hashlib
import json
from pathlib import Path
import secrets
import shutil
import time
from urllib.parse import quote
import zipfile

from PIL import Image, ImageFilter

from asset_repository import AssetRepository, atomic, name, read
from building_structure import compile_structure, validate, geometry, render
from static_props import cutout, single_object
from task_lock import task_lock
from terrain import decode_image
from terrain_images import Provider, SubmissionRejected, receipt_identity

SCHEMA = 'studio.building-kit/0.1'
PROCESS_VERSION = 'building-cutout/2'
CHECKS = ('silhouette', 'roof_topology', 'openings', 'scale', 'edges', 'style')


def now(): return datetime.now(timezone.utc).isoformat()
def digest(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def identity(): return datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+secrets.token_hex(4)


def folder_for(root, task):
    return AssetRepository(root).scoped('.local/buildings/jobs/'+name(task), '.local/buildings/jobs')


def attempt_folder(folder, attempt):
    return AssetRepository(folder).scoped('attempts/'+name(attempt), 'attempts')


def require_job(root, task):
    folder = folder_for(root, task); job = read(folder/'job.json')
    if not job or job.get('id') != task: raise ValueError('建筑任务不存在')
    return folder, job


def prompt(structure, appearance, correction):
    spec = structure['spec']
    return (
        'Edit image 1 into ONE finished standalone building sprite for a hand-painted 2D game. '
        'Image 1 is an EXACT STRUCTURE TARGET, not a loose style guide. '
        'Keep its orthographic 2:1 ground axes, framing, ground contacts, wall corners, roof ridge, '
        'roof pitch, eave silhouette and all door/window positions and dimensions. '
        f"Footprint: {spec['footprint_cells']}; wall height: {spec['wall_height_units']}; "
        f"roof: {json.dumps(spec['roof'])}; openings: {json.dumps(spec['openings'])}. "
        'Roof has exactly TWO sloped surfaces and VERTICAL triangular gable walls at the ridge ends. '
        'A triangular gable wall is plaster/timber, NEVER a third tiled roof slope. '
        'Image 2, if supplied, describes palette and painting style ONLY; never copy its geometry. '
        f'Art direction: {appearance}. '
        f'Correction to the previous attempt: {correction or "none"}. '
        'Render broad readable painted forms, upper-left light, restrained surface detail. '
        'Preserve every architectural landmark and the outer silhouette. '
        'Use a completely flat pure magenta #FF00FF background, including the surrounding margins; '
        'no ground, cast shadow, scene, props, people, chimney, stairs, porch, extra openings, '
        'extra floors, text, diagram marks, watermark, border or collage. '
        'Do not zoom, crop, rotate, move or reshape the building. Change only surface appearance.'
    )


def decode_art_image(content, png_only=False):
    try:
        raw = base64.b64decode(content, validate=True)
        if not raw or len(raw) > 8*1024*1024: raise ValueError('图片需小于8MB')
        with Image.open(BytesIO(raw)) as image:
            if png_only and image.format != 'PNG': raise ValueError('修正图必须为透明PNG')
            if min(image.size) < 32 or image.width*image.height > 16_000_000: raise ValueError('图片尺寸无效')
            image.load(); return image.convert('RGBA')
    except (OSError, TypeError, Image.DecompressionBombError):
        raise ValueError('请选择有效图片') from None


def prepare(root, data):
    if data.get('workflow') == 'line_drawing':
        from building_candidates import prepare as prepare_candidates
        with task_lock(root): return prepare_candidates(root, data)
    title, appearance = data.get('title', ''), data.get('appearance', '')
    if not isinstance(title, str) or not 1 <= len(title.strip()) <= 60: raise ValueError('建筑名称需为1–60字')
    if not isinstance(appearance, str) or len(appearance.strip()) > 2000: raise ValueError('外观描述最多2000字')
    spec = validate(data.get('structure', {}))
    source = None
    if data.get('source_task'):
        source, parent = require_job(root, data['source_task']); check_revision(parent, data.get('source_revision'))
        verify_inputs(source, parent)
    style = decode_image(data['style_reference']) if data.get('style_reference') else None
    task = identity(); folder = folder_for(root, task); folder.mkdir(parents=True)
    structure = compile_structure(spec, folder/'structure')
    # Stable square AI input, centered without changing ground-pixel density.
    with Image.open(folder/'structure/reference.png') as image:
        side = max(image.size); offset = [(side-image.width)//2, (side-image.height)//2]
        canvas = Image.new('RGB', (side, side), '#f3f1ec'); canvas.paste(image, tuple(offset))
        canvas.resize((1024, 1024), Image.Resampling.LANCZOS).save(folder/'structure/ai-reference.png')
    if style is not None: style.save(folder/'style.png')
    elif source and (source/'style.png').exists() and not data.get('remove_style'):
        shutil.copyfile(source/'style.png', folder/'style.png')
    atomic(folder/'input-transform.json', {'square_side': side, 'offset_px': offset,
                                         'source_size': structure['canvas_px'], 'ai_size': [1024, 1024]})
    job = dict(id=task, spec=dict(title=title.strip(), appearance=appearance.strip()),
               status='draft', stage='结构待确认', created_at=now(), revision=1,
               current_attempt=None, attempts=[], error=None, parent_task=data.get('source_task'),
               structure_sha256=structure['structure_sha256'])
    job['input_sha256'] = input_hashes(folder)
    atomic(folder/'job.json', job)
    return job


def input_hashes(folder):
    if (folder/'template-request.json').exists():return {'template-request.json':digest(folder/'template-request.json')}
    if (folder/'request.json').exists():
        paths=['request.json','outline.png']
        if (folder/'template-source.json').exists():paths.append('template-source.json')
        return {p: digest(folder/p) for p in paths}
    paths = ['structure/structure.json', 'structure/structure.png', 'structure/ai-reference.png',
             'input-transform.json', 'structure/reference.png', 'structure/inspection.png']
    if (folder/'style.png').exists(): paths.append('style.png')
    return {p: digest(folder/p) for p in paths}


def verify_inputs(folder, job):
    actual = input_hashes(folder); expected = job['input_sha256']
    legacy_additions = {'structure/reference.png', 'structure/inspection.png'}
    if any(actual.get(p) != sha for p, sha in expected.items()) or set(actual)-set(expected)-legacy_additions:
        raise ValueError('建筑结构或来源文件已变化，请创建新任务')


def check_revision(job, revision):
    if type(revision) is not int or revision != job['revision']: raise ValueError('任务已更新，请刷新后再操作')


def new_attempt(root, task, revision, correction='', mode='fresh', source_attempt=None):
    with task_lock(root):
        folder, job = require_job(root, task); check_revision(job, revision); verify_inputs(folder, job)
        if job.get('purpose') == 'template':
            from building_templates import new_attempt as template_attempt
            return template_attempt(folder,job,correction,mode)
        if job.get('workflow') == 'line_drawing':
            from building_candidates import new_attempt as candidate_attempt
            return candidate_attempt(folder, job, correction, mode)
        if job['status'] not in ('draft', 'waiting_review', 'approved', 'rejected', 'failed', 'complete'):
            raise ValueError('当前阶段不能创建生成尝试')
        if not isinstance(correction, str) or len(correction) > 2000: raise ValueError('修正说明最多2000字')
        if not job['spec']['appearance'].strip(): raise ValueError('请先保存外观描述，再发起生图')
        if mode not in ('fresh', 'edit'): raise ValueError('生成方式无效')
        structure_spec = read(folder/'structure/structure.json')['spec']
        faces, _ = geometry(structure_spec)
        _, _, _, visibility = render(structure_spec, faces)
        if any(o['type'] == 'door' and o['visible_ratio'] < .1 for o in visibility):
            raise ValueError('入口不可见或被遮挡，请先修改结构')
        previous = job['current_attempt']
        if previous:
            receipt = read(attempt_folder(folder, previous)/'generation.json', {})
            if receipt.get('submission_uncertain'): raise ValueError('上次提交结果不明，请先在服务商后台核实，勿重复付费')
            if receipt.get('remote_id') and receipt.get('status') not in ('completed', 'failed'):
                raise ValueError('原远程任务尚未结束，请继续查询，不能重新生成')
        source_meta = {}; corrections = []
        if mode == 'edit':
            source_attempt = source_attempt or previous
            if source_attempt not in job['attempts']: raise ValueError('请选择已有候选')
            source_target = attempt_folder(folder, source_attempt)
            source_meta = read(source_target/'attempt.json', {})
            receipt = read(source_target/'generation.json', {})
            if not (source_target/'raw.png').is_file() or receipt.get('sha256') != digest(source_target/'raw.png'):
                raise ValueError('所选候选没有经过校验的原图')
            corrections = source_meta.get('corrections', [source_meta['correction']] if source_meta.get('correction') else [])
        if correction.strip(): corrections = corrections+[correction.strip()]
        attempt = identity(); target = attempt_folder(folder, attempt); target.mkdir(parents=True)
        structure = read(folder/'structure/structure.json')
        text = prompt(structure, job['spec']['appearance'], '\n'.join(corrections))
        roles = [{'path': 'structure/ai-reference.png', 'role': 'structure', 'sha256': digest(folder/'structure/ai-reference.png')}]
        if (folder/'style.png').exists(): roles.append({'path': 'style.png', 'role': 'style', 'sha256': digest(folder/'style.png')})
        if not (folder/'style.png').exists():
            text = text.replace('Image 2, if supplied, describes palette and painting style ONLY; never copy its geometry. ', '')
        if mode == 'edit':
            shutil.copyfile(source_target/'raw.png', target/'edit-source.png')
            roles.append({'path': 'edit-source.png', 'role': 'edit_target', 'sha256': digest(target/'edit-source.png')})
            text += f' Image {len(roles)} is the selected previous candidate to EDIT. Preserve its successful appearance; apply the cumulative corrections while obeying image 1 geometry.'
        else: text = text.replace('Correction to the previous attempt:', 'Additional requirements for this new candidate:')
        (target/'prompt.txt').write_text(text, encoding='utf-8')
        atomic(target/'attempt.json', {'id': attempt, 'parent_attempt': previous, 'correction': correction,
                                     'mode': mode, 'source_attempt': source_attempt if mode == 'edit' else None,
                                     'corrections': corrections, 'image_roles': roles,
                                     'prompt_sha256': digest(target/'prompt.txt'),
                                     'inputs_sha256': job['input_sha256'], 'parent_kit': job.get('kit_id'), 'created_at': now()})
        job.update(current_attempt=attempt, execution_mode='submit', status='queued', stage='等待生成建筑外观', error=None,
                   revision=job['revision']+1)
        job.pop('kit_id', None); job['attempts'].append(attempt)
        atomic(folder/'job.json', job)
        return job


def verify_attempt(folder, target, job):
    meta = read(target/'attempt.json', {})
    if meta.get('prompt_sha256') != digest(target/'prompt.txt') or meta.get('inputs_sha256') != job['input_sha256']:
        raise ValueError('生成尝试的提示词或输入已变化，请创建新任务')
    for role in meta.get('image_roles', []):
        path = target/role['path'] if role['role'] == 'edit_target' else folder/role['path']
        if not path.is_file() or digest(path) != role['sha256']: raise ValueError('生图输入指纹已变化')


def recovery(folder, target):
    receipt = read(target/'generation.json', {})
    if receipt.get('submission_uncertain'): return 'uncertain'
    if (target/'raw.png').exists() and receipt.get('sha256') == digest(target/'raw.png'): return 'process'
    if (target/'raw.pending.png').exists() and receipt.get('sha256') == digest(target/'raw.pending.png'): return 'process'
    if receipt.get('status') == 'failed': return 'remote_failed'
    if receipt.get('remote_id'): return 'query'
    if (target/'raw.png').exists() or receipt.get('sha256'): return 'invalid'
    return 'unsubmitted'


def store_result(target, receipt, image):
    pending = target/'raw.pending.png'; image.save(pending, format='PNG')
    receipt.update(submission_uncertain=False, status='completed', sha256=digest(pending))
    atomic(target/'generation.json', receipt)
    pending.replace(target/'raw.png')


def generate(folder, target, provider, deadline_seconds, allow_submit=False):
    receipt_path = target/'generation.json'; receipt = read(receipt_path, {})
    raw = target/'raw.png'
    pending = target/'raw.pending.png'
    if pending.exists() and receipt.get('sha256') == digest(pending): pending.replace(raw)
    if raw.exists() and receipt.get('sha256'):
        if receipt['sha256'] != digest(raw): raise ValueError('建筑原图指纹不一致')
        return
    if raw.exists() and not receipt.get('remote_id'): raise ValueError('原图缺少可信回执，不能自动提交新任务')
    if receipt.get('status') == 'failed': raise ValueError('远程任务已失败；重新生成须创建新尝试')
    if receipt.get('submission_uncertain'): raise ValueError('提交未收到任务ID，请在服务商核实，禁止自动重提')
    if receipt and receipt.get('base_url') != provider.base: raise ValueError('图片服务地址已变化，请恢复原地址再继续')
    if not receipt.get('remote_id'):
        if not allow_submit: raise ValueError('尚未提交图片服务，请明确发起生成（可能产生费用）')
        receipt.update(**receipt_identity(provider), submission_uncertain=True)
        atomic(receipt_path, receipt)
        roles = read(target/'attempt.json', {}).get('image_roles')
        references = [(target/r['path'] if r['role'] == 'edit_target' else folder/r['path']) for r in roles] if roles is not None else [folder/'structure/ai-reference.png']
        if not roles and (folder/'style.png').exists(): references.append(folder/'style.png')
        for role, path in zip(roles or [], references):
            if digest(path) != role['sha256']: raise ValueError('生图输入指纹已变化')
        try: response = provider.create((target/'prompt.txt').read_text(), references)
        except SubmissionRejected:
            receipt.update(submission_uncertain=False, status='failed'); atomic(receipt_path, receipt); raise
        if response.get('id'):
            receipt.update(remote_id=str(response['id']), submission_uncertain=False)
            atomic(receipt_path, receipt)
        elif response.get('data'):
            image = decode_art_image(response['data'][0].get('b64_json')); store_result(target, receipt, image); return
        else: raise ValueError('服务未返回任务ID，请核实服务商记录')
    deadline = time.monotonic()+deadline_seconds
    remote = quote(receipt['remote_id'], safe='')
    while True:
        response = provider.request('/images/'+remote); status = response.get('status')
        if status == 'completed':
            content = provider.request('/images/'+remote+'/content', binary=True)
            image = decode_art_image(base64.b64encode(content).decode()); store_result(target, receipt, image); return
        if status == 'failed':
            receipt['status'] = 'failed'; atomic(receipt_path, receipt)
            raise ValueError('远程任务失败；原尝试已保留，重新生成须明确创建新尝试')
        if status not in ('pending', 'queued', 'running', 'processing'): raise ValueError('远程任务状态未知，保留编号待继续查询')
        if time.monotonic() >= deadline: raise ValueError('本次等待结束，可继续查询原任务，不重新提交')
        time.sleep(3)


def process(folder, target):
    if (folder/'template-request.json').exists():
        from building_templates import process as process_template
        return process_template(folder,target)
    if (folder/'request.json').exists():
        from building_candidates import process as process_candidate
        return process_candidate(folder, target)
    transform = read(folder/'input-transform.json')
    processing = read(target/'processing.json', {})
    source = target/processing.get('source', 'raw.png')
    if processing and digest(source) != processing.get('sha256'): raise ValueError('后处理输入指纹已变化')
    with Image.open(source) as image:
        if processing:
            with Image.open(target/'raw.png') as raw:
                if image.size != raw.size: raise ValueError('修正图必须保持原图坐标和尺寸')
        if image.width != image.height: raise ValueError('生成图不是正方形，不能沿用结构坐标')
        if processing:
            sprite, method = image.convert('RGBA'), 'manual_alpha'
            if sprite.getchannel('A').getextrema() == (255, 255): raise ValueError('修正图需要透明背景')
        else: sprite, method = cutout(image)
    side = transform['square_side']; x, y = transform['offset_px']; w, h = transform['source_size']
    # One uniform resampling; no bbox fit, recentering or anisotropic deformation.
    sprite = sprite.resize((side, side), Image.Resampling.LANCZOS)
    alpha = sprite.getchannel('A'); bbox = alpha.point(lambda v: 255 if v > 16 else 0).getbbox()
    if not bbox or bbox[0] < x or bbox[1] < y or bbox[2] > x+w or bbox[3] > y+h:
        raise ValueError('生成建筑超出结构画布，不能直接裁切，请复核或生成新尝试')
    sprite = sprite.crop((x, y, x+w, y+h)); connectivity = single_object(sprite)
    sprite.save(target/'sprite.png')
    with Image.open(folder/'structure/structure.png') as ref:
        overlay = Image.new('RGBA', (w, h), '#eef0eb'); overlay.alpha_composite(sprite)
        edge = ref.getchannel('A').filter(ImageFilter.FIND_EDGES)
        tint = Image.new('RGBA', (w, h), '#00bec7'); tint.putalpha(edge); overlay.alpha_composite(tint)
        overlay.convert('RGB').save(target/'comparison.png')
    preview = Image.new('RGBA', (w*2, h), '#edf0e9')
    for i, color in enumerate(['#edf0e9', '#34404b']):
        panel = Image.new('RGBA', (w, h), color); panel.alpha_composite(sprite); preview.paste(panel, (i*w, 0))
    preview.convert('RGB').save(target/'preview.png')
    report = dict(raw_sha256=digest(target/'raw.png'), structure_sha256=digest(folder/'structure/structure.json'),
                  sprite_sha256=digest(target/'sprite.png'), background=method, connectivity=connectivity,
                  automatic=dict(decoded=True, canvas_mapping=True, not_clipped=True),
                  semantic_structure='requires_human_review', required_checks=list(CHECKS))
    report.update(algorithm=PROCESS_VERSION, evidence_sha256=evidence_hashes(folder, target))
    atomic(target/'checks.json', report)


def execute(root, task, deadline_seconds=1200, provider_factory=Provider):
    with task_lock(root):
        folder, job = require_job(root, task)
        if job['status'] not in ('queued', 'failed'): raise ValueError('仅能执行新尝试或继续失败任务')
        target = attempt_folder(folder, job['current_attempt'])
        try:
            verify_inputs(folder, job); verify_attempt(folder, target, job)
            allow_submit = job['status'] == 'queued' and job.get('execution_mode', 'submit') == 'submit'
            job.update(status='running', execution_mode='resume', stage='生成建筑外观', error=None); atomic(folder/'job.json', job)
            generate(folder, target, provider_factory(target/'http.jsonl') if recovery(folder, target) != 'process' else None, deadline_seconds, allow_submit)
            job['stage'] = '处理透明背景与制作复核图'; atomic(folder/'job.json', job)
            process(folder, target)
            job.update(status='waiting_review', stage='线框候选已就绪，请检查后保存模板' if job.get('purpose') == 'template' else ('候选已就绪，可继续生成或选用' if job.get('workflow') == 'line_drawing' else '等待人工复核结构与外观'))
        except Exception as error: job.update(status='failed', stage='建筑制作需处理', error=str(error))
        if job.get('workflow') == 'line_drawing':
            atomic(target/'result.json', dict(status=job['status'], error=job.get('error')))
        job['revision'] += 1; atomic(folder/'job.json', job)
        return job


def evidence_hashes(folder, target):
    paths = {p: target/p for p in ['raw.png', 'sprite.png', 'preview.png', 'comparison.png']}
    paths.update({p: folder/p for p in ['structure/structure.json', 'structure/reference.png', 'structure/inspection.png', 'input-transform.json']})
    if (target/'processing.json').exists():
        paths['processing.json'] = target/'processing.json'
        processing = read(target/'processing.json'); paths[processing['source']] = target/processing['source']
    return {key: digest(path) for key, path in paths.items()}


def verify_evidence(folder, target):
    if (folder/'template-request.json').exists():
        from building_templates import verify_candidate
        return verify_candidate(folder,target)
    if (folder/'request.json').exists():
        from building_candidates import verify_evidence as verify_candidate
        return verify_candidate(folder, target)
    report = read(target/'checks.json', {})
    if report.get('algorithm') != PROCESS_VERSION or report.get('evidence_sha256') != evidence_hashes(folder, target):
        raise ValueError('检查图或处理版本已变化，请重新制作复核图并重新复核')
    return report


def archive_review(target):
    if (target/'review.json').exists():
        history = target/'review-history'; history.mkdir(exist_ok=True)
        shutil.copyfile(target/'review.json', history/(identity()+'.json'))


def review(root, task, revision, checks, note='', action='decide'):
    with task_lock(root):
        folder, job = require_job(root, task); check_revision(job, revision)
        if job.get('workflow') == 'line_drawing': raise ValueError('框线图流程请选择候选后标定保存，无需结构复核')
        if job['status'] not in ('waiting_review', 'approved', 'rejected'): raise ValueError('当前没有待复核候选')
        verify_inputs(folder, job); target = attempt_folder(folder, job['current_attempt'])
        verify_attempt(folder, target, job)
        report = verify_evidence(folder, target)
        if action not in ('decide', 'draft', 'reopen'): raise ValueError('复核操作无效')
        if not isinstance(checks, dict) or set(checks) != set(CHECKS) or any(type(v) is not bool for v in checks.values()):
            raise ValueError('请明确检查全部结构、外观和透明边缘项目')
        if not isinstance(note, str) or len(note) > 2000: raise ValueError('复核说明最多2000字')
        accepted = all(checks.values()) and action == 'decide'
        archive_review(target)
        atomic(target/'review.json', {'checks': checks, 'note': note, 'accepted': accepted,
                                      'artifact_sha256': report, 'action': action, 'reviewed_at': now()})
        job.update(status=('waiting_review' if action != 'decide' else ('approved' if accepted else 'rejected')), stage='可导出候选包' if accepted else '候选待继续复核',
                   revision=job['revision']+1)
        atomic(folder/'job.json', job); return job


def adjust(root, data):
    with task_lock(root):
        folder, job = require_job(root, data.get('task')); check_revision(job, data.get('revision')); verify_inputs(folder, job)
        action = data.get('action')
        if job.get('workflow') == 'line_drawing' and action != 'reconcile': raise ValueError('此流程仅支持选择候选、标定保存或核实原任务')
        if job['status'] in ('queued', 'running'): raise ValueError('生成进行中，请等待完成')
        if action == 'appearance':
            if job['status'] != 'draft': raise ValueError('已有尝试的外观方案不可改写，请复制结构创建新版本')
            appearance = data.get('appearance', '')
            if not isinstance(appearance, str) or not 1 <= len(appearance.strip()) <= 2000: raise ValueError('外观描述需为1–2000字')
            job['spec']['appearance'] = appearance.strip()
            if data.get('style_reference'): decode_image(data['style_reference']).save(folder/'style.png')
            if data.get('remove_style') and (folder/'style.png').exists(): (folder/'style.png').unlink()
            job['input_sha256'] = input_hashes(folder)
        elif action == 'reconcile':
            if job['status'] != 'failed' or not job.get('current_attempt'): raise ValueError('仅可核实中断的提交')
            target = attempt_folder(folder, job['current_attempt'])
            receipt = read(target/'generation.json', {})
            if not receipt.get('submission_uncertain'): raise ValueError('当前提交不属于结果不明')
            remote = data.get('remote_id', '')
            if not isinstance(remote, str) or not 1 <= len(remote.strip()) <= 200: raise ValueError('请填写服务商核实的任务ID')
            history = target/'generation-history'; history.mkdir(exist_ok=True)
            atomic(history/(identity()+'.json'), receipt)
            receipt.update(remote_id=remote.strip(), submission_uncertain=False, reconciled_at=now())
            atomic(target/'generation.json', receipt)
            job.update(stage='已补录远程编号，可继续查询原任务', error=None, execution_mode='resume')
        elif action in ('adopt', 'recheck', 'repair'):
            attempt = data.get('attempt', job['current_attempt'])
            if attempt not in job['attempts']: raise ValueError('候选不存在')
            target = attempt_folder(folder, attempt)
            if job['current_attempt'] and recovery(folder, attempt_folder(folder, job['current_attempt'])) in ('query', 'uncertain'):
                raise ValueError('当前远程尝试尚未结束，不能切换候选')
            verify_attempt(folder, target, job)
            receipt = read(target/'generation.json', {})
            if not (target/'raw.png').exists() or receipt.get('sha256') != digest(target/'raw.png'): raise ValueError('原图缺少可信回执，请先恢复原任务')
            if action == 'repair':
                image = decode_art_image(data.get('image'), png_only=True)
                with Image.open(target/'raw.png') as raw:
                    if image.size != raw.size: raise ValueError('修正图必须与原始生成图尺寸完全一致')
                if image.mode != 'RGBA' or image.getchannel('A').getextrema() == (255, 255): raise ValueError('请导入带透明Alpha的PNG修正图')
            # Published files stay immutable; further processing gets its own local candidate.
            if any(read(p, {}).get('attempt_id') == attempt for p in (Path(root)/'building-kits').glob('*/manifest.json')):
                original = target; attempt = identity(); target = attempt_folder(folder, attempt)
                shutil.copytree(original, target)
                meta = read(target/'attempt.json'); meta.update(id=attempt, parent_attempt=original.name, local_copy=True)
                atomic(target/'attempt.json', meta); job['attempts'].append(attempt)
            archive_review(target)
            if (target/'review.json').exists(): (target/'review.json').unlink()
            if action == 'repair':
                repairs = target/'repairs'; repairs.mkdir(exist_ok=True)
                source = repairs/(identity()+'.png'); image.save(source)
                atomic(target/'processing.json', dict(source=str(source.relative_to(target)), sha256=digest(source), created_at=now()))
            try:
                process(folder, target)
                job.update(status='waiting_review', stage='检查图已更新，请重新人工复核', error=None)
            except Exception as error:
                job.update(status='failed', stage='后处理需修正', error=str(error))
            job.update(current_attempt=attempt); job.pop('kit_id', None)
        else: raise ValueError('建筑调整操作无效')
        job['revision'] += 1; atomic(folder/'job.json', job); return job


def _load_package(root, kit):
    assets = AssetRepository(root); prefix = 'building-kits/'+name(kit)
    folder = assets.scoped(prefix, 'building-kits'); manifest = read(folder/'manifest.json', {})
    if manifest.get('schema') not in (SCHEMA, 'studio.building-kit/0.2') or manifest.get('id') != kit: raise ValueError('建筑包清单无效')
    expected = manifest.get('files_sha256', {})
    required = {'sprite.png','preview.png','integration.json','INTEGRATION.md'}
    required.update({'calibration.json','selection.json','inputs/outline.png'} if manifest['schema'] == 'studio.building-kit/0.2' else {'structure.json','review.json'})
    if not required.issubset(expected): raise ValueError('建筑包缺少交付记录')
    for relative, sha in expected.items():
        path = assets.scoped(prefix+'/'+relative, prefix)
        if not path.is_file() or digest(path) != sha: raise ValueError('建筑包文件缺失或指纹不符：'+relative)
    with zipfile.ZipFile(folder/'kit.zip') as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or set(names) != set(expected)|{'manifest.json'}: raise ValueError('建筑ZIP文件集合无效')
        for relative in names:
            path = assets.scoped(prefix+'/'+relative, prefix)
            if archive.read(relative) != path.read_bytes(): raise ValueError('建筑ZIP与磁盘文件不一致')
    return manifest


def load_package(root, kit):
    try:
        return _load_package(root, kit)
    except (OSError, KeyError, TypeError, AttributeError, zipfile.BadZipFile, RuntimeError) as error:
        raise ValueError('建筑包缺失或损坏：'+str(error)) from None


def publish(root, task, revision):
    with task_lock(root):
        folder, job = require_job(root, task); check_revision(job, revision); verify_inputs(folder, job)
        if job.get('workflow') == 'line_drawing': raise ValueError('请使用标定保存入口保存选定候选')
        if job['status'] == 'complete': return load_package(root, job['kit_id'])
        if job['status'] != 'approved': raise ValueError('候选未通过人工复核，不能发布')
        target = attempt_folder(folder, job['current_attempt']); verify_attempt(folder, target, job)
        approval = read(target/'review.json', {})
        if not approval.get('accepted'): raise ValueError('候选缺少通过记录')
        report = verify_evidence(folder, target)
        if approval.get('artifact_sha256') != report: raise ValueError('已复核文件发生变化，请重新检查')
        kit = job['id']+'-'+job['current_attempt'].split('-')[-1]
        final = AssetRepository(root).scoped('building-kits/'+kit, 'building-kits')
        if final.exists(): manifest = load_package(root, kit)
        else:
            staging = folder/('publish-'+kit)
            if staging.exists(): shutil.rmtree(staging)
            (staging/'inputs').mkdir(parents=True)
            for source, dest in [(target/'sprite.png','sprite.png'), (target/'preview.png','preview.png'),
                (folder/'structure/structure.json','structure.json'), (target/'review.json','review.json'),
                (target/'checks.json','checks.json'), (target/'attempt.json','attempt.json'), (target/'prompt.txt','prompt.txt'),
                (target/'generation.json','generation.json'), (target/'raw.png','inputs/raw.png'),
                (folder/'structure/ai-reference.png','inputs/structure.png'),
                (folder/'input-transform.json','input-transform.json')]: shutil.copyfile(source, staging/dest)
            shutil.copytree(folder/'structure',staging/'structure')
            for extra in ['processing.json', 'edit-source.png']:
                if (target/extra).exists(): shutil.copyfile(target/extra, staging/extra)
            if (target/'repairs').exists(): shutil.copytree(target/'repairs', staging/'repairs')
            if (target/'review-history').exists(): shutil.copytree(target/'review-history', staging/'review-history')
            if (target/'generation-history').exists(): shutil.copytree(target/'generation-history', staging/'generation-history')
            if (folder/'style.png').exists(): shutil.copyfile(folder/'style.png', staging/'inputs/style.png')
            structure = read(folder/'structure/structure.json'); anchor = structure['ground_anchor_px']
            integration = dict(anchor_px=anchor, sprite_offset_px=[-v for v in anchor],
                footprint_polygon=[[p[0]-anchor[0],p[1]-anchor[1]] for p in structure['footprint_polygon_px']],
                units='pixels_relative_to_ground_anchor_x_right_y_down',
                entrance=structure['entrance'], entrance_coordinate_space='image_pixels_and_world_cells_as_named',
                collision=dict(enabled_by_default=False, proposal='structural_footprint_solid_no_door_hole'),
                visual_layers='single_sprite', occlusion='not_tested', game_integration='not_tested')
            atomic(staging/'integration.json', integration)
            (staging/'INTEGRATION.md').write_text('# Building candidate\n\nUse sprite_offset_px with the ground anchor; retain the recorded cell pixel scale.\n'
                'Collision is OFF by default. Footprint is a suggestion, not a wall mesh.\n'
                'Entrance is a scene transition marker, not an opening in collision.\n'
                'Single sprite occlusion and character scale require game testing.\n'
                'Human appearance/structure review does not imply engine acceptance.\n', encoding='utf-8')
            manifest = dict(schema=SCHEMA,id=kit,title=job['spec']['title'],created_at=now(),
                asset_family='building', view='isometric_2_1', structure_files_base='structure', structure_sha256=job['structure_sha256'],
                task_id=task, attempt_id=job['current_attempt'], parent_attempt_id=read(target/'attempt.json').get('parent_attempt'), parent_kit=read(target/'attempt.json').get('parent_kit'), production_ready=False,
                human_review='passed', game_integration='not_tested',
                files_sha256={str(p.relative_to(staging)):digest(p) for p in sorted(staging.rglob('*')) if p.is_file()})
            atomic(staging/'manifest.json',manifest)
            with zipfile.ZipFile(staging/'kit.zip','w',zipfile.ZIP_DEFLATED) as archive:
                for path in sorted(staging.rglob('*')):
                    if path.is_file() and path.name!='kit.zip': archive.write(path,str(path.relative_to(staging)))
            final.parent.mkdir(parents=True,exist_ok=True); staging.rename(final)
            load_package(root,kit)
        job.update(status='complete',stage='建筑候选包已完成，游戏接入待验证',kit_id=kit,revision=job['revision']+1)
        atomic(folder/'job.json',job); return manifest


def catalog(root):
    jobs = [value for p in (Path(root)/'.local/buildings/jobs').glob('*/job.json') if (value:=read(p))]
    for job in jobs:
        folder = folder_for(root, job['id'])
        job['template_source']=read(folder/'template-source.json')
        job['structure_spec'] = read(folder/'structure/structure.json', {}).get('spec')
        job['has_style'] = (folder/'style.png').exists()
        job['has_outline'] = (folder/'outline.png').exists()
        job['candidates'] = []
        for attempt in job['attempts']:
            target = attempt_folder(folder, attempt)
            candidate = dict(id=attempt, has_raw=(target/'raw.png').exists(), review=read(target/'review.json'))
            if job.get('workflow') == 'line_drawing':
                result = read(target/'result.json', {})
                candidate.update(error=result.get('error'), ready=False)
                try:
                    report = verify_evidence(folder, target)
                    candidate.update(ready=True, canvas_px=report['canvas_px'], evidence_key=digest(target/'checks.json'))
                except (OSError, ValueError, KeyError): pass
            job['candidates'].append(candidate)
        if job.get('current_attempt'):
            target = attempt_folder(folder, job['current_attempt'])
            job['recovery'] = recovery(folder, target)
            job['review'] = read(target/'review.json')
            job['evidence_key'] = digest(target/'checks.json') if (target/'checks.json').exists() else None
            try: verify_evidence(folder, target); job['evidence_valid'] = True
            except (ValueError, OSError, KeyError): job['evidence_valid'] = False
    kits = []
    for p in (Path(root)/'building-kits').glob('*/manifest.json'):
        try:
            kit = load_package(root,p.parent.name); kit['integrity']={'passed':True}
        except (ValueError,OSError,zipfile.BadZipFile) as error:
            kit=read(p,{})
            if not kit: continue
            kit['integrity']={'passed':False,'error':str(error)}
        kits.append(kit)
    return {'jobs':sorted(jobs,key=lambda j:j['created_at'],reverse=True),
            'kits':sorted(kits,key=lambda k:k.get('created_at',''),reverse=True)}


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1])
    commands=parser.add_subparsers(dest='command',required=True)
    create=commands.add_parser('prepare');create.add_argument('--spec',type=Path,required=True)
    run=commands.add_parser('run');run.add_argument('task');run.add_argument('--revision',type=int,required=True);run.add_argument('--correction',default='')
    resume=commands.add_parser('resume');resume.add_argument('task')
    check=commands.add_parser('review');check.add_argument('task');check.add_argument('--revision',type=int,required=True);check.add_argument('--checks',type=Path,required=True)
    export=commands.add_parser('publish');export.add_argument('task');export.add_argument('--revision',type=int,required=True)
    args=parser.parse_args();root=args.root
    if args.command=='prepare':result=prepare(root,json.loads(args.spec.read_text()))
    elif args.command=='run':
        new_attempt(root,args.task,args.revision,args.correction);result=execute(root,args.task)
    elif args.command=='resume':result=execute(root,args.task)
    elif args.command=='review':
        data=json.loads(args.checks.read_text());result=review(root,args.task,args.revision,data['checks'],data.get('note',''))
    else:result=publish(root,args.task,args.revision)
    print(json.dumps(result,ensure_ascii=False,indent=2))
