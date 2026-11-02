"""Project production and set handoff contracts, with no image-service calls."""
from http.server import ThreadingHTTPServer
from io import BytesIO
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request,urlopen
import zipfile

from PIL import Image,ImageDraw
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from asset_repository import read
from static_props import package,validate
import studio_projects as projects
from panel import Panel,handler
try:
    from playwright.sync_api import sync_playwright,expect
except ImportError:
    sync_playwright=None


class ProjectTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        image=Image.new('RGBA',(128,128));ImageDraw.Draw(image).ellipse((30,40,98,108),fill='#92744b')
        self.asset=package(self.root,image,validate(dict(mode='import',kind='rock',title='测试石头',projection='isometric_2_1')),provenance={'art_source':'external_complete_object'}).name
        self.project=projects.change(self.root,dict(action='create',title='村庄'))
        self.update(action='add',kind='prop',title='广场石头')
        self.entry=self.project['items'][0]['id']

    def update(self,**data):
        self.project=projects.change(self.root,dict(project=self.project['id'],revision=self.project['revision'],**data));return self.project

    def select(self):self.update(action='select',item=self.entry,asset=self.asset)
    def review(self):self.update(action='review',checks=dict(style=True,scale=True,view=True),placements={self.entry:[300,400,1]},note='仅视觉检查')

    def test_selection_snapshot_survives_source_changes_and_release_is_immutable(self):
        self.select();self.review()
        selected=self.project['items'][0]['selected'];original=projects.selection_file(self.root,self.project['id'],selected,'archive')
        (self.root/'prop-kits'/self.asset/'sprite.png').write_bytes(b'changed')
        self.project=projects.release(self.root,dict(project=self.project['id'],revision=self.project['revision']))
        release=self.project['releases'][0];path=projects.folder(self.root,self.project['id'])/'releases'/(release['id']+'.zip')
        with zipfile.ZipFile(path) as archive:
            self.assertEqual(archive.read('assets/'+self.entry+'.zip'),original)
            manifest=json.loads(archive.read('project.json'));self.assertFalse(manifest['production_ready'])
            self.assertEqual(manifest['review']['scope'],'composition_layout_only')
        before=path.read_bytes();self.update(action='baseline',baseline=dict(style='冷色石造'))
        self.assertIsNone(self.project['review']);self.assertEqual(path.read_bytes(),before)
        self.project=projects.release(self.root,dict(project=self.project['id'],revision=self.project['revision']))
        self.assertEqual(len(self.project['releases']),2)

    def test_stale_revision_cross_kind_and_path_escape_are_rejected(self):
        with self.assertRaisesRegex(ValueError,'更新'):projects.change(self.root,dict(project=self.project['id'],revision=0,action='add',kind='prop',title='旧页面'))
        with self.assertRaises(ValueError):projects.load(self.root,'../../outside')
        self.update(action='add',kind='building',title='住宅')
        with self.assertRaisesRegex(ValueError,'类别'):self.update(action='select',item=self.project['items'][1]['id'],asset=self.asset)

    def test_preview_never_adopts_and_release_needs_no_review_but_requires_all_items(self):
        before=projects.load(self.root,self.project['id'])
        candidate=projects.preview(self.root,before,before['items'][0],self.asset)
        self.assertTrue(candidate['image'].startswith('data:image/png;base64,'))
        self.assertEqual(projects.load(self.root,self.project['id']),before)
        self.select()
        self.assertIsNone(self.project['review'])
        self.project=projects.release(self.root,dict(project=self.project['id'],revision=self.project['revision']))
        self.assertEqual(len(self.project['releases']),1)
        self.update(action='add',kind='ground',title='草地')
        with self.assertRaisesRegex(ValueError,'每项'):projects.release(self.root,dict(project=self.project['id'],revision=self.project['revision']))
        self.update(action='review',placements={self.entry:[300,400,1]})
        self.assertEqual(self.project['review']['checks'],{})

    def test_generated_building_can_be_previewed_then_adopted_directly(self):
        import building_pipeline as bp
        from pipeline.tests.test_building_candidates import drawings,encoded
        from unittest.mock import Mock
        outline,raw=drawings()
        self.update(action='add',kind='building',title='农舍')
        entry=self.project['items'][-1]
        job=bp.prepare(self.root,dict(workflow='line_drawing',title='农舍',appearance='暖色',line_drawing=encoded(outline)))
        job=bp.new_attempt(self.root,job['id'],job['revision'])
        provider=Mock(base='mock://images');provider.create.return_value={'data':[{'b64_json':encoded(raw)}]}
        job=bp.execute(self.root,job['id'],provider_factory=lambda *args:provider)
        projects.record_task(self.root,dict(project=self.project['id'],item=entry['id'],baseline_revision=1),'/api/buildings/prepare',job)
        self.project=projects.load(self.root,self.project['id'])
        aid=projects.candidates(self.root,self.project)[0]['id']
        preview=projects.preview(self.root,self.project,entry,aid)
        self.assertEqual(preview['canvas_px'],[256,256])
        self.assertIsNone(projects.load(self.root,self.project['id'])['items'][-1]['selected'])
        with self.assertRaisesRegex(ValueError,'不属于'):self.update(action='adopt_candidate',item=self.entry,asset=aid)
        self.update(action='adopt_candidate',item=entry['id'],asset=aid)
        selection=self.project['items'][-1]['selected']
        self.assertEqual(selection['family'],'building')
        self.assertTrue(projects.selection_file(self.root,self.project['id'],selection,'archive'))

    def test_snapshot_tamper_and_incomplete_review_are_rejected(self):
        with self.assertRaisesRegex(ValueError,'采用'):self.review()
        self.select();s=self.project['items'][0]['selected']
        path=projects.folder(self.root,self.project['id'])/'selected'/(s['sha256']+'.zip');path.write_bytes(b'broken')
        with self.assertRaisesRegex(ValueError,'快照'):self.review()

    def test_baseline_is_snapshotted_and_stale_workbench_rejected(self):
        self.update(action='baseline',baseline=dict(style='手绘',palette='暖色'))
        data=dict(studio_context=dict(project=self.project['id'],item=self.entry,baseline_revision=2),mode='ai',description='矮石头')
        c=projects.context(self.root,data);projects.inherit(self.root,c,'/api/props/generate',data)
        self.assertIn('手绘',data['description']);self.assertEqual(data['projection'],'isometric_2_1')
        projects.record_task(self.root,c,'/api/props/generate',dict(id='task-1'))
        self.project=projects.load(self.root,self.project['id'])
        self.update(action='baseline',baseline=dict(style='新风格'))
        self.assertEqual(self.project['tasks'][0]['context']['baseline']['style'],'手绘')
        with self.assertRaisesRegex(ValueError,'基准已变化'):projects.context(self.root,data)

    def test_camera_and_orientation_are_separate_from_ground_texture_rules(self):
        self.update(action='baseline',baseline=dict(style='像素农场',camera_rules='屋顶可见，正面水平',orientation_rules='门朝屏幕下方'))
        c=dict(project=self.project['id'],item=self.entry,baseline=self.project['baseline'])
        data=dict(mode='ai',description='石头')
        projects.inherit(self.root,c,'/api/props/generate',data)
        self.assertIn('正面水平',data['description'])
        self.assertIn('门朝屏幕下方',data['description'])
        self.update(action='add',kind='ground',title='草地')
        c['item']=self.project['items'][-1]['id']
        data=dict(mode='ai',description='草地',asset_type='material')
        projects.inherit(self.root,c,'/api/terrain/generate',data)
        self.assertNotIn('门朝屏幕下方',data['description'])

    def test_item_archive_can_be_restored(self):
        self.select();self.update(action='archive_item',item=self.entry);self.assertEqual(self.project['items'],[])
        self.update(action='restore_item',item=self.entry);self.assertEqual(self.project['items'][0]['selected']['asset'],self.asset)

    def test_synchronous_transition_manifest_is_a_completed_task(self):
        from asset_repository import atomic
        p=dict(self.project,tasks=[dict(id='transition-test',family='transitions',context={},created_at='test')])
        self.assertEqual(projects.task_state(self.root,p)[0]['status'],'missing')
        atomic(self.root/'terrain-transitions/transition-test/manifest.json',dict(id='transition-test'))
        task=projects.task_state(self.root,p)[0]
        self.assertEqual(task['status'],'complete')
        self.assertEqual(task['kit'],'transition-test')

    def test_building_template_binding_validates_view_and_enables_production(self):
        from building_templates import save
        from pipeline.tests.test_building_candidates import drawings,encoded
        outline,_=drawings()
        self.update(action='baseline',baseline=dict(style='乡村像素',view='orthographic_three_quarter'))
        self.update(action='add',kind='building',title='农舍',description='单层双坡屋顶')
        entry=self.project['items'][-1]
        wrong=save(self.root,dict(title='等距模板',view='isometric_2_1',line_drawing=encoded(outline),confirmed=True))
        with self.assertRaisesRegex(ValueError,'视角'):self.update(action='bind_template',item=entry['id'],template_id=wrong['id'])
        template=save(self.root,dict(title='农舍模板',view='orthographic_three_quarter',line_drawing=encoded(outline),confirmed=True))
        self.update(action='bind_template',item=entry['id'],template_id=template['id'])
        with patch('terrain_images.configured',return_value=True):
            plan=projects.production_plan(self.root,self.project,self.project['items'][-1])
        self.assertTrue(plan['ready']);self.assertEqual(plan['data']['template_id'],template['id'])
        self.assertEqual(plan['data']['appearance'],'乡村像素。柔和中性光，统一左上方受光')

    def test_batch_import_preserves_existing_and_is_atomic(self):
        self.select();before=self.project['items'][0].copy()
        rows=[dict(kind='prop',title='广场石头',description='不要覆盖'),
              dict(kind='ground',title='草地',description='春季'),
              dict(kind='ground',title='草地',description='重复')]
        self.update(action='import_items',items=rows)
        self.assertEqual(len(self.project['items']),2)
        self.assertEqual(self.project['items'][0],before)
        revision=self.project['revision']
        self.update(action='import_items',items=rows)
        self.assertEqual(self.project['revision'],revision)
        with self.assertRaises(ValueError):
            self.update(action='import_items',items=[dict(kind='prop',title='木桶'),dict(kind='invalid',title='坏项')])
        self.assertEqual(projects.load(self.root,self.project['id']),self.project)

    def test_production_plan_validates_style_projection_and_missing_inputs(self):
        entry=self.project['items'][0]
        self.assertFalse(projects.production_plan(self.root,self.project,entry)['ready'])
        self.update(action='baseline',baseline=dict(style='像素农场',view='orthographic_three_quarter',cell_px=64))
        self.update(action='edit_item',item=self.entry,title='石头',description='一块灰色石头')
        with patch('terrain_images.configured',return_value=True):
            plan=projects.production_plan(self.root,self.project,self.project['items'][0])
            self.assertTrue(plan['ready']);self.assertIn('像素农场',plan['data']['description'])
            self.assertEqual(plan['data']['projection'],'orthographic_three_quarter')
            for kind in ('building','shore','transition','character'):
                self.assertFalse(projects.production_plan(self.root,self.project,dict(kind=kind))['ready'])
            self.update(action='baseline',baseline=dict(style='像素',view='top_down'))
            self.assertFalse(projects.production_plan(self.root,self.project,self.project['items'][0])['ready'])


