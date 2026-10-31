import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import mixamo_state as state
import mixamo_controller as controller

class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve()
        for target in ['mixamo_state.BASE_DIR','mixamo_controller.BASE_DIR','progress.BASE_DIR']:
            patcher=patch(target,self.root);patcher.start();self.addCleanup(patcher.stop)
        source=self.root/'source.zip';source.write_bytes(b'source')
        bound=self.root/'bound.fbx';bound.write_bytes(b'bound')
        self.info={'triangles':100,'textured_surfaces':1,'skeleton_bones':2,'skinned_meshes':1,'bone_names':['root','hand'],'animations':[{'changing_tracks':2}]}
        self.fields={'source_model':str(source),'source_sha256':state.file_hash(source),'bound_model':str(bound),'bound_sha256':state.file_hash(bound),'human_reviewed':True,'geometry':self.info}
        state.write_state('hero','ready',**self.fields)
        self.context,self.page=MagicMock(),MagicMock()
        self.output=self.root/'workspaces/hero/animations/b1/idle.fbx'
    def run_download(self,infos,restore=None):
        values=iter(infos)
        def request(page,name,path):
            path.write_bytes(b'download')
            value=next(values)
            if isinstance(value,Exception): raise value
            return value
        with patch.object(controller,'sync_playwright'),patch.object(controller,'open_profile',return_value=(self.context,self.page)),patch.object(controller,'request_animation',side_effect=request),patch.object(controller,'restore_bound_character',side_effect=restore) as recover:
            controller.action_download('Idle',self.output,'hero')
        return recover
    def test_matching_character_never_uploads(self):
        recover=self.run_download([self.info]);recover.assert_not_called()
        self.assertTrue(self.output.exists())
    def test_mismatch_restores_once_and_publishes_only_verified_result(self):
        recover=self.run_download([{**self.info,'triangles':40},self.info])
        recover.assert_called_once()
        self.assertTrue(self.output.exists());self.assertEqual(state.read_state('hero')['status'],'ready')
        self.assertTrue((self.output.parent/'.mixamo-recovery.json').exists())
    def test_second_mismatch_never_published_and_requires_manual_review(self):
        with self.assertRaisesRegex(ValueError,'自动恢复一次'):self.run_download([{**self.info,'triangles':40},{**self.info,'triangles':40}])
        self.assertFalse(self.output.exists());self.assertFalse(state.read_state('hero')['cloud_recovery'])
        with self.assertRaises(ValueError):state.require_ready('hero',allow_cloud_recovery=True)
    def test_static_motion_does_not_upload_or_revoke_review(self):
        with self.assertRaisesRegex(ValueError,'动态轨道'):self.run_download([{**self.info,'animations':[]}])
        self.assertFalse(self.output.exists());self.assertEqual(state.read_state('hero')['status'],'ready')
    def test_search_timeout_does_not_revoke_local_binding(self):
        with self.assertRaisesRegex(RuntimeError,'timeout'):self.run_download([RuntimeError('timeout')])
        self.assertEqual(state.read_state('hero')['status'],'ready')
    def test_legacy_cloud_mismatch_can_recover_but_changed_source_cannot(self):
        state.write_state('hero','needs_review',**self.fields,error='下载网格面数与角色不符')
        self.assertEqual(state.require_ready('hero',allow_cloud_recovery=True)['status'],'needs_review')
        self.run_download([{**self.info,'triangles':40},self.info])
        Path(self.fields['source_model']).write_bytes(b'changed')
        with self.assertRaises(ValueError):state.require_ready('hero',allow_cloud_recovery=True)
    def test_same_batch_cannot_upload_twice(self):
        self.output.parent.mkdir(parents=True)
        (self.output.parent/'.mixamo-recovery.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'自动恢复一次'):self.run_download([{**self.info,'bone_names':['different']}])
        self.assertFalse(self.output.exists())
    def test_restore_failure_never_overwrites_local_binding(self):
        with self.assertRaisesRegex(ValueError,'markers'):self.run_download([{**self.info,'triangles':40}],ValueError('markers required'))
        self.assertFalse(self.output.exists());self.assertEqual(Path(self.fields['bound_model']).read_bytes(),b'bound')
    def test_cloud_tasks_are_serialized_across_characters(self):
        with controller.cloud_lock():
            with self.assertRaisesRegex(ValueError,'云端任务'):
                with controller.cloud_lock():pass
    def test_restore_marker_wizard_is_never_advanced(self):
        self.page.is_closed.return_value=False
        modal=self.page.locator.return_value.first
        modal.count.return_value=1;modal.is_visible.return_value=True
        modal.inner_text.return_value='Place markers on chin, wrists and groin'
        with self.assertRaisesRegex(ValueError,'重新摆点'):controller.restore_bound_character(self.page,'hero',state.require_ready('hero'))
        modal.get_by_role.assert_not_called()

    def test_restore_accepts_review_confirmation_without_marker_steps(self):
        self.page.is_closed.return_value=False
        modal=MagicMock();modal.count.side_effect=[1]+[0]*6;modal.is_visible.return_value=True
        modal.inner_text.return_value='Review your uploaded character'
        next_button=MagicMock();next_button.count.return_value=1
        next_button.first.is_visible.return_value=True;next_button.first.is_enabled.return_value=True
        absent=MagicMock();absent.count.return_value=0
        modal.get_by_role.side_effect=lambda role,name,exact: next_button if name=='Next' else absent
        loading=MagicMock();loading.count.return_value=0
        self.page.locator.side_effect=lambda selector: MagicMock(first=modal) if 'modal-dialog' in selector else loading
        self.page.get_by_role.return_value.count.return_value=1
        self.page.get_by_role.return_value.first.is_visible.return_value=True
        controller.restore_bound_character(self.page,'hero',state.require_ready('hero'))
        next_button.first.click.assert_called_once()
        self.page.locator.assert_any_call('input[type="file"]')
