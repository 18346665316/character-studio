"""MVP scene persistence, delivery, and HTTP boundaries."""
import base64
from hashlib import sha256
from http.server import ThreadingHTTPServer
from io import BytesIO
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import zipfile
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import scene_modules as sm
from panel import Panel, handler


def png():
    image=Image.new('RGBA',(128,128),(0,0,0,0))
    from PIL import ImageDraw
    ImageDraw.Draw(image).rectangle((0,40,127,110),fill='#9b8064')
    stream=BytesIO();image.save(stream,format='PNG')
    return stream.getvalue()


class ModuleSceneTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.scene=sm.change(self.root,dict(action='create',title='模块测试'))

    def change(self,**kw):
        self.scene=sm.change(self.root,dict(scene=self.scene['id'],revision=self.scene['revision'],**kw))
        return self.scene

    def imported(self):
        self.change(action='import',title='墙',image=base64.b64encode(png()).decode())
        return self.scene['modules'][-1]

    def test_roundtrip_repeated_instances_and_export_bytes(self):
        module=self.imported()
        shape=[[-60,-4],[60,-4],[60,4],[-60,4]]
        self.change(action='module',module=module['id'],title='墙',anchor=[64,100],behavior='blocking',polygons=[shape])
        instances=[dict(id='one',module=module['id'],position=[0,0]),dict(id='two',module=module['id'],position=[128,0])]
        self.change(action='layout',instances=instances,spawn=[0,100])
        loaded=sm.load(self.root,self.scene['id']);self.assertEqual(loaded['instances'],instances)
        with zipfile.ZipFile(BytesIO(sm.export(self.root,self.scene['id']))) as archive:
            self.assertEqual(json.loads(archive.read('scene.json')),loaded)
            raw=archive.read('images/'+module['image'])
            self.assertEqual(raw,png());self.assertEqual(sha256(raw).hexdigest()+'.png',module['image'])
            self.assertIn('move_and_slide',archive.read('scene.gd').decode())
        old=self.scene['revision']
        self.change(action='layout',instances=instances[:1],spawn=[0,100])
        with self.assertRaises(ValueError):sm.change(self.root,dict(action='layout',scene=self.scene['id'],revision=old,instances=[],spawn=[0,0]))

    def test_invalid_geometry_and_behavior_are_atomic(self):
        m=self.imported();before=sm.load(self.root,self.scene['id'])
        for behavior,shapes in [('blocking',[]),('opening',[[[0,0],[10,0],[10,10],[0,10]]]),('passable',[[[0,0],[10,0],[0,10]]]),('blocking',[[[0,0],[10,10],[0,10],[10,0]]])]:
            with self.assertRaises(ValueError):self.change(action='module',module=m['id'],title='bad',anchor=[64,100],behavior=behavior,polygons=shapes)
            self.assertEqual(sm.load(self.root,self.scene['id']),before)
        with self.assertRaises(ValueError):self.change(action='layout',instances=[dict(id='a',module='missing',position=[0,0])],spawn=[0,0])
        with self.assertRaises(ValueError):self.change(action='layout',instances=[],spawn=[float('nan'),0])

    def test_size_validation_versions_and_export(self):
        from static_props import load_package
        m=self.imported();before=sm.load(self.root,self.scene['id'])
        self.assertEqual(m['world_scale'],1)
        for scale in [0,-1,.001,101,True,'1',float('nan'),float('inf')]:
            with self.assertRaises(ValueError):
                self.change(action='module',module=m['id'],title='尺寸',anchor=[64,100],behavior='passable',polygons=[],world_scale=scale)
            self.assertEqual(sm.load(self.root,self.scene['id']),before)
        source=m['source']['id'];original=(self.root/'prop-kits'/source/'kit.zip').read_bytes()
        self.change(action='module',module=m['id'],title='半尺寸',anchor=[64,100],behavior='passable',polygons=[],world_scale=.5)
        current=self.scene['modules'][0]
        self.assertEqual(current['world_scale'],.5)
        manifest=load_package(self.root,current['source']['id'])
        self.assertEqual(manifest['display_spec']['canvas_world_units'],[64,64])
        self.assertEqual((self.root/'prop-kits'/source/'kit.zip').read_bytes(),original)
        self.assertEqual((self.root/'prop-kits'/manifest['id']/'sprite.png').read_bytes(),png())
        with zipfile.ZipFile(BytesIO(sm.export(self.root,self.scene['id']))) as archive:
            self.assertEqual(json.loads(archive.read('scene.json'))['modules'][0]['world_scale'],.5)
        # Legacy cached modules acquire the default without rewriting the file.
        old=before;old['modules'][0].pop('world_scale')
        path=sm.directory(self.root)/(old['id']+'.json');path.write_text(json.dumps(old))
        self.assertEqual(sm.load(self.root,old['id'])['modules'][0]['world_scale'],1)

    def test_terrain_adoption_layer_integrity_and_export(self):
        kit='terrain-fixture';folder=self.root/'terrain-kits'/kit;folder.mkdir(parents=True)
        manifest=dict(id=kit,title='地面',view='isometric_2_1',asset_type='material',ground='tiles/ground.png',tiles=[],
            projection_spec=dict(cell_px=[128,64],variants=[dict(image='tiles/ground.png',anchor_px=[64,32])]))
        files={'preview.png':png(),'atlas.png':png(),'ground_material.png':png(),'tiles/ground.png':png(),
               'INTEGRATION.md':b'fixture','manifest.json':json.dumps(manifest).encode()}
        with zipfile.ZipFile(folder/'kit.zip','w') as z:
            for name,raw in files.items():
                path=folder/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw);z.writestr(name,raw)
        self.change(action='adopt',family='terrain',kit=kit)
        m=self.scene['modules'][0]
        self.assertEqual(m['layer'],'ground');self.assertEqual(m['polygons'],[])
        self.assertEqual(m['source']['family'],'terrain')
        self.assertTrue(any(a.get('family')=='terrain' for a in sm.library(self.root)))
        with zipfile.ZipFile(BytesIO(sm.export(self.root,self.scene['id']))) as z:
            self.assertEqual(z.read('images/'+m['image']),png())
            self.assertEqual(z.read('assets/'+kit+'.zip'),(folder/'kit.zip').read_bytes())
        with self.assertRaisesRegex(ValueError,'地面工作台'):
            self.change(action='module',module=m['id'],title='改',anchor=[64,32],behavior='passable',polygons=[])
        # A cached ground layer cannot be changed independently of its terrain version.
        path=sm.directory(self.root)/(self.scene['id']+'.json')
        changed=json.loads(path.read_text());changed['modules'][0]['layer']='objects';path.write_text(json.dumps(changed))
        with self.assertRaises(ValueError):sm.load(self.root,self.scene['id'])
        path.write_text(json.dumps(self.scene));(folder/'tiles/ground.png').write_bytes(b'corrupt')
        with self.assertRaises(ValueError):sm.export(self.root,self.scene['id'])

    def transition_fixture(self):
        kit='transition-fixture';folder=self.root/'terrain-transitions'/kit;folder.mkdir(parents=True)
        tiles=[dict(corners=b,variant=v,image=f'tiles/iso-{b}-{v}.png',anchor_px=[64,32])
               for b,v in [(0,0),(3,1)]]
        tiles[1].update(behavior='blocking',polygons=[[[0,-32],[64,0],[0,32],[-64,0]]])
        manifest=dict(id=kit,title='草土',schema='studio.terrain-transition/0.1',
            view='isometric_2_1',tiles=[dict(image='tiles/top.png')],
            projection_spec=dict(tiles=tiles))
        files={'preview.png':png(),'atlas.png':png(),'tiles/top.png':png(),'INTEGRATION.md':b'fixture',
               'manifest.json':json.dumps(manifest).encode()}
        files.update({t['image']:png() for t in tiles})
        with zipfile.ZipFile(folder/'kit.zip','w') as z:
            for relative,raw in files.items():
                path=folder/relative;path.parent.mkdir(parents=True,exist_ok=True)
                path.write_bytes(raw);z.writestr(relative,raw)
        return kit,tiles

    def test_transition_selectors_pin_distinct_tiles_and_export_one_source(self):
        kit,tiles=self.transition_fixture()
        folder=self.root/'terrain-transitions'/kit
        for b,v in [(0,0),(3,1),(3,1)]:
            self.change(action='adopt',family='transition',kit=kit,corners=b,variant=v)
        self.assertEqual(len(self.scene['modules']),2)
        self.assertEqual(self.scene['modules'][1]['source']['corners'],3)
        self.assertEqual(self.scene['modules'][1]['layer'],'ground')
        self.assertEqual(self.scene['modules'][1]['behavior'],'blocking')
        self.assertEqual(self.scene['modules'][1]['polygons'],tiles[1]['polygons'])
        before=sm.load(self.root,self.scene['id'])
        for b,v in [(16,0),(3,9),(True,0),('3',1)]:
            with self.assertRaises(ValueError):
                self.change(action='adopt',family='transition',kit=kit,corners=b,variant=v)
            self.assertEqual(sm.load(self.root,self.scene['id']),before)
        with zipfile.ZipFile(BytesIO(sm.export(self.root,self.scene['id']))) as z:
            self.assertEqual(len([n for n in z.namelist() if n.startswith('assets/')]),1)
            self.assertEqual(z.read('assets/'+kit+'.zip'),(folder/'kit.zip').read_bytes())
        bad=dict(before);bad['modules']=json.loads(json.dumps(before['modules']))
        bad['modules'][1]['source']['variant']=8
        (sm.directory(self.root)/(bad['id']+'.json')).write_text(json.dumps(bad))
        with self.assertRaises(ValueError):sm.load(self.root,bad['id'])

    def test_image_integrity_and_paths(self):
        m=self.imported()
        with self.assertRaises(ValueError):sm.image_bytes(self.root,'../scene.json')
        (sm.directory(self.root)/'images'/m['image']).write_bytes(b'bad')
        with self.assertRaises(ValueError):sm.export(self.root,self.scene['id'])

    def test_http_auth_roundtrip(self):
        panel=Panel(self.root);server=ThreadingHTTPServer(('127.0.0.1',0),handler(panel))
        threading.Thread(target=server.serve_forever,daemon=True).start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        base='http://127.0.0.1:'+str(server.server_port)
        def post(data,token):
            return urlopen(Request(base+'/api/module-scenes/change',json.dumps(data).encode(),headers={'Content-Type':'application/json','X-Studio-Token':token}))
        with self.assertRaises(HTTPError):post(dict(action='create',title='no'),'bad')
        with urlopen(base+'/api/module-scenes/state') as r:self.assertEqual(json.load(r)['token'],panel.token)
        with post(dict(action='create',title='HTTP'),panel.token) as r:s=json.load(r)
        with urlopen(base+'/api/module-scenes/export?scene='+s['id']) as r:self.assertEqual(r.headers.get_content_type(),'application/zip')
        with urlopen(base+'/module-scenes.html') as r:self.assertIn(b'scene-canvas',r.read())
        with self.assertRaises(HTTPError):urlopen(base+'/api/module-scenes/image?file=../.env')

    def test_library_versions_are_shared_pinned_and_byte_preserving(self):
        from static_props import annotate,load_package,module_settings
        m=self.imported();source=m['source'];original=(self.root/'prop-kits'/source['id']/'kit.zip').read_bytes()
        second=sm.change(self.root,dict(action='create',title='第二场景'))
        second=sm.change(self.root,dict(action='adopt',scene=second['id'],revision=second['revision'],kit=source['id']))
        self.change(action='layout',instances=[dict(id='a',module=m['id'],position=[5,10])],spawn=[0,100])
        shapes=[[[-60,-5],[-20,-5],[-20,5],[-60,5]],[[20,-5],[60,-5],[60,5],[20,5]]]
        self.change(action='module',module=m['id'],title='开口',anchor=[64,100],behavior='opening',polygons=shapes)
        current=self.scene['modules'][0];self.assertNotEqual(current['source']['id'],source['id'])
        self.assertEqual((self.root/'prop-kits'/source['id']/'kit.zip').read_bytes(),original)
        self.assertEqual(sm.load(self.root,second['id'])['modules'][0]['source'],source)
        manifest=load_package(self.root,current['source']['id'])
        self.assertEqual(module_settings(manifest)['polygons'],shapes)
        self.assertEqual(manifest['provenance']['parent_kit'],source['id'])
        self.assertEqual((self.root/'prop-kits'/manifest['id']/'sprite.png').read_bytes(),png())
        self.assertEqual(self.scene['instances'][0]['position'],[5,10])
        with zipfile.ZipFile(BytesIO(sm.export(self.root,self.scene['id']))) as archive:
            raw=archive.read('assets/'+manifest['id']+'.zip')
            self.assertEqual(sha256(raw).hexdigest(),current['source']['sha256'])
        self.assertTrue(any(a['id']==manifest['id'] for a in sm.library(self.root)))
        # A version saved in the workbench can be explicitly selected by a scene.
        newer=annotate(self.root,dict(source_kit=manifest['id'],title='无阻挡版本',anchor=[64,100],behavior='passable',polygons=[]))
        self.change(action='adopt',kit=newer['id'],module=m['id'])
        self.assertEqual(self.scene['modules'][0]['behavior'],'passable')
        self.assertEqual(self.scene['instances'][0]['module'],m['id'])
        self.assertEqual(sm.load(self.root,second['id'])['modules'][0]['source'],source)

    def test_library_rejects_incompatible_projection_and_tampered_version(self):
        from static_props import import_exact
        kit=import_exact(self.root,dict(title='俯视',projection='orthographic_three_quarter',image=base64.b64encode(png()).decode()))
        with self.assertRaisesRegex(ValueError,'投影'):
            self.change(action='adopt',kit=kit['id'])
        m=self.imported()
        (self.root/'prop-kits'/m['source']['id']/'kit.zip').write_bytes(b'corrupt')
        with self.assertRaises(ValueError):sm.export(self.root,self.scene['id'])


