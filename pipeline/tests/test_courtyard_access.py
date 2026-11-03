from pathlib import Path
import sys
import unittest
import numpy as np
from PIL import Image,ImageDraw
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from courtyard_access import floor_profile
from sprite_contract import settings


class CourtyardAccessTests(unittest.TestCase):
    def test_floor_collision_does_not_use_roof_only_fragment_as_ground(self):
        image=Image.new('RGBA',(256,256));d=ImageDraw.Draw(image)
        d.rectangle((10,60,99,180),fill='white')
        d.rectangle((100,60,200,80),fill='white')
        polygons,slices=floor_profile(image,[128,180],baselines=[(0,180)])
        self.assertTrue(polygons);self.assertTrue(slices)
        self.assertTrue(all(max(p[0] for p in poly)<0 for poly in polygons))
        self.assertTrue(all(s['foot_y']==0 for s in slices))
        settings(dict(title='wall',anchor=[128,180],world_scale=1,behavior='blocking',polygons=polygons))

    def test_passage_gap_has_no_floor_collision_but_keeps_occlusion_baseline(self):
        image=Image.new('RGBA',(256,256));d=ImageDraw.Draw(image)
        d.rectangle((0,30,255,180),fill='white');d.rectangle((96,90,159,255),fill=(0,0,0,0))
        before=np.asarray(image).copy()
        polygons,slices=floor_profile(image,[128,180],gap=[96,160],baselines=[(0,180)])
        for poly in polygons:
            self.assertTrue(max(p[0] for p in poly)<=-32 or min(p[0] for p in poly)>=32)
        self.assertTrue(all(s['foot_y']==0 for s in slices))
        self.assertTrue(np.array_equal(np.asarray(image),before))
