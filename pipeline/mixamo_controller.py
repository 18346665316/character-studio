"""Mixamo human-assisted rigging and verified downloads, with one profile per character."""
import argparse
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import sys
import time
import uuid

from playwright.sync_api import sync_playwright
from progress import update as progress_update
from asset_inspector import inspect_download, source_geometry
from mixamo_state import (character_name, check_mesh_identity, check_motion, file_hash,
                          read_state, require_ready, state_path, write_state, MeshIdentityError, check_bound_skeleton)

BASE_DIR = Path(__file__).resolve().parent.parent
SESSION_FILE = BASE_DIR / '.local/auth/mixamo_session.json'


@contextmanager
def character_lock(character):
    path = state_path(character).parent / 'browser.lock'
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('该角色已有 Mixamo 窗口或任务正在运行，请先完成或关闭它')
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


@contextmanager
def cloud_lock():
    # Different character profiles can still share the same Adobe cloud character.
    path=BASE_DIR/'.local/mixamo/cloud.lock'
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w') as lock:
        try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError: raise ValueError('已有 Mixamo 云端任务，请等待完成后再切换人物')
        try: yield
        finally: fcntl.flock(lock,fcntl.LOCK_UN)


def browser_options(playwright):
    override = os.environ.get('STUDIO_CHROMIUM_BIN')
    if override:
        if not Path(override).is_file():
            raise ValueError('STUDIO_CHROMIUM_BIN 指定的浏览器不存在')
        return {'executable_path': override}
    if Path(playwright.chromium.executable_path).is_file():
        return {}
    # A Python environment upgrade can change the bundled browser revision.
    # Reuse an already installed full Chromium rather than downloading silently.
    installed = [p for p in (Path.home() / 'Library/Caches/ms-playwright').glob(
        'chromium-*/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing') if p.is_file()]
    if installed:
        return {'executable_path': str(max(installed, key=lambda p:p.stat().st_mtime))}
    raise ValueError('缺少 Chromium；安装 Playwright 浏览器或设置 STUDIO_CHROMIUM_BIN')


def open_profile(playwright, character, visible):
    profile = state_path(character).parent / 'browser'
    first_use = not (profile / 'Default').exists()
    context = playwright.chromium.launch_persistent_context(
        str(profile), headless=not visible, accept_downloads=True,
        viewport={'width': 1440, 'height': 1000}, **browser_options(playwright))
    if first_use and SESSION_FILE.is_file():
        saved = json.loads(SESSION_FILE.read_text())
        context.add_cookies(saved.get('cookies', []))
        # Seed this new role profile once. Its later storage belongs to this role.
        origins = {origin['origin']: origin.get('localStorage', []) for origin in saved.get('origins', [])}
        context.add_init_script('''(() => {
            const entries = %s[location.origin] || [];
            for (const item of entries) if (localStorage.getItem(item.name) === null)
                localStorage.setItem(item.name, item.value);
        })();''' % json.dumps(origins))
    page = context.pages[0] if context.pages else context.new_page()
    return context, page


def action_login():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, **browser_options(p))
        context = browser.new_context()
        page = context.new_page()
        page.goto('https://www.mixamo.com/#/', wait_until='domcontentloaded')
        print('请在浏览器中登录 Adobe；登录完成后保存本地会话。', flush=True)
        page.get_by_role('button', name='Upload Character', exact=False).wait_for(timeout=360000)
        SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
        context.storage_state(path=str(SESSION_FILE))
        SESSION_FILE.chmod(0o600)
        browser.close()


def modal_open(page):
    return page.locator('.modal-dialog:visible, [role="dialog"]:visible').count() > 0


def save_download(page, target, *, bind_pose=False):
    page.get_by_role('button', name='Download', exact=True).first.click()
    modal = page.locator('.modal-dialog:visible, [role="dialog"]:visible').first
    modal.wait_for(timeout=20000)
    # Ensure files contain this character's mesh, not animation-only data.
    skin_selected = False
    pose_selected = False
    format_selected = False
    for select in modal.locator('select').all():
        options = select.locator('option').all_text_contents()
        for label in options:
            if label.strip().casefold() == 'with skin':
                select.select_option(label=label)
                skin_selected = True
            elif label.strip().casefold().startswith('fbx binary'):
                select.select_option(label=label)
                format_selected = True
            elif bind_pose and label.strip().casefold() == 't-pose':
                select.select_option(label=label)
                pose_selected = True
    if not format_selected:
        raise ValueError('下载窗口没有可验证的 FBX Binary 选项')
    # Character-only exports expose Pose instead of Skin; inspect actual skin/bones afterward.
    if not skin_selected and not (bind_pose and pose_selected):
        raise ValueError('下载窗口没有可验证的 With Skin 选项，停止下载')
    with page.expect_download(timeout=180000) as event:
        modal.get_by_role('button', name='Download', exact=True).click()
    downloaded = event.value
    if downloaded.failure():
        raise ValueError('Mixamo 下载失败: ' + downloaded.failure())
    target.parent.mkdir(parents=True, exist_ok=True)
    downloaded.save_as(str(target))
    if not target.is_file() or target.stat().st_size == 0:
        raise ValueError('Mixamo 返回空文件')
    # Wait for the download dialog to close before the next action.
    if modal.count() and modal.is_visible():
        close = modal.locator('button.close, button[aria-label="Close"]')
        if close.count():
            close.first.click()
        else:
            page.keyboard.press('Escape')
    return target


