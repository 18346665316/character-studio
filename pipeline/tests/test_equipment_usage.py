import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from equipment_usage import load,save,validate,recipe,fingerprint
from test_equipment import config
from weapon_assets import digest

class UsageTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.equipment=self.root/'workspaces/hero/equipment/e1';self.equipment.mkdir(parents=True)
        (self.equipment/'equipment.json').write_text(json.dumps(config()))
        self.batch=self.root/'workspaces/hero/animations/b1';self.batch.mkdir(parents=True)
        (self.batch/'idle.fbx').write_bytes(b'idle');self.sha=digest(self.batch/'idle.fbx')
        self.files={'idle.fbx':self.sha}
        (self.batch/'batch.json').write_text(json.dumps({'rig_sha256':'rig','files':self.files}))
    def test_default_is_hand_and_no_settings_written_on_read(self):
        data=load(self.root,'hero','e1')
        self.assertEqual(data['default'],'hand')
        self.assertFalse((self.equipment/'usage.json').exists())
        self.assertEqual(recipe(data,self.files)['clips']['idle']['initial'],'inherit')
    def test_settings_and_timed_events_pin_content_and_preserve_other_actions(self):
        data=load(self.root,'hero','e1')
        action={'initial':'waist','events':[{'at':.3,'state':'hand'},{'at':.8,'state':'hidden'}]}
        result=save(self.root,'hero','e1','back',data['mounts'],'b1','idle.fbx',action)
        self.assertNotEqual(fingerprint(result),fingerprint(data))
        self.assertEqual(recipe(result,{'renamed.fbx':self.sha})['clips']['renamed'],action)
        self.assertEqual(recipe(result,{'idle.fbx':'different'})['clips']['idle']['initial'],'inherit')
        save(self.root,'hero','e1','back',data['mounts'],'b1','idle.fbx',{'initial':'inherit','events':[]})
        self.assertEqual(load(self.root,'hero','e1')['actions'],{})
    def test_bad_timing_mounts_and_changed_sources_rejected(self):
        data=load(self.root,'hero','e1')
        for events in [[{'at':float('nan'),'state':'hand'}],[{'at':1,'state':'hand'}],[{'at':.6,'state':'hand'},{'at':.5,'state':'back'}],[{'at':.5,'state':'other'}]]:
            bad=copy.deepcopy(data);bad['actions'][self.sha]={'initial':'hand','events':events}
            with self.assertRaises(ValueError):validate(bad)
        bad=copy.deepcopy(data);bad['mounts']['back']['position']=[0,2,0]
        with self.assertRaises(ValueError):validate(bad)
        (self.batch/'idle.fbx').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'变化'):save(self.root,'hero','e1','hand',data['mounts'],'b1','idle.fbx',{'initial':'hand','events':[]})
    def test_other_rig_and_tampered_equipment_rejected(self):
        data=load(self.root,'hero','e1');save(self.root,'hero','e1','hand',data['mounts'])
        cfg=config();cfg['weapon_scale']=1.2;(self.equipment/'equipment.json').write_text(json.dumps(cfg))
        with self.assertRaisesRegex(ValueError,'不匹配'):load(self.root,'hero','e1')

    def test_panel_export_pins_settings_and_rejects_changed_retry(self):
        from panel import Panel
        from unittest.mock import patch
        panel=Panel(self.root)
        c={'has_model':True,'model_approved':True,'rig':{'ready':True},'batches':[{'id':'b1','files':['idle.fbx'],'fingerprint':'fp','current_rig':True}],
           'approvals':{'motions':{'b1':{'fingerprint':'fp'}}}}
        params={'batch':'b1','equipment_id':'e1'}
        with patch.object(panel,'character',return_value=c):
            pinned=panel.validate_task('hero','bake',params)
            data=load(self.root,'hero','e1')
            save(self.root,'hero','e1','hidden',data['mounts'])
            with self.assertRaisesRegex(ValueError,'已变化'):panel.validate_task('hero','bake',pinned)
            fresh=panel.validate_task('hero','bake',params)
            self.assertNotEqual(fresh['equipment_usage_sha256'],pinned['equipment_usage_sha256'])
