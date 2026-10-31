"""No cloud/browser required: verify human handoff, identity and reusable rig guards."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import mixamo_state as state
import mixamo_controller as controller
import studio_core as studio


class Handoff(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.patches = [patch('progress.BASE_DIR', self.root), patch.object(state, 'BASE_DIR', self.root), patch.object(studio, 'BASE_DIR', self.root)]
        for p in self.patches:
            p.start()
        self.source = self.root / 'workspaces/hero/models/hero.zip'
        self.source.parent.mkdir(parents=True)
        self.source.write_bytes(b'source')
        self.bound = self.source.parent / 'bound.fbx'
        self.bound.write_bytes(b'bound')
        self.fields = dict(human_reviewed=True, source_model=str(self.source), source_sha256=state.file_hash(self.source),
                           bound_model=str(self.bound), bound_sha256=state.file_hash(self.bound))

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_only_reviewed_ready_state_can_download(self):
        for status in ['unbound', 'waiting_for_markers', 'processing_rig', 'waiting_for_review',
                       'verifying_bound_model', 'interrupted', 'failed', 'needs_review']:
            state.write_state('hero', status, **self.fields)
            with self.assertRaises(ValueError):
                state.require_ready('hero')
        state.write_state('hero', 'ready', **self.fields)
        self.assertEqual(state.require_ready('hero')['status'], 'ready')

    def test_changed_source_or_binding_requires_new_review(self):
        state.write_state('hero', 'ready', **self.fields)
        self.source.write_bytes(b'changed')
        with self.assertRaises(ValueError):
            state.require_ready('hero')
        self.source.write_bytes(b'source')
        self.bound.unlink()
        with self.assertRaises(ValueError):
            state.require_ready('hero')

    def test_defaults_wrong_mesh_and_static_clips_rejected(self):
        reference = {'triangles': 64056, 'mesh_names': ['hero']}
        valid = {'triangles': 64056, 'mesh_names': ['hero'], 'skeleton_bones': 65,
                 'skinned_meshes': 1, 'animations': [{'changing_tracks': 53}]}
        state.check_mesh_identity(valid, reference)
        state.check_motion(valid)
        for override in [{'mesh_names': ['Beta_Surface']}, {'triangles': 10000},
                         {'skeleton_bones': 0}, {'skinned_meshes': 0}]:
            with self.assertRaises(ValueError):
                state.check_mesh_identity({**valid, **override}, reference)
        with self.assertRaises(ValueError):
            state.check_motion({**valid, 'animations': [{'changing_tracks': 0}]})

    def test_download_reuses_binding_without_upload(self):
        state.write_state('hero', 'ready', **self.fields)
        def fake_controller(*args):
            self.assertEqual(args[0], 'download')
            self.assertEqual(args[-2:], ('--character', 'hero'))
            Path(args[2]).write_bytes(b'validated-motion')
        with patch.object(studio, 'controller', side_effect=fake_controller) as call:
            studio.download('hero', ['Running'], 'batch1')
        self.assertEqual(call.call_count, 1)
        receipt = json.loads((self.root / 'workspaces/hero/animations/batch1/batch.json').read_text())
        self.assertEqual(receipt['rig_sha256'], state.file_hash(self.bound))

    def test_unreviewed_role_cannot_start_download_batch(self):
        with patch.object(studio, 'controller') as call:
            with self.assertRaises(ValueError):
                studio.download('hero', ['Running'], 'batch1')
        call.assert_not_called()
        self.assertFalse((self.root / 'workspaces/hero/animations').exists())

    def test_unreviewed_role_cannot_open_download_browser(self):
        with patch.object(controller, 'BASE_DIR', self.root), patch.object(controller, 'sync_playwright') as browser:
            # Playwright context may be initialized, but no browser/profile is opened.
            with patch.object(controller, 'open_profile') as profile:
                with self.assertRaises(ValueError):
                    controller.action_download('Running', self.root / 'workspaces/hero/animations/batch/run.fbx', 'hero')
                profile.assert_not_called()

    def test_upload_waits_for_explicit_browser_approval(self):
        page = MagicMock()
        page.is_closed.return_value = False
        page.locator.return_value.count.return_value = 0
        page.get_by_role.return_value.count.return_value = 1
        page.locator('body').inner_text.return_value = 'Review character'
        callback = {}
        page.expose_function.side_effect = lambda name, function: callback.update(approve=function)
        enabled = []
        def evaluate(script, data):
            enabled.append(data['enabled'])
            if data['enabled']:
                callback['approve']()
        page.evaluate.side_effect = evaluate
        context = MagicMock()
        p = MagicMock()
        info = {'triangles': 100, 'mesh_names': ['hero'], 'skeleton_bones': 65, 'skinned_meshes': 1}
        def save(page, target, **kwargs):
            target.write_bytes(b'reviewed-bound-model')
            return target
        with patch.object(controller, 'BASE_DIR', self.root), \
             patch.object(controller, 'sync_playwright', return_value=p), \
             patch.object(controller, 'open_profile', return_value=(context, page)) as profile, \
             patch.object(controller, 'modal_open', side_effect=[True, False, False]), \
             patch.object(controller, 'source_geometry', return_value={'triangles': 100, 'mesh_names': []}), \
             patch.object(controller, 'save_download', side_effect=save), \
             patch.object(controller, 'inspect_download', return_value=info):
            controller.action_upload(self.source, 'hero')
        self.assertEqual(enabled, [False, True])
        self.assertTrue(profile.call_args.kwargs['visible'])
        self.assertTrue(state.require_ready('hero')['human_reviewed'])
        # Studio only clicked Upload Character. No Next button was requested.
        self.assertFalse(any('Next' in str(call) for call in page.get_by_role.call_args_list))
        context.close.assert_called_once()

    def test_closed_browser_does_not_mark_binding_ready(self):
        page = MagicMock()
        page.is_closed.return_value = True
        context = MagicMock()
        with patch.object(controller, 'BASE_DIR', self.root), \
             patch.object(controller, 'sync_playwright'), \
             patch.object(controller, 'open_profile', return_value=(context, page)), \
             patch.object(controller, 'source_geometry', return_value={'triangles': 100}):
            with self.assertRaises(ValueError):
                controller.action_upload(self.source, 'hero')
        self.assertEqual(state.read_state('hero')['status'], 'failed')
        with self.assertRaises(ValueError):
            state.require_ready('hero')

    def test_character_pose_export_is_allowed_only_for_binding(self):
        page = MagicMock()
        modal = page.locator.return_value.first
        format_select = MagicMock()
        pose_select = MagicMock()
        format_select.locator.return_value.all_text_contents.return_value = ['FBX Binary(.fbx)']
        pose_select.locator.return_value.all_text_contents.return_value = ['T-pose', 'Original Pose(.fbx)']
        modal.locator.return_value.all.return_value = [format_select, pose_select]
        downloaded = page.expect_download.return_value.__enter__.return_value.value
        downloaded.failure.return_value = None
        def save(path):
            Path(path).write_bytes(b'bound-file')
        downloaded.save_as.side_effect = save
        target = self.root / 'download.fbx'
        controller.save_download(page, target, bind_pose=True)
        self.assertEqual(target.read_bytes(), b'bound-file')
        with self.assertRaises(ValueError):
            controller.save_download(page, self.root / 'motion.fbx')
        self.assertFalse((self.root / 'motion.fbx').exists())

    def test_role_path_cannot_write_another_role(self):
        with self.assertRaises(ValueError):
            controller.action_download('Running', self.root / 'workspaces/other/animations/batch/run.fbx', 'hero')

    def test_selects_result_title_without_cancelling_search_query(self):
        page = MagicMock()
        events = []
        search = page.get_by_placeholder.return_value
        card = page.locator.return_value.filter.return_value.first
        search.press.side_effect = lambda key: events.append(key)
        card.wait_for.side_effect = lambda **kwargs: events.append('results_ready')
        card.get_by_text.return_value.click.side_effect = lambda: events.append('select')
        controller.select_animation(page, 'Walking')
        self.assertEqual(events, ['Enter', 'results_ready', 'select'])


if __name__ == '__main__':
    unittest.main()
