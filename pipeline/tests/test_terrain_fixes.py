"""Regression cases from the core/operation review; no paid image calls."""
import base64
from io import BytesIO
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import numpy as np
from PIL import Image

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from asset_repository import read
from terrain import prepare,execute
from terrain_images import load_config,configured
from terrain_integrity import inspect
from terrain_transition import build


class TerrainReviewFixes(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def kit(self,finish='natural',size=64,seed=2):
        a=np.random.default_rng(seed).integers(0,256,(400,400,3),dtype='uint8')
        stream=BytesIO();Image.fromarray(a).save(stream,format='PNG')
        content=base64.b64encode(stream.getvalue()).decode()
        job=prepare(self.root,dict(title='test',description='test',mode='import',
                    finish=finish,tile_size=size,ground=content,road=content))
        execute(self.root,job['id'])
        return self.root/'terrain-kits'/job['id']

    def test_config_file_rotation_removal_and_environment_precedence(self):
        with patch.dict(os.environ,{},clear=True):
            file=self.root/'.env'
            file.write_text('OPENAI_API_KEY=first-placeholder\nSTUDIO_IMAGE_BASE_URL=https://one.example/v1\n')
            self.assertTrue(configured(self.root))
            self.assertEqual(load_config(self.root)['OPENAI_API_KEY'],'first-placeholder')
            self.assertNotIn('OPENAI_API_KEY',os.environ)
            file.write_text('OPENAI_API_KEY=second-placeholder\nSTUDIO_IMAGE_BASE_URL=https://two.example/v1\n')
            self.assertEqual(load_config(self.root)['OPENAI_API_KEY'],'second-placeholder')
            self.assertEqual(load_config(self.root)['STUDIO_IMAGE_BASE_URL'],'https://two.example/v1')
            os.environ['OPENAI_API_KEY']='explicit-env-placeholder'
            self.assertEqual(load_config(self.root)['OPENAI_API_KEY'],'explicit-env-placeholder')
            del os.environ['OPENAI_API_KEY'];file.unlink()
            self.assertFalse(configured(self.root))

    def test_source_pixels_are_preserved_for_classic_and_natural_variants(self):
        first=self.kit('classic');second=self.kit('natural',seed=4)
        dest=build(self.root,first.name,second.name,64,interactive=False)
        manifest=read(dest/'manifest.json')
        self.assertEqual(manifest['source_policy'],'delivered_ground_exact')
        self.assertEqual(manifest['variants'],4)
        base=Image.open(first/'tiles/ground.png').convert('RGB')
        for v in range(4):
            overlay=Image.open(second/('tiles/ground.png' if v==0 else f'tiles/ground_v{v}.png')).convert('RGB')
            self.assertTrue(np.array_equal(np.array(base),np.array(Image.open(dest/f'tiles/terrain_00_v{v}.png'))))
            self.assertTrue(np.array_equal(np.array(overlay),np.array(Image.open(dest/f'tiles/terrain_15_v{v}.png'))))
        self.assertTrue(inspect(self.root,'terrain-transitions',dest.name)['passed'])
        with self.assertRaisesRegex(ValueError,'尺寸须与'):
            build(self.root,first.name,second.name,32,interactive=False)
        # Transition downloads receive the same archive protection as roads.
        (dest/'kit.zip').write_bytes(b'bad archive')
        self.assertFalse(inspect(self.root,'terrain-transitions',dest.name)['passed'])

    def test_two_single_group_sources_do_not_invent_variations(self):
        first=self.kit('classic');second=self.kit('classic',seed=4)
        dest=build(self.root,first.name,second.name,interactive=False)
        self.assertEqual(read(dest/'manifest.json')['variants'],1)
        self.assertEqual(len(read(dest/'manifest.json')['tiles']),16)

    def test_missing_modified_and_mismatched_archive_are_rejected(self):
        kit=self.kit()
        self.assertTrue(inspect(self.root,'terrain-kits',kit.name)['passed'])
        atlas=kit/'atlas.png';original=atlas.read_bytes();atlas.write_bytes(b'changed')
        self.assertFalse(inspect(self.root,'terrain-kits',kit.name)['passed'])
        atlas.write_bytes(original)
        missing=kit/'tiles/road_00.png';saved=missing.read_bytes();missing.unlink()
        self.assertFalse(inspect(self.root,'terrain-kits',kit.name)['passed']);missing.write_bytes(saved)
        # A syntactically valid ZIP with valid CRC must still match disk content.
        with zipfile.ZipFile(kit/'kit.zip') as archive:
            contents={name:archive.read(name) for name in archive.namelist()}
        contents['atlas.png']=b'different archive content'
        with zipfile.ZipFile(kit/'kit.zip','w') as archive:
            for name,data in contents.items():archive.writestr(name,data)
        self.assertFalse(inspect(self.root,'terrain-kits',kit.name)['passed'])


if __name__=='__main__':unittest.main()
