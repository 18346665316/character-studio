"""Provider switching: persistence, lease/CSRF protection and browser drafts."""
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from asset_repository import atomic
from image_provider_settings import state,switch
from terrain_images import load_config
from task_lock import acquire
from panel import Panel,handler


class ProviderSettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.env=patch.dict(os.environ,{},clear=True);self.env.start();self.addCleanup(self.env.stop)
        self.config=self.root/'.env';self.original='# keep this comment\nOPENAI_API_KEY=private-placeholder\nGCP_PROJECT_ID=example-project\nGCP_LOCATION=us-central1\nSTUDIO_IMAGE_PROVIDER=google_cloud\n'
        self.config.write_text(self.original)

    def select(self,provider):return switch(self.root,dict(provider=provider,revision=state(self.root)['revision']))

    def test_switch_preserves_credentials_and_persists_across_reads(self):
        first=state(self.root);self.assertEqual(first['current'],'google_cloud')
        self.assertNotIn('private-placeholder',json.dumps(first));self.assertNotIn('GCP_PROJECT_ID',json.dumps(first))
        changed=self.select('openai_compatible');self.assertEqual(changed['current'],'openai_compatible')
        self.assertEqual(load_config(self.root)['STUDIO_IMAGE_PROVIDER'],'openai_compatible')
        self.assertIn('# keep this comment',self.config.read_text());self.assertIn('OPENAI_API_KEY=private-placeholder',self.config.read_text())
        self.assertEqual(self.config.stat().st_mode&0o777,0o600)
        self.assertNotIn('STUDIO_IMAGE_PROVIDER',os.environ)
        with self.assertRaisesRegex(ValueError,'更新'):switch(self.root,dict(provider='google_cloud',revision=first['revision']))
        self.select('google_cloud');self.assertEqual(state(self.root)['current'],'google_cloud')
        self.assertEqual(self.config.read_text().count('STUDIO_IMAGE_PROVIDER='),1)

    def test_active_receipt_or_worker_lease_blocks_switch(self):
        atomic(self.root/'.local/buildings/jobs/example/job.json',dict(status='running'))
        with self.assertRaisesRegex(ValueError,'任务'):self.select('openai_compatible')
        self.assertEqual(self.config.read_text(),self.original)
        atomic(self.root/'.local/buildings/jobs/example/job.json',dict(status='failed'))
        fd=acquire(self.root)
        try:
            with self.assertRaisesRegex(ValueError,'任务'):self.select('openai_compatible')
        finally:os.close(fd)
        self.assertEqual(self.select('openai_compatible')['current'],'openai_compatible')

    def test_environment_override_and_unconfigured_provider_cannot_fake_success(self):
        os.environ['STUDIO_IMAGE_PROVIDER']='google_cloud'
        self.assertTrue(state(self.root)['environment_override'])
        with self.assertRaisesRegex(ValueError,'环境变量'):self.select('openai_compatible')
        del os.environ['STUDIO_IMAGE_PROVIDER']
        self.config.write_text('STUDIO_IMAGE_PROVIDER=google_cloud\nGCP_PROJECT_ID=example-project\n')
        with self.assertRaisesRegex(ValueError,'尚未配置'):self.select('openai_compatible')
        self.assertEqual(state(self.root)['current'],'google_cloud')
        with self.assertRaises(ValueError):self.select('other')

    def serve(self):
        panel=Panel(self.root);server=ThreadingHTTPServer(('127.0.0.1',0),handler(panel))
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        return panel,'http://127.0.0.1:'+str(server.server_port)

    def test_http_switch_requires_token_and_exposes_only_public_configuration(self):
        panel,base=self.serve()
        with urlopen(base+'/api/image-provider') as response:public=json.load(response)
        self.assertEqual(public['token'],panel.token);self.assertNotIn('private-placeholder',json.dumps(public))
        body=json.dumps(dict(provider='openai_compatible',revision=public['revision'])).encode()
        headers={'Content-Type':'application/json'}
        with self.assertRaises(HTTPError) as error:urlopen(Request(base+'/api/image-provider',body,headers=headers))
        self.assertEqual(error.exception.code,403)
        headers['X-Studio-Token']=panel.token
        with urlopen(Request(base+'/api/image-provider',body,headers=headers)) as response:result=json.load(response)
        self.assertEqual(result['current'],'openai_compatible')
        with self.assertRaises(HTTPError):urlopen(Request(base+'/api/image-provider',body,headers=headers))

    def test_browser_switch_without_discarding_form_and_persists_after_reload(self):
        try:from playwright.sync_api import sync_playwright,expect,Error as BrowserError
        except ImportError:raise unittest.SkipTest('Playwright unavailable')
        _,base=self.serve()
        with sync_playwright() as p:
            try:browser=p.chromium.launch(channel='chrome',headless=True)
            except BrowserError as error:raise unittest.SkipTest(str(error))
            page=browser.new_page(viewport=dict(width=1280,height=900));page.set_default_timeout(7000)
            errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
            page.goto(base+'/buildings.html');picker=page.get_by_label('图片服务',exact=True)
            expect(picker).to_have_value('google_cloud')
            page.get_by_label('名称',exact=True).fill('未提交的建筑草稿')
            picker.select_option('openai_compatible');page.get_by_role('button',name='切换',exact=True).click()
            page.get_by_text('图片服务：兼容接口',exact=False).wait_for()
            expect(page.get_by_label('名称',exact=True)).to_have_value('未提交的建筑草稿')
            page.reload();expect(picker).to_have_value('openai_compatible')
            expect(page.get_by_label('名称',exact=True)).to_have_value('未提交的建筑草稿')
            picker.select_option('google_cloud');page.get_by_role('button',name='切换',exact=True).click()
            page.get_by_text('图片服务：Google Cloud Vertex AI',exact=False).wait_for()
            # Same entry is available on the hub and small screens.
            page.goto(base+'/');expect(picker).to_have_value('google_cloud')
            page.set_viewport_size(dict(width=390,height=900))
            self.assertFalse(page.evaluate('document.documentElement.scrollWidth>innerWidth'))
            self.assertFalse(errors);browser.close()


if __name__=='__main__':unittest.main()
