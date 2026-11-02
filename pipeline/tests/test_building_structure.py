"""Building structure invariants, independently of image generation."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from building_structure import compile_structure, validate, screen

ROOT = Path(__file__).resolve().parents[2]


class BuildingStructureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cottage = json.loads((ROOT/'examples/buildings/cottage.json').read_text())
        self.hall = json.loads((ROOT/'examples/buildings/hall.json').read_text())

    def test_different_footprints_keep_world_scale_and_fit_canvas(self):
        for name, spec in [('cottage', self.cottage), ('hall', self.hall)]:
            folder = self.root/name
            result = compile_structure(spec, folder)
            points = np.array(result['footprint_polygon_px'])
            np.testing.assert_allclose(points[1]-points[0], [64*spec['footprint_cells'][0], 32*spec['footprint_cells'][0]])
            np.testing.assert_allclose(points[3]-points[0], [-64*spec['footprint_cells'][1], 32*spec['footprint_cells'][1]])
            image = Image.open(folder/'structure.png')
            bbox = image.getbbox()
            self.assertGreater(bbox[0], 20); self.assertGreater(bbox[1], 20)
            self.assertLess(bbox[2], image.width-20); self.assertLess(bbox[3], image.height-20)
            ids = set(np.asarray(Image.open(folder/'faces.png')).ravel())
            self.assertIn(10, ids); self.assertIn(11, ids)
            self.assertEqual(result['review']['art'], 'not_generated')
        with Image.open(self.root/'hall/structure.png') as hall, Image.open(self.root/'cottage/structure.png') as cottage:
            self.assertGreater(hall.width, cottage.width)

    def test_ridge_orientation_and_entrance_coordinates(self):
        for name, spec, slope in [('x', self.cottage, .5), ('y', self.hall, -.5)]:
            result = compile_structure(spec, self.root/name)
            a, b = np.array(result['landmarks_px']['ridge'])
            self.assertAlmostEqual((b[1]-a[1])/(b[0]-a[0]), slope)
            world = result['entrance']['world_position']
            np.testing.assert_allclose(result['entrance']['pixel_position'], screen(world, 128)+result['world_origin_px'])

    def test_deterministic_fingerprints_and_no_overwrite(self):
        a = compile_structure(self.cottage, self.root/'a')
        b = compile_structure(copy.deepcopy(self.cottage), self.root/'b')
        self.assertEqual(a, b)
        before = (self.root/'a/structure.json').read_bytes()
        with self.assertRaises(FileExistsError): compile_structure(self.hall, self.root/'a')
        self.assertEqual(before, (self.root/'a/structure.json').read_bytes())
        self.hall['openings'][0]['center'] = 1.6
        c = compile_structure(self.hall, self.root/'c')
        self.assertNotEqual(a['structure_sha256'], c['structure_sha256'])

    def test_invalid_inputs_rejected_before_creating_output(self):
        cases = [dict(footprint_cells=[True, 2]), dict(footprint_cells=[9, 2]),
                 dict(cell_px=256), dict(wall_height_units=float('nan')),
                 dict(roof={'ridge_axis': 'z'}), dict(roof={'type': 'hip'}),
                 dict(openings=[]), dict(unknown=1)]
        for i, changes in enumerate(cases):
            with self.assertRaises(ValueError): compile_structure({**self.cottage, **changes}, self.root/str(i))
            self.assertFalse((self.root/str(i)).exists())
        for field, value in [('center', 0), ('bottom', .1), ('height', 4)]:
            data = copy.deepcopy(self.cottage); data['openings'][0][field] = value
            with self.assertRaises(ValueError): validate(data)
        data = copy.deepcopy(self.cottage); data['openings'].append(data['openings'][1].copy())
        with self.assertRaisesRegex(ValueError, '重叠'): validate(data)

    def test_half_cell_pixels_halves_world_distances(self):
        large = compile_structure(self.cottage, self.root/'large')
        self.cottage['cell_px'] = 64
        small = compile_structure(self.cottage, self.root/'small')
        for result in [large, small]:
            self.assertEqual(result['vertical_screen_px_per_unit'], result['spec']['cell_px']/2)
        p = lambda r: np.array(r['footprint_polygon_px'][1])-r['footprint_polygon_px'][0]
        np.testing.assert_allclose(p(large), p(small)*2)

    def test_invisible_or_eave_hidden_entrance_is_rejected(self):
        hidden=copy.deepcopy(self.cottage);hidden['openings'][0]['facade']='-y'
        with self.assertRaisesRegex(ValueError,'入口'):compile_structure(hidden,self.root/'back')
        hidden=validate({});hidden['roof'].update(rise_units=2,overhang_cells=.5)
        hidden['openings'][0]['height']=.8
        with self.assertRaisesRegex(ValueError,'入口'):compile_structure(hidden,self.root/'eave')
        self.assertFalse((self.root/'back').exists());self.assertFalse((self.root/'eave').exists())

    def test_each_window_has_independent_visibility_report(self):
        spec=validate({});spec['openings'].extend([
            dict(type='window',facade='-y',center=.6,width=.5,bottom=.6,height=.4),
            dict(type='window',facade='+x',center=.7,width=.5,bottom=.6,height=.4)])
        result=compile_structure(spec,self.root/'windows')
        windows=result['opening_visibility'][1:]
        self.assertEqual(windows[0]['visible_ratio'],0)
        self.assertGreater(windows[1]['visible_ratio'],.8)


if __name__ == '__main__': unittest.main()