class ProjectHTTPTests(ProjectTests):
    def setUp(self):
        super().setUp();self.panel=Panel(self.root);self.server=ThreadingHTTPServer(('127.0.0.1',0),handler(self.panel))
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start();self.base='http://127.0.0.1:'+str(self.server.server_port)
        self.addCleanup(self.shutdown)
    def shutdown(self):self.server.shutdown();self.server.server_close();self.thread.join()
    def test_one_click_records_task_without_calling_provider_in_test(self):
        self.update(action='baseline',baseline=dict(style='像素农场',view='orthographic_three_quarter'))
        self.update(action='edit_item',item=self.entry,title='石头',description='单个石头')
        payload=dict(project=self.project['id'],revision=self.project['revision'],item=self.entry)
        def submit():
            return urlopen(Request(self.base+'/api/projects/generate',data=json.dumps(payload).encode(),
                headers={'Content-Type':'application/json','X-Studio-Token':self.panel.token}))
        with patch('terrain_images.configured',return_value=True),patch.object(self.panel,'start_terrain',return_value={'id':'single-item-task'}) as start:
            with submit() as r:self.assertEqual(json.load(r)['id'],'single-item-task')
            self.assertEqual(start.call_count,1)

            self.assertIn('像素农场',start.call_args[0][0]['description'])
            self.assertEqual(projects.load(self.root,self.project['id'])['tasks'][0]['id'],'single-item-task')
            with self.assertRaises(HTTPError):submit()
            self.assertEqual(start.call_count,1)

    def test_bound_building_one_click_reuses_template_and_records_task(self):
        from building_templates import save
        from pipeline.tests.test_building_candidates import drawings,encoded
        outline,_=drawings()
        self.update(action='baseline',baseline=dict(style='乡村像素',view='orthographic_three_quarter'))
        self.update(action='add',kind='building',title='农舍',description='单层双坡屋顶')
        entry=self.project['items'][-1]
        template=save(self.root,dict(title='农舍模板',view='orthographic_three_quarter',line_drawing=encoded(outline),confirmed=True))
        self.update(action='bind_template',item=entry['id'],template_id=template['id'])
        with patch('terrain_images.configured',return_value=True),patch.object(self.panel,'start_building',side_effect=lambda d:dict(id=d['task'])) as start:
            payload=dict(project=self.project['id'],revision=self.project['revision'],item=entry['id'])
            with urlopen(Request(self.base+'/api/projects/generate',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json','X-Studio-Token':self.panel.token})) as response:
                job=json.load(response)
            self.assertEqual(start.call_count,1)
            saved=projects.load(self.root,self.project['id'])
            self.assertEqual(len(saved['tasks']),1)
            self.assertEqual(saved['tasks'][0]['id'],job['id'])
    def test_http_auth_and_project_roundtrip(self):
        with urlopen(self.base+'/api/projects/state?project='+self.project['id']) as r:state=json.load(r)
        self.assertEqual(state['selected']['title'],'村庄')
        payload=json.dumps(dict(action='create',title='另一套')).encode()
        with self.assertRaises(HTTPError) as cm:urlopen(Request(self.base+'/api/projects/change',data=payload,headers={'Content-Type':'application/json'}))
        self.assertEqual(cm.exception.code,403)
        with urlopen(Request(self.base+'/api/projects/change',data=payload,headers={'Content-Type':'application/json','X-Studio-Token':state['token']})) as r:created=json.load(r)
        self.assertNotEqual(created['id'],self.project['id']);self.assertEqual(created['items'],[])

    def test_building_prepare_inherits_project_and_records_exact_baseline(self):
        import base64
        self.update(action='baseline',baseline=dict(style='统一手绘',palette='暖灰色'))
        self.update(action='add',kind='building',title='村口住宅')
        entry=self.project['items'][-1]['id'];stream=BytesIO();Image.new('RGB',(128,128),'white').save(stream,'PNG')
        data=dict(workflow='line_drawing',title='村口住宅',appearance='页面旧值',line_drawing=base64.b64encode(stream.getvalue()).decode(),
                  studio_context=dict(project=self.project['id'],item=entry,baseline_revision=self.project['baseline_revision']))
        req=Request(self.base+'/api/buildings/prepare',data=json.dumps(data).encode(),headers={'Content-Type':'application/json','X-Studio-Token':self.panel.token})
        with urlopen(req) as r:job=json.load(r)
        self.assertIn('统一手绘',job['spec']['appearance']);self.assertNotIn('页面旧值',job['spec']['appearance'])
        fresh=projects.load(self.root,self.project['id']);self.assertEqual(fresh['tasks'][0]['id'],job['id'])
        receipt=read(self.root/'.local/studio/task-context'/('buildings-'+job['id']+'.json'))
        self.assertEqual(receipt['baseline']['style'],'统一手绘')
        self.assertEqual(job['status'],'draft')

    @unittest.skipIf(sync_playwright is None,'Playwright unavailable')
    def test_browser_template_binding_and_workbench_prefill(self):
        from building_templates import save
        from pipeline.tests.test_building_candidates import drawings,encoded
        outline,_=drawings()
        self.update(action='baseline',baseline=dict(style='乡村像素',view='orthographic_three_quarter'))
        self.update(action='add',kind='building',title='农舍',description='单层双坡屋顶')
        template=save(self.root,dict(title='斜俯视农舍',view='orthographic_three_quarter',line_drawing=encoded(outline),confirmed=True))
        with sync_playwright() as pw:
            browser=pw.chromium.launch(channel='chrome',headless=True)
            try:
                page=browser.new_page();page.set_default_timeout(8000)
                page.goto(self.base+'/?project='+self.project['id'])
                building=page.locator('.production-entry').filter(has=page.get_by_role('heading',name='农舍',exact=True))
                expect(building.get_by_label('此建筑使用的线稿模板',exact=True)).not_to_be_visible()
                building.get_by_role('button',name='详情',exact=True).click()
                page.get_by_label('此建筑使用的线稿模板',exact=True).select_option(template['id'])
                page.get_by_role('button',name='保存模板绑定',exact=True).click()
                expect(building.locator('.production-detail-dialog')).not_to_be_visible()
                building.get_by_role('button',name='详情',exact=True).click()
                expect(page.get_by_label('此建筑使用的线稿模板',exact=True)).to_have_value(template['id'])
                expect(page.get_by_role('link',name='制作 / 导入建筑模板 →',exact=True)).to_have_attribute('href',__import__('re').compile('template='+template['id']))
                page.get_by_role('link',name='制作 / 导入建筑模板 →',exact=True).click()
                expect(page.locator('#template-view')).to_have_value('orthographic_three_quarter')
                expect(page.locator('#template-description')).to_have_value('单层双坡屋顶')
                expect(page.locator('#building-template')).to_have_value(template['id'])
                page.set_viewport_size(dict(width=390,height=844))
                self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),392)
            finally:browser.close()

    @unittest.skipIf(sync_playwright is None,'Playwright unavailable')
    def test_browser_select_review_deliver_and_workbench_context(self):
        with sync_playwright() as pw:
            browser=pw.chromium.launch(channel='chrome',headless=True)
            page=browser.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(self.base+'/?project='+self.project['id'])
            expect(page.get_by_role('heading',name='村庄',exact=True)).to_be_visible()
            expect(page.get_by_role('button',name='加入清单',exact=True)).not_to_be_visible()
            page.get_by_text('新增需求',exact=True).click()
            expect(page.get_by_role('button',name='加入清单',exact=True)).to_be_visible()
            page.get_by_text('新增需求',exact=True).click()
            page.get_by_role('button',name='批量导入清单',exact=True).click()
            expect(page.get_by_role('button',name='预览导入',exact=True)).to_be_visible()
            page.get_by_role('button',name='批量导入清单',exact=True).click()
            page.set_viewport_size(dict(width=390,height=844))
            self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),392)
            page.set_viewport_size(dict(width=1280,height=900))
            page.get_by_role('button',name='挑选已有成果').click()
            expect(page.locator('#asset-options .picker-card')).to_have_count(0)
            page.get_by_role('button',name='素材库',exact=True).click()
            page.get_by_role('button',name='放入组合比较').click()
            expect(page.locator('#project-composition')).to_be_visible()
            self.assertIsNone(projects.load(self.root,self.project['id'])['items'][0]['selected'])
            expect(page.get_by_role('link',name='组合挑选',exact=True)).to_have_attribute('aria-current','page')
            page.get_by_role('button',name='采用此结果').click()
            expect(page.locator('#asset-picker')).not_to_be_visible()
            page.get_by_role('link',name='组合挑选',exact=True).click()
            expect(page.locator('#project-composition')).to_be_visible()
            self.assertEqual(page.get_by_role('checkbox').count(),0)
            canvas=page.locator('#project-composition')
            self.assertLess(canvas.bounding_box()['y'],400)
            page.wait_for_function('() => Array.from(document.images).every(i => i.complete)')
            rect=canvas.bounding_box()
            def point(x,y):return (rect['x']+x*rect['width']/1000,rect['y']+y*rect['height']/640)
            page.mouse.click(*point(180,200))
            page.mouse.move(*point(180,200));page.mouse.down();page.mouse.move(*point(230,220));page.mouse.up()
            draft=page.evaluate("JSON.parse(localStorage.getItem(Object.keys(localStorage).find(k=>k.startsWith('studio.composition.'))))")
            self.assertAlmostEqual(draft[self.entry][0],230,delta=1)
            self.assertAlmostEqual(draft[self.entry][1],270,delta=1)
            page.get_by_role('button',name='保存组合位置').click()
            expect(page.locator('#hub-description')).to_contain_text('组合位置已保存')
            page.get_by_role('link',name='交付',exact=True).click();page.get_by_role('button',name='导出整套素材').click()
            expect(page.get_by_role('link',name='下载交付版本',exact=False)).to_be_visible()
            page.get_by_role('link',name='生产',exact=True).click()
            expect(page.get_by_role('link',name='制作 / 继续生产')).not_to_be_visible()
            page.get_by_role('button',name='详情',exact=True).click()
            page.get_by_role('link',name='制作 / 继续生产').click()
            expect(page.locator('.studio-project-context')).to_contain_text('广场石头')
            self.assertIn('project=',page.url);self.assertIn('item=',page.url);self.assertIn('kit='+self.asset,page.url)
            page.set_viewport_size(dict(width=390,height=844))
            self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),392)
            self.assertEqual(errors,[])
            browser.close()