class ModuleSceneBrowserTests(ModuleSceneTests):
    def test_tiled_scene_and_material_selection_preserves_layout(self):
        from playwright.sync_api import sync_playwright,expect
        module=self.imported()
        first=self.scene['id']
        second=sm.change(self.root,dict(action='create',title='第二个验证场景'))
        state=sm.state(self.root)
        summary=next(s for s in state['scenes'] if s['id']==first)
        self.assertEqual(summary['images'],[module['image']])
        self.assertEqual(summary['material_count'],1)
        panel=Panel(self.root);server=ThreadingHTTPServer(('127.0.0.1',0),handler(panel))
        threading.Thread(target=server.serve_forever,daemon=True).start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        with sync_playwright() as pw:
            browser=pw.chromium.launch(channel='chrome',headless=True)
            try:
                page=browser.new_page(viewport=dict(width=1440,height=1000));errors=[]
                page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto('http://127.0.0.1:'+str(server.server_port)+'/module-scenes.html')
                expect(page.locator('#scene-cards .scene-card')).to_have_count(2)
                expect(page.locator('#scenes, #modules, #tool')).to_have_count(0)
                expect(page.locator('#save-layout')).to_be_disabled()
                first_card=page.locator('[data-scene="'+first+'"]')
                expect(first_card.locator('img')).to_be_visible()
                first_card.focus();first_card.press('Enter')
                expect(first_card).to_have_attribute('aria-pressed','true')
                material=page.locator('#asset-cards .asset-card')
                expect(material.locator('img')).to_be_visible()
                material.click()
                expect(material).to_have_attribute('aria-pressed','true')
                page.locator('#scene-canvas').click(position=dict(x=200,y=180))
                page.locator('[data-scene="'+second['id']+'"]').click()
                expect(page.locator('[data-scene="'+second['id']+'"]')).to_have_attribute('aria-pressed','true')
                self.assertEqual(len(sm.load(self.root,first)['instances']),1)
                expect(page.locator('#asset-cards .asset-card')).to_have_count(0)
                page.locator('[data-scene="'+first+'"]').click()
                expect(page.locator('#layout-summary')).to_contain_text('1 个实例')
                page.set_viewport_size(dict(width=390,height=844))
                self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),392)
                self.assertEqual(errors,[])
            finally:browser.close()

    def test_browser_import_edit_place_save_reopen_export(self):
        from playwright.sync_api import sync_playwright
        panel=Panel(self.root);server=ThreadingHTTPServer(('127.0.0.1',0),handler(panel))
        threading.Thread(target=server.serve_forever,daemon=True).start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        base='http://127.0.0.1:'+str(server.server_port)
        with sync_playwright() as pw:
            browser=pw.chromium.launch(channel='chrome',headless=True)
            page=browser.new_page(viewport={'width':1440,'height':1100})
            errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(base+'/module-scenes.html?scene='+self.scene['id'])
            page.wait_for_selector('#workspace',state='visible')
            page.click('#show-import')
            page.fill('#module-title','浏览器导入')
            page.set_input_files('#image-file',dict(name='module.png',mimeType='image/png',buffer=png()))
            page.locator('#import-form button').last.click()
            page.wait_for_function('() => document.querySelector("#asset-cards").children.length === 1')
            page.click('#view-annotation')
            page.fill('#anchor-y','100');page.locator('#anchor-y').blur()
            page.locator('#module-dialog details').evaluate('(d)=>d.open=true')
            page.fill('#world-width','64');page.locator('#world-width').blur()
            self.assertEqual(page.input_value('#world-height'),'64')
            page.click('#save-module')
            page.wait_for_function('() => document.querySelector("#status").textContent.includes("模块设置已保存")')
            page.click('#close-editor')
            page.click('[data-tool=place]');page.locator('#scene-canvas').click(position={'x':250,'y':200})
            page.click('#duplicate');page.click('#save-layout')
            page.wait_for_function('() => document.querySelector("#status").textContent === "布局已保存。"')
            page.reload()
            page.wait_for_function('() => document.querySelector("#layout-summary").textContent.includes("2 个实例")')
            self.assertEqual(page.input_value('#anchor-y'),'100')
            self.assertEqual(page.input_value('#world-width'),'64')
            with page.expect_download() as pending:page.click('#export')
            file=self.root/'download.zip';pending.value.save_as(file)
            with zipfile.ZipFile(file) as z:
                saved=json.loads(z.read('scene.json'));self.assertEqual(len(saved['instances']),2)
                self.assertEqual(saved['modules'][0]['world_scale'],.5)
                self.assertEqual(z.read('images/'+saved['modules'][0]['image']),png())
            self.assertEqual(errors,[])
            browser.close()

    def test_size_preview_slider_invalid_input_and_reset(self):
        from playwright.sync_api import sync_playwright,expect
        self.imported()
        panel=Panel(self.root);server=ThreadingHTTPServer(('127.0.0.1',0),handler(panel))
        threading.Thread(target=server.serve_forever,daemon=True).start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        with sync_playwright() as pw:
            browser=pw.chromium.launch(channel='chrome',headless=True)
            page=browser.new_page(viewport={'width':1440,'height':900});errors=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto('http://127.0.0.1:'+str(server.server_port)+'/module-scenes.html?scene='+self.scene['id'])
            page.click('#open-editor')
            expect(page.locator('#view-size')).to_have_attribute('aria-pressed','true')
            canvas=page.locator('#module-canvas');before=canvas.evaluate('(c)=>c.toDataURL()')
            page.locator('#module-dialog details').evaluate('(d)=>d.open=true')
            page.locator('#world-scale-slider').press('End')
            self.assertEqual(page.input_value('#world-width'),'384')
            self.assertNotEqual(before,canvas.evaluate('(c)=>c.toDataURL()'))
            page.locator('#module-dialog details').evaluate('(d)=>d.open=true')
            page.fill('#world-percent','50')
            self.assertEqual(page.input_value('#world-height'),'64')
            expect(page.locator('#editor-save-state')).to_have_text('有未保存的修改')
            page.locator('#module-dialog details').evaluate('(d)=>d.open=true')
            page.fill('#world-width','0')
            page.click('#save-module')
            expect(page.locator('#editor-status')).to_contain_text('请先修正尺寸')
            self.assertEqual(sm.load(self.root,self.scene['id'])['modules'][0]['world_scale'],1)
            page.click('#reset-world-size')
            self.assertEqual(page.input_value('#world-percent'),'100')
            page.click('#view-annotation')
            expect(page.locator('#annotation-tools')).to_be_visible()
            page.click('#view-size')
            self.assertEqual(before,canvas.evaluate('(c)=>c.toDataURL()'))
            # The footer stays reachable on a small screen as content scrolls.
            page.set_viewport_size({'width':390,'height':844})
            rect=page.locator('#save-module').bounding_box()
            self.assertLessEqual(rect['y']+rect['height'],844)
            self.assertEqual(errors,[])
            browser.close()

    def test_subject_size_scales_export_without_changing_source_pixels(self):
        from playwright.sync_api import sync_playwright,expect
        original=self.imported()
        self.change(action='module',module=original['id'],title='带留白的物件',anchor=[64,110],
                    behavior='blocking',polygons=[[[-20,-10],[20,-10],[20,0],[-20,0]]],world_scale=1)
        panel=Panel(self.root);server=ThreadingHTTPServer(('127.0.0.1',0),handler(panel))
        threading.Thread(target=server.serve_forever,daemon=True).start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        with sync_playwright() as pw:
            browser=pw.chromium.launch(channel='chrome',headless=True)
            page=browser.new_page(viewport={'width':1440,'height':1000})
            page.goto('http://127.0.0.1:'+str(server.server_port)+'/module-scenes.html?scene='+self.scene['id'])
            page.click('#open-editor')
            # Canvas is 128x128, but visible pixels occupy only 128x71.
            self.assertEqual(page.input_value('#subject-height'),str(round(71/34,6)))
            page.fill('#subject-height',str(35.5/34))
            self.assertEqual(page.input_value('#world-height'),'64')
            self.assertEqual(page.input_value('#subject-width'),str(round(64/34,6)))
            page.fill('#subject-width','0')
            page.click('#save-module')
            expect(page.locator('#editor-status')).to_contain_text('请先修正尺寸')
            page.fill('#subject-height',str(35.5/34))
            page.click('#save-module')
            expect(page.locator('#status')).to_contain_text('模块设置已保存')
            page.click('#close-editor');page.click('#open-editor')
            self.assertEqual(page.input_value('#subject-height'),str(round(35.5/34,6)))
            page.set_viewport_size({'width':390,'height':844})
            self.assertFalse(page.evaluate('document.documentElement.scrollWidth>innerWidth'))
            exported=sm.export(self.root,self.scene['id'])
            with zipfile.ZipFile(BytesIO(exported)) as archive:
                m=json.loads(archive.read('scene.json'))['modules'][0]
                self.assertEqual(m['world_scale'],.5)
                self.assertEqual(m['anchor'],[64,110])
                self.assertEqual(m['polygons'],[[[-20,-10],[20,-10],[20,0],[-20,0]]])
                self.assertEqual(archive.read('images/'+m['image']),png())
            checks=page.evaluate('''async()=>{
              const editor=new StudioSpriteEditor();
              const c=document.createElement('canvas');c.width=32;c.height=32;
              const image=await createImageBitmap(c);
              editor.$('subject-height').setCustomValidity('old error');
              editor.load({title:'透明图',anchor:[16,32],polygons:[],behavior:'passable',world_scale:1},image,()=>{});
              const result={disabled:editor.$('subject-height').disabled,empty:editor.$('subject-height').value==='',canvas:editor.$('world-height').value,valid:editor.$('subject-height').validationMessage===''};
              editor.root.remove();return result;
            }''')
            self.assertEqual(checks,dict(disabled=True,empty=True,canvas='32',valid=True))
            page.set_viewport_size({'width':1440,'height':1000})
            page.fill('#subject-height','0.6')
            self.assertAlmostEqual(float(page.input_value('#world-height')),128*.6*34/71,places=5)
            page.click('#save-module')
            expect(page.locator('#status')).to_contain_text('模块设置已保存')
            expect(page.locator('#editor-save-state')).to_have_text('已保存')
            with zipfile.ZipFile(BytesIO(sm.export(self.root,self.scene['id']))) as archive:
                m=json.loads(archive.read('scene.json'))['modules'][0]
                # 0.6 human heights remains 0.6 relative to the exported reference.
                self.assertAlmostEqual(71*m['world_scale']/34,.6)
                self.assertIn('const HUMAN_HEIGHT: float = 34.0',archive.read('scene.gd').decode())
            browser.close()

    def test_transition_library_visual_pick_place_reopen_and_export(self):
        from playwright.sync_api import sync_playwright,expect
        kit,tiles=self.transition_fixture()
        panel=Panel(self.root);server=ThreadingHTTPServer(('127.0.0.1',0),handler(panel))
        threading.Thread(target=server.serve_forever,daemon=True).start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        base='http://127.0.0.1:'+str(server.server_port)
        with sync_playwright() as pw:
            browser=pw.chromium.launch(channel='chrome',headless=True)
            try:
                page=browser.new_page(viewport={'width':1440,'height':1000})
                errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto(base+'/module-scenes.html?scene='+self.scene['id'])
                def pick(variant,corners):
                    page.click('#show-library');page.fill('#library-search',kit)
                    card=page.locator('.library-item[data-kit="'+kit+'"]')
                    card.locator('select').select_option(str(variant))
                    tile=card.locator('.transition-tiles button[data-corners="'+str(corners)+'"]')
                    tile.click();expect(tile).to_have_attribute('aria-pressed','true')
                    expect(tile.locator('img')).to_have_js_property('naturalWidth',128)
                    card.get_by_role('button',name='加入场景',exact=True).click()
                    expect(page.locator('#library-dialog')).not_to_be_visible()
                pick(0,0)
                pick(1,3)
                expect(page.locator('.asset-card[aria-pressed=true]')).to_contain_text('角点 3 / 变化 2')
                page.locator('#scene-canvas').click(position={'x':300,'y':250})
                page.click('#save-layout');expect(page.locator('#status')).to_have_text('布局已保存。')
                # Selecting the same tile reuses its module, with the exact selector.
                pick(1,3)
                expect(page.locator('.asset-card')).to_have_count(2)
                page.reload();expect(page.locator('#layout-summary')).to_contain_text('1 个实例')
                with page.expect_download() as pending:page.click('#export')
                target=self.root/'transition-download.zip';pending.value.save_as(target)
                with zipfile.ZipFile(target) as archive:
                    saved=json.loads(archive.read('scene.json'))
                    selected=next(m for m in saved['modules'] if m['id']==saved['instances'][0]['module'])
                    self.assertEqual((selected['source']['corners'],selected['source']['variant']),(3,1))
                    self.assertEqual(selected['behavior'],'blocking')
                    self.assertEqual(archive.read('images/'+selected['image']),png())
                response=page.request.get(base+'/api/module-scenes/transition-image?kit='+kit+'&corners=15&variant=9')
                self.assertEqual(response.status,400)
                # A damaged package disappears from the picker and cannot serve a tile.
                (self.root/'terrain-transitions'/kit/'tiles/top.png').write_bytes(b'broken')
                self.assertFalse(any(a['family']=='transition' for a in sm.library(self.root)))
                self.assertEqual(page.request.get(base+'/api/module-scenes/transition-image?kit='+kit).status,400)
                self.assertEqual(errors,[])
            finally:browser.close()

    def test_scaled_scene_alpha_selection(self):
        from playwright.sync_api import sync_playwright,expect
        m=self.imported()
        self.change(action='module',module=m['id'],title='半尺寸素材',anchor=[64,100],behavior='passable',polygons=[],world_scale=.5)
        self.change(action='layout',instances=[dict(id='one',module=m['id'],position=[0,0])],spawn=[0,200])
        panel=Panel(self.root);server=ThreadingHTTPServer(('127.0.0.1',0),handler(panel))
        threading.Thread(target=server.serve_forever,daemon=True).start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        with sync_playwright() as pw:
            browser=pw.chromium.launch(channel='chrome',headless=True)
            page=browser.new_page(viewport={'width':1440,'height':1000})
            page.goto('http://127.0.0.1:'+str(server.server_port)+'/module-scenes.html?scene='+self.scene['id'])
            page.wait_for_function('() => document.querySelector("#layout-summary").textContent.includes("1 个实例")')
            page.click('[data-tool=select]');canvas=page.locator('#scene-canvas');box=canvas.bounding_box()
            zoom=min(1.5,(box['width']-100)/64,(box['height']-100)/280)
            def click_world(x,y):
                canvas.click(position={'x':box['width']/2+x*zoom,'y':box['height']/2+(y-90)*zoom})
            click_world(20,-15)
            expect(page.locator('#selection-label')).to_have_text('半尺寸素材')
            # This point is opaque at original scale, but outside the half-sized image.
            click_world(45,-15)
            expect(page.locator('#selection-label')).to_have_text('未选中物件')
            browser.close()

    def test_existing_library_selection_and_shared_workbench_editor(self):
        from playwright.sync_api import sync_playwright,expect
        from static_props import annotate,load_package
        original=self.imported()['source']['id']
        newer=annotate(self.root,dict(source_kit=original,title='库中的开口',anchor=[64,100],behavior='opening',
            polygons=[[[-60,-5],[-20,-5],[-20,5],[-60,5]],[[20,-5],[60,-5],[60,5],[20,5]]]))
        empty=sm.change(self.root,dict(action='create',title='从库选用'))
        panel=Panel(self.root);server=ThreadingHTTPServer(('127.0.0.1',0),handler(panel))
        threading.Thread(target=server.serve_forever,daemon=True).start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        base='http://127.0.0.1:'+str(server.server_port)
        with sync_playwright() as pw:
            browser=pw.chromium.launch(channel='chrome',headless=True)
            page=browser.new_page(viewport={'width':1440,'height':1000});errors=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(base+'/module-scenes.html?scene='+empty['id'])
            page.click('#show-library');page.fill('#library-search',newer['id'])
            page.locator('.library-item button').click()
            expect(page.locator('.asset-card')).to_have_count(1)
            page.locator('#scene-canvas').click(position={'x':300,'y':250})
            page.click('#save-layout');expect(page.locator('#status')).to_have_text('布局已保存。')
            scene=sm.load(self.root,empty['id']);module=scene['modules'][0]
            self.assertEqual(module['source']['id'],newer['id'])
            self.assertEqual(module['behavior'],'opening')
            page.click('#source-link');page.get_by_role('tab',name='调整',exact=True).click()
            page.click('#prop-edit-settings')
            expect(page.locator('#polygon-list .polygon-row')).to_have_count(2)
            page.fill('#edit-title','工作台另存版本')
            page.locator('#module-dialog details').evaluate('(d)=>d.open=true')
            page.fill('#world-height','256');page.locator('#world-height').blur()
            self.assertEqual(page.input_value('#world-width'),'256')
            page.click('#save-module')
            page.wait_for_url(lambda u:'kit='+newer['id'] not in str(u))
            from urllib.parse import parse_qs,urlparse
            saved_id=parse_qs(urlparse(page.url).query)['kit'][0]
            self.assertEqual(load_package(self.root,saved_id)['provenance']['parent_kit'],newer['id'])
            # The workbench save does not silently change scene references.
            self.assertEqual(sm.load(self.root,empty['id'])['modules'][0]['source']['id'],newer['id'])
            page.goto(base+'/module-scenes.html?scene='+empty['id'])
            page.click('#replace-source');page.fill('#library-search',saved_id)
            page.locator('.library-item button').click()
            expect(page.locator('.asset-card')).to_contain_text('工作台另存版本')
            linked=sm.load(self.root,empty['id'])
            self.assertEqual(linked['modules'][0]['id'],module['id'])
            self.assertEqual(linked['modules'][0]['source']['id'],saved_id)
            self.assertEqual(linked['instances'],scene['instances'])
            self.assertEqual(linked['modules'][0]['world_scale'],2)
            self.assertEqual(page.input_value('#world-width'),'256')
            self.assertEqual(errors,[])
            browser.close()

    def test_shortcuts_undo_zoom_drag_drop_and_collision_rectangle(self):
        from playwright.sync_api import sync_playwright, expect
        self.imported()
        panel=Panel(self.root);server=ThreadingHTTPServer(('127.0.0.1',0),handler(panel))
        threading.Thread(target=server.serve_forever,daemon=True).start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        base='http://127.0.0.1:'+str(server.server_port)
        with sync_playwright() as pw:
            browser=pw.chromium.launch(channel='chrome',headless=True)
            page=browser.new_page(viewport={'width':1440,'height':1000})
            errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(base+'/module-scenes.html?scene='+self.scene['id'])
            page.wait_for_selector('.asset-card')
            page.click('.asset-card')
            expect(page.locator('[data-tool=place]')).to_have_attribute('aria-pressed','true')
            canvas=page.locator('#scene-canvas')
            canvas.click(position={'x':300,'y':250})
            canvas.press('Control+d')
            expect(page.locator('#layout-summary')).to_contain_text('2 个实例')
            canvas.press('Control+z')
            expect(page.locator('#layout-summary')).to_contain_text('1 个实例')
            canvas.press('Control+Shift+z')
            expect(page.locator('#layout-summary')).to_contain_text('2 个实例')
            before=float(page.input_value('#instance-x'))
            canvas.press('ArrowRight')
            self.assertEqual(float(page.input_value('#instance-x')),before+1)
            canvas.press('Delete')
            expect(page.locator('#layout-summary')).to_contain_text('1 个实例')
            canvas.press('Control+z')
            expect(page.locator('#layout-summary')).to_contain_text('2 个实例')
            initial=page.locator('#zoom-label').inner_text()
            canvas.hover();page.mouse.wheel(0,-150)
            expect(page.locator('#zoom-label')).not_to_have_text(initial)
            canvas.press('Escape')
            expect(page.locator('[data-tool=select]')).to_have_attribute('aria-pressed','true')
            page.locator('.asset-card').drag_to(canvas,target_position={'x':450,'y':280})
            expect(page.locator('#layout-summary')).to_contain_text('3 个实例')
            page.click('#edit-selected')
            page.click('#view-annotation')
            page.select_option('#edit-mode','rectangle')
            mc=page.locator('#module-canvas');box=mc.bounding_box()
            page.mouse.move(box['x']+180,box['y']+180);page.mouse.down()
            page.mouse.move(box['x']+280,box['y']+250,steps=5);page.mouse.up()
            expect(page.locator('#polygon-list .polygon-row')).to_have_count(1)
            self.assertEqual(page.input_value('#behavior'),'blocking')
            page.click('#save-module')
            expect(page.locator('#editor-status')).to_contain_text('模块设置已保存')
            saved=sm.load(self.root,self.scene['id'])
            self.assertEqual(len(saved['instances']),3)
            self.assertEqual(len(saved['modules'][0]['polygons']),1)
            # Drag an existing vertex rather than redrawing the collision.
            page.select_option('#edit-mode','edit')
            box=mc.bounding_box()
            vertex=saved['modules'][0]['polygons'][0][0]
            anchor=saved['modules'][0]['anchor'];factor=400/128
            vx=box['x']+(160+(vertex[0]+anchor[0])*factor)*box['width']/720
            vy=box['y']+(40+(vertex[1]+anchor[1])*factor)*box['height']/480
            page.mouse.move(vx,vy);page.mouse.down()
            page.mouse.move(vx-10,vy-10,steps=4);page.mouse.up()
            page.click('#save-module')
            page.wait_for_function('() => document.querySelector("#editor-status").textContent.includes("模块设置已保存")')
            page.click('#close-editor')
            page.reload();page.wait_for_selector('.asset-card')
            changed=sm.load(self.root,self.scene['id'])
            self.assertNotEqual(changed['modules'][0]['polygons'],saved['modules'][0]['polygons'])
            self.assertEqual(len(changed['instances']),3)
            self.assertEqual(errors,[])
            browser.close()

if __name__=='__main__':unittest.main()
