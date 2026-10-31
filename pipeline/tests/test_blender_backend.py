import json
from pathlib import Path
import sys
import tempfile
import unittest
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from blender_backend import assemble

class BlenderAssemblyTests(unittest.TestCase):
    def test_png_frames_preserve_alpha_order_and_timing(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            clip={'name':'attack','frame_count':8,'duration_seconds':.7}
            (root/'clips.json').write_text(json.dumps([clip]))
            (root/'attack_render.json').write_text(json.dumps({**clip,'renderer':'blender'}))
            for i in range(8): Image.new('RGBA',(64,64),(i*20,50,80,128)).save(root/f'attack_{i:03d}.png')
            assemble(root,root,root,64)
            with Image.open(root/'attack_spritesheet.png') as sheet:
                self.assertEqual(sheet.size,(512,64))
                self.assertEqual(sheet.getpixel((7*64,0)),(140,50,80,128))
            (root/'attack_003.png').unlink()
            with self.assertRaises(FileNotFoundError):assemble(root,root,root,64)

    def test_wrong_size_or_timing_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            clip={'name':'attack','frame_count':8,'duration_seconds':.7}
            (root/'clips.json').write_text(json.dumps([clip]))
            for i in range(8): Image.new('RGBA',(64,64),'red').save(root/f'attack_{i:03d}.png')
            (root/'attack_render.json').write_text(json.dumps({**clip,'renderer':'blender','frame_count':9}))
            with self.assertRaisesRegex(ValueError,'时序'):assemble(root,root,root,64)
            Image.new('RGBA',(32,32),'red').save(root/'attack_000.png')
            with self.assertRaisesRegex(ValueError,'尺寸'):assemble(root,root,root,64)
