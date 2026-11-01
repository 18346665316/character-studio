"""Panel workflow gates, durable retries, and local asset boundaries."""
import base64
from io import BytesIO
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from panel import Panel, atomic
import panel_worker


class PanelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.panel = Panel(self.root)
        self.ws = self.root/'workspaces/hero'
        self.ws.mkdir(parents=True)

    def upload(self):
        data = BytesIO()
        Image.new('RGB',(100,100),'green').save(data,format='PNG')
        return self.panel.upload({'character':'hero','content':base64.b64encode(data.getvalue()).decode()})

    def model(self):
        model = self.ws/'models/hero.obj'
        model.parent.mkdir(exist_ok=True)
        model.write_text('mesh-one')
        prepared = self.ws/'models/prepared/v1'
        prepared.mkdir(parents=True,exist_ok=True)
        atomic(prepared/'prepare.json',{'source_sha256':self.panel.digest(model),'triangles_after':10})
        return self.panel.character('hero')['prepared']

    def batch(self):
        path = self.ws/'animations/b1/batch.json'
        atomic(path,{'character':'hero','batch':'b1','files':{'idle.fbx':'hash'}})
        return self.panel.character('hero')['batches'][0]

    def test_upload_validates_and_saves_a_real_image(self):
        upload = self.upload()
        path = self.root/upload['image']
        with Image.open(path) as image:
            self.assertEqual(image.size,(100,100))
        self.assertEqual(self.panel.character('hero')['inputs'][0]['path'],upload['image'])
        with self.assertRaises(ValueError):
            self.panel.upload({'character':'../escape','content':'AA=='})
        with self.assertRaises(ValueError):
            self.panel.upload({'character':'hero','content':'not base64'})

    def test_friendly_name_is_independent_of_internal_id(self):
        data=BytesIO()
        Image.new('RGB',(100,100),'green').save(data,format='PNG')
        content=base64.b64encode(data.getvalue()).decode()
        upload=self.panel.upload({'display_name':'武术少年','content':content})
        self.assertTrue(upload['character'].startswith('character-'))
        self.assertEqual(self.panel.character(upload['character'])['display_name'],'武术少年')
        self.assertTrue(any(c['display_name']=='武术少年' for c in self.panel.catalog()))
        self.panel.upload({'character':upload['character'],'display_name':'其他名字','content':content})
        self.assertEqual(self.panel.character(upload['character'])['display_name'],'武术少年')
        for label in ['', ' '*3, 'x'*61, 3]:
            with self.assertRaises(ValueError):
                self.panel.upload({'display_name':label,'content':content})

    def test_individual_animation_approval_does_not_approve_siblings(self):
        receipt=self.ws/'animations/b1/batch.json'
        hashes={'idle.fbx':'idle-hash','walking.fbx':'walk-hash'}
        atomic(receipt,{'character':'hero','batch':'b1','files':hashes})
        batch=self.panel.character('hero')['batches'][0]
        viewer=self.ws/'reviews/r1/viewer'
        atomic(viewer/'review.json',{'batch':'b1','files':hashes})
        atomic(viewer/'character-report.json',{})
        captures=viewer/'captures';captures.mkdir()
        (captures/'idle_0.png').write_bytes(b'preview')
        (captures/'walking_0.png').write_bytes(b'preview')
        request={'character':'hero','kind':'animation','batch':'b1','fingerprint':batch['fingerprint']}
        self.panel.approve(dict(request,file='idle.fbx'))
        c=self.panel.character('hero')
        self.assertIn('idle.fbx',c['approvals']['animations']['b1'])
        self.assertNotIn('walking.fbx',c['approvals']['animations']['b1'])
        with self.assertRaisesRegex(ValueError,'确认所选动作'):
            self.panel.validate_task('hero','bake',{'batch':'b1'})
        self.assertEqual(self.panel.validate_task('hero','bake',{'batch':'b1','files':['idle.fbx']})['files'],['idle.fbx'])
        for files in [[],['idle.fbx','idle.fbx'],['other.fbx'],'idle.fbx']:
            with self.assertRaises(ValueError):
                self.panel.validate_task('hero','bake',{'batch':'b1','files':files})
        with self.assertRaisesRegex(ValueError,'不属于'):
            self.panel.approve(dict(request,file='other.fbx'))
        (captures/'walking_0.png').unlink()
        with self.assertRaisesRegex(ValueError,'姿态检查'):
            self.panel.approve(dict(request,file='walking.fbx'))
        (captures/'walking_0.png').write_bytes(b'preview')
        self.panel.approve(dict(request,file='walking.fbx'))
        self.assertEqual(self.panel.validate_task('hero','bake',{'batch':'b1'})['batch'],'b1')
        self.assertEqual(self.panel.validate_task('hero','bake',{'batch':'b1'})['renderer'],'godot')
        self.assertEqual(self.panel.validate_task('hero','bake',{'batch':'b1','renderer':'blender'})['renderer'],'blender')
        with self.assertRaisesRegex(ValueError,'未知渲染'):
            self.panel.validate_task('hero','bake',{'batch':'b1','renderer':'other'})
        atomic(receipt,{'character':'hero','batch':'b1','files':{'idle.fbx':'changed','walking.fbx':'walk-hash'}})
        with self.assertRaisesRegex(ValueError,'已变化'):
            self.panel.approve(dict(request,file='idle.fbx'))
        with self.assertRaisesRegex(ValueError,'确认所选动作'):
            self.panel.validate_task('hero','bake',{'batch':'b1'})

    def test_animation_title_preserves_mixamo_request(self):
        self.batch()
        atomic(self.ws/'animations/b1/request.json',{'names':['Idle','Sword And Shield Slash']})
        batch=self.panel.character('hero')['batches'][0]
        self.assertEqual(batch['titles']['sword_and_shield_slash.fbx'],'Sword And Shield Slash')
        self.assertEqual(batch['hashes'],{'idle.fbx':'hash'})

    def test_new_model_invalidates_visual_approval_and_stale_prepared(self):
        prepared = self.model()
        self.panel.approve({'character':'hero','kind':'model','fingerprint':prepared['fingerprint']})
        self.assertTrue(self.panel.character('hero')['model_approved'])
        (self.ws/'models/hero.obj').write_text('different-model')
        self.assertIsNone(self.panel.character('hero')['prepared'])
        self.assertFalse(self.panel.character('hero')['model_approved'])

    def test_binding_requires_current_model_approval(self):
        self.model()
        with self.assertRaisesRegex(ValueError,'确认当前模型'):
            self.panel.validate_task('hero','rig',{})
        prepared = self.panel.character('hero')['prepared']
        self.panel.approve({'character':'hero','kind':'model','fingerprint':prepared['fingerprint']})
        self.assertEqual(self.panel.validate_task('hero','rig',{}),{})

    def test_motion_approval_requires_preview_of_same_source(self):
        batch = self.batch()
        data = {'character':'hero','kind':'motion','batch':'b1','fingerprint':batch['fingerprint']}
        with self.assertRaisesRegex(ValueError,'检查画面'):
            self.panel.approve(data)
        review = self.ws/'reviews/r1/viewer'
        atomic(review/'review.json',{'batch':'b1','files':{'idle.fbx':'hash'}})
        atomic(review/'character-report.json',{})
        self.panel.approve(data)
        config = self.panel.validate_task('hero','bake',{'batch':'b1','frame_size':64,'supersample':4})
        self.assertEqual(config['frame_size'],64)
        atomic(self.ws/'animations/b1/batch.json',{'character':'hero','batch':'b1','files':{'idle.fbx':'changed'}})
        with self.assertRaisesRegex(ValueError,'确认所选动作'):
            self.panel.validate_task('hero','bake',{'batch':'b1'})

    def test_asset_access_denies_private_files_and_traversal(self):
        secret = self.root/'.local/auth/credentials.json'
        atomic(secret,{'private':True})
        for value in ['.local/auth/credentials.json','workspaces/hero/models/../../../../.local/auth/credentials.json',
                      'workspaces/hero/../../.local/auth/credentials.json']:
            with self.assertRaises(ValueError):
                self.panel.asset_path(value)
        original = self.upload()['image']
        self.assertEqual(self.panel.asset_path(original),self.root/original)

    def test_symlink_cannot_move_asset_boundary(self):
        secret = self.root/'.local/secrets'
        atomic(secret/'secret.json',{'private':True})
        (self.ws/'models').symlink_to(secret,target_is_directory=True)
        with self.assertRaises(ValueError):
            self.panel.asset_path('workspaces/hero/models/secret.json')

    def test_resource_lock_survives_another_panel_instance(self):
        import os
        fd = self.panel.worker_lock()
        self.addCleanup(os.close,fd)
        other = Panel(self.root)
        self.assertIsNone(other.worker_lock())

    def test_dead_worker_is_marked_interrupted(self):
        atomic(self.panel.tasks_dir/'task1.json',{'id':'task1','status':'running','created_at':'2026-01-01'})
        self.panel.recover_jobs()
        self.assertEqual(self.panel.jobs()[0]['status'],'interrupted')

    def test_retry_preserves_checkpoint_and_uses_no_shell(self):
        image = self.upload()['image']
        job = {'id':'task1','character':'hero','action':'reconstruct','params':{'image':image},
               'created_at':'2026-01-01','status':'failed','attempts':1,
               'outputs':{'reconstruction':{'model_sha256':'abc'}}}
        atomic(self.panel.tasks_dir/'task1.json',job)
        with patch('panel.subprocess.Popen') as spawn:
            result = self.panel.start({'character':'hero','retry':'task1'})
        self.assertEqual(result['attempts'],2)
        self.assertEqual(result['outputs'],job['outputs'])
        self.assertIsInstance(spawn.call_args.args[0],list)
        self.assertNotIn('shell',spawn.call_args.kwargs)
        self.assertIn('pass_fds',spawn.call_args.kwargs)

    def test_reconstruction_retry_skips_completed_generation(self):
        image = self.upload()['image']
        self.model()
        model = self.ws/'models/hero.obj'
        job = {'character':'hero','action':'reconstruct','params':{'image':image},'outputs':{
            'reconstruction':{'image_sha256':self.panel.digest(self.root/image), 'model_sha256':self.panel.digest(model)}}}
        prepared = self.ws/'models/prepared/v1'
        with patch.object(panel_worker.studio,'BASE_DIR',self.root), \
             patch.object(panel_worker.studio,'generate') as generate, \
             patch.object(panel_worker.studio,'prepare',return_value=prepared) as prepare:
            panel_worker.execute(job,lambda:None)
        generate.assert_not_called()
        prepare.assert_called_once_with('hero')

    def test_download_retry_reuses_verified_files(self):
        batch='resume1'
        target=self.ws/'animations'/batch
        target.mkdir(parents=True)
        (target/'idle.fbx').write_bytes(b'already-downloaded')
        binding={'bound_sha256':'bound','geometry':{'reference':True}}
        job={'character':'hero','action':'download','params':{'actions':['Idle']},'outputs':{'batch':batch}}
        with patch.object(panel_worker.studio,'BASE_DIR',self.root), \
             patch.object(panel_worker.studio,'model_path',return_value=Path('model.zip')), \
             patch.object(panel_worker,'require_ready',return_value=binding), \
             patch.object(panel_worker,'inspect_download',return_value={}), \
             patch.object(panel_worker,'check_animation'), \
             patch.object(panel_worker.studio,'controller') as controller, \
             patch.object(panel_worker.studio,'progress_update'):
            panel_worker.execute(job,lambda:None)
        controller.assert_not_called()
        receipt=json.loads((target/'batch.json').read_text())
        self.assertEqual(receipt['rig_sha256'],'bound')
        self.assertIn('idle.fbx',receipt['files'])

    def test_failed_compact_worker_retains_quality_report(self):
        import os
        receipt=self.panel.tasks_dir/'compact1.json'
        atomic(receipt,{'id':'compact1','character':'hero','action':'compact','params':{},'outputs':{}})
        directory=self.root/'.local/jobs/compact-job'
        report={'schema':1,'summary':{'passed':0,'review':0,'failed':1},'results':[{'name':'idle','status':'failed','reason':'empty'}]}
        atomic(directory/'quality.json',report)
        fd=self.panel.worker_lock()
        with patch.object(panel_worker.studio,'BASE_DIR',self.root),patch.object(sys,'argv',['worker',str(receipt),str(fd)]), \
             patch.object(panel_worker,'execute',side_effect=ValueError('全部动作精简失败')), \
             patch.object(panel_worker.studio,'progress_read',return_value={'job':str(directory)}), \
             patch.object(panel_worker.studio,'progress_update'),patch.object(panel_worker.traceback,'print_exc'):
            self.assertEqual(panel_worker.main(),1)
        job=json.loads(receipt.read_text())
        self.assertEqual(job['quality_report'],report)
        self.assertEqual(job['status'],'failed')

    def test_preflight_failure_does_not_reuse_previous_quality_report(self):
        import os
        import progress
        receipt=self.panel.tasks_dir/'compact2.json'
        old={'schema':1,'summary':{'passed':0,'review':0,'failed':1},'results':[{'name':'old','status':'failed'}]}
        atomic(receipt,{'id':'compact2','character':'hero','action':'compact','params':{},'outputs':{},'quality_report':old})
        directory=self.root/'.local/jobs/old-job';atomic(directory/'quality.json',old)
        with patch.object(progress,'BASE_DIR',self.root):
            progress.update('hero','validate','old',job=str(directory))
            fd=self.panel.worker_lock()
            with patch.object(panel_worker.studio,'BASE_DIR',self.root),patch.object(sys,'argv',['worker',str(receipt),str(fd)]), \
                 patch.object(panel_worker,'execute',side_effect=ValueError('来源已变化')),patch.object(panel_worker.traceback,'print_exc'):
                self.assertEqual(panel_worker.main(),1)
        self.assertNotIn('quality_report',json.loads(receipt.read_text()))

    def test_export_contains_only_published_assets(self):
        import zipfile
        target=self.root/'deliverables/hero/job1'
        atomic(target/'manifest.json',{'source':{'character':'hero'}})
        (target/'idle_spritesheet.png').write_bytes(b'png')
        (target/'not_an_asset.txt').write_text('private')
        (target/'game').mkdir()
        (target/'game/idle_spritesheet.png').write_bytes(b'png')
        (target/'game/idle.tres').write_text('[gd_resource]')
        self.assertEqual(self.panel.asset_path('deliverables/hero/job1/game/idle.tres'),target/'game/idle.tres')
        (target/'game/private.txt').write_text('private')
        data=self.panel.export('hero','job1')
        with zipfile.ZipFile(BytesIO(data)) as archive:
            self.assertEqual(set(archive.namelist()),{'manifest.json','idle_spritesheet.png','game/idle_spritesheet.png','game/idle.tres'})

class PanelHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from http.server import ThreadingHTTPServer
        import threading
        from panel import handler
        cls.temp = tempfile.TemporaryDirectory()
        cls.panel = Panel(Path(cls.temp.name))
        cls.server = ThreadingHTTPServer(('127.0.0.1',0),handler(cls.panel))
        cls.server.daemon_threads = True
        cls.thread = threading.Thread(target=cls.server.serve_forever,daemon=True)
        cls.thread.start()
        cls.url = 'http://127.0.0.1:'+str(cls.server.server_port)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)
        cls.temp.cleanup()

    def request(self,path,body=None,headers=None):
        import urllib.request
        request = urllib.request.Request(self.url+path,data=json.dumps(body).encode() if body is not None else None,
                                         headers=headers or {})
        return urllib.request.urlopen(request,timeout=5)

    def test_state_and_static_app_load(self):
        with self.request('/api/state') as response:
            self.assertIn('token',json.load(response))
        with self.request('/app.js') as response:
            self.assertIn(b'/api/tasks',response.read())

    def test_mutation_rejects_missing_token_and_cross_origin(self):
        from urllib.error import HTTPError
        for headers in [{'Content-Type':'application/json'},
                        {'Content-Type':'application/json','X-Studio-Token':self.panel.token,'Origin':'https://untrusted.example'}]:
            with self.assertRaises(HTTPError) as error:
                self.request('/api/upload',{},headers)
            self.assertEqual(error.exception.code,403)

    def test_rejects_untrusted_host_and_encoded_private_paths(self):
        from urllib.error import HTTPError
        with self.assertRaises(HTTPError) as error:
            self.request('/api/state',headers={'Host':'untrusted.example'})
        self.assertEqual(error.exception.code,403)
        with self.assertRaises(HTTPError) as error:
            self.request('/asset/workspaces/hero/models/%2e%2e/%2e%2e/%2e%2e/.local/private.json')
        self.assertEqual(error.exception.code,400)

    def test_upload_to_workspace_via_http(self):
        image=BytesIO()
        Image.new('RGB',(64,64),'blue').save(image,format='PNG')
        data={'character':'http_hero','content':base64.b64encode(image.getvalue()).decode()}
        with self.request('/api/upload',data,{'Content-Type':'application/json','X-Studio-Token':self.panel.token}) as response:
            result=json.load(response)
        with self.request('/api/state?character=http_hero') as response:
            character=json.load(response)['selected']
        self.assertEqual(character['inputs'][0]['path'],result['image'])
        with self.request(character['inputs'][0]['url']) as response:
            self.assertEqual(Image.open(BytesIO(response.read())).size,(64,64))


