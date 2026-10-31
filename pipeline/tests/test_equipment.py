import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from equipment import validate, load


def config():
    return {'schema':1,'weapon':'studio_sword_v1','bone':'mixamorig_RightHand',
            'hand_points':[[0,0,0],[0,.01,0],[.01,0,0]],
            'weapon_points':[[0,0,0],[0,.7,0],[.1,0,0]],
            'source_units_per_meter':1,'weapon_scale':1,'confirmed':True,
            'character':'hero','batch':'batch1','files':{'idle.fbx':'sha'},'rig_sha256':'rig'}

class EquipmentTests(unittest.TestCase):
    def test_valid_frame_and_both_hands(self):
        value=config()
        self.assertIs(validate(value),value)
        value['bone']='mixamorig_LeftHand'
        validate(value)

    def test_rejects_missing_collinear_and_nonfinite_points(self):
        for points in [[],[[0,0,0],[0,0,0],[1,0,0]],[[0,0,0],[0,1,0],[0,2,0]],[[0,0,0],[0,1,0],[float('nan'),0,0]]]:
            value=config();value['hand_points']=points
            with self.assertRaises(ValueError):validate(value)

    def test_rejects_unconfirmed_invalid_bone_or_scale(self):
        for key,value in [('confirmed',False),('bone','root'),('weapon_scale',0),('weapon_scale',float('inf')),('source_units_per_meter',True)]:
            settings=config();settings[key]=value
            with self.assertRaises(ValueError):validate(settings)

    def test_rejects_far_away_grip(self):
        settings=config();settings['hand_points'][0]=[100,0,0]
        with self.assertRaises(ValueError):validate(settings)

    def test_load_reuses_same_rig_across_batches(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            settings=config()
            path=root/'workspaces/hero/equipment/e1/equipment.json'
            path.parent.mkdir(parents=True);path.write_text(json.dumps(settings))
            receipt=root/'workspaces/hero/animations/batch1/batch.json'
            receipt.parent.mkdir(parents=True)
            original={'files':settings['files'],'rig_sha256':'rig'}
            receipt.write_text(json.dumps(original))
            self.assertEqual(load(root,'hero','batch1','e1')['bone'],'mixamorig_RightHand')
            second=root/'workspaces/hero/animations/batch2/batch.json'
            second.parent.mkdir(parents=True)
            second.write_text(json.dumps({'files':{'slash.fbx':'new'},'rig_sha256':'rig'}))
            self.assertEqual(load(root,'hero','batch2','e1')['hand_points'],settings['hand_points'])
            self.assertEqual(load(root,'hero','batch2','e1')['batch'],'batch1')
            receipt.unlink()
            self.assertEqual(load(root,'hero',None,'e1')['rig_sha256'],'rig')
            self.assertEqual(load(root,'hero','batch2','e1')['weapon'],'studio_sword_v1')
            for change in [{'rig_sha256':'other'},{'rig_sha256':None},{'character':'other'}]:
                receipt.write_text(json.dumps({**original,**change}))
                with self.assertRaises(ValueError):load(root,'hero','batch1','e1')

    def test_panel_supports_equipment_task_and_bake_selection(self):
        from panel import ACTIONS
        self.assertIn('equipment',ACTIONS)
