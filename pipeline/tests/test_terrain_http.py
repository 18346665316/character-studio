"""Terrain HTTP boundaries share the existing panel authentication rules."""
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import sys
import tempfile
import threading
import zipfile
from io import BytesIO
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from panel import Panel, handler
from terrain import prepare, execute


class TerrainHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.panel=Panel(self.root)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),handler(self.panel))
        thread=threading.Thread(target=self.server.serve_forever,daemon=True);thread.start()
        self.addCleanup(self.server.server_close);self.addCleanup(self.server.shutdown)
        self.base='http://127.0.0.1:'+str(self.server.server_port)

    def test_catalog_has_token_but_no_credentials_and_static_page_loads(self):
        with urlopen(self.base+'/api/terrain/state') as response:
            data=json.load(response)
        self.assertEqual(data['token'],self.panel.token)
        self.assertEqual(data['kits'],[])
        self.assertNotIn('api_key',data)
        with urlopen(self.base+'/terrain.html') as response:
            self.assertIn('kit-form',response.read().decode())
        for page in ('water.html','water-shore.html'):
            with urlopen(self.base+'/'+page) as response:
                self.assertIn('data-asset-area="water"',response.read().decode())

    def test_generation_requires_token_before_creating_any_job(self):
        request=Request(self.base+'/api/terrain/generate',data=b'{"mode":"demo"}',
                        headers={'Content-Type':'application/json'})
        with self.assertRaises(HTTPError) as caught: urlopen(request)
        self.assertEqual(caught.exception.code,403)
        self.assertFalse((self.root/'.local/terrain').exists())

    def test_components_require_auth_and_publish_separate_downloadable_packages(self):
        params={'mode':'demo'}
        endpoint=self.base+'/api/components/build'
        with self.assertRaises(HTTPError) as caught:
            urlopen(Request(endpoint,data=json.dumps(params).encode(),headers={'Content-Type':'application/json'}))
        self.assertEqual(caught.exception.code,403)
        headers={'Content-Type':'application/json','X-Studio-Token':self.panel.token}
        with urlopen(Request(endpoint,data=json.dumps(params).encode(),headers=headers)) as response:kit=json.load(response)
        self.assertEqual(kit['asset_family'],'connected_component')
        self.assertEqual(kit['ai_calls'],0)
        self.assertEqual(len(kit['modules']),12)
        with urlopen(self.base+'/api/components/state') as response:
            self.assertTrue(json.load(response)['kits'][0]['integrity']['passed'])
        with urlopen(self.base+'/component-asset/'+kit['id']+'/kit.zip') as response:
            self.assertGreater(len(response.read()),0)
        for path in ('../.env',kit['id']+'/inputs/wood.png'):
            with self.assertRaises(HTTPError):urlopen(self.base+'/component-asset/'+path)
        (self.root/'component-kits'/kit['id']/'kit.zip').write_bytes(b'bad zip')
        with self.assertRaises(HTTPError) as caught:
            urlopen(self.base+'/component-asset/'+kit['id']+'/kit.zip')
        self.assertEqual(caught.exception.code,400)

    def test_job_log_whitelists_fields_and_rejects_outside_paths(self):
        from unittest.mock import patch
        job=prepare(self.root,dict(title='test',description='test',mode='demo'))
        folder=self.root/'.local/terrain/jobs'/job['id']
        (folder/'http.jsonl').write_text(json.dumps({'event':'response','http_status':200,
            'Authorization':'secret','response':{'id':'remote','error':'secret','data':'private-image'}})+'\n')
        with patch('terrain_images.load_config',return_value={'OPENAI_API_KEY':'secret'}):
            with urlopen(self.base+'/api/terrain/job-log?id='+job['id']) as response: result=json.load(response)
        self.assertEqual(result['events'][0]['response']['error'],'[REDACTED]')
        self.assertNotIn('Authorization',result['events'][0])
        self.assertNotIn('data',result['events'][0]['response'])

    def test_component_ai_requires_auth_and_exposes_separate_jobs(self):
        from unittest.mock import patch
        from component_jobs import prepare as prepare_component
        endpoint=self.base+'/api/components/generate'
        with self.assertRaises(HTTPError) as caught:
            urlopen(Request(endpoint,data=b'{}',headers={'Content-Type':'application/json'}))
        self.assertEqual(caught.exception.code,403)
        with patch('component_jobs.configured',return_value=True):
            job=prepare_component(self.root,{'description':'wood grain'})
        with patch.object(self.panel,'start_terrain',return_value=job) as start:
            with urlopen(Request(endpoint,data=b'{"description":"wood"}',headers={
                'Content-Type':'application/json','X-Studio-Token':self.panel.token})) as response:
                self.assertEqual(json.load(response)['id'],job['id'])
            start.assert_called_once_with({'description':'wood'},components=True)
        with urlopen(self.base+'/api/components/state') as response:
            state=json.load(response)
        self.assertEqual(state['jobs'][0]['id'],job['id'])
        self.assertEqual(state['jobs'][0]['status'],'failed')  # No worker owns this prepared receipt.
        with urlopen(self.base+'/api/components/job-log?id='+job['id']) as response:
            self.assertEqual(json.load(response)['events'],[])

    def test_static_prop_routes_auth_production_remake_and_scoping(self):
        import base64
        from PIL import Image, ImageDraw
        from unittest.mock import patch
        from static_props import prepare as prepare_prop, execute as execute_prop
        image=Image.new('RGBA',(64,64));ImageDraw.Draw(image).ellipse((12,16,52,52),fill=(120,120,100,255))
        raw=BytesIO();image.save(raw,format='PNG')
        data={'mode':'import','image':base64.b64encode(raw.getvalue()).decode()}
        endpoint=self.base+'/api/props/generate'
        headers={'Content-Type':'application/json','X-Studio-Token':self.panel.token}
        with self.assertRaises(HTTPError) as caught:
            urlopen(Request(endpoint,data=json.dumps(data).encode(),headers={'Content-Type':'application/json'}))
        self.assertEqual(caught.exception.code,403)
        job=prepare_prop(self.root,data)
        with patch.object(self.panel,'start_terrain',return_value=job) as start:
            with urlopen(Request(endpoint,data=json.dumps(data).encode(),headers=headers)) as response:
                self.assertEqual(json.load(response)['id'],job['id'])
            start.assert_called_once_with(data,props=True)
        execute_prop(self.root,job['id'])
        with urlopen(self.base+'/api/props/state') as response: state=json.load(response)
        self.assertEqual(state['jobs'][0]['status'],'complete')
        self.assertTrue(state['jobs'][0]['original_available'])
        self.assertEqual(state['kits'][0]['provenance']['art_source'],'external_complete_object')
        with urlopen(self.base+'/props.html') as response:self.assertIn('prop-form',response.read().decode())
        with urlopen(self.base+'/api/props/job-image?id='+job['id']) as response:self.assertTrue(response.read().startswith(b'\x89PNG'))
        with urlopen(Request(self.base+'/api/props/remake',data=json.dumps({'source_kit':job['id'],'anchor_x':124}).encode(),headers=headers)) as response:
            adjusted=json.load(response)
        self.assertEqual(adjusted['anchor_px'][0],124)
        self.assertNotEqual(adjusted['id'],job['id'])
        with urlopen(self.base+'/prop-asset/'+adjusted['id']+'/kit.zip') as response:self.assertGreater(len(response.read()),100)
        for path in ['/api/props/job-image?id=../secret','/api/props/job-log?id=../secret','/prop-asset/'+job['id']+'/inputs/original.png']:
            with self.assertRaises(HTTPError):urlopen(self.base+path)
        folder=self.root/'.local/props/jobs'/job['id']
        (folder/'http.jsonl').write_text(json.dumps({'event':'response','Authorization':'secret','response':{'id':'remote','error':'secret','data':'private'}})+'\n')
        with patch('terrain_images.load_config',return_value={'OPENAI_API_KEY':'secret'}):
            with urlopen(self.base+'/api/props/job-log?id='+job['id']) as response:log=json.load(response)
        self.assertEqual(log['events'][0]['response']['error'],'[REDACTED]')
        self.assertNotIn('Authorization',log['events'][0])
        (self.root/'prop-kits'/adjusted['id']/'sprite.png').write_bytes(b'changed')
        with self.assertRaises(HTTPError) as caught:urlopen(self.base+'/prop-asset/'+adjusted['id']+'/kit.zip')
        self.assertEqual(caught.exception.code,400)
        with self.assertRaises(HTTPError): urlopen(self.base+'/api/terrain/job-log?id=..%2F.env')

    def test_export_and_preview_are_public_but_internal_files_cannot_be_read(self):
        job=prepare(self.root,dict(title='测试',description='草地',mode='demo'))
        execute(self.root,job['id'])
        for filename in ['kit.zip','atlas.png','preview.png']:
            with urlopen(self.base+'/terrain-asset/'+job['id']+'/'+filename) as response:
                self.assertGreater(len(response.read()),0)
        for relative in [job['id']+'/inputs/ground.png',job['id']+'/manifest.json',
                         '../.env',job['id']+'/%2e%2e/.env']:
            with self.assertRaises(HTTPError) as caught:
                urlopen(self.base+'/terrain-asset/'+relative)
            self.assertEqual(caught.exception.code,400)

    def test_transition_generation_exports_assets_without_map_editor(self):
        identities=[]
        for title in ['地表A','地表B']:
            job=prepare(self.root,dict(title=title,description='地表测试',mode='demo'))
            execute(self.root,job['id']);identities.append(job['id'])
        params={'title':'地表过渡','base_kit':identities[0],'overlay_kit':identities[1],'tile_size':64}
        url=self.base+'/api/terrain/transition'
        headers={'Content-Type':'application/json','X-Studio-Token':self.panel.token}
        with self.assertRaises(HTTPError) as caught:
            urlopen(Request(url,data=json.dumps(params).encode(),headers={'Content-Type':'application/json'}))
        self.assertEqual(caught.exception.code,403)
        with urlopen(Request(url,data=json.dumps(params).encode(),headers=headers)) as response:
            kit=json.load(response)
        self.assertEqual(len(kit['tiles']),64)
        self.assertEqual(kit['ai_calls'],0)
        self.assertTrue(kit['validation']['passed'])
        with urlopen(self.base+'/transition-asset/'+kit['id']+'/kit.zip') as response:
            with zipfile.ZipFile(BytesIO(response.read())) as archive:
                self.assertNotIn('index.html',archive.namelist())
                self.assertIn('INTEGRATION.md',archive.namelist())
        with urlopen(self.base+'/api/terrain/state') as response:
            self.assertEqual(json.load(response)['transitions'][0]['id'],kit['id'])
        params['transition_mode']='shoreline'
        with urlopen(Request(url,data=json.dumps(params).encode(),headers=headers)) as response:
            water=json.load(response)
        self.assertEqual(water['transition_mode'],'shoreline')
        self.assertTrue(water['validation']['passed'])
        with urlopen(self.base+'/transition-asset/'+water['id']+'/kit.zip') as response:
            with zipfile.ZipFile(BytesIO(response.read())) as archive:
                for tile in water['tiles']:
                    self.assertIn(tile['water_mask'],archive.namelist())
                self.assertIn('静态水岸',archive.read('INTEGRATION.md').decode())
        params['transition_mode']='unknown'
        with self.assertRaises(HTTPError) as caught:
            urlopen(Request(url,data=json.dumps(params).encode(),headers=headers))
        self.assertEqual(caught.exception.code,400)
        params['transition_mode']='surface'
        for resource in ['inputs/grass.png','manifest.json','../.env']:
            with self.assertRaises(HTTPError):
                urlopen(self.base+'/transition-asset/'+kit['id']+'/'+resource)
        params['overlay_kit']=params['base_kit']
        with self.assertRaises(HTTPError):
            urlopen(Request(url,data=json.dumps(params).encode(),headers=headers))

    def test_corrupt_downloads_are_blocked_and_catalog_marks_invalid_delivery(self):
        job=prepare(self.root,dict(title='完整性测试',description='fixture',mode='demo'))
        execute(self.root,job['id'])
        kit=self.root/'terrain-kits'/job['id']
        (kit/'kit.zip').write_bytes(b'broken zip')
        with self.assertRaises(HTTPError) as caught:
            urlopen(self.base+'/terrain-asset/'+job['id']+'/kit.zip')
        self.assertEqual(caught.exception.code,400)
        with urlopen(self.base+'/api/terrain/state') as response:
            self.assertFalse(json.load(response)['kits'][0]['integrity']['passed'])
        execute(self.root,job['id'])
        from asset_repository import read
        self.assertEqual(read(self.root/'.local/terrain/jobs'/job['id']/'job.json')['status'],'failed')


if __name__ == '__main__': unittest.main()
