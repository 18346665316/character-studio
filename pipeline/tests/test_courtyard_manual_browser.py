"""Manual clicks must produce the same coordinates as courtyard expansion."""
from pathlib import Path
from http.server import ThreadingHTTPServer
import sys,tempfile,threading,unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from panel import Panel,handler
from asset_repository import read
import static_props as props
import scene_modules as scenes
from courtyard_ring import reference
from test_wall_repeat import provider_result
try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright=None


@unittest.skipIf(sync_playwright is None,'Playwright unavailable')
class CourtyardManualBrowser(unittest.TestCase):
    def test_corner_wall_repeat_and_far_corner_snap_without_grid_rounding(self):
        with tempfile.TemporaryDirectory() as tmp,sync_playwright() as pw:
            root=Path(tmp)
            with patch('static_props.configured',return_value=True):
                job=props.prepare(root,dict(mode='ai',kind='custom',description='wall',title='Yard',projection='isometric_2_1',courtyard_ring_build=True))
            with patch('static_props.generate_materials',side_effect=lambda f,s,p:provider_result(f,s,p,reference())):
                props.execute(root,job['id'])
            folder=root/'.local/props/jobs'/job['id'];ids=read(folder/'expansion-published.json');checks=read(folder/'expansion-checks.json')
            s=scenes.change(root,dict(action='create',title='Manual'));modules=[]
            for i in range(8):
                s=scenes.change(root,dict(action='adopt',scene=s['id'],revision=s['revision'],kit=ids[str(i)]));modules.append(s['modules'][-1])
            s=scenes.change(root,dict(action='layout',scene=s['id'],revision=s['revision'],instances=[dict(id='back',module=modules[0]['id'],position=[23,17])],spawn=[23,17]))
            server=ThreadingHTTPServer(('127.0.0.1',0),handler(Panel(root)));thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            browser=pw.chromium.launch(channel='chrome',headless=True)
            try:
                page=browser.new_page(viewport={'width':1440,'height':1100});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto('http://127.0.0.1:%s/module-scenes.html?scene=%s'%(server.server_port,s['id']))
                page.wait_for_function("() => document.querySelector('#layout-summary').textContent.includes('1 个实例')")
                canvas=page.locator('#scene-canvas');canvas.scroll_into_view_if_needed();w,h=canvas.evaluate('c=>[c.width,c.height]')
                zoom=max(.2,min(1.5,(w-100)/1024,(h-100)/1024))
                la,lb=checks['lengths']
                steps=[(4,[215,113]),(4,[215+la,113+la//2]),(1,[407+la,209+la//2]),
                       (6,[-169,113]),(6,[-169-lb,113+lb//2]),(3,[-361-lb,209+lb//2])]
                for index,(part,target) in enumerate(steps):
                    if index in (1,4):
                        page.locator('#duplicate').click()
                    else:
                        page.locator('[data-module="%s"]'%modules[part]['id']).click();page.locator('[data-tool="place"]').click()
                        canvas.click(position=dict(x=w/2+(target[0]+4-23)*zoom,y=h/2+(target[1]+3-229)*zoom))
                    page.locator('#save-layout').click();page.wait_for_function("() => document.querySelector('#layout-summary').textContent.includes('已保存')")
                    self.assertEqual(scenes.load(root,s['id'])['instances'][-1]['position'],target)
                page.reload();page.wait_for_function("() => document.querySelector('#layout-summary').textContent.includes('7 个实例')")
                self.assertTrue(all(m.get('assembly_ports') for m in scenes.load(root,s['id'])['modules']))
                self.assertEqual(errors,[])
            finally:
                browser.close();server.shutdown();server.server_close();thread.join()
