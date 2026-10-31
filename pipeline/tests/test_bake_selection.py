"""A selected render must not inspect or stage unchecked sibling motions."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import studio_core as core


class BakeSelectionTests(unittest.TestCase):
    def test_only_selected_motion_is_verified_and_staged(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            source=root/'workspaces/hero/animations/b1'
            source.mkdir(parents=True)
            (source/'idle.fbx').write_bytes(b'valid-motion')
            receipt={'character':'hero','batch':'b1','files':{'idle.fbx':core.digest(source/'idle.fbx'),'unchecked.fbx':'missing'}}
            (source/'batch.json').write_text(json.dumps(receipt))
            (root/'pipeline/godot').mkdir(parents=True)
            def stop_after_staging(*args,**kwargs):
                self.assertEqual([p.name for p in (root/'.local/jobs/test/godot/animations').iterdir()],['idle.fbx'])
                job=json.loads((root/'.local/jobs/test/job.json').read_text())
                self.assertEqual(job['source_files'],{'idle.fbx':receipt['files']['idle.fbx']})
                raise RuntimeError('verified staging')
            with patch.object(core,'BASE_DIR',root),patch.object(core,'progress_update'),patch.object(core,'new_batch',return_value='test'),patch.object(core,'inspect_download',return_value={'textured_surfaces':1,'animations':[{'changing_tracks':1}]}) as inspect,patch.object(core.subprocess,'run',side_effect=stop_after_staging):
                with self.assertRaisesRegex(RuntimeError,'verified staging'):
                    core.bake('hero','b1',selected_files=['idle.fbx'])
                inspect.assert_called_once_with(source/'idle.fbx')
            self.assertEqual(json.loads((source/'batch.json').read_text()),receipt)
