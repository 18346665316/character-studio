"""Browser regressions for asset context, task routing and adjustment drafts.

Run with the Studio Python environment. Uses a temporary local server and mocked
API/asset responses; every POST is intercepted, so no production can start.
Requires Playwright and an installed Google Chrome.
"""
import copy
from http.server import ThreadingHTTPServer
from io import BytesIO
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from urllib.parse import urlparse

from PIL import Image
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from panel import Panel, handler
from static_props import KINDS
try:
    from playwright.sync_api import sync_playwright, Error as BrowserError
except ImportError:
    sync_playwright = None


def prop(identity, parent=None):
    return {'id': identity, 'title': identity, 'asset_kind': 'crate',
            'view': 'isometric_2_1', 'canvas_px': [256, 256],
            'anchor_px': [128, 210], 'integrity': {'passed': True},
            'provenance': {'art_source': 'external_complete_object',
                           **({'parent_kit': parent} if parent else {})},
            'suggested_collision': {'usage': 'blocking', 'width_px': 100,
                                    'depth_px': 50}}


@unittest.skipIf(sync_playwright is None, 'Playwright is not installed')
class PanelOperationsBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        try:
            cls.browser = cls.playwright.chromium.launch(channel='chrome', headless=True)
        except BrowserError as exc:
            cls.playwright.stop()
            raise unittest.SkipTest('Google Chrome is unavailable: ' + str(exc))
        cls.temp = tempfile.TemporaryDirectory()
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), handler(Panel(Path(cls.temp.name))))
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f'http://127.0.0.1:{cls.server.server_port}'
        png = BytesIO()
        Image.new('RGBA', (256, 256), (130, 110, 70, 255)).save(png, 'PNG')
        cls.png = png.getvalue()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
        cls.temp.cleanup()

    def setUp(self):
        self.context = self.browser.new_context(viewport={'width': 1280, 'height': 900})
        self.addCleanup(self.context.close)
        self.page = self.context.new_page()
        self.page.set_default_timeout(5000)
        self.errors, self.posts = [], []
        self.page.on('pageerror', lambda error: self.errors.append(str(error)))
        self.props = {'kits': [prop('a'), prop('b', 'a'), prop('unrelated')],
                      'jobs': [
                          {'id': 'done', 'kit_id': 'b', 'status': 'complete',
                           'stage': '物件已完成', 'spec': {'title': 'b', 'kind': 'crate'}},
                          {'id': 'failed', 'status': 'failed', 'error': '原任务失败',
                           'stage': '失败', 'spec': {'title': '失败任务', 'kind': 'crate'}}],
                      'token': 'test', 'image_api_configured': True, 'kinds': KINDS}
        self.terrain = {'kits': [], 'transitions': [], 'jobs': [], 'token': 'test',
                        'image_api_configured': True}
        self.post_result = None
        self.context.route('**/api/**', self.api)
        self.context.route('**/prop-asset/**', lambda route: route.fulfill(
            content_type='image/png', body=self.png))
        self.context.route('**/terrain-asset/**', lambda route: route.fulfill(
            content_type='image/png', body=self.png))

    def api(self, route):
        path = urlparse(route.request.url).path
        if route.request.method == 'POST':
            self.posts.append((path, route.request.post_data_json))
            if self.post_result:
                route.fulfill(json=self.post_result)
            else:
                route.fulfill(status=400, json={'error': '请求被拒绝（测试）'})
        elif path == '/api/props/state':
            route.fulfill(json=self.props)
        elif path == '/api/props/settings':
            from urllib.parse import parse_qs
            identity=parse_qs(urlparse(route.request.url).query)['kit'][0]
            item=next(k for k in self.props['kits'] if k['id']==identity)
            route.fulfill(json={'sha256':'test','settings':{'title':item['title'],'anchor':item['anchor_px'],
                'behavior':'blocking','polygons':[[[-50,-25],[50,-25],[50,25],[-50,25]]]}})
        elif path == '/api/terrain/state':
            route.fulfill(json=self.terrain)
        elif path == '/api/components/state':
            route.fulfill(json={'kits': [], 'jobs': [], 'token': 'test'})
        elif path == '/api/state':
            route.fulfill(json={'characters': [], 'jobs': [], 'token': 'test'})
        else:
            route.fulfill(status=404, json={'error': 'Unmocked API: ' + path})

    def open_prop(self, identity='a'):
        self.page.goto(self.url + '/props.html?kit=' + identity)
        self.page.wait_for_selector('#prop-result:not([hidden])')
        self.page.get_by_role('tab', name='调整', exact=True).click()
        self.page.click('#prop-edit-settings')
        self.page.wait_for_selector('#module-dialog[open]')

    def test_new_page_never_borrows_a_historical_result(self):
        self.page.goto(self.url + '/props.html')
        self.page.wait_for_selector('#prop-kind:not([disabled])')
        self.assertTrue(self.page.locator('#prop-form').is_visible())
        self.assertFalse(self.page.locator('#prop-result').is_visible())
        self.assertEqual(self.page.locator('#prop-history option').count(), 0)
        self.assertFalse(self.errors)

    def test_related_version_switch_and_reload_keep_draft(self):
        self.page.on('dialog',lambda d:d.accept())
        self.open_prop()
        canvas=self.page.locator('#module-canvas')
        before=canvas.evaluate('(c)=>c.toDataURL()')
        self.page.click('#view-annotation')
        self.page.fill('#anchor-x','17.5');self.page.locator('#anchor-x').blur()
        self.assertNotEqual(before,canvas.evaluate('(c)=>c.toDataURL()'))
        self.open_prop('b')
        self.assertEqual(self.page.input_value('#anchor-x'),'128')
        self.open_prop('a')
        self.assertEqual(self.page.input_value('#anchor-x'),'17.5')
        self.page.reload()
        self.page.wait_for_selector('#prop-edit-settings')
        self.page.click('#prop-edit-settings')
        self.page.wait_for_selector('#module-dialog[open]')
        self.assertEqual(self.page.input_value('#anchor-x'),'17.5')
        self.assertFalse(self.errors)

    def test_task_error_is_visible_and_completed_task_opens_exact_result(self):
        self.page.goto(self.url + '/props.html?task=failed')
        self.page.wait_for_selector('.studio-task-focus')
        self.page.locator('.studio-task-focus').get_by_role('button', name='继续任务（可能产生费用）', exact=True).click()
        self.page.wait_for_function("() => document.querySelector('#asset-feedback').textContent==='请求被拒绝（测试）'")
        self.assertTrue(self.page.locator('#asset-feedback').is_visible())
        self.assertEqual(self.posts[-1][1], {'resume': 'failed'})
        self.page.goto(self.url + '/props.html?task=done')
        self.page.locator('.job-result-link:visible').click()
        self.page.wait_for_selector('#prop-result:not([hidden])')
        self.assertEqual(self.page.locator('#prop-history').input_value(), 'b')
        self.assertTrue(self.page.locator('#asset-delivery').is_visible())
        self.assertFalse(self.errors)

    def test_successful_submit_tracks_only_the_new_job(self):
        self.post_result = {'id': 'new-job'}
        self.props['jobs'].append({'id': 'new-job', 'status': 'queued', 'stage': '等待制作',
                                   'spec': {'title': '新物件', 'kind': 'rock'}})
        # Only the other queued job would disable creation, so introduce it after submit.
        queued = self.props['jobs'].pop()
        self.page.goto(self.url + '/props.html')
        self.page.wait_for_selector('#prop-kind:not([disabled])')
        self.props['jobs'].append(queued)
        self.page.locator('#prop-generate').click()
        self.page.wait_for_url('**/props.html?task=new-job')
        self.page.wait_for_selector('.studio-task-focus')
        self.assertIn('新物件', self.page.locator('#asset-feedback').inner_text())
        self.assertFalse(self.page.locator('#prop-result').is_visible())
        self.assertFalse(self.errors)

    def test_terrain_remake_submits_edited_name_and_keeps_source(self):
        self.terrain['kits'] = [{'id': 'ground', 'title': '原地面', 'asset_type': 'material',
            'material_kind': 'grass', 'projection': 'top_down', 'view': 'top_down',
            'tile_size': 64, 'road_width': .5, 'finish': 'natural', 'description': '草地',
            'variants': [{'ground_cell': [0, 0]}], 'integrity': {'passed': True},
            'validation': {'matching_edge_pairs': 2, 'max_channel_difference': 0}}]
        self.page.goto(self.url + '/terrain.html?kit=ground')
        self.page.wait_for_selector('#kit-result:not([hidden])')
        self.page.get_by_role('tab', name='调整', exact=True).click()
        self.page.locator('#kit-title').fill('新的地面名称')
        self.page.locator('#kit-title').press('Enter')
        self.page.wait_for_function("() => document.querySelector('#asset-feedback').textContent==='请求被拒绝（测试）'")
        self.assertEqual(self.posts[-1][1]['title'], '新的地面名称')
        self.assertEqual(self.posts[-1][1]['source_kit'], 'ground')
        self.assertEqual(self.posts[-1][1]['mode'], 'reuse')
        self.assertFalse(self.errors)

    def test_terrain_import_only_sends_images_and_output_settings(self):
        for path in ['/terrain.html','/water.html']:
            self.page.goto(self.url+path)
            self.page.wait_for_function("() => !document.querySelector('#generate').disabled")
            self.page.locator('#source-mode').select_option('import')
            self.page.locator('#kit-title').fill('导入素材')
            self.assertFalse(self.page.locator('#terrain-ai').is_visible())
            self.assertFalse(self.page.locator('#material-kind').is_visible())
            self.page.locator('#ground-file').set_input_files(
                {'name':'texture.png','mimeType':'image/png','buffer':self.png})
            self.page.locator('#generate').click()
            self.page.wait_for_function("() => document.querySelector('#asset-feedback').textContent==='请求被拒绝（测试）'")
            data=self.posts[-1][1]
            self.assertEqual(data['mode'],'import')
            self.assertIn('ground',data)
            for unused in ['reference','description','road','road_width']:
                self.assertNotIn(unused,data)
        self.assertFalse(self.errors)

    def test_terrain_mode_switch_keeps_ai_draft_but_import_does_not_require_it(self):
        self.page.goto(self.url+'/terrain.html')
        self.page.wait_for_function("() => !document.querySelector('#generate').disabled")
        self.page.locator('#description').fill('蓝色岩石纹理')
        self.page.locator('#source-mode').select_option('import')
        self.assertTrue(self.page.locator('#description').is_disabled())
        self.page.locator('#source-mode').select_option('ai')
        self.assertEqual(self.page.locator('#description').input_value(),'蓝色岩石纹理')
        self.page.locator('#kit-title').fill('新纹理')
        self.page.locator('#generate').click()
        self.page.wait_for_function("() => document.querySelector('#asset-feedback').textContent==='请求被拒绝（测试）'")
        self.assertEqual(self.posts[-1][1]['description'],'蓝色岩石纹理')
        self.assertNotIn('ground',self.posts[-1][1])
        self.assertFalse(self.errors)

    def test_road_import_requires_both_textures_and_has_fixed_top_down_output(self):
        self.page.goto(self.url+'/terrain.html?type=terrain')
        self.page.wait_for_function("() => !document.querySelector('#generate').disabled")
        self.page.locator('#source-mode').select_option('import')
        self.page.locator('#kit-title').fill('道路')
        self.assertFalse(self.page.locator('#terrain-projection-field').is_visible())
        self.assertTrue(self.page.locator('#road-width-field').is_visible())
        self.page.locator('#ground-file').set_input_files(
            {'name':'ground.png','mimeType':'image/png','buffer':self.png})
        self.page.locator('#generate').click()
        self.assertEqual(len(self.posts),0)
        self.page.locator('#road-file').set_input_files(
            {'name':'road.png','mimeType':'image/png','buffer':self.png})
        self.page.locator('#generate').click()
        self.page.wait_for_function("() => document.querySelector('#asset-feedback').textContent==='请求被拒绝（测试）'")
        self.assertIn('road',self.posts[-1][1])
        self.assertEqual(self.posts[-1][1]['projection'],'top_down')
        self.assertFalse(self.errors)

    def test_prop_import_explains_existing_view_and_omits_ai_inputs(self):
        self.page.goto(self.url+'/props.html')
        self.page.wait_for_selector('#prop-kind:not([disabled])')
        self.page.locator('#prop-mode').select_option('import')
        self.assertEqual(self.page.locator('#prop-projection-label').inner_text(),'原图片的视角')
        self.page.locator('#prop-image').set_input_files(
            {'name':'object.png','mimeType':'image/png','buffer':self.png})
        self.page.locator('#prop-generate').click()
        self.page.wait_for_function("() => document.querySelector('#asset-feedback').textContent==='请求被拒绝（测试）'")
        self.assertIn('image',self.posts[-1][1])
        self.assertNotIn('description',self.posts[-1][1])
        self.assertNotIn('reference',self.posts[-1][1])
        self.assertFalse(self.errors)

    def test_fence_import_uses_only_wood_texture(self):
        self.page.goto(self.url+'/components.html')
        self.page.wait_for_function("() => document.querySelector('#component-api').textContent.length>0")
        self.page.locator('#component-source').select_option('import')
        self.assertFalse(self.page.locator('#ai-input').is_visible())
        self.page.locator('#wood-file').set_input_files(
            {'name':'wood.png','mimeType':'image/png','buffer':self.png})
        self.page.locator('#component-build').click()
        self.page.wait_for_function("() => document.querySelector('#asset-feedback').textContent==='请求被拒绝（测试）'")
        self.assertEqual(set(self.posts[-1][1]),{'mode','wood'})
        self.assertFalse(self.errors)

    def test_transition_requires_explicit_sources_and_uses_source_size(self):
        self.terrain['kits']=[{'id':k,'title':k,'tile_size':64,'view':'top_down',
                              'asset_type':'material'} for k in ['a','b']]
        self.page.goto(self.url+'/transition.html')
        self.page.wait_for_selector('#base-kit option[value="a"]',state='attached')
        self.assertEqual(self.page.locator('#base-kit').input_value(),'')
        self.assertEqual(self.page.locator('#overlay-kit').input_value(),'')
        self.assertTrue(self.page.locator('#transition-generate').is_disabled())
        self.page.locator('#base-kit').select_option('a')
        self.page.locator('#overlay-kit').select_option('b')
        self.assertFalse(self.page.locator('#transition-generate').is_disabled())
        self.assertIn('64',self.page.locator('#transition-size-display').inner_text())
        self.assertFalse(self.errors)

    def test_anchor_pointer_and_mobile_page_fit(self):
        self.open_prop()
        self.page.set_viewport_size({'width': 390, 'height': 844})
        self.page.click('#view-annotation')
        self.page.select_option('#edit-mode','anchor')
        self.page.locator('#module-canvas').click(position={'x': 30, 'y': 30})
        self.assertNotEqual(self.page.locator('#anchor-x').input_value(), '128')
        self.page.on('dialog',lambda d:d.accept())
        self.page.click('#close-editor')
        for tab in ['预览', '调整', '来源与记录']:
            self.page.get_by_role('tab', name=tab, exact=True).click()
            self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
        self.assertFalse(self.errors)


if __name__ == '__main__':
    unittest.main()
