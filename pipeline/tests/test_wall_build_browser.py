"""Studio project button runs the build; only the remote image response is fake."""
from http.server import ThreadingHTTPServer
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from panel import Panel,handler
from asset_repository import read
import studio_projects as projects
import static_props as props
from test_wall_repeat import art,provider_result
try:
    from playwright.sync_api import sync_playwright,expect
except ImportError:
    sync_playwright=None


@unittest.skipIf(sync_playwright is None,'Playwright unavailable')
class WallBuildBrowser(unittest.TestCase):
    def test_generate_button_builds_and_rejection_keeps_current_material(self):
        with tempfile.TemporaryDirectory() as tmp, sync_playwright() as pw:
            root=Path(tmp);p=projects.change(root,dict(action='create',title='院墙自动构建',baseline=dict(style='painted')))
            p=projects.change(root,dict(action='add',project=p['id'],revision=p['revision'],kind='prop',title='A轴院墙',description='painted wall'))
            entry=p['items'][0]['id']
            p=projects.change(root,dict(action='wall_template',project=p['id'],revision=p['revision'],item=entry,axis='a'))
            panel=Panel(root);bad=[False]
            def run_worker(data,components=False,props=False):
                # Same prepare/execute used by the child process; synchronous
                # execution keeps this browser test deterministic.
                self.assertTrue(props)
                import static_props
                job=static_props.prepare(root,data);static_props.execute(root,job['id'])
                return read(root/'.local/props/jobs'/job['id']/'job.json')
            server=ThreadingHTTPServer(('127.0.0.1',0),handler(panel))
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            browser=pw.chromium.launch(channel='chrome',headless=True)
            try:
                with patch.object(panel,'start_terrain',side_effect=run_worker),patch('static_props.configured',return_value=True),patch('terrain_images.configured',return_value=True),patch('static_props.generate_materials',side_effect=lambda f,s,p:provider_result(f,s,p,art(drift=bad[0]))) as provider:
                    page=browser.new_page(viewport={'width':1400,'height':1000});errors=[]
                    page.on('pageerror',lambda e:errors.append(str(e)))
                    page.goto('http://127.0.0.1:%s/?project=%s&view=production'%(server.server_port,p['id']))
                    page.get_by_role('button',name='生成',exact=True).click()
                    expect(page.get_by_role('button',name='重新生成',exact=True)).to_be_visible(timeout=10000)
                    current=projects.current_assets(root,projects.load(root,p['id']))[entry]['id']
                    manifest=props.load_package(root,current)
                    self.assertEqual(manifest['processing']['method'],'automatic_wall_repeat')
                    page.get_by_role('button',name='详情',exact=True).click()
                    expect(page.get_by_role('heading',name='连续拼接',exact=True)).to_be_visible()
                    repeat=page.get_by_alt_text('同一墙段连续拼接三次')
                    expect(repeat).to_be_visible()
                    expect(repeat).to_have_js_property('naturalWidth',1024)
                    page.get_by_role('button',name='关闭',exact=True).click()
                    bad[0]=True
                    page.get_by_role('button',name='重新生成',exact=True).click()
                    expect(page.get_by_role('button',name='重新生成',exact=True)).to_be_enabled(timeout=10000)
                    page.get_by_role('button',name='详情',exact=True).click()
                    expect(page.get_by_text('长墙切割后边界差异仍过大',exact=False)).to_be_visible(timeout=10000)
                    latest=projects.load(root,p['id'])
                    self.assertEqual(projects.current_assets(root,latest)[entry]['id'],current)
                    self.assertEqual(projects.task_state(root,latest)[-1]['status'],'failed')
                    self.assertEqual(provider.call_count,2)
                    self.assertEqual(errors,[])
            finally:
                browser.close();server.shutdown();server.server_close();thread.join()