PANEL = '''({character, status, enabled}) => {
    let panel = document.getElementById('studio-rig-review');
    if (!panel) {
        panel = document.createElement('div');
        panel.id = 'studio-rig-review';
        panel.style.cssText = 'position:fixed;left:16px;bottom:16px;z-index:2147483647;background:#172331;color:white;padding:16px;border-radius:10px;width:390px;font:14px sans-serif;box-shadow:0 2px 16px #0008';
        const title = document.createElement('strong'); title.id='studio-rig-title';
        const text = document.createElement('p'); text.id='studio-rig-text';
        const button = document.createElement('button'); button.id='studio-rig-confirm';
        button.textContent='确认当前角色及绑定变形正确，继续';
        button.style.cssText='padding:10px;cursor:pointer;color:#111';
        button.onclick=()=>{button.disabled=true;window.studioApproveRig();};
        panel.append(title,text,button);document.body.appendChild(panel);
    }
    panel.querySelector('#studio-rig-title').textContent='Studio · '+character;
    panel.querySelector('#studio-rig-text').textContent=status;
    panel.querySelector('button').disabled=!enabled;
}'''


def action_upload(model, character):
    character_name(character)
    source = Path(model).resolve()
    if not source.is_file():
        raise ValueError(f'找不到模型: {source}')
    source_sha = file_hash(source)
    with cloud_lock(), character_lock(character), sync_playwright() as p:
        fields = {'source_model': str(source), 'source_sha256': source_sha}
        write_state(character, 'opening_browser', **fields)
        progress_update(character, 'rig', '正在打开 Mixamo 并上传指定角色')
        context = None
        try:
            reference = source_geometry(source)
            context, page = open_profile(p, character, visible=True)
            approved = {'value': False}
            page.expose_function('studioApproveRig', lambda: approved.update(value=True))
            page.goto('https://www.mixamo.com/#/', wait_until='domcontentloaded')
            print('请在可见 Mixamo 窗口确认朝向、放置关节点、完成绑定，并检查角色与变形。', flush=True)
            print('完成网页向导后，点击左下角 Studio 的确认按钮；关闭窗口将取消本次绑定。', flush=True)
            upload = page.get_by_role('button', name='Upload Character', exact=False)
            upload.wait_for(timeout=360000)  # User can renew an expired login here.
            upload.click()
            page.locator('input[type="file"]').set_input_files(str(source))
            write_state(character, 'waiting_for_markers', **fields)
            started = time.monotonic()
            last_status = None
            saw_wizard = False
            # No Next buttons are clicked by Studio. All wizard/marker steps are human-owned.
            while not approved['value']:
                if page.is_closed():
                    raise ValueError('浏览器已关闭，尚未完成绑定验收')
                if time.monotonic() - started > 1800:
                    raise ValueError('人工绑定等待超过 30 分钟，请重新运行 rig')
                text = page.locator('body').inner_text()
                dialog = modal_open(page)
                saw_wizard = saw_wizard or dialog
                ready_to_review = saw_wizard and not dialog and page.get_by_role('button', name='Download', exact=True).count() > 0
                loading = page.locator('.loading:visible, .loading-spinner:visible').count() > 0 or any(line.strip().upper().startswith('LOADING') for line in text.splitlines())
                ready_to_review = ready_to_review and not loading
                processing = dialog and any(word in text.lower() for word in ('auto-rigging', 'processing', 'calculating'))
                status = 'waiting_for_review' if ready_to_review else ('processing_rig' if processing else 'waiting_for_markers')
                if status != last_status:
                    write_state(character, status, **fields)
                    last_status = status
                    descriptions = {'waiting_for_markers': '请在 Mixamo 中放置关节点并完成向导', 'processing_rig': 'Mixamo 正在处理绑定，请等待网页预览就绪', 'waiting_for_review': '预览已就绪，请检查角色变形后点击 Studio 确认'}
                    progress_update(character, 'rig', descriptions[status], status='running' if status == 'processing_rig' else 'waiting')
                hint = ('请核对当前模型确实是此角色，并在动作预览中检查四肢变形；确认后点击下方按钮。'
                        if ready_to_review else '请在 Mixamo 向导中确认朝向、手动放置关节点并提交，等待自动蒙皮完成。')
                if 'processing' in text.lower() and dialog:
                    hint = 'Mixamo 正在处理。等待完成后检查角色和变形，再结束网页向导。'
                page.evaluate(PANEL, {'character': character, 'status': hint, 'enabled': ready_to_review})
                page.wait_for_timeout(500)
            if modal_open(page):
                raise ValueError('Mixamo 绑定向导尚未结束，不能登记成功')
            progress_update(character, 'rig', '已收到确认，正在下载绑定模型并验证贴图、骨骼与网格')
            fields['human_reviewed'] = True
            write_state(character, 'verifying_bound_model', **fields)
            attempt = uuid.uuid4().hex[:12]
            directory = BASE_DIR / 'workspaces' / character / 'rig' / attempt
            directory.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(directory / 'review.png'))
            bound = save_download(page, directory / 'bound.fbx', bind_pose=True)
            info = inspect_download(bound)
            check_mesh_identity(info, reference)
            # A new reference must remain byte-identical throughout the handoff.
            if file_hash(source) != source_sha:
                raise ValueError('等待期间源模型已变更，请重新绑定')
            receipt = {'character': character, 'source_sha256': source_sha,
                       'bound_sha256': file_hash(bound), 'inspection': info,
                       'human_reviewed': True}
            (directory / 'rig.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n')
            write_state(character, 'ready', **fields, bound_model=str(bound),
                        bound_sha256=file_hash(bound), geometry=info)
            progress_update(character, 'rig', '人工绑定、贴图和网格检查通过')
            print(f'人工验收及网格检查通过。绑定模型已保存: {bound}', flush=True)
        except BaseException as exc:
            progress_update(character, 'rig', str(exc), status='failed')
            write_state(character, 'interrupted' if isinstance(exc, KeyboardInterrupt) else 'failed',
                        **fields, error=str(exc))
            raise
        finally:
            if context:
                context.close()


