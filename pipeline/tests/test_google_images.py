"""Vertex AI protocol, credentials isolation, receipts and no automatic retry."""
import base64
from io import BytesIO
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from google_images import GoogleProvider, settings, DEFAULT_MODEL
from terrain_images import Provider, configured, load_config, provider_info, SubmissionRejected, generate_materials
from asset_repository import atomic, read


class Response(BytesIO):
    status=200
    headers={'x-request-id':'trace-vertex'}


class GoogleImagesTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.config=dict(STUDIO_IMAGE_PROVIDER='google_cloud',GCP_PROJECT_ID='example-project',GCP_LOCATION='us-central1')
        stream=BytesIO();Image.new('RGB',(64,64),'#92744b').save(stream,format='PNG');self.raw=stream.getvalue()
        self.image=self.root/'outline.png';self.image.write_bytes(self.raw)

    def client(self):
        client=GoogleProvider.__new__(GoogleProvider)
        client.base=settings(self.config,self.root)['base'];client.model=DEFAULT_MODEL;client.provider='google_cloud'
        client.audit_path=self.root/'http.jsonl';client.credentials=Mock(valid=True,token='private-oauth-token')
        client.opener=Mock();client.auth_request=Mock()
        client.opener.open.return_value=Response(json.dumps({'candidates':[{'content':{'parts':[
            {'text':'private-generated-explanation'},
            {'inlineData':{'mimeType':'image/png','data':base64.b64encode(self.raw).decode()}}]}}]}).encode())
        return client

    def test_reference_image_and_style_are_submitted_to_vertex_generate_content(self):
        client=self.client();result=client.create('private-style-prompt',[self.image])
        request=client.opener.open.call_args.args[0];payload=json.loads(request.data)
        self.assertTrue(request.full_url.endswith('/gemini-2.5-flash-image:generateContent'))
        self.assertIn('/projects/example-project/locations/us-central1/',request.full_url)
        self.assertEqual(request.get_header('Authorization'),'Bearer private-oauth-token')
        self.assertEqual(payload['contents'][0]['parts'][0],{'text':'private-style-prompt'})
        self.assertEqual(base64.b64decode(payload['contents'][0]['parts'][1]['inlineData']['data']),self.raw)
        self.assertEqual(payload['generationConfig']['responseModalities'],['TEXT','IMAGE'])
        self.assertEqual(payload['generationConfig']['imageConfig']['aspectRatio'],'1:1')
        self.assertEqual(base64.b64decode(result['data'][0]['b64_json']),self.raw)
        client.opener.open.assert_called_once()
        logs=client.audit_path.read_text()
        for secret in ['private-oauth-token','private-style-prompt','private-generated-explanation',base64.b64encode(self.raw).decode()]:
            self.assertNotIn(secret,logs)
        self.assertIn('trace-vertex',logs)

    def test_text_only_prompt_supports_shared_material_provider(self):
        client=self.client();client.create('material',[])
        payload=json.loads(client.opener.open.call_args.args[0].data)
        self.assertEqual(payload['contents'][0]['parts'],[{'text':'material'}])

    def test_http_rejection_is_definite_and_never_retries_or_echoes_body(self):
        for code,exception in [(400,SubmissionRejected),(403,SubmissionRejected),(429,SubmissionRejected),(503,ValueError)]:
            client=self.client();client.opener.open.side_effect=HTTPError(client.base,code,'error',{},BytesIO(b'private-oauth-token secret-image'))
            with self.assertRaises(exception) as result:client.create('style',[self.image])
            self.assertNotIn('private-oauth-token',str(result.exception));client.opener.open.assert_called_once()
            self.assertNotIn('secret-image',client.audit_path.read_text())

    def test_timeout_is_uncertain_without_paid_retries(self):
        client=self.client();client.opener.open.side_effect=URLError('private-oauth-token')
        with self.assertRaisesRegex(ValueError,'结果不明') as error:client.create('style',[self.image])
        self.assertNotIsInstance(error.exception,SubmissionRejected);client.opener.open.assert_called_once()
        self.assertNotIn('private-oauth-token',client.audit_path.read_text())

    def test_filtered_or_text_only_result_is_not_fake_image_success(self):
        client=self.client();client.opener.open.return_value=Response(json.dumps({'candidates':[{'content':{'parts':[{'text':'blocked private text'}]}}]}).encode())
        with self.assertRaisesRegex(SubmissionRejected,'没有图片'):client.create('style',[])
        self.assertNotIn('blocked private text',client.audit_path.read_text())

    def test_adc_and_service_account_do_not_mutate_process_environment(self):
        with patch('google.auth.default',return_value=(Mock(token='token'), 'ignored-project')) as adc:
            with patch('google.auth.transport.requests.Request'):
                before=dict(os.environ);client=GoogleProvider(self.config,self.root)
                self.assertEqual(dict(os.environ),before);adc.assert_called_once()
                client.credentials.refresh.assert_called_once()
        account=self.root/'key.json';account.write_text(json.dumps(dict(type='service_account',project_id='key-project')))
        config=dict(STUDIO_IMAGE_PROVIDER='google_cloud',GOOGLE_APPLICATION_CREDENTIALS='key.json')
        self.assertEqual(settings(config,self.root)['project'],'key-project')
        with patch('google.oauth2.service_account.Credentials.from_service_account_file',return_value=Mock(token='token')) as auth:
            with patch('google.auth.transport.requests.Request'):
                before=dict(os.environ);GoogleProvider(config,self.root)
                self.assertEqual(dict(os.environ),before)
                self.assertEqual(auth.call_args.args[0],str(account))

    def test_global_location_and_unsupported_imagen_model(self):
        config={**self.config,'GCP_LOCATION':'global'}
        self.assertTrue(settings(config,self.root)['base'].startswith('https://aiplatform.googleapis.com/'))
        with self.assertRaisesRegex(ValueError,'参考图'):settings({**config,'STUDIO_GOOGLE_IMAGE_MODEL':'imagen-3.0-generate-002'},self.root)
        with self.assertRaises(ValueError):settings({**config,'GCP_PROJECT_ID':'project/other'},self.root)

    def test_config_selection_and_reload_without_openai_key(self):
        with patch.dict(os.environ,{},clear=True):
            path=self.root/'.env';path.write_text('STUDIO_IMAGE_PROVIDER=google_cloud\nGCP_PROJECT_ID=example-project\nGCP_LOCATION=global\nSTUDIO_GOOGLE_IMAGE_MODEL=gemini-2.5-flash-image\n')
            self.assertTrue(configured(self.root));self.assertEqual(provider_info(self.root)['image_provider'],'google_cloud')
            self.assertNotIn('STUDIO_IMAGE_PROVIDER',os.environ)
            path.write_text('STUDIO_IMAGE_PROVIDER=google_cloud\nGOOGLE_APPLICATION_CREDENTIALS=missing.json\n')
            self.assertFalse(configured(self.root));path.unlink();self.assertFalse(configured(self.root))

    def test_facade_routes_google_and_preserves_compatible_default(self):
        with patch('terrain_images.load_config',return_value=self.config):
            with patch('google_images.GoogleProvider') as cls:
                cls.return_value.base='https://vertex.example';cls.return_value.model=DEFAULT_MODEL;cls.return_value.provider='google_cloud'
                client=Provider(self.root/'http.jsonl');client.create('style',[self.image])
                cls.return_value.create.assert_called_once_with('style',[self.image])
                self.assertEqual(client.model,DEFAULT_MODEL)
        with patch('terrain_images.load_config',return_value={'OPENAI_API_KEY':'placeholder'}):
            client=Provider();self.assertEqual(client.model,'gpt-image-2');self.assertFalse(hasattr(client,'google'))

    def test_google_generation_receipt_records_real_provider_and_model(self):
        from building_pipeline import prepare,new_attempt,execute,folder_for,attempt_folder
        from pipeline.tests.test_building_candidates import drawings,encoded
        outline,raw=drawings()
        client=self.client();stream=BytesIO();raw.save(stream,format='PNG')
        client.opener.open.return_value=Response(json.dumps({'candidates':[{'content':{'parts':[{'inlineData':{
            'mimeType':'image/png','data':base64.b64encode(stream.getvalue()).decode()}}]}}]}).encode())
        job=prepare(self.root,dict(workflow='line_drawing',title='Vertex building',appearance='手绘',line_drawing=encoded(outline)))
        job=new_attempt(self.root,job['id'],job['revision']);job=execute(self.root,job['id'],provider_factory=lambda _:client)
        self.assertEqual(job['status'],'waiting_review')
        receipt=read(attempt_folder(folder_for(self.root,job['id']),job['current_attempt'])/'generation.json')
        self.assertEqual(receipt['provider'],'google_cloud');self.assertEqual(receipt['model'],DEFAULT_MODEL)
        self.assertEqual(receipt['base_url'],client.base);self.assertFalse(receipt['submission_uncertain'])
        self.assertNotIn('private-oauth-token',json.dumps(receipt))

    def test_shared_material_pipeline_records_google_and_reuses_local_materials(self):
        folder=self.root/'material';(folder/'inputs').mkdir(parents=True)
        client=self.client()
        with patch('terrain_images.Provider',return_value=client):
            generate_materials(folder,dict(asset_type='material',description='stone'),lambda _:None)
        record=read(folder/'generation.json')['ground']
        self.assertEqual(record['provider'],'google_cloud');self.assertEqual(record['model'],DEFAULT_MODEL)
        changed=self.client();changed.base='https://other-model.example'
        with patch('terrain_images.Provider',return_value=changed):
            generate_materials(folder,dict(asset_type='material',description='stone'),lambda _:None)
        changed.opener.open.assert_not_called()


if __name__=='__main__':unittest.main()
