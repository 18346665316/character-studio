import sys
from pathlib import Path
import unittest
import numpy as np
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from wall_seam import select,cut
from wall_strip import source_origin
from wall_assets import whole_cutout
from test_wall_repeat import art


class WallSeamTests(unittest.TestCase):
    def test_both_axes_repeat_with_exact_pixel_partition(self):
        for axis in ('a','b'):
            source=whole_cutout(art(axis));origin=source_origin(axis)
            result=select(source,origin,axis)
            self.assertTrue(result['passed'],result['selected'])
            self.assertEqual(result,select(source,origin,axis))
            sprites,expected,report=cut(source,origin,axis,result,count=2)
            restored=Image.new('RGBA',source.size)
            for sprite,offset in zip(sprites,report['source_offsets_px']):
                restored.alpha_composite(sprite,offset)
            self.assertTrue(np.array_equal(np.asarray(restored),np.asarray(expected)))
            offsets=report['source_offsets_px']
            self.assertEqual([offsets[1][i]-offsets[0][i] for i in range(2)],report['repeat_offset_px'])

    def test_color_drift_still_rejected(self):
        result=select(whole_cutout(art(drift=True)),source_origin('a'))
        self.assertFalse(result['passed'])

    def test_absolute_art_height_does_not_define_repeatability(self):
        source=whole_cutout(art());shifted=Image.new('RGBA',source.size)
        shifted.alpha_composite(source,(0,-20))
        result=select(shifted,source_origin('a'))
        self.assertTrue(result['passed'])
