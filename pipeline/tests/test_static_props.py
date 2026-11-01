"""Synthetic geometry fixtures test transparency and packaging, not AI art quality."""
import base64
from io import BytesIO
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from PIL import Image,ImageDraw
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from asset_repository import read
import static_props as props
from terrain_images import Provider


def fixture(transparent=False):
    image=Image.new('RGBA' if transparent else 'RGB',(128,128),(0,0,0,0) if transparent else (255,0,255))
    ImageDraw.Draw(image).ellipse((24,32,104,104),fill=(110,115,100,255) if transparent else (110,115,100))
    return image


def encoded(image):
    output=BytesIO();image.save(output,format='PNG')
    return base64.b64encode(output.getvalue()).decode()


class StaticPropTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.spec=props.validate({'mode':'import','title':'synthetic test'})

    def prepare(self,mode='import',image=None):
        with patch('static_props.configured',return_value=True):
            job=props.prepare(self.root,{'mode':mode,'description':'hand painted grey stone','image':encoded(image or fixture()),'reference':encoded(fixture())})
        return job,self.root/'.local/props/jobs'/job['id']

    def test_chroma_key_preserves_foreground_and_removes_border_only(self):
        source=fixture();source.putpixel((60,60),(255,0,255))
        output,info=props.cutout(source)
        self.assertEqual(output.getpixel((0,0))[3],0)
        self.assertEqual(output.getpixel((50,50)),(110,115,100,255))
        self.assertEqual(output.getpixel((60,60)),(255,0,255,255)) # Interior hole deliberately not inferred.
        self.assertEqual(info['method'],'border_connected_magenta_key')

    def test_antialiased_boundary_removes_key_color_spill(self):
        source=fixture();source.putpixel((64,31),(167,40,167))
        output,_=props.cutout(source)
        r,g,b,a=output.getpixel((64,31))
        self.assertTrue(120<a<140)
        self.assertLess(abs(r-g),4);self.assertLess(abs(b-g),4)

    def test_transparent_import_preserves_supplied_alpha(self):
        source=fixture(True);source.putpixel((64,32),(80,85,70,100))
        output,info=props.cutout(source)
        self.assertEqual(output.tobytes(),source.tobytes())
        self.assertEqual(info['method'],'preserve_supplied_alpha')

    def test_near_white_background_and_antialiasing_preserve_internal_highlights(self):
        source=Image.new('RGB',(128,128),(254,254,254))
        ImageDraw.Draw(source).rectangle((32,32,96,96),fill=(100,110,90))
        source.putpixel((64,31),(177,182,172))  # Half foreground, half white matte.
        source.putpixel((64,64),(254,254,254))  # Interior highlight is not background.
        output,info=props.cutout(source)
        self.assertEqual(info['method'],'border_connected_near_white_key')
        self.assertEqual(output.getpixel((0,0))[3],0)
        self.assertEqual(output.getpixel((64,64)),(254,254,254,255))
        r,g,b,a=output.getpixel((64,31))
        self.assertTrue(120<a<140)
        self.assertLess(abs(r-100),3);self.assertLess(abs(g-110),3);self.assertLess(abs(b-90),3)

    def test_nonuniform_scene_background_is_rejected(self):
        source=Image.new('RGB',(128,128),'white')
        ImageDraw.Draw(source).rectangle((0,70,128,128),fill=(210,220,200))
        with self.assertRaisesRegex(ValueError,'背景未识别'):props.cutout(source)

    def test_invalid_or_clipped_backgrounds_are_rejected(self):
        for image in [Image.new('RGB',(64,64),'white'),Image.new('RGB',(64,64),(255,0,255)),Image.new('RGBA',(64,64))]:
            with self.assertRaises(ValueError): props.cutout(image)
        clipped=fixture(True);clipped.putpixel((0,40),(100,100,100,255))
        with self.assertRaisesRegex(ValueError,'裁断'):props.cutout(clipped)

    def test_package_exports_anchor_local_disabled_collision_and_true_origin(self):
        target=props.package(self.root,fixture(),self.spec)
        manifest=props.load_package(self.root,target.name)
        self.assertEqual(manifest['canvas_px'],[256,256])
        self.assertEqual(manifest['anchor_px'],[128,239])
        self.assertEqual(manifest['provenance']['art_source'],'external_complete_object')
        self.assertFalse(manifest['suggested_collision']['enabled_by_default'])
        polygon=manifest['suggested_collision']['polygon']
        self.assertTrue(all(y<=0 for x,y in polygon))
        self.assertLess(min(x for x,y in polygon),0)
        self.assertFalse(manifest['production_ready'])
        with Image.open(target/'sprite.png') as image:
            self.assertEqual(image.size,(256,256));self.assertEqual(image.getpixel((0,0))[3],0)

    def test_adjustments_export_new_version_without_changing_original(self):
        original=props.package(self.root,fixture(),self.spec)
        old=(original/'manifest.json').read_bytes()
        adjusted=props.remake(self.root,{'source_kit':original.name,'anchor_x':120,'anchor_y':230,'collision_width':70,'collision_depth':20})
        self.assertNotEqual(original,adjusted)
        self.assertEqual((original/'manifest.json').read_bytes(),old)
        manifest=props.load_package(self.root,adjusted.name)
        self.assertEqual(manifest['anchor_px'],[120,230])
        self.assertEqual(manifest['sprite_offset_px'],[-120,-230])
        self.assertEqual(manifest['provenance']['this_build'],'reuse_no_ai_call')
        for invalid in [float('nan'),float('inf'),-1,256,True]:
            with self.assertRaises(ValueError): props.remake(self.root,{'source_kit':original.name,'anchor_x':invalid})

    def test_modified_files_and_archive_entries_are_rejected(self):
        target=props.package(self.root,fixture(),self.spec)
        with zipfile.ZipFile(target/'kit.zip','a') as archive: archive.writestr('../escape','bad')
        with self.assertRaises(ValueError): props.load_package(self.root,target.name)
        self.assertFalse(props.catalog(self.root)['kits'][0]['integrity']['passed'])
        target=props.package(self.root,fixture(),self.spec)
        (target/'sprite.png').write_bytes(b'changed')
        with self.assertRaises(ValueError):props.load_package(self.root,target.name)

    def test_import_worker_does_not_construct_provider(self):
        job,folder=self.prepare()
        with patch('static_props.generate_materials',side_effect=AssertionError('No AI for import')):
            props.execute(self.root,job['id'])
        self.assertEqual(read(folder/'job.json')['status'],'complete')
        self.assertTrue(props.catalog(self.root)['jobs'][0]['original_available'])

    def test_ai_receipts_reuse_and_adjustments_preserve_source_hash(self):
        job,folder=self.prepare('ai')
        with patch.object(Provider,'__init__',lambda obj,*args:setattr(obj,'base','mock://images')), \
             patch.object(Provider,'create',return_value={'data':[{'b64_json':encoded(fixture())}]}) as create:
            props.execute(self.root,job['id']);props.execute(self.root,job['id'])
        self.assertEqual(create.call_count,1)
        self.assertIn('full rock silhouette',create.call_args.args[0])
        self.assertEqual(read(folder/'job.json')['status'],'complete')
        manifest=props.load_package(self.root,job['id'])
        self.assertEqual(manifest['provenance']['art_source'],'ai_complete_object')
        self.assertEqual(read(folder/'generation.json')['ground']['sha256'],manifest['files_sha256']['inputs/original.png'])
        adjusted=props.remake(self.root,{'source_kit':job['id'],'anchor_y':232})
        self.assertEqual(props.load_package(self.root,adjusted.name)['provenance']['art_source'],'ai_complete_object')
        self.assertTrue((adjusted/'generation.json').exists())
        self.assertTrue((adjusted/'inputs/reference.png').exists())

    def test_postprocessing_failure_retains_successful_image_without_resubmission(self):
        job,folder=self.prepare('ai')
        with patch.object(Provider,'__init__',lambda obj,*args:setattr(obj,'base','mock://images')), \
             patch.object(Provider,'create',return_value={'data':[{'b64_json':encoded(Image.new('RGB',(64,64),'white'))}]}) as create:
            props.execute(self.root,job['id']);props.execute(self.root,job['id'])
        self.assertEqual(create.call_count,1)
        self.assertEqual(read(folder/'job.json')['status'],'failed')
        self.assertTrue((folder/'inputs/original.png').exists())
        self.assertIn('未识别到合理大小',read(folder/'job.json')['error'])
        with patch.object(Provider,'__init__',side_effect=AssertionError('No provider needed for saved image')):
            props.execute(self.root,job['id'])
        self.assertIn('未识别到合理大小',read(folder/'job.json')['error'])

    def test_remote_terminal_failure_is_not_polled_indefinitely(self):
        job,folder=self.prepare('ai')
        with patch.object(Provider,'__init__',lambda obj,*args:setattr(obj,'base','mock://images')), \
             patch.object(Provider,'create',return_value={'id':'failed-image'}) as create, \
             patch.object(Provider,'request',return_value={'status':'failed'}) as request:
            props.execute(self.root,job['id'])
            self.assertEqual(request.call_count,1)
            self.assertEqual(create.call_count,1)
        self.assertEqual(read(folder/'job.json')['status'],'failed')

    def test_bad_settings_rejected_before_creating_jobs(self):
        for data in [{'size':64},{'size':True},{'mode':'demo'},{'description':''},{'title':'','description':'rock'}]:
            with self.assertRaises(ValueError):props.prepare(self.root,data)
        with self.assertRaises(ValueError):props.decode_sprite(encoded(Image.new('RGB',(16,16))))
        self.assertFalse((self.root/'.local/props').exists())

    def test_types_share_pipeline_but_keep_subjects_and_collision_defaults(self):
        for kind,profile in props.KINDS.items():
            spec=props.validate({'kind':kind,'mode':'import'})
            self.assertEqual(spec['kind'],kind)
            self.assertEqual(spec['collision_usage'],profile['collision_usage'])
            text=props.prompt('one styled asset',kind)
            self.assertIn(profile['subject'],text)
            if kind!='rock': self.assertNotIn('single compact stone',text)
            target=props.package(self.root,fixture(True),spec)
            manifest=props.load_package(self.root,target.name)
            self.assertEqual(manifest['asset_kind'],kind)
            self.assertFalse(manifest['suggested_collision']['enabled_by_default'])
            if kind=='custom': self.assertEqual(manifest['suggested_collision']['polygon'],[])
        for invalid in [{'kind':'wall'},{'kind':[]},{'collision_usage':'enabled'},{'collision_usage':False}]:
            with self.assertRaises(ValueError):props.validate({'mode':'import',**invalid})

    def test_collision_can_be_omitted_and_restored_without_ai(self):
        original=props.package(self.root,fixture(True),self.spec)
        omitted=props.remake(self.root,{'source_kit':original.name,'collision_usage':'none'})
        manifest=props.load_package(self.root,omitted.name)
        self.assertEqual(manifest['suggested_collision']['polygon'],[])
        self.assertEqual(manifest['suggested_collision']['usage'],'none')
        restored=props.remake(self.root,{'source_kit':omitted.name,'collision_usage':'optional'})
        manifest=props.load_package(self.root,restored.name)
        self.assertEqual(len(manifest['suggested_collision']['polygon']),16)
        self.assertFalse(manifest['suggested_collision']['enabled_by_default'])

    def test_multiple_large_regions_rejected_for_opaque_and_alpha_inputs(self):
        for transparent in (False,True):
            image=Image.new('RGBA' if transparent else 'RGB',(128,128),(0,0,0,0) if transparent else 'white')
            draw=ImageDraw.Draw(image)
            for box in ((10,40,48,90),(80,40,118,90)):draw.ellipse(box,fill=(100,100,90,255) if transparent else (100,100,90))
            with self.assertRaisesRegex(ValueError,'多个明显分离'):
                props.package(self.root,image,self.spec)
        image=fixture(True);image.putpixel((5,5),(100,100,100,255))
        result=props.single_object(image)
        self.assertEqual(result['major_regions'],1)
        self.assertEqual(result['minor_regions'],1)