class BrowserRuntimeTests(unittest.TestCase):
    def test_controller_reports_underlying_mixamo_failure(self):
        from unittest.mock import MagicMock
        import studio_core
        process=MagicMock()
        process.stdout=iter(['Mixamo 任务失败: 下载网格面数与角色不符（角色 47340，下载 44392）\n'])
        # Use a real in-memory stream to exercise close as well as iteration.
        from io import StringIO
        process.stdout=StringIO('Mixamo 任务失败: 下载网格面数与角色不符（角色 47340，下载 44392）\n')
        process.wait.return_value=1
        with patch.object(studio_core.subprocess,'Popen',return_value=process):
            with self.assertRaisesRegex(ValueError,'47340.*44392.*无需重新建模'):
                studio_core.controller('download','Idle','out.fbx','--character','hero')

    def test_missing_default_browser_reuses_installed_chromium(self):
        from unittest.mock import MagicMock
        import mixamo_controller
        with tempfile.TemporaryDirectory() as directory:
            home=Path(directory)
            installed=home/'Library/Caches/ms-playwright/chromium-1234/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing'
            installed.parent.mkdir(parents=True)
            installed.write_text('runtime')
            runtime=MagicMock()
            runtime.chromium.executable_path=str(home/'missing')
            with patch.object(mixamo_controller.Path,'home',return_value=home), patch.dict('os.environ',{},clear=True):
                self.assertEqual(mixamo_controller.browser_options(runtime),{'executable_path':str(installed)})
