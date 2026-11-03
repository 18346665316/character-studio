"""Both straight axes snap to a generated corner's distinct ports."""
from pathlib import Path
from http.server import ThreadingHTTPServer
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from panel import Panel,handler
from asset_repository import read
import static_props as props
import scene_modules as scenes
from test_wall_corner import corner_art
from test_wall_repeat import provider_result
try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright=None


@unittest.skipIf(sync_playwright is None,'Playwright unavailable')
class WallCornerBrowser(unittest.TestCase):
    def test_both_axes_snap_to_corner_ports_and_persist(self):
        with tempfile.TemporaryDirectory() as tmp,sync_playwright() as pw:
            root=Path(tmp)
            with patch('static_props.configured',return_value=True):
                job=props.prepare(root,dict(mode='ai',kind='custom',description='wall',title='Corner',projection='isometric_2_1',wall_corner_build=True))
            with patch('static_props.generate_materials',side_effect=lambda f,s,p:provider_result(f,s,p,corner_art())):
                props.execute(root,job['id'])
            ids=read(root/'.local/props/jobs'/job['id']/'corner-published.json')
            scene=scenes.change(root,dict(action='create',title='Ports'));modules={}
            for role in ('corner','a','b'):
                scene=scenes.change(root,dict(action='adopt',scene=scene['id'],revision=scene['revision'],kit=ids[role]))
                modules[role]=scene['modules'][-1]
            scene=scenes.change(root,dict(action='layout',scene=scene['id'],revision=scene['revision'],instances=[dict(id='corner',module=modules['corner']['id'],position=[23,17])],spawn=[23,17]))
            server=ThreadingHTTPServer(('127.0.0.1',0),handler(Panel(root)))
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            browser=pw.chromium.launch(channel='chrome',headless=True)
            try:
                page=browser.new_page(viewport={'width':1440,'height':1100});errors=[]
                page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto('http://127.0.0.1:%s/module-scenes.html?scene=%s'%(server.server_port,scene['id']))
                page.wait_for_function("() => document.querySelector('#layout-summary').textContent.includes('1 个实例')")
                for axis in ('a','b'):
                    page.locator('[data-module="%s"]'%modules[axis]['id']).click()
                    page.locator('[data-tool="place"]').click()
                    canvas=page.locator('#scene-canvas');canvas.scroll_into_view_if_needed()
                    w,h=canvas.evaluate('c=>[c.width,c.height]')
                    zoom=max(.2,min(1.5,(w-100)/768,(h-100)/768))
                    port=modules['corner']['corner_ports'][axis];target=[23+port[0],17+port[1]]
                    canvas.click(position=dict(x=w/2+(target[0]+4-23)*zoom,y=h/2+(target[1]+3-1)*zoom))
                    page.locator('#save-layout').click()
                    page.wait_for_function("() => document.querySelector('#layout-summary').textContent.includes('已保存')")
                    saved=scenes.load(root,scene['id'])
                    self.assertEqual(saved['instances'][-1]['position'],target)
                self.assertEqual(errors,[])
            finally:
                browser.close();server.shutdown();server.server_close();thread.join()
