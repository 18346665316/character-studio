"""Exact building delivery bridge: provenance, pixels, package and annotation."""
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from PIL import Image
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import static_props as props

class BuildingSpriteAdapterTests(unittest.TestCase):
    def test_building_zip_and_original_png_survive_annotation(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);folder=root/'building-kits/building-test';folder.mkdir(parents=True)
            png=BytesIO();Image.new('RGBA',(512,512),(0,0,0,0)).save(png,format='PNG')
            (folder/'sprite.png').write_bytes(png.getvalue())
            (folder/'integration.json').write_text(json.dumps(dict(anchor_px=[256,400])))
            original=BytesIO()
            with zipfile.ZipFile(original,'w') as z:z.writestr('sprite.png',png.getvalue())
            (folder/'kit.zip').write_bytes(original.getvalue())
            with patch('building_pipeline.load_package',return_value=dict(id='building-test',title='Farm')):
                manifest=props.from_building(root,dict(kit='building-test',projection='isometric_2_1'))
            saved=props.load_package(root,manifest['id'])
            self.assertEqual(saved['provenance']['parent_building'],'building-test')
            self.assertEqual(saved['anchor_px'],[256,400])
            newer=props.annotate(root,dict(source_kit=saved['id'],title='Farm',anchor=[256,400],behavior='blocking',polygons=[[[-80,-20],[80,-20],[80,20],[-80,20]]],world_scale=.8))
            with zipfile.ZipFile(root/'prop-kits'/newer['id']/'kit.zip') as z:
                self.assertEqual(z.read('sprite.png'),png.getvalue())
                self.assertEqual(z.read('inputs/source-building.zip'),original.getvalue())
            self.assertEqual((folder/'kit.zip').read_bytes(),original.getvalue())

if __name__=='__main__':unittest.main()
