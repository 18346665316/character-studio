"""Exercise real canvas placement, connector snapping and saved scene reload."""
from http.server import ThreadingHTTPServer
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from panel import Panel,handler
import scene_modules as scenes
import wall_assets as walls
from test_wall_assets import fixture
try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright=None


@unittest.skipIf(sync_playwright is None,'Playwright unavailable')
class WallSceneBrowser(unittest.TestCase):
    def test_both_axes_snap_off_grid_endpoints_and_persist(self):
        with tempfile.TemporaryDirectory() as tmp, sync_playwright() as pw:
            root=Path(tmp)
            server=ThreadingHTTPServer(('127.0.0.1',0),handler(Panel(root)))
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            browser=pw.chromium.launch(channel='chrome',headless=True)
            try:
                page=browser.new_page(viewport={'width':1440,'height':1100})
                errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                for axis,delta in [('a',[128,64]),('b',[-128,64])]:
                    folder=root/('input-'+axis);(folder/'inputs').mkdir(parents=True)
                    spec={'title':'Wall '+axis,'description':'plain plaster wall'};walls.configure(folder,spec,axis)
                    fixture(axis).save(folder/'inputs/original.png')
                    kit=walls.publish(root,folder,spec)
                    scene=scenes.change(root,dict(action='create',title='Snap '+axis))
                    scene=scenes.change(root,dict(action='adopt',scene=scene['id'],revision=scene['revision'],kit=kit['id']))
                    module=scene['modules'][0]
                    scene=scenes.change(root,dict(action='layout',scene=scene['id'],revision=scene['revision'],instances=[dict(id='first',module=module['id'],position=[23,17])],spawn=[0,150]))
                    page.goto('http://127.0.0.1:%s/module-scenes.html?scene=%s'%(server.server_port,scene['id']))
                    page.wait_for_function("() => document.querySelector('#layout-summary').textContent.includes('1 个实例')")
                    page.locator('[data-tool="place"]').click()
                    canvas=page.locator('#scene-canvas');canvas.scroll_into_view_if_needed()
                    # fitView includes the entire fixed 512px source canvas.
                    bounds=canvas.bounding_box()
                    width,height=page.eval_on_selector('#scene-canvas','c=>[c.width,c.height]')
                    zoom=max(.2,min(1.5,(width-100)/512,(height-100)/512))
                    def click_world(p):
                        canvas.click(position={'x':(width/2+(p[0]-23)*zoom)*bounds['width']/width,
                                               'y':(height/2+(p[1]+7)*zoom)*bounds['height']/height})
                    expected=[23+delta[0],17+delta[1]]
                    click_world([expected[0]+6,expected[1]+4])
                    page.locator('#save-layout').click()
                    page.wait_for_function("() => document.querySelector('#layout-summary').textContent.includes('2 个实例') && document.querySelector('#layout-summary').textContent.includes('已保存')")
                    saved=scenes.load(root,scene['id']);self.assertEqual(saved['instances'][-1]['position'],expected)
                    page.reload()
                    page.wait_for_function("() => document.querySelector('#layout-summary').textContent.includes('2 个实例')")
                    self.assertEqual(scenes.load(root,scene['id'])['instances'][-1]['position'],expected)
                    page.locator('[data-tool="select"]').click()
                    canvas.scroll_into_view_if_needed();bounds=canvas.bounding_box()
                    width,height=page.eval_on_selector('#scene-canvas','c=>[c.width,c.height]')
                    minx=min(23,expected[0])-256;maxx=max(23,expected[0])+256
                    miny=17-280;maxy=expected[1]-280+512
                    zoom=max(.2,min(1.5,(width-100)/(maxx-minx),(height-100)/(maxy-miny)))
                    def screen(p):
                        return (bounds['x']+(width/2+(p[0]-(minx+maxx)/2)*zoom)*bounds['width']/width,
                                bounds['y']+(height/2+(p[1]-(miny+maxy)/2)*zoom)*bounds['height']/height)
                    # Move the second wall before the first, with a small error.
                    inside=[expected[0]+delta[0]/2,expected[1]-16]
                    target=[23-delta[0],17-delta[1]]
                    page.mouse.move(*screen(inside));page.mouse.down()
                    page.mouse.move(*screen([inside[0]-2*delta[0]+6,inside[1]-2*delta[1]+4]),steps=5)
                    page.mouse.up();page.locator('#save-layout').click()
                    page.wait_for_function("() => document.querySelector('#layout-summary').textContent.includes('已保存')")
                    self.assertEqual(scenes.load(root,scene['id'])['instances'][-1]['position'],target)
                self.assertEqual(errors,[])
            finally:
                browser.close();server.shutdown();server.server_close();thread.join()
