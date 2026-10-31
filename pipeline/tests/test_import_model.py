import base64
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import trimesh
import numpy as np
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from import_model import validate_glb,import_character
from panel import Panel

class ImportModelTests(unittest.TestCase):
    def model(self):
        mesh=trimesh.creation.box()
        mesh.visual=trimesh.visual.texture.TextureVisuals(uv=np.zeros((len(mesh.vertices),2)),material=trimesh.visual.material.SimpleMaterial(image=Image.new('RGB',(64,64),'red')))
        return mesh.export(file_type='glb')
    def test_upload_and_prepare_without_reconstruction(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);panel=Panel(root)
            upload=panel.upload_model({'display_name':'Imported','content':base64.b64encode(self.model()).decode(),'up':'-Z','yaw':90})
            with patch('preview_model.preview'):
                dest=import_character(root,upload['character'],root/upload['source'],'-Z',90)
            c=panel.character(upload['character'])
            self.assertEqual(c['prepared']['id'],dest.name)
            self.assertFalse(c['model_approved']);self.assertFalse(c['rig']['ready'])
            self.assertTrue((root/upload['source']).is_file())
            self.assertEqual(c['prepared']['info']['origin'],'import_glb')
            self.assertAlmostEqual(trimesh.load(dest/'preview.glb',force='mesh').extents[1],1.7,places=5)
            with self.assertRaisesRegex(ValueError,'不能覆盖'):
                import_character(root,upload['character'],root/upload['source'])
    def test_malformed_glb_and_invalid_orientation_rejected(self):
        for value in (b'',b'not glb'*20):
            with self.assertRaises(ValueError):validate_glb(value)
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(ValueError):Panel(Path(temp)).upload_model({'display_name':'x','content':base64.b64encode(self.model()).decode(),'up':'bad'})
