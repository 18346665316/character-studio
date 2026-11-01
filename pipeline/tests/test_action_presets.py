import sys,unittest,tempfile,json
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from action_presets import PRESETS,validate_metadata,receipt_metadata
from panel import Panel
import panel_worker

class ActionPresets(unittest.TestCase):
    def test_replacement_retains_stable_role_and_rejects_stale_mapping(self):
        params={'roles':{'Jogging':'run','Standing Jump':'jump'},'preset':{'id':'basic_movement','version':1}}
        validated=validate_metadata(['Jogging','Standing Jump'],params)
        metadata=receipt_metadata(validated)
        self.assertEqual(metadata['action_roles']['jogging.fbx'],'run')
        self.assertFalse(metadata['loop_intent']['standing_jump.fbx'])
        with self.assertRaises(ValueError):validate_metadata(['Running'],params)
        with self.assertRaises(ValueError):validate_metadata(['Idle','Walking'],{'roles':{'Idle':'idle','Walking':'idle'}})
        with self.assertRaises(ValueError):validate_metadata(['Idle'],{'preset':{'id':'missing','version':1}})

    def test_preset_download_receipt_survives_worker_and_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);ws=root/'workspaces/hero';ws.mkdir(parents=True)
            preset=PRESETS[0];actions=[a['title'] for a in preset['actions']]
            params={'actions':actions,'roles':{a['title']:a['role'] for a in preset['actions']},'preset':{'id':preset['id'],'version':1}}
            with patch.object(Panel,'character',return_value={'rig':{'ready':True},'batches':[]}):
                params=Panel(root).validate_task('hero','download',params)
            job={'character':'hero','action':'download','params':params,'outputs':{'batch':'batch'}}
            def download(*args):Path(args[2]).write_bytes(b'fbx')
            binding={'bound_sha256':'rig','geometry':{}}
            with patch('studio_core.BASE_DIR',root),patch('progress.BASE_DIR',root),patch.object(panel_worker,'require_ready',return_value=binding),patch('studio_core.model_path',return_value=ws/'model.zip'),patch('studio_core.controller',side_effect=download) as controller,patch.object(panel_worker,'inspect_download',return_value={}),patch.object(panel_worker,'check_animation'):
                panel_worker.execute(job,lambda:None)
                receipt=json.loads((ws/'animations/batch/batch.json').read_text())
                self.assertEqual(set(receipt['action_roles'].values()),{'idle','walk','run','jump'})
                self.assertEqual(receipt['preset'],params['preset'])
                self.assertEqual(controller.call_count,4)
                panel_worker.execute(job,lambda:None)
                self.assertEqual(controller.call_count,4)
                self.assertEqual(receipt,json.loads((ws/'animations/batch/batch.json').read_text()))
