"""Regression checks for cross-entry execution, recovery and asset-layer boundaries."""
import ast
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

PIPELINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PIPELINE))
from asset_repository import AssetRepository, atomic
from panel import Panel
from task_lock import acquire, child_options, task_lock, TaskBusyError
import mixamo_mcp_server as mcp
import mixamo_state
import panel_worker
import studio_core as studio


class ArchitectureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.panel = Panel(self.root)

    def test_recovery_preserves_worker_completion_before_lock_acquisition(self):
        path = self.panel.tasks_dir / 'race.json'
        initial = {'id':'race', 'status':'running', 'created_at':'2026-11-01'}
        completed = {**initial, 'status':'succeeded', 'outputs':{'delivery':'published'}}
        atomic(path, initial)
        def finish_then_lock():
            atomic(path, completed)
            return acquire(self.root)
        with patch.object(self.panel, 'worker_lock', side_effect=finish_then_lock):
            self.panel.recover_jobs()
        self.assertEqual(json.loads(path.read_text()), completed)

    def test_jobs_is_read_only_and_recovery_leaves_active_worker_alone(self):
        path = self.panel.tasks_dir / 'active.json'
        atomic(path, {'id':'active', 'status':'running', 'created_at':'2026-11-01'})
        before = path.read_bytes()
        self.panel.jobs()
        self.assertEqual(path.read_bytes(), before)
        with task_lock(self.root):
            self.panel.recover_jobs()
        self.assertEqual(path.read_bytes(), before)
        self.panel.recover_jobs()
        self.assertEqual(json.loads(path.read_text())['status'], 'interrupted')

    def test_nested_services_reuse_lease_but_other_threads_cannot_enter(self):
        import concurrent.futures
        with task_lock(self.root) as first:
            with task_lock(self.root) as second:
                self.assertEqual(first, second)
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    self.assertIsNone(pool.submit(acquire, self.root).result(timeout=5))
        fd = acquire(self.root)
        self.assertIsNotNone(fd)
        os.close(fd)

    def test_child_handoff_keeps_lease_after_parent_releases_it(self):
        code = '''
import sys
from task_lock import task_lock
with task_lock(sys.argv[1]):
    print('ready', flush=True)
    sys.stdin.readline()
'''
        child = None
        try:
            with task_lock(self.root):
                child = subprocess.Popen([sys.executable, '-c', code, str(self.root)],
                    cwd=PIPELINE, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE, text=True, **child_options())
            self.assertEqual(child.stdout.readline().strip(), 'ready')
            self.assertIsNone(acquire(self.root))
            output, error = child.communicate('\n', timeout=10)
            self.assertEqual(child.returncode, 0, error)
            fd = acquire(self.root)
            self.assertIsNotNone(fd)
            os.close(fd)
        finally:
            if child:
                if child.poll() is None:
                    child.kill()
                child.communicate(timeout=10)

    def test_busy_web_lease_rejects_cli_without_overwriting_progress(self):
        import progress
        with patch.object(studio, 'BASE_DIR', self.root), patch.object(progress, 'BASE_DIR', self.root):
            progress.update('hero', 'render', 'active task', job='active-job')
            path = self.root / '.local/progress/hero.json'
            before = path.read_bytes()
            fd = self.panel.worker_lock()
            try:
                with patch.object(sys, 'argv', ['studio', 'prepare', '--character', 'hero']), \
                     patch('prepare_model.prepare_character') as prepare:
                    self.assertEqual(studio.main(), 1)
                prepare.assert_not_called()
                self.assertEqual(path.read_bytes(), before)
            finally:
                os.close(fd)

    def test_busy_cli_lease_blocks_web_start_approval_and_mcp_before_mutation(self):
        root_patch = patch.object(mcp, 'CONTROLLER_SCRIPT', str(self.root / 'pipeline/mixamo_controller.py'))
        fd = acquire(self.root)
        try:
            with patch.object(self.panel, 'validate_task') as validate, \
                 patch.object(mcp, 'write_state') as write_state, \
                 patch.object(mcp.subprocess, 'Popen') as spawn, root_patch:
                for call in (lambda: self.panel.start({'character':'hero', 'action':'prepare'}),
                             lambda: self.panel.approve({'character':'hero', 'kind':'model'}),
                             lambda: mcp.handle_request({'method':'tools/call', 'id':1, 'params':{
                                 'name':'mixamo_upload_and_rig', 'arguments':{'character':'hero', 'file_path':str(self.root / 'missing.zip')}}})):
                    with self.assertRaises(TaskBusyError):
                        call()
                validate.assert_not_called()
                write_state.assert_not_called()
                spawn.assert_not_called()
        finally:
            os.close(fd)

    def test_reused_foreign_skeleton_is_quarantined_before_registration(self):
        directory = self.root / 'workspaces/hero/animations/retry'
        directory.mkdir(parents=True)
        source = directory / 'idle.fbx'
        source.write_bytes(b'foreign-skeleton')
        binding = {'bound_sha256':'current-rig', 'geometry':{'triangles':100, 'bone_names':['ExpectedBone']}}
        info = {'triangles':100, 'skeleton_bones':1, 'skinned_meshes':1,
                'bone_names':['ForeignBone'], 'animations':[{'changing_tracks':1}]}
        job = {'character':'hero', 'action':'download', 'params':{'actions':['Idle']}, 'outputs':{'batch':'retry'}}
        with patch.object(studio, 'BASE_DIR', self.root), \
             patch.object(studio, 'model_path', return_value=self.root / 'model.zip'), \
             patch.object(panel_worker, 'require_ready', return_value=binding), \
             patch.object(panel_worker, 'inspect_download', return_value=info), \
             patch.object(studio, 'progress_update'), \
             patch.object(studio, 'controller', side_effect=ValueError('download unavailable')) as download:
            with self.assertRaisesRegex(ValueError, 'download unavailable'):
                panel_worker.execute(job, lambda: None)
        download.assert_called_once()
        self.assertFalse((directory / 'batch.json').exists())
        self.assertFalse(source.exists())
        self.assertEqual(len(list(directory.glob('rejected-*/idle.fbx'))), 1)
        with self.assertRaises(mixamo_state.MeshIdentityError):
            mixamo_state.check_animation(info, binding['geometry'])

    def test_mcp_spawn_failure_restores_binding_and_releases_execution_lease(self):
        source = self.root / 'model.zip'
        source.write_bytes(b'upload')
        state_path = self.root / '.local/mixamo/hero/state.json'
        previous = {'character':'hero', 'status':'ready', 'bound_sha256':'reviewed'}
        atomic(state_path, previous)
        def fail_spawn(*args, **kwargs):
            fd, = kwargs['pass_fds']
            self.assertEqual(kwargs['env']['STUDIO_TASK_LOCK_FD'], str(fd))
            self.assertIsNone(acquire(self.root))
            raise OSError('spawn failed')
        with patch.object(mcp, 'CONTROLLER_SCRIPT', str(self.root / 'pipeline/mixamo_controller.py')), \
             patch.object(mixamo_state, 'BASE_DIR', self.root), \
             patch.object(mcp.subprocess, 'Popen', side_effect=fail_spawn):
            with self.assertRaisesRegex(OSError, 'spawn failed'):
                mcp.handle_request({'method':'tools/call', 'id':1, 'params':{
                    'name':'mixamo_upload_and_rig', 'arguments':{'character':'hero', 'file_path':str(source)}}})
        self.assertEqual(json.loads(state_path.read_text()), previous)
        fd = acquire(self.root)
        self.assertIsNotNone(fd)
        os.close(fd)

    def test_sequence_query_does_not_load_full_character_or_create_panel_state(self):
        from sequence_render import make_plan
        self.root = self.root / 'offline'
        self.root.mkdir()
        ws = self.root / 'workspaces/hero'
        prepared = ws / 'models/prepared/v1'
        prepared.mkdir(parents=True)
        (ws / 'models/hero.obj').write_bytes(b'mesh')
        (prepared / 'mixamo.zip').write_bytes(b'upload')
        bound = ws / 'rig/v1/bound.fbx'
        bound.parent.mkdir(parents=True)
        bound.write_bytes(b'bound')
        repo = AssetRepository(self.root)
        atomic(prepared / 'prepare.json', {'source_sha256':repo.digest(ws / 'models/hero.obj')})
        atomic(self.root / '.local/mixamo/hero/state.json', {'status':'ready', 'human_reviewed':True,
            'bound_model':str(bound), 'bound_sha256':repo.digest(bound), 'source_sha256':repo.digest(prepared / 'mixamo.zip')})
        source = ws / 'animations/b1/idle.fbx'
        source.parent.mkdir(parents=True)
        source.write_bytes(b'idle')
        hashes = {'idle.fbx':repo.digest(source)}
        atomic(source.parent / 'batch.json', {'character':'hero', 'batch':'b1', 'rig_sha256':repo.digest(bound), 'files':hashes})
        delivery = self.root / 'deliverables/hero/d1'
        atomic(delivery / 'manifest.json', {'source':{'character':'hero', 'batch':'b1', 'files':hashes}, 'idle_spritesheet.png':{}})
        (delivery / 'idle_spritesheet.png').write_bytes(b'sheet')
        recipe = {'sources':['d1/idle'], 'renderer':'godot', 'view':'front', 'frame_size':128, 'supersample':1, 'equipment_id':None}
        with patch.object(AssetRepository, 'character', side_effect=AssertionError('full UI read')):
            result = make_plan(repo, 'hero', recipe)
        self.assertEqual(result['sources'][0]['sha256'], hashes['idle.fbx'])
        self.assertFalse((self.root / '.local/panel/tasks').exists())

    def test_business_modules_do_not_import_web_adapter(self):
        for filename in ('asset_repository.py', 'sequence_render.py', 'compact_delivery.py',
                         'motion_heading.py', 'equipment_usage.py', 'motion_sampling.py', 'sampling_compare.py'):
            tree = ast.parse((PIPELINE / filename).read_text())
            imports = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
            self.assertNotIn('panel', imports, filename)


if __name__ == '__main__':
    unittest.main()
