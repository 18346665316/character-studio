"""Real deletion, stale requests, live references and UI cancellation in isolated storage."""
from http.server import ThreadingHTTPServer
from pathlib import Path
import json
import os
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from asset_repository import atomic, read
from deletion import inspect, delete
from panel import Panel, handler
from static_props import package, validate
import studio_projects as projects
from task_lock import acquire, TaskBusyError

try:
    from playwright.sync_api import sync_playwright, expect
except ImportError:
    sync_playwright = None


class DeletionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        image = Image.new('RGBA',(128,128));ImageDraw.Draw(image).ellipse((30,40,98,108),fill='#92744b')
        self.asset = package(self.root,image,validate({'mode':'import','kind':'rock','title':'测试石头','projection':'isometric_2_1'})).name
        self.target = {'kind':'asset','family':'prop','id':self.asset}
        self.project = projects.change(self.root,{'action':'create','title':'测试项目'})
        self.project = self.change('add',kind='prop',title='广场石头')

    def change(self,action,**data):
        self.project=projects.change(self.root,dict(action=action,project=self.project['id'],revision=self.project['revision'],**data))
        return self.project

    def remove(self, target):
        return delete(self.root,{**target,'fingerprint':inspect(self.root,target)['fingerprint']})

    def test_delete_asset_removes_files_and_catalog_entry(self):
        self.remove(self.target)
        self.assertFalse((self.root/'prop-kits'/self.asset).exists())
        self.assertFalse(any(a['id']==self.asset for a in projects.available(self.root)))

    def test_project_removal_preserves_shared_materials_and_other_projects(self):
        self.change('select',item=self.project['items'][0]['id'],asset=self.asset)
        other=projects.change(self.root,{'action':'create','title':'另一个项目'})
        self.remove({'kind':'project','id':self.project['id']})
        self.assertFalse((self.root/'.local/studio/projects'/self.project['id']).exists())
        self.assertTrue((self.root/'prop-kits'/self.asset/'kit.zip').is_file())
        self.assertTrue(projects.load(self.root,other['id']))

    def test_reference_created_after_inspection_blocks_delete(self):
        request={**self.target,'fingerprint':inspect(self.root,self.target)['fingerprint']}
        self.change('select',item=self.project['items'][0]['id'],asset=self.asset)
        with self.assertRaisesRegex(ValueError,'测试项目'):delete(self.root,request)
        self.assertTrue((self.root/'prop-kits'/self.asset/'kit.zip').is_file())

    def test_live_library_reference_blocks_deletion(self):
        self.change('set_asset',item=self.project['items'][0]['id'],asset=self.asset)
        self.assertTrue(inspect(self.root,self.target)['references'])
        with self.assertRaisesRegex(ValueError,'测试项目'): self.remove(self.target)

    def test_generated_output_is_protected_without_adoption(self):
        task=dict(id='done',context=dict(item=self.project['items'][0]['id']),status='complete',kit=self.asset)
        with patch('studio_projects.task_state',return_value=[task]):
            self.assertTrue(inspect(self.root,self.target)['references'])
            with self.assertRaisesRegex(ValueError,'测试项目'): self.remove(self.target)

    def test_archived_requirement_is_still_a_reference(self):
        entry=self.project['items'][0]['id']
        self.change('select',item=entry,asset=self.asset);self.change('archive_item',item=entry)
        self.assertTrue(inspect(self.root,self.target)['references'])

    def test_deleting_requirement_unlinks_it_without_deleting_material(self):
        entry=self.project['items'][0]['id'];self.change('select',item=entry,asset=self.asset)
        self.remove({'kind':'item','project':self.project['id'],'id':entry})
        self.assertEqual(projects.load(self.root,self.project['id'])['items'],[])
        self.assertFalse(inspect(self.root,self.target)['references'])
        self.assertTrue((self.root/'prop-kits'/self.asset).is_dir())
        self.assertFalse(list((self.root/'.local/studio/projects'/self.project['id']/'selected').glob('*')))

    def test_shared_selected_snapshot_survives_deleting_one_requirement(self):
        first=self.project['items'][0]['id'];self.change('select',item=first,asset=self.asset)
        self.change('add',kind='prop',title='另一块石头');second=self.project['items'][1]['id']
        self.change('select',item=second,asset=self.asset)
        self.remove({'kind':'item','project':self.project['id'],'id':first})
        current=projects.load(self.root,self.project['id'])['items'][0]['selected']
        self.assertTrue(projects.selection_file(self.root,self.project['id'],current,'archive'))

    def test_scene_reference_then_scene_deletion(self):
        atomic(self.root/'.local/module-scenes/scene.json',{'id':'scene','title':'小院','modules':[
            {'title':'井','source':{'family':'prop','id':self.asset}}]})
        with self.assertRaisesRegex(ValueError,'小院'):self.remove(self.target)
        self.remove({'kind':'scene','id':'scene'})
        self.remove(self.target)

    def test_transition_source_is_protected(self):
        path=self.root/'terrain-kits/grass';path.mkdir(parents=True);atomic(path/'manifest.json',{'title':'草地'})
        atomic(self.root/'terrain-transitions/shore/manifest.json',{'title':'水岸','sources':[{'kit':'grass'}]})
        with self.assertRaisesRegex(ValueError,'水岸'):self.remove({'kind':'asset','family':'terrain','id':'grass'})

    def test_character_removal_includes_outputs_and_local_character_state(self):
        for directory in ('workspaces','deliverables','.local/mixamo','.local/production'):
            path=self.root/directory/'hero';path.mkdir(parents=True);(path/'data.txt').write_text('fixture')
        atomic(self.root/'workspaces/hero/character.json',{'display_name':'主角'})
        atomic(self.root/'.local/jobs/owned/job.json',{'character':'hero'})
        atomic(self.root/'.local/jobs/shared/job.json',{'character':'other'})
        atomic(self.root/'.local/panel/tasks/owned.json',{'character':'hero'})
        (self.root/'.local/panel/tasks/owned.log').write_text('fixture')
        atomic(self.root/'.local/scene-characters/unreferenced/manifest.json',{'character':'hero'})
        self.remove({'kind':'asset','family':'character','id':'hero'})
        for directory in ('workspaces','deliverables','.local/mixamo','.local/production'):
            self.assertFalse((self.root/directory/'hero').exists())
        self.assertFalse((self.root/'.local/jobs/owned').exists())
        self.assertTrue((self.root/'.local/jobs/shared/job.json').exists())
        self.assertFalse((self.root/'.local/panel/tasks/owned.log').exists())
        self.assertFalse((self.root/'.local/scene-characters/unreferenced').exists())

    def test_character_used_by_pinned_scene_is_protected(self):
        (self.root/'workspaces/hero').mkdir(parents=True)
        atomic(self.root/'.local/scene-characters/snapshot/manifest.json',{'character':'hero'})
        atomic(self.root/'.local/module-scenes/scene.json',{'title':'人物验证','modules':[
            {'title':'主角','source':{'family':'character','id':'snapshot'}}]})
        with self.assertRaisesRegex(ValueError,'人物验证'):self.remove({'kind':'asset','family':'character','id':'hero'})

    def test_changed_content_missing_fingerprint_and_path_escape_rejected(self):
        request={**self.target,'fingerprint':inspect(self.root,self.target)['fingerprint']}
        (self.root/'prop-kits'/self.asset/'new.txt').write_text('changed')
        with self.assertRaisesRegex(ValueError,'已更新'):delete(self.root,request)
        with self.assertRaises(ValueError):delete(self.root,self.target)
        for target in ({'kind':'asset','family':'other','id':'a'},dict(self.target,id='../outside')):
            with self.assertRaises(ValueError):inspect(self.root,target)

    def test_symlink_target_is_never_deleted(self):
        outside=self.root/'outside';outside.mkdir();(outside/'keep.txt').write_text('keep')
        (self.root/'prop-kits/link').symlink_to(outside,target_is_directory=True)
        with self.assertRaises(ValueError):inspect(self.root,dict(self.target,id='link'))
        self.assertTrue((outside/'keep.txt').exists())

    def test_active_production_blocks_deletion(self):
        request={**self.target,'fingerprint':inspect(self.root,self.target)['fingerprint']}
        fd=acquire(self.root)
        try:
            with self.assertRaises(TaskBusyError):delete(self.root,request)
        finally:os.close(fd)
        self.assertTrue((self.root/'prop-kits'/self.asset).exists())


