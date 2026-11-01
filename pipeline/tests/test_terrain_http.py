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

    def test_generation_requires_token_before_creating_any_job(self):
        request=Request(self.base+'/api/terrain/generate',data=b'{"mode":"demo"}',
                        headers={'Content-Type':'application/json'})
        with self.assertRaises(HTTPError) as caught: urlopen(request)
        self.assertEqual(caught.exception.code,403)
        self.assertFalse((self.root/'.local/terrain').exists())

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
