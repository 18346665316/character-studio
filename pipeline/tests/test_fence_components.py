"""Fence asset invariants and immutable package consumption; no image API calls."""
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from asset_repository import read
from fence_components import MODULES,module_record,build,validate_geometry
from validate_fence_godot import stage


class FenceComponentsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def test_ground_collision_is_independent_of_tall_image_and_has_a_clear_opening(self):
        record=module_record('straight_ew',MODULES['straight_ew'])
        polygon=record['suggested_collision']['polygons']
        self.assertTrue(all(29<=y<=35 for p in polygon for _,y in p))
        self.assertEqual(record['canvas_px'],[64,96])
        self.assertEqual(record['anchor_px'],[32,64])
        self.assertFalse(record['suggested_collision']['enabled_by_default'])
        gate=module_record('opening_ew',MODULES['opening_ew'])
        self.assertEqual(gate['passages'][0]['clear_width_px'],24)
        self.assertTrue(all(max(x for x,y in p)<=20 or min(x for x,y in p)>=44 for p in gate['suggested_collision']['polygons']))

    def test_invalid_anchor_and_ports_fail_validation(self):
        record=module_record('end_n',1)
        invalid=deepcopy(record);invalid['anchor_px']=[32,32]
        with self.assertRaisesRegex(ValueError,'锚点'):validate_geometry([invalid])
        invalid=deepcopy(record);invalid['connections'][0]['position_px']=[32,10]
        with self.assertRaisesRegex(ValueError,'接口'):validate_geometry([invalid])

    def test_package_is_explicitly_a_fixture_and_can_be_consumed_from_zip(self):
        first=build(self.root);manifest=read(first/'manifest.json')
        self.assertEqual(len(manifest['modules']),12)
        self.assertFalse(manifest['production_ready'])
        self.assertEqual(manifest['validation']['engine_physics'],'pending')
        self.assertEqual(manifest['ai_calls'],0)
        staged=stage(self.root,first.name)
        self.assertEqual(read(staged/'assets/manifest.json'),manifest)
        second=build(self.root)
        self.assertNotEqual(first.name,second.name)
        self.assertTrue((first/'kit.zip').is_file())
        # Corrupt disk input cannot be laundered through a still-valid old ZIP.
        (first/'tiles/straight_ew.png').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'指纹'):stage(self.root,first.name)

    def test_zip_must_match_manifest_and_cannot_have_extra_members(self):
        folder=build(self.root)
        with zipfile.ZipFile(folder/'kit.zip','a') as archive:
            archive.writestr('../outside.txt','unexpected')
        with self.assertRaisesRegex(ValueError,'资源清单'):stage(self.root,folder.name)
        self.assertFalse((self.root/'outside.txt').exists())

    def test_timber_layers_recompose_and_keep_the_fixture_collision_contract(self):
        from PIL import Image
        timber=build(self.root,appearance='timber')
        manifest=read(timber/'manifest.json')
        self.assertEqual(manifest['art_source'],'procedural_wood_texture_program_geometry')
        self.assertFalse(manifest['production_ready'])
        self.assertEqual(manifest['ai_calls'],0)
        for module in manifest['modules']:
            original=module_record(module['id'],MODULES[module['id']])
            self.assertEqual(module['suggested_collision'],original['suggested_collision'])
            self.assertEqual(module['passages'],original['passages'])
            canvas=Image.new('RGBA',(64,96))
            for layer in module['visual_layers']:
                self.assertEqual(layer['sort_position_px'][1]+layer['image_offset_px'][1],-32)
                with Image.open(timber/layer['image']) as image:canvas.alpha_composite(image.convert('RGBA'))
            with Image.open(timber/module['image']) as expected:
                self.assertEqual(canvas.tobytes(),expected.convert('RGBA').tobytes())
        staged=stage(self.root,timber.name)
        self.assertTrue((staged/'assets/layers/straight_ns_depth_04.png').exists())

    def test_external_wood_input_is_preserved_and_not_claimed_as_ai_output(self):
        from PIL import Image
        texture=self.root/'wood.png'
        Image.new('RGB',(64,64),(170,100,40)).save(texture)
        folder=build(self.root,appearance='timber',wood_image=texture)
        manifest=read(folder/'manifest.json')
        self.assertEqual(manifest['art_source'],'external_wood_texture_program_geometry')
        with Image.open(folder/'inputs/wood.png') as image:
            self.assertEqual(image.getpixel((0,0)),(170,100,40))
        (folder/'kit.zip').write_bytes(b'bad zip')
        with self.assertRaisesRegex(ValueError,'损坏'):stage(self.root,folder.name)


if __name__=='__main__':unittest.main()