class DeletionHTTPTests(DeletionTests):
    def setUp(self):
        super().setUp();self.panel=Panel(self.root)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),handler(self.panel))
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.base='http://127.0.0.1:'+str(self.server.server_port);self.addCleanup(self.shutdown)

    def shutdown(self):
        self.server.shutdown();self.server.server_close();self.thread.join()

    def test_http_requires_token_and_rechecks_content(self):
        from urllib.parse import urlencode
        with urlopen(self.base+'/api/delete/inspect?'+urlencode(self.target)) as response:info=json.load(response)
        request={**self.target,'fingerprint':info['fingerprint']}
        with self.assertRaises(HTTPError):urlopen(Request(self.base+'/api/delete',data=json.dumps(request).encode(),headers={'Content-Type':'application/json'}))
        with urlopen(Request(self.base+'/api/delete',data=json.dumps(request).encode(),headers={'Content-Type':'application/json','X-Studio-Token':info['token']})) as response:
            self.assertTrue(json.load(response)['deleted'])

    @unittest.skipIf(sync_playwright is None,'Playwright unavailable')
    def test_browser_requirement_and_library_deletion(self):
        with sync_playwright() as pw:
            browser=pw.chromium.launch(channel='chrome',headless=True)
            try:
                page=browser.new_page();page.goto(self.base+'/?project='+self.project['id'])
                page.get_by_role('button',name='详情',exact=True).click()
                page.get_by_role('button',name='删除这项需求',exact=True).click()
                dialog=page.locator('.studio-delete-dialog');expect(dialog).to_contain_text('素材库中的成果保留')
                dialog.get_by_role('button',name='删除',exact=True).click()
                expect(page.locator('.production-entry')).to_have_count(0)
                self.assertTrue((self.root/'prop-kits'/self.asset).exists())
                self.project=projects.load(self.root,self.project['id']);self.change('add',kind='prop',title='新需求')
                page.reload();page.get_by_role('button',name='选择已有素材',exact=True).click()
                page.get_by_role('button',name='素材库',exact=True).click()
                page.locator('.picker-card').get_by_role('button',name='删除素材',exact=True).click()
                dialog.get_by_role('button',name='删除',exact=True).click()
                expect(page.locator('.picker-card')).to_have_count(0)
                self.assertFalse((self.root/'prop-kits'/self.asset).exists())
            finally:browser.close()

    @unittest.skipIf(sync_playwright is None,'Playwright unavailable')
    def test_browser_cancel_delete_reference_feedback_and_project_removal(self):
        with sync_playwright() as pw:
            browser=pw.chromium.launch(channel='chrome',headless=True)
            try:
                page=browser.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto(self.base+'/props.html?kit='+self.asset)
                page.get_by_role('button',name='删除素材',exact=True).click()
                dialog=page.locator('.studio-delete-dialog');expect(dialog.get_by_role('button',name='删除',exact=True)).to_be_enabled()
                dialog.get_by_role('button',name='取消',exact=True).click()
                self.assertTrue((self.root/'prop-kits'/self.asset).exists())
                self.change('select',item=self.project['items'][0]['id'],asset=self.asset)
                page.get_by_role('button',name='删除素材',exact=True).click()
                expect(dialog).to_contain_text('测试项目');expect(dialog.get_by_role('button',name='删除',exact=True)).not_to_be_visible()
                dialog.get_by_role('button',name='关闭',exact=True).click()
                page.goto(self.base+'/?view=projects')
                page.get_by_role('button',name='删除项目',exact=True).click()
                expect(dialog).to_contain_text('共用素材保留')
                dialog.get_by_role('button',name='删除',exact=True).click()
                expect(page.locator('.project-browser-entry')).to_have_count(0)
                self.assertTrue((self.root/'prop-kits'/self.asset).exists())
                page.goto(self.base+'/props.html?kit='+self.asset)
                page.get_by_role('button',name='删除素材',exact=True).click()
                dialog.get_by_role('button',name='删除',exact=True).click()
                expect(page).to_have_url(self.base+'/props.html')
                self.assertFalse((self.root/'prop-kits'/self.asset).exists())
                page.set_viewport_size({'width':390,'height':844})
                self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),392)
                self.assertEqual(errors,[])
            finally:browser.close()
