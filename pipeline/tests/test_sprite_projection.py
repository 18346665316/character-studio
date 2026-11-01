import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sprite_projection import plan

class ProjectionTests(unittest.TestCase):
    def measurement(self,lo=(-.6,0),hi=(.6,1.8)):
        return {'reference_height':1.8,'reference_origin':[0,0,0],'screen_min':lo,'screen_max':hi,'view':'front'}

    def test_weapon_and_jump_expand_canvas_without_shrinking_character(self):
        stand=plan(self.measurement(),96,4,'rig')
        jump=plan(self.measurement((-2,-.2),(2,4)),96,4,'rig')
        self.assertGreater(jump['frame_size'],stand['frame_size'])
        self.assertEqual(jump['pixels_per_source_unit'],stand['pixels_per_source_unit'])
        self.assertAlmostEqual(jump['reference_height']/jump['camera_size']*jump['frame_size'],96)
        self.assertEqual(jump['render_size'],jump['frame_size']*4)

    def test_exported_anchor_reconstructs_common_ground_coordinates(self):
        for measurement in [self.measurement(),self.measurement((-2,-.3),(1,4))]:
            p=plan(measurement,96,2,'rig')
            c=p['camera_center'];d=p['pixels_per_source_unit'];size=p['frame_size']
            self.assertAlmostEqual(p['anchor_px'][0],-c[0]*d+size/2)
            self.assertAlmostEqual(p['anchor_px'][1],c[1]*d+size/2)
            self.assertEqual(p['reference_sha256'],'rig')

    def test_bad_parameters_and_excessive_root_motion_rejected(self):
        for value in [True,95,0,256]:
            with self.assertRaises(ValueError):plan(self.measurement(),value,4,'rig')
        m=self.measurement();m['reference_height']=float('nan')
        with self.assertRaises(ValueError):plan(m,96,4,'rig')
        with self.assertRaises(ValueError):plan(self.measurement((0,0),(100,100)),96,4,'rig')
