"""Wall-strip slicing must preserve source pixels and shared cut ownership."""
import sys
from pathlib import Path
import unittest
import tempfile
import hashlib
import numpy as np
from PIL import Image,ImageDraw
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from build_courtyard_wall_templates import faces,project,LENGTH,ANCHOR
from wall_strip import SOURCE_CANVAS,SOURCE_ORIGIN,slice_middle,analyze,publish_trial


def painted(axis='a'):
    origin=SOURCE_ORIGIN if axis=='a' else (840,400)
    image=Image.new('RGBA',SOURCE_CANVAS);draw=ImageDraw.Draw(image)
    for face in faces(axis,LENGTH*5):
        draw.polygon([(project(p)[0]+origin[0],project(p)[1]+origin[1]) for p in face],fill=(180,160,125,255))
    # Nonuniform RGBA makes lost/overlapping/interpolated pixels detectable.
    pixels=np.asarray(image).copy();yy,xx=np.indices(pixels.shape[:2]);visible=pixels[:,:,3]>0
    pixels[:,:,0][visible]=(xx[visible]%127)+80
    pixels[:,:,1][visible]=(yy[visible]%73)+100
    pixels[:,:,3][visible]=np.where(xx[visible]%7==0,128,255)
    return Image.fromarray(pixels),origin


class WallStripTests(unittest.TestCase):
    def test_three_slices_reconstruct_painted_source_exactly_on_both_axes(self):
        for axis in ('a','b'):
            source,origin=painted(axis)
            sprites,expected,report=slice_middle(source,origin=origin,axis=axis)
            rebuilt=Image.new('RGBA',source.size)
            for sprite,offset in zip(sprites,report['source_offsets_px']):rebuilt.alpha_composite(sprite,offset)
            self.assertTrue(np.array_equal(np.asarray(rebuilt),np.asarray(expected)))
            a=np.asarray(source);b=np.asarray(rebuilt);visible=b[:,:,3]>0
            self.assertTrue(np.array_equal(a[visible],b[visible]))
            self.assertEqual(report['reconstruction_pixel_errors'],0)
            self.assertTrue(all(s.size==(512,512) for s in sprites))

    def test_roof_cut_is_a_cross_section_not_a_vertical_rectangle(self):
        source,origin=painted()
        sprites,_,_=slice_middle(source)
        # On the ridge q=0, t starts at anchor X. On the wall q=8,
        # the same start plane is eight pixels to its left.
        alpha=np.asarray(sprites[1].getchannel('A'))
        self.assertEqual(alpha[ANCHOR[1]-108,ANCHOR[0]-4],0)
        self.assertGreater(alpha[ANCHOR[1]-40,ANCHOR[0]-4],0)

    def test_out_of_canvas_art_and_empty_cuts_are_rejected(self):
        with self.assertRaises(ValueError):slice_middle(Image.new('RGBA',SOURCE_CANVAS))
        source,_=painted()
        with self.assertRaises(ValueError):slice_middle(source,origin=(160,900))
        with self.assertRaises(ValueError):slice_middle(source,length=127)

    def test_cut_positions_use_one_fixed_translation(self):
        source,_=painted();_,_,report=slice_middle(source)
        positions=report['source_offsets_px']
        self.assertEqual([positions[1][i]-positions[0][i] for i in range(2)],[128,64])
        self.assertEqual([positions[2][i]-positions[1][i] for i in range(2)],[128,64])

    def test_analysis_checks_original_and_reference_receipts_before_writing_slices(self):
        from asset_repository import atomic
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);(folder/'inputs').mkdir()
            source,_=painted();source.save(folder/'inputs/ground.png')
            Image.new('RGB',SOURCE_CANVAS,'white').save(folder/'inputs/reference.png')
            receipt=dict(ground=dict(sha256='wrong',reference_sha256={'reference.png':'wrong'}))
            atomic(folder/'generation.json',receipt)
            with self.assertRaisesRegex(ValueError,'原图'):analyze(folder)
            self.assertFalse((folder/'slice-0.png').exists())
            receipt['ground']['sha256']=hashlib.sha256((folder/'inputs/ground.png').read_bytes()).hexdigest()
            atomic(folder/'generation.json',receipt)
            with self.assertRaisesRegex(ValueError,'参考图'):analyze(folder)
            receipt['ground']['reference_sha256']['reference.png']=hashlib.sha256((folder/'inputs/reference.png').read_bytes()).hexdigest()
            atomic(folder/'generation.json',receipt)
            _,report=analyze(folder)
            self.assertEqual(report['reconstruction_pixel_errors'],0)
            self.assertTrue((folder/'join-board.png').is_file())

    def test_published_scene_references_exact_slices_and_reentry_does_not_duplicate_assets(self):
        from asset_repository import atomic
        from static_props import load_package
        import scene_modules
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);folder=root/'.local/wall-strips/jobs/test';(folder/'inputs').mkdir(parents=True)
            source,_=painted();source.save(folder/'inputs/ground.png')
            Image.new('RGB',SOURCE_CANVAS,'white').save(folder/'inputs/reference.png')
            atomic(folder/'generation.json',dict(ground=dict(
                sha256=hashlib.sha256((folder/'inputs/ground.png').read_bytes()).hexdigest(),
                reference_sha256={'reference.png':hashlib.sha256((folder/'inputs/reference.png').read_bytes()).hexdigest()})))
            atomic(folder/'production.json',dict(material_prompt='synthetic test, no provider call'))
            result=publish_trial(root,folder)
            scene=scene_modules.load(root,result['scene'])
            self.assertEqual(len(scene['modules']),3);self.assertEqual(len(scene['instances']),9)
            for index,kit in enumerate(result['kits']):
                manifest=load_package(root,kit)
                self.assertEqual(manifest['provenance']['source_job'],'test')
                self.assertNotIn('wall_connectors',manifest)
                sprite=Image.open(root/'prop-kits'/kit/'sprite.png')
                self.assertTrue(np.array_equal(np.asarray(sprite),np.asarray(Image.open(folder/('slice-'+str(index)+'.png')))))
            self.assertEqual(publish_trial(root,folder),result)
            self.assertEqual(len(list((root/'prop-kits').glob('*/manifest.json'))),3)
