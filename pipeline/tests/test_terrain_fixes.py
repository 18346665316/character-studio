"""Regression cases from the core/operation review; no paid image calls."""
import base64
from io import BytesIO
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import numpy as np
from PIL import Image

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from asset_repository import read
from terrain import prepare,execute
from terrain_images import load_config,configured,Provider
from terrain_integrity import inspect
from terrain_transition import build


class TerrainReviewFixes(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def kit(self,finish='natural',size=64,seed=2):
        a=np.random.default_rng(seed).integers(0,256,(400,400,3),dtype='uint8')
        stream=BytesIO();Image.fromarray(a).save(stream,format='PNG')
        content=base64.b64encode(stream.getvalue()).decode()
        job=prepare(self.root,dict(title='test',description='test',mode='import',
                    finish=finish,tile_size=size,ground=content,road=content))
        execute(self.root,job['id'])
        return self.root/'terrain-kits'/job['id']

    def test_transport_audit_retains_evidence_without_credentials_or_image_data(self):
        client=Provider.__new__(Provider)
        client.base='https://example.com/v1';client.key='private-test-key'
        client.audit_path=self.root/'http.jsonl'
        class Response(BytesIO):
            status=200
            headers={'x-request-id':'trace-123'}
        response=Response(json.dumps({'id':'remote-1','status':'failed','operation':'edit',
            'error':'failed private-test-key Bearer other-secret',
            'data':[{'b64_json':'image-bytes-must-not-be-logged'}]}).encode())
        with patch.object(client,'opener',create=True) as opener:
            opener.open.return_value=response
            result=client.request('/images/remote-1')
        self.assertEqual(result['status'],'failed')
        raw=client.audit_path.read_text()
        for secret in ['private-test-key','other-secret','image-bytes-must-not-be-logged']:
            self.assertNotIn(secret,raw)
        events=[json.loads(line) for line in raw.splitlines()]
        self.assertEqual(events[0]['method'],'GET')
        self.assertEqual(events[1]['http_status'],200)
        self.assertEqual(events[1]['request_id'],'trace-123')
        self.assertEqual(events[1]['response']['operation'],'edit')

    def test_reference_request_matches_documented_multipart_edit_contract(self):
        from email.parser import BytesParser
        from email.policy import default
        client=Provider.__new__(Provider)
        image=self.root/'reference.png';image.write_bytes(b'example-png')
        with patch.object(client,'request',return_value={'id':'accepted'}) as request:
            client.create('water texture',[image])
        endpoint,body,content_type=request.call_args.args
        self.assertEqual(endpoint,'/images/edits')
        message=BytesParser(policy=default).parsebytes(('Content-Type: '+content_type+'\r\n\r\n').encode()+body)
        fields={part.get_param('name',header='content-disposition'):part.get_payload(decode=True)
                for part in message.iter_parts()}
        self.assertEqual(fields['async'],b'true')
        self.assertEqual(fields['n'],b'1')
        self.assertEqual(fields['image[]'],b'example-png')
        self.assertEqual(fields['model'],b'gpt-image-2')

    def test_http_errors_preserve_safe_details_and_redact_credentials(self):
        from urllib.error import HTTPError
        from terrain_images import SubmissionRejected
        client=Provider.__new__(Provider)
        client.base='https://example.com/v1';client.key='private-test-key'
        client.audit_path=self.root/'http.jsonl'
        body=json.dumps({'error':{'type':'invalid_request_error','code':'bad_image',
            'message':'Unsupported image[] private-test-key Bearer another-secret',
            'data':'private-image','Authorization':'hidden'}}).encode()
        error=HTTPError(client.base+'/images/edits',400,'Bad Request',{'x-request-id':'trace'},BytesIO(body))
        with patch.object(client,'opener',create=True) as opener:
            opener.open.side_effect=error
            with self.assertRaisesRegex(SubmissionRejected,r'Unsupported image\[\]') as caught:
                client.request('/images/edits',b'payload')
        raw=client.audit_path.read_text()+str(caught.exception)
        for private in ('private-test-key','another-secret','private-image','hidden'):
            self.assertNotIn(private,raw)
        event=json.loads(client.audit_path.read_text().splitlines()[-1])
        self.assertEqual(event['response']['error']['code'],'bad_image')
        self.assertEqual(event['response']['error']['type'],'invalid_request_error')
        self.assertEqual(event['request_id'],'trace')

    def test_error_bodies_are_bounded_and_non_json_is_not_exposed(self):
        client=Provider.__new__(Provider);client.key='placeholder'
        class Limited(BytesIO):
            def read(self,size=-1):
                self.requested=size
                return super().read(size)
        large=Limited(b'x'*50000)
        self.assertIn('16KB',client.error_detail(large)['message'])
        self.assertEqual(large.requested,16*1024+1)
        self.assertEqual(client.error_detail(BytesIO(b'<html>private proxy page</html>')), {})

    def test_config_file_rotation_removal_and_environment_precedence(self):
        with patch.dict(os.environ,{},clear=True):
            file=self.root/'.env'
            file.write_text('OPENAI_API_KEY=first-placeholder\nSTUDIO_IMAGE_BASE_URL=https://one.example/v1\n')
            self.assertTrue(configured(self.root))
            self.assertEqual(load_config(self.root)['OPENAI_API_KEY'],'first-placeholder')
            self.assertNotIn('OPENAI_API_KEY',os.environ)
            file.write_text('OPENAI_API_KEY=second-placeholder\nSTUDIO_IMAGE_BASE_URL=https://two.example/v1\n')
            self.assertEqual(load_config(self.root)['OPENAI_API_KEY'],'second-placeholder')
            self.assertEqual(load_config(self.root)['STUDIO_IMAGE_BASE_URL'],'https://two.example/v1')
            os.environ['OPENAI_API_KEY']='explicit-env-placeholder'
            self.assertEqual(load_config(self.root)['OPENAI_API_KEY'],'explicit-env-placeholder')
            del os.environ['OPENAI_API_KEY'];file.unlink()
            self.assertFalse(configured(self.root))

    def test_source_pixels_are_preserved_for_classic_and_natural_variants(self):
        first=self.kit('classic');second=self.kit('natural',seed=4)
        dest=build(self.root,first.name,second.name,64,interactive=False)
        manifest=read(dest/'manifest.json')
        self.assertEqual(manifest['source_policy'],'delivered_ground_exact')
        self.assertEqual(manifest['variants'],4)
        base=Image.open(first/'tiles/ground.png').convert('RGB')
        for v in range(4):
            overlay=Image.open(second/('tiles/ground.png' if v==0 else f'tiles/ground_v{v}.png')).convert('RGB')
            self.assertTrue(np.array_equal(np.array(base),np.array(Image.open(dest/f'tiles/terrain_00_v{v}.png'))))
            self.assertTrue(np.array_equal(np.array(overlay),np.array(Image.open(dest/f'tiles/terrain_15_v{v}.png'))))
        self.assertTrue(inspect(self.root,'terrain-transitions',dest.name)['passed'])
        with self.assertRaisesRegex(ValueError,'尺寸须与'):
            build(self.root,first.name,second.name,32,interactive=False)
        # Transition downloads receive the same archive protection as roads.
        (dest/'kit.zip').write_bytes(b'bad archive')
        self.assertFalse(inspect(self.root,'terrain-transitions',dest.name)['passed'])

    def test_two_single_group_sources_do_not_invent_variations(self):
        first=self.kit('classic');second=self.kit('classic',seed=4)
        dest=build(self.root,first.name,second.name,interactive=False)
        self.assertEqual(read(dest/'manifest.json')['variants'],1)
        self.assertEqual(len(read(dest/'manifest.json')['tiles']),16)

    def test_single_material_import_reuse_and_water_transition(self):
        source=self.kit()
        content=base64.b64encode((source/'inputs/ground.png').read_bytes()).decode()
        spec=dict(title='水面',description='外部水面',mode='import',asset_type='material',
                  material_kind='water',tile_size=64,finish='natural',ground=content)
        job=prepare(self.root,spec);execute(self.root,job['id'])
        folder=self.root/'terrain-kits'/job['id']
        manifest=read(folder/'manifest.json')
        self.assertEqual(manifest['asset_type'],'material')
        self.assertEqual(len(manifest['variants']),4)
        self.assertEqual(manifest['tiles'],[])
        self.assertFalse((folder/'inputs/road.png').exists())
        self.assertFalse((folder/'road_material.png').exists())
        self.assertTrue(inspect(self.root,'terrain-kits',folder.name)['passed'])
        with zipfile.ZipFile(folder/'kit.zip') as archive:
            self.assertFalse(any('road' in entry for entry in archive.namelist()))
        dest=build(self.root,source.name,folder.name,interactive=False,mode='shoreline')
        self.assertTrue(inspect(self.root,'terrain-transitions',dest.name)['passed'])
        repeat=prepare(self.root,{**spec,'mode':'reuse','source_kit':folder.name})
        execute(self.root,repeat['id'])
        repeated=read(self.root/'terrain-kits'/repeat['id']/'manifest.json')
        self.assertEqual(repeated['asset_type'],'material')
        self.assertTrue(repeated['validation']['passed'])

    def test_missing_modified_and_mismatched_archive_are_rejected(self):
        kit=self.kit()
        self.assertTrue(inspect(self.root,'terrain-kits',kit.name)['passed'])
        atlas=kit/'atlas.png';original=atlas.read_bytes();atlas.write_bytes(b'changed')
        self.assertFalse(inspect(self.root,'terrain-kits',kit.name)['passed'])
        atlas.write_bytes(original)
        missing=kit/'tiles/road_00.png';saved=missing.read_bytes();missing.unlink()
        self.assertFalse(inspect(self.root,'terrain-kits',kit.name)['passed']);missing.write_bytes(saved)
        # A syntactically valid ZIP with valid CRC must still match disk content.
        with zipfile.ZipFile(kit/'kit.zip') as archive:
            contents={name:archive.read(name) for name in archive.namelist()}
        contents['atlas.png']=b'different archive content'
        with zipfile.ZipFile(kit/'kit.zip','w') as archive:
            for name,data in contents.items():archive.writestr(name,data)
        self.assertFalse(inspect(self.root,'terrain-kits',kit.name)['passed'])


if __name__=='__main__':unittest.main()
