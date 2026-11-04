"""Recover a failed source with explicit background seeds; never generate again."""
import base64
from io import BytesIO
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image,ImageDraw
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import static_props as props
from asset_repository import atomic


def hollow():
    image=Image.new('RGB',(128,128),(215,51,138))
    draw=ImageDraw.Draw(image);draw.rectangle((24,24,104,104),fill=(70,110,50))
    draw.rectangle((36,36,92,92),fill=(215,51,138))
    return image


class PropRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.job='failed-source'
        self.folder=self.root/'.local/props/jobs'/self.job;(self.folder/'inputs').mkdir(parents=True)
        self.image=hollow();self.image.save(self.folder/'inputs/original.png')
        spec=props.validate(dict(kind='custom',mode='ai',title='Hollow prop',description='Single basket',projection='isometric_2_1'))
        atomic(self.folder/'job.json',dict(id=self.job,status='failed',stage='cutout failed',error='20%',created_at='2026-11-04',spec=spec))
        atomic(self.folder/'generation.json',{'ground':{'sha256':hashlib.sha256((self.folder/'inputs/original.png').read_bytes()).hexdigest()}})
        self.info=props.recovery_source(self.root,self.job)
        self.data={**self.info,'background_points':[[50,50]]}

    def test_seed_opens_hole_preserves_body_and_keeps_default_guard(self):
        with self.assertRaisesRegex(ValueError,'20%'):
            props.cutout(self.image,adaptive_magenta=True,reserved_magenta=True)
        result,meta=props.cutout(self.image,adaptive_magenta=True,reserved_magenta=True,background_points=[[50,50]])
        self.assertEqual(result.getpixel((50,50))[3],0)
        self.assertEqual(result.getpixel((28,64)),(70,110,50,255))
        self.assertEqual(meta['background_points'],[[50,50]])
        self.assertFalse(meta['semantic_removal_verified'])
        # A border seed cannot bypass the threshold for an unmarked large hole.
        with self.assertRaisesRegex(ValueError,'20%'):
            props.cutout(self.image,adaptive_magenta=True,reserved_magenta=True,background_points=[[0,0]])
        with self.assertRaisesRegex(ValueError,'不属于'):
            props.cutout(self.image,adaptive_magenta=True,reserved_magenta=True,background_points=[[28,64]])

    def test_invalid_coordinates_are_rejected(self):
        for points in ([[True,1]],[[1.5,2]],[[128,2]],[[-1,0]],[[1]],'bad',[[0,0]]*65):
            with self.subTest(points=points),self.assertRaises(ValueError):
                props.cutout(self.image,background_points=points)

    def test_preview_and_save_preserve_source_and_receipt_and_export_exact_preview(self):
        before={str(p.relative_to(self.folder)):p.read_bytes() for p in self.folder.rglob('*') if p.is_file()}
        with patch('static_props.generate_materials',side_effect=AssertionError('Must not generate')):
            preview=props.recovery_preview(self.root,self.data)
            self.assertFalse((self.root/'prop-kits').exists())
            raw=base64.b64decode(preview['image'].split(',')[1]);image=Image.open(BytesIO(raw))
            self.assertEqual(image.size,(256,256))
            data={**self.data,'preview_sha256':preview['preview_sha256']}
            manifest=props.recovery_preview(self.root,data,save=True)
            again=props.recovery_preview(self.root,data,save=True)
        self.assertEqual(again['id'],manifest['id'])
        output=self.root/'prop-kits'/manifest['id']
        self.assertEqual((output/'sprite.png').read_bytes(),raw)
        self.assertEqual(manifest['provenance']['source_job'],self.job)
        self.assertEqual(manifest['processing']['background_points'],[[50,50]])
        self.assertEqual({str(p.relative_to(self.folder)):p.read_bytes() for p in self.folder.rglob('*') if p.is_file()},before)
        self.assertEqual((output/'inputs/original.png').read_bytes(),before['inputs/original.png'])
        self.assertEqual((output/'generation.json').read_bytes(),before['generation.json'])
        props.load_package(self.root,manifest['id'])
        catalog=props.catalog(self.root)
        self.assertEqual(catalog['jobs'][0]['status'],'failed')
        self.assertEqual(catalog['jobs'][0]['recovered_kits'],[manifest['id']])
        # Later ordinary remake must keep the explicit background recipe.
        remade=props.remake(self.root,dict(source_kit=manifest['id'],transparency_only=True))
        self.assertEqual((remade/'sprite.png').read_bytes(),raw)

    def test_stale_preview_source_and_active_jobs_cannot_be_saved(self):
        preview=props.recovery_preview(self.root,self.data)
        for change in ({'background_points':[[52,52]]},{'preview_sha256':'wrong'},{'source_sha256':'wrong'}):
            data={**self.data,'preview_sha256':preview['preview_sha256'],**change}
            with self.assertRaises(ValueError):props.recovery_preview(self.root,data,save=True)
        self.assertFalse((self.root/'prop-kits').exists())
        job=json.loads((self.folder/'job.json').read_text());job['status']='running';atomic(self.folder/'job.json',job)
        with self.assertRaises(ValueError):props.recovery_source(self.root,self.job)
        job['status']='failed';atomic(self.folder/'job.json',job)
        (self.folder/'inputs/original.png').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'不一致'):props.recovery_source(self.root,self.job)


if __name__=='__main__':unittest.main()