def select_animation(page, anim_name):
    search = page.get_by_placeholder('Search', exact=True)
    search.wait_for(timeout=30000)
    search.fill(anim_name)
    search.press('Enter')
    card = page.locator('.product-animation').filter(has=page.get_by_text(anim_name, exact=True)).first
    # The title sits below the search overlay. Escape can restore the old query.
    card.wait_for(timeout=60000)
    card.get_by_text(anim_name, exact=True).click()


def restore_bound_character(page, character, state):
    """Reuse reviewed skinning only. Never place markers or approve new auto-rigging."""
    current=require_ready(character,allow_cloud_recovery=True)
    if current['bound_sha256']!=state['bound_sha256']:
        raise ValueError('本地绑定版本已变化，请新建下载任务')
    progress_update(character,'download','云端人物不匹配，正在上传本地已验收绑定模型自动恢复')
    upload=page.get_by_role('button',name='Upload Character',exact=False)
    upload.wait_for(timeout=30000)
    upload.click()
    page.locator('input[type="file"]').set_input_files(state['bound_model'])
    started=time.monotonic()
    stable=0
    clicks=0
    while time.monotonic()-started<180:
        if page.is_closed(): raise ValueError('恢复人物时浏览器已关闭')
        modal=page.locator('.modal-dialog:visible, [role="dialog"]:visible').first
        if modal.count() and modal.is_visible():
            stable=0
            text=modal.inner_text().lower()
            if any(word in text for word in ('place markers','place the markers','chin','groin','auto-rigging','auto rigging')):
                raise ValueError('Mixamo 要求重新摆点或绑定；自动恢复已停止，请到人工绑定检查')
            if any(word in text for word in ('upload failed','unable to','error occurred','sorry')):
                raise ValueError('Mixamo 拒绝已绑定模型，请到人工绑定检查')
            # Only advance the review/replace confirmation for an already-skinned model.
            for label in ('Use This Character','Use this character','Confirm','Next'):
                button=modal.get_by_role('button',name=label,exact=True)
                if button.count() and button.first.is_visible() and button.first.is_enabled():
                    if label=='Next' and not any(word in text for word in ('review','uploaded successfully','ready','change character','replace')):
                        continue
                    if clicks>=4: raise ValueError('恢复人物的网页确认未完成，请到人工绑定检查')
                    button.first.click();clicks+=1
                    break
        else:
            loading=page.locator('.loading:visible, .loading-spinner:visible').count()>0
            download=page.get_by_role('button',name='Download',exact=True)
            stable=stable+1 if not loading and download.count() and download.first.is_visible() else 0
            if stable>=6:
                if file_hash(Path(state['bound_model']))!=state['bound_sha256']:
                    raise ValueError('恢复期间本地绑定模型已变化')
                progress_update(character,'download','已上传绑定模型，正在重新选择动作并验证人物身份')
                return
        page.wait_for_timeout(500)
    raise ValueError('自动恢复人物超时；请检查登录状态或到人工绑定恢复')


