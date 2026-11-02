"""HTTP task boundaries and browser production flow, with fake image generation."""
import base64
from http.server import ThreadingHTTPServer
from io import BytesIO
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from panel import Panel,handler
from asset_repository import read,atomic
from building_pipeline import prepare,folder_for,new_attempt,execute,CHECKS
try:
    from playwright.sync_api import sync_playwright, expect, Error as BrowserError
except ImportError:
    sync_playwright=None


class BuildingHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.panel=Panel(self.root)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),handler(self.panel))
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.addCleanup(self.server.server_close);self.addCleanup(self.server.shutdown)
        self.base='http://127.0.0.1:'+str(self.server.server_port)

    def post(self,path,data,token=True):
        headers={'Content-Type':'application/json'}
        if token:headers['X-Studio-Token']=self.panel.token
        with urlopen(Request(self.base+path,json.dumps(data).encode(),headers=headers)) as response:
            return json.load(response)

    def fake_generation(self,data):
        job=new_attempt(self.root,data['task'],data['revision'],data.get('correction',''))
        folder=folder_for(self.root,job['id'])
        if job.get('workflow') == 'line_drawing':
            from pipeline.tests.test_building_candidates import drawings,encoded
            _,image=drawings()
            provider=Mock();provider.base='https://example.invalid/v1'
            provider.create.return_value={'data':[{'b64_json':encoded(image)}]}
            return execute(self.root,job['id'],provider_factory=lambda _:provider)
        transform=read(folder/'input-transform.json')
        with Image.open(folder/'structure/structure.png') as sprite:
            side=transform['square_side'];image=Image.new('RGBA',(side,side),'#ff00ff')
            image.alpha_composite(sprite,tuple(transform['offset_px']))
            image=image.convert('RGB').resize((1024,1024),Image.Resampling.LANCZOS)
        stream=BytesIO();image.save(stream,format='PNG')
        provider=Mock();provider.base='https://example.invalid/v1'
        provider.create.return_value={'data':[{'b64_json':base64.b64encode(stream.getvalue()).decode()}]}
        return execute(self.root,job['id'],provider_factory=lambda _:provider)

    def test_auth_paths_and_no_paid_creation_on_prepare(self):
        data={'title':'测试','appearance':'木墙红瓦','structure':{}}
        with self.assertRaises(HTTPError) as e:self.post('/api/buildings/prepare',data,False)
        self.assertEqual(e.exception.code,403)
        with patch('terrain_images.Provider.create',side_effect=AssertionError('Unexpected charge')):
            job=self.post('/api/buildings/prepare',data)
        with urlopen(self.base+'/api/buildings/file?task='+job['id']+'&kind=reference') as response:
            self.assertEqual(response.headers.get_content_type(),'image/png')
        for suffix in ['&kind=../../.env','&kind=raw&attempt=../../bad']:
            with self.assertRaises(HTTPError):urlopen(self.base+'/api/buildings/file?task='+job['id']+suffix)
        with self.assertRaises(HTTPError):self.post('/api/buildings/publish',{'task':job['id'],'revision':1})

    def test_real_api_roundtrip_with_mock_worker_and_revision_conflict(self):
        job=self.post('/api/buildings/prepare',{'title':'测试','appearance':'木墙红瓦'})
        with patch.object(self.panel,'start_building',side_effect=self.fake_generation):
            job=self.post('/api/buildings/generate',{'task':job['id'],'revision':job['revision']})
        self.assertEqual(job['status'],'waiting_review')
        checks=dict.fromkeys(CHECKS,True)
        with self.assertRaises(HTTPError):self.post('/api/buildings/review',{'task':job['id'],'revision':1,'checks':checks})
        job=self.post('/api/buildings/review',{'task':job['id'],'revision':job['revision'],'checks':checks})
        kit=self.post('/api/buildings/publish',{'task':job['id'],'revision':job['revision']})
        with urlopen(self.base+'/building-asset/'+kit['id']+'/kit.zip') as response:self.assertGreater(len(response.read()),100)
        with urlopen(self.base+'/api/buildings/state') as response:
            state=json.load(response);self.assertEqual(len(state['kits']),1)
        self.assertNotIn('api_key',state)
        (self.root/'building-kits'/kit['id']/'kit.zip').write_bytes(b'bad zip')
        with self.assertRaises(HTTPError) as error:
            urlopen(self.base+'/building-asset/'+kit['id']+'/kit.zip')
        self.assertEqual(error.exception.code,400)

    def test_worker_launch_uses_shared_lease_and_recovers_interruption(self):
        from task_lock import task_lock
        job=prepare(self.root,{'title':'进程测试','appearance':'红瓦'})
        with patch('panel.subprocess.Popen') as spawn:
            result=self.panel.start_building({'task':job['id'],'revision':job['revision']})
            args,kwargs=spawn.call_args
            self.assertTrue(args[0][1].endswith('building_worker.py'))
            self.assertTrue(kwargs['pass_fds'])
            self.assertEqual(result['status'],'queued')
        # The fake child is gone. Recovery is only performed while lease is free.
        self.panel.recover_jobs()
        recovered=read(folder_for(self.root,job['id'])/'job.json')
        self.assertEqual(recovered['status'],'failed')
        self.assertGreater(recovered['revision'],result['revision'])
        # Current owner on a separate acquisition blocks the panel's launch.
        with task_lock(self.root):
            with self.assertRaisesRegex(ValueError,'生产任务'):
                self.panel.start_building({'resume':job['id'],'revision':recovered['revision']})


    def test_resume_contract_distinguishes_paid_submission_from_query(self):
        job=prepare(self.root,{'title':'恢复测试','appearance':'灰墙'})
        job=new_attempt(self.root,job['id'],job['revision'])
        folder=folder_for(self.root,job['id']);job['status']='failed';atomic(folder/'job.json',job)
        with patch('panel.subprocess.Popen') as spawn:
            with self.assertRaisesRegex(ValueError,'尚未提交'):
                self.panel.start_building({'resume':job['id'],'revision':job['revision']})
            spawn.assert_not_called()
            queued=self.panel.start_building({'resume':job['id'],'revision':job['revision'],'submit_unsubmitted':True})
            self.assertEqual(queued['execution_mode'],'submit')
        queued['status']='failed';atomic(folder/'job.json',queued)
        target=folder/'attempts'/job['current_attempt']
        atomic(target/'generation.json',{'remote_id':'remote-id'})
        with patch('panel.subprocess.Popen'):
            resumed=self.panel.start_building({'resume':job['id'],'revision':queued['revision']})
        self.assertEqual(resumed['execution_mode'],'resume')

    @unittest.skipIf(sync_playwright is None,'Playwright is not installed')
    def test_browser_create_review_publish_and_library(self):
        with sync_playwright() as p:
            try:browser=p.chromium.launch(channel='chrome',headless=True)
            except BrowserError as error:raise unittest.SkipTest(str(error))
            page=browser.new_page(viewport={'width':1280,'height':1000});page.set_default_timeout(7000);errors=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            # State from the real API, but expose configuration solely in this test.
            def state_route(route):
                response=route.fetch();value=response.json();value['image_api_configured']=True
                route.fulfill(response=response,json=value)
            page.route('**/api/buildings/state',state_route)
            # The only mocked production operation replaces the worker, never real network.
            def generate_route(route):
                result=self.fake_generation(route.request.post_data_json)
                route.fulfill(json=result)
            page.route('**/api/buildings/generate',generate_route)
            page.goto(self.base+'/building-structure.html')
            page.locator('#building-title').fill('浏览器小屋')
            page.get_by_role('button',name='制作结构预览（不生图）').click()
            page.wait_for_url('**/building-structure.html?task=*')
            page.locator('#building-appearance').fill('灰泥墙红瓦')
            page.get_by_label('我已检查占地、门窗和屋顶结构').check()
            page.get_by_role('button',name='确认结构并生成外观（可能产生费用）').click()
            page.get_by_role('button',name='提交复核结论').wait_for()
            # Polling must preserve a dirty review and require an explicit reload
            # after another operation changes the task revision.
            first=page.get_by_label('整体轮廓与墙角保持一致');first.check()
            page.get_by_label('复核或修正说明').fill('刷新后保留')
            page.reload()
            expect(first).to_be_checked()
            expect(page.get_by_label('复核或修正说明')).to_have_value('刷新后保留')
            task=page.url.split('task=')[1]
            job_path=folder_for(self.root,task)/'job.json';updated=read(job_path)
            updated['revision']+=1;atomic(job_path,updated)
            page.get_by_role('button',name='载入最新任务').wait_for()
            self.assertTrue(first.is_checked())
            page.get_by_role('button',name='载入最新任务').click()
            expect(first).not_to_be_checked()
            for label in ['整体轮廓与墙角保持一致','双坡屋顶与山墙结构正确','门窗数量、位置与比例正确',
                          '地面接触和建筑比例正确','透明边缘无残色、缺口或裁断','材质、配色与画风符合要求']:
                page.get_by_label(label).check()
            page.get_by_role('button',name='提交复核结论').click()
            export=page.get_by_role('button',name='导出已复核的建筑候选包')
            export.wait_for()
            first.uncheck();expect(export).to_be_disabled()
            first.check();expect(export).to_be_disabled()
            page.get_by_role('button',name='提交复核结论').click()
            expect(export).to_be_enabled();export.click()
            page.get_by_role('link',name='查看并下载候选包 →').click()
            page.get_by_role('link',name='下载候选包 ZIP').wait_for()
            for width in [390,1280]:
                page.set_viewport_size({'width':width,'height':1000})
                self.assertTrue(page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
            from studio_projects import change
            project=change(self.root,dict(action='create',title='浏览器素材项目'))
            project=change(self.root,dict(action='add',project=project['id'],revision=project['revision'],kind='building',title='测试住宅'))
            page.goto(self.base+'/?project='+project['id'])
            page.get_by_role('button',name='挑选已有成果').click()
            page.get_by_role('button',name='素材库',exact=True).click()
            page.get_by_role('heading',name='浏览器小屋',exact=True).wait_for()
            self.assertFalse(errors)

    @unittest.skipIf(sync_playwright is None,'Playwright is not installed')
    def test_browser_structure_edit_keeps_spec_and_persists_draft(self):
        parent=prepare(self.root,{'title':'大厅','appearance':'木墙红瓦',
                                 'structure':{'footprint_cells':[4,3],'roof':{'ridge_axis':'y'}}})
        with sync_playwright() as p:
            try: browser=p.chromium.launch(channel='chrome',headless=True)
            except BrowserError as error: raise unittest.SkipTest(str(error))
            page=browser.new_page();page.set_default_timeout(7000)
            page.goto(self.base+'/building-structure.html?task='+parent['id'])
            page.get_by_role('link',name='载入当前规格修改结构').click()
            expect(page.locator('#building-title')).to_have_value('大厅')
            expect(page.locator('#building-width')).to_have_value('4')
            expect(page.locator('#building-ridge')).to_have_value('y')
            page.locator('#building-door-center').fill('1.8');page.reload()
            expect(page.locator('#building-door-center')).to_have_value('1.8')
            page.get_by_role('button',name='制作结构预览（不生图）').click()
            page.wait_for_url('**/building-structure.html?task=*')
            expect(page.locator('#building-appearance')).to_have_value('木墙红瓦')
            task=page.url.split('task=')[1]
            child=read(folder_for(self.root,task)/'job.json')
            self.assertEqual(child['parent_task'],parent['id'])
            self.assertEqual(child['attempts'],[])
            browser.close()

    def test_line_drawing_api_auth_selection_and_delivery(self):
        from pipeline.tests.test_building_candidates import drawings,encoded
        outline,_=drawings()
        data=dict(workflow='line_drawing',title='旅馆',appearance='暖色手绘',line_drawing=encoded(outline))
        with self.assertRaises(HTTPError): self.post('/api/buildings/prepare',data,False)
        job=self.post('/api/buildings/prepare',data)
        with patch.object(self.panel,'start_building',side_effect=self.fake_generation):
            job=self.post('/api/buildings/generate',dict(task=job['id'],revision=job['revision']))
        task=job['id'];attempt=job['current_attempt']
        with self.assertRaises(HTTPError):self.post('/api/buildings/select',dict(task=task,revision=job['revision'],attempt=attempt),False)
        job=self.post('/api/buildings/select',dict(task=task,revision=job['revision'],attempt=attempt))
        with urlopen(self.base+'/api/buildings/state') as response: state=json.load(response)
        candidate=state['jobs'][0]['candidates'][0]
        self.assertTrue(candidate['ready'])
        kit=self.post('/api/buildings/save',dict(task=task,revision=job['revision'],attempt=attempt,evidence_key=candidate['evidence_key'],
            calibration=dict(anchor_px=[128,200],footprint_polygon_px=[[64,170],[128,145],[205,180],[128,220]],output_width_px=512)))
        with urlopen(self.base+'/building-asset/'+kit['id']+'/kit.zip') as response:self.assertGreater(len(response.read()),100)
        self.assertEqual(kit['human_review'],'candidate_selected')

    @unittest.skipIf(sync_playwright is None,'Playwright is not installed')
    def test_browser_line_drawing_reroll_select_calibrate_and_save(self):
        from pipeline.tests.test_building_candidates import drawings
        outline,_=drawings();stream=BytesIO();outline.save(stream,format='PNG')
        with sync_playwright() as p:
            try:browser=p.chromium.launch(channel='chrome',headless=True)
            except BrowserError as error:raise unittest.SkipTest(str(error))
            page=browser.new_page(viewport={'width':1280,'height':1000});page.set_default_timeout(7000)
            errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
            def state_route(route):
                response=route.fetch();data=response.json();data['image_api_configured']=True
                route.fulfill(response=response,json=data)
            page.route('**/api/buildings/state',state_route)
            def generation_route(route):route.fulfill(json=self.fake_generation(route.request.post_data_json))
            page.route('**/api/buildings/generate',generation_route)
            page.goto(self.base+'/buildings.html')
            page.get_by_label('名称',exact=True).fill('框线旅馆')
            page.get_by_label('风格提示词（材质、配色、画风）').fill('暖色木材手绘')
            page.get_by_label('原始建筑框线图',exact=True).set_input_files(dict(name='outline.png',mimeType='image/png',buffer=stream.getvalue()))
            page.get_by_role('button',name='生成第一个候选（可能产生费用）').click()
            page.wait_for_url('**/buildings.html?task=*')
            page.get_by_role('button',name='设置游戏占地与锚点（可选）',exact=True).wait_for()
            task=page.url.split('task=')[1]
            page.get_by_role('button',name='使用相同输入再生成一张（可能产生费用）').click()
            expect(page.locator('.building-candidate')).to_have_count(2)
            page.locator('.building-candidate').first.get_by_role('button',name='设置游戏占地与锚点（可选）').click()
            canvas=page.locator('#building-calibration-canvas');canvas.wait_for()
            box=canvas.bounding_box()
            for x,y in [(.25,.67),(.5,.57),(.8,.7),(.5,.86)]:canvas.click(position=dict(x=box['width']*x,y=box['height']*y))
            page.get_by_label('标记方式',exact=True).select_option('anchor')
            canvas.click(position=dict(x=box['width']*.5,y=box['height']*.78))
            page.reload()
            page.get_by_text('已标记 4 个占地顶点；锚点已设置。',exact=False).wait_for()
            page.get_by_label('成品画布宽度（px，整体等比例缩放）').fill('384')
            page.get_by_role('button',name='保存选定建筑素材').click()
            page.wait_for_url('**/buildings.html?kit=*')
            page.get_by_role('link',name='下载建筑素材 ZIP').wait_for()
            with urlopen(self.base+'/api/buildings/state') as response:state=json.load(response)
            self.assertEqual(len(state['jobs'][0]['attempts']),2)
            self.assertEqual(state['kits'][0]['attempt_id'],state['jobs'][0]['attempts'][0])
            for width in [390,1280]:
                page.set_viewport_size(dict(width=width,height=1000))
                page.goto(self.base+'/buildings.html?task='+task)
                canvas.wait_for();self.assertTrue(page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
            self.assertFalse(errors);browser.close()

    @unittest.skipIf(sync_playwright is None,'Playwright is not installed')
    def test_browser_template_settings_upload_generate_and_reuse_for_style(self):
        from pipeline.tests.test_building_candidates import drawings
        outline,_=drawings();stream=BytesIO();outline.save(stream,format='PNG')
        with sync_playwright() as p:
            try:browser=p.chromium.launch(channel='chrome',headless=True)
            except BrowserError as error:raise unittest.SkipTest(str(error))
            page=browser.new_page(viewport={'width':1280,'height':1000});page.set_default_timeout(7000);errors=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            def state_route(route):
                response=route.fetch();value=response.json();value['image_api_configured']=True;route.fulfill(response=response,json=value)
            page.route('**/api/buildings/state',state_route)
            page.route('**/api/buildings/generate',lambda route:route.fulfill(json=self.fake_generation(route.request.post_data_json)))
            page.goto(self.base+'/buildings.html?settings=templates')
            page.get_by_label('模板名称',exact=True).fill('可复用旅馆')
            page.get_by_label('模板来源',exact=True).select_option('upload')
            page.get_by_label('模板线框图',exact=True).set_input_files(dict(name='outline.png',mimeType='image/png',buffer=stream.getvalue()))
            page.get_by_role('button',name='保存建筑模板',exact=True).click()
            page.get_by_text('模板已保存，可在下方填写风格并生成建筑。',exact=True).wait_for()
            selected=page.get_by_label('建筑模板',exact=True).input_value();self.assertTrue(selected)
            expect(page.locator('#building-drawing')).to_be_hidden()
            page.get_by_label('名称',exact=True).fill('旅馆外观')
            page.get_by_label('风格提示词（材质、配色、画风）',exact=True).fill('暖色手绘木材')
            page.get_by_role('button',name='仅保存生成方案',exact=True).click();page.wait_for_url('**/buildings.html?task=*')
            job=read(folder_for(self.root,page.url.split('task=')[1])/'job.json');self.assertEqual(job['template_id'],selected)
            self.assertEqual(job['spec']['appearance'],'暖色手绘木材')
            page.goto(self.base+'/buildings.html?settings=templates')
            page.get_by_label('模板名称',exact=True).fill('等距塔楼')
            page.get_by_label('模板来源',exact=True).select_option('generate')
            page.get_by_label('建筑形体描述',exact=True).fill('两层方形塔楼，平顶')
            page.get_by_role('button',name='生成线框候选（可能产生费用）',exact=True).click()
            page.wait_for_url('**/buildings.html?task=*')
            page.get_by_role('button',name='保存为建筑模板',exact=True).click()
            page.wait_for_url('**/buildings.html?template=*')
            expect(page.get_by_label('建筑模板',exact=True)).not_to_have_value('')
            expect(page.locator('#building-drawing')).to_be_hidden()
            page.set_viewport_size(dict(width=390,height=1000));self.assertFalse(page.evaluate('document.documentElement.scrollWidth>innerWidth'))
            self.assertFalse(errors);browser.close()

    def test_template_upload_api_checks_token_and_file_scope(self):
        from pipeline.tests.test_building_candidates import drawings,encoded
        outline,_=drawings();data=dict(title='母版',view='isometric_2_1',confirmed=True,line_drawing=encoded(outline))
        with self.assertRaises(HTTPError) as error:self.post('/api/buildings/templates/save',data,False)
        self.assertEqual(error.exception.code,403)
        template=self.post('/api/buildings/templates/save',data)
        with urlopen(self.base+'/api/buildings/template-file?id='+template['id']) as response:self.assertEqual(response.headers.get_content_type(),'image/png')
        with self.assertRaises(HTTPError):urlopen(self.base+'/api/buildings/template-file?id=../../.env')
        unconfirmed=self.post('/api/buildings/templates/save',{**data,'confirmed':False})
        self.assertEqual(unconfirmed['review'],'saved_for_reuse_not_projection_measurement')
        with urlopen(self.base+'/api/buildings/state') as response:state=json.load(response)
        self.assertEqual(state['templates'][0]['id'],unconfirmed['id'])


if __name__=='__main__':unittest.main()
