"""Wall interfaces agree in world and projected coordinates on both ground axes."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from build_courtyard_wall_templates import LENGTH,THICKNESS,HEIGHT,CAP_RISE,point,project,section,render,render_continuous


class WallInterfaces(unittest.TestCase):
    def test_continuous_reference_does_not_draw_vertical_end_outlines(self):
        for axis,x in [('a',248),('b',264)]:
            self.assertLess(max(render(axis).getpixel((x,230))),100)
            self.assertGreater(min(render_continuous(axis).getpixel((x,230))),120)

    def test_two_axes_have_distinct_two_to_one_slopes(self):
        self.assertEqual(project(point('a',LENGTH,0,0)),(128,64))
        self.assertEqual(project(point('b',LENGTH,0,0)),(-128,64))

    def test_all_cross_section_vertices_match_at_both_seams(self):
        for axis in ('a','b'):
            step=point(axis,LENGTH,0,0)
            for n in (1,2):
                for left,right in zip(section(axis,(n-1)*LENGTH),section(axis,n*LENGTH)):
                    self.assertEqual(tuple(left[i]+step[i] for i in range(3)),right)
                    self.assertEqual(tuple(project(left)[i]+project(step)[i] for i in range(2)),project(right))

    def test_wall_and_cap_dimensions_are_shared(self):
        for axis in ('a','b'):
            cross=section(axis,0)
            transverse=[v[1] if axis=='a' else v[0] for v in cross]
            self.assertEqual(max(transverse)-min(transverse),THICKNESS)
            self.assertEqual(max(v[2] for v in cross),HEIGHT+CAP_RISE)