def request_animation(page, anim_name, pending):
    select_animation(page,anim_name)
    page.wait_for_timeout(8000)
    in_place=page.get_by_label('In Place',exact=True)
    if in_place.count() and in_place.first.is_visible():
        in_place.first.check();page.wait_for_timeout(2000)
    save_download(page,pending)
    return inspect_download(pending)


def action_download(anim_name, output_fbx, character):
    character_name(character)
    output = Path(output_fbx).resolve()
    base = BASE_DIR / 'workspaces' / character / 'animations'
    try:
        parts = output.relative_to(base).parts
    except ValueError:
        raise ValueError('动作必须位于指定角色的 animations/<批次>/<动作>.fbx')
    if len(parts) != 2 or output.suffix.lower() != '.fbx' or output.exists():
        raise ValueError('非法动作路径或目标已存在，拒绝覆盖')
    with cloud_lock(), character_lock(character), sync_playwright() as p:
        state = require_ready(character,allow_cloud_recovery=True)
        context, page = open_profile(p, character, visible=False)
        pending = state_path(character).parent / ('download-' + uuid.uuid4().hex[:12] + '.fbx')
        marker=output.parent/'.mixamo-recovery.json'
        recovery_started=False
        try:
            page.goto('https://www.mixamo.com/#/?page=1&type=Motion%2CMotionPack', wait_until='domcontentloaded')
            for attempt in range(2):
                progress_update(character,'download',f'{anim_name}：正在下载并检查人物、贴图、骨骼和动态轨道',action=anim_name)
                info=request_animation(page,anim_name,pending)
                try:
                    check_mesh_identity(info,state['geometry'])
                    check_bound_skeleton(info,state['geometry'])
                except MeshIdentityError as mismatch:
                    if attempt or marker.exists():
                        raise MeshIdentityError(str(mismatch)+'；本任务已尝试自动恢复一次，请到人工绑定恢复并确认本角色，再新建下载任务') from mismatch
                    output.parent.mkdir(parents=True,exist_ok=True)
                    marker.write_text(json.dumps({'character':character,'bound_sha256':state['bound_sha256'],'reason':str(mismatch)},ensure_ascii=False,indent=2))
                    recovery_started=True
                    print('人物身份校验失败，尝试一次自动恢复：'+str(mismatch),flush=True)
                    # Keep the rejected file local for diagnostics; never publish it.
                    pending.rename(pending.with_name(pending.stem+'-rejected.fbx'))
                    restore_bound_character(page,character,state)
                    continue
                check_motion(info)
                current=require_ready(character,allow_cloud_recovery=True)
                if current['bound_sha256']!=state['bound_sha256']:
                    raise ValueError('下载期间本地绑定版本已变化')
                output.parent.mkdir(parents=True,exist_ok=True)
                pending.rename(output)
                output.with_suffix('.inspection.json').write_text(json.dumps(info,indent=2)+'\n')
                fields={k:v for k,v in state.items() if k not in ('character','status','error','cloud_recovery')}
                write_state(character,'ready',**fields)
                progress_update(character,'download',f'{anim_name}：人物身份、贴图、骨骼与动态轨道校验通过',action=anim_name)
                print(f'角色网格和动态轨道检查通过: {output}',flush=True)
                return
        except Exception as exc:
            if isinstance(exc,MeshIdentityError) or recovery_started:
                fields={k:v for k,v in state.items() if k not in ('character','status','error','cloud_recovery')}
                write_state(character,'needs_review',**fields,error=str(exc),cloud_recovery=False)
            raise
        finally:
            context.close()


def main():
    parser = argparse.ArgumentParser(description='Mixamo 人工辅助绑定与已验收角色复用')
    sub = parser.add_subparsers(dest='cmd', required=True)
    sub.add_parser('login')
    up = sub.add_parser('upload')
    up.add_argument('file')
    up.add_argument('--character', required=True, type=character_name)
    down = sub.add_parser('download')
    down.add_argument('animation')
    down.add_argument('output')
    down.add_argument('--character', required=True, type=character_name)
    args = parser.parse_args()
    try:
        if args.cmd == 'login':
            action_login()
        elif args.cmd == 'upload':
            action_upload(args.file, args.character)
        else:
            action_download(args.animation, args.output, args.character)
        return 0
    except KeyboardInterrupt:
        print('任务已取消；未登记为成功。', file=sys.stderr)
        return 130
    except Exception as exc:
        print(f'Mixamo 任务失败: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
