"""Positive/negative repeat fixtures exercise automatic worker publication."""
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from asset_repository import read,atomic
import static_props as props
from wall_strip import source_origin,slice_middle
from wall_repeat import select


def art(axis='a',drift=False):
    yy,xx=np.indices((1024,1024),dtype=float);ox,oy=source_origin(axis)
    sx=xx-ox if axis=='a' else ox-xx
    k=yy-oy-.5*sx
    t=sx+np.clip((k+108)/2,0,8)
    visible=(t>=0)&(t<640)&(k>=-108)&(k<=8)
    rgb=np.zeros((1024,1024,4),dtype=np.uint8);rgb[:]=[255,0,255,255]
    phase=(np.floor(t).astype(int)%16)<8
    roof=k<-88
    red=np.where(roof,np.where(phase,80,130),np.where(phase,220,225))
    rgb[:,:,0][visible]=red[visible].astype(np.uint8)
    rgb[:,:,1][visible]=np.where(roof,120,210)[visible]
    rgb[:,:,2][visible]=np.where(roof,140,190)[visible]
    if drift:
        for channel,(roof_base,wall_base) in enumerate(((65,110),(75,100),(95,90))):
            values=np.where(roof,roof_base,wall_base)+t*.25
            rgb[:,:,channel][visible]=np.clip(values[visible],0,255).astype(np.uint8)
    return Image.fromarray(rgb)


def provider_result(folder,spec,progress,image):
    image.save(folder/'inputs/ground.png')
    atomic(folder/'generation.json',dict(ground=dict(
        sha256=hashlib.sha256((folder/'inputs/ground.png').read_bytes()).hexdigest(),
        reference_sha256={'reference.png':hashlib.sha256((folder/'inputs/reference.png').read_bytes()).hexdigest()})))


class WallRepeatTests(unittest.TestCase):
    def test_periodic_source_passes_deterministically_on_both_axes(self):
        from wall_assets import whole_cutout
        for axis in ('a','b'):
            source=whole_cutout(art(axis))
            first=select(source,source_origin(axis),axis)
            self.assertEqual(first,select(source,source_origin(axis),axis))
            self.assertTrue(first['passed'],first)
            self.assertEqual(first['selected']['length']%16,0)
            self.assertEqual(first['selected']['length']%2,0)
            self.assertGreater(first['candidate_count'],5000)

    def test_nonperiodic_color_drift_is_rejected(self):
        from wall_assets import whole_cutout
        result=select(whole_cutout(art(drift=True)),source_origin('a'))
        self.assertFalse(result['passed'],result)

    def test_periodic_but_displaced_geometry_is_rejected(self):
        from wall_assets import whole_cutout
        source=whole_cutout(art())
        shifted=Image.new('RGBA',source.size)
        shifted.alpha_composite(source,(0,10))
        result=select(shifted,source_origin('a'))
        self.assertFalse(result['passed'],result)
        self.assertGreater(result['selected']['shape_offset'],result['limits']['shape_offset'])

    def test_worker_builds_exact_selected_pixels_and_reuses_success(self):
        from wall_assets import whole_cutout
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with patch('static_props.configured',return_value=True):
                job=props.prepare(root,dict(mode='ai',kind='custom',description='wall',title='墙',projection='isometric_2_1',wall_axis='a',wall_strip_build=True))
            folder=root/'.local/props/jobs'/job['id'];source=art()
            with patch('static_props.generate_materials',side_effect=lambda f,s,p:provider_result(f,s,p,source)) as provider:
                props.execute(root,job['id']);done=read(folder/'job.json')
                self.assertEqual(done['status'],'complete',done)
                manifest=props.load_package(root,done['kit_id'])
                checks=read(folder/'repeat-checks.json');cut=checks['selected']
                expected,_,_=slice_middle(whole_cutout(source),start=cut['start'],length=cut['length'],count=1)
                self.assertTrue(np.array_equal(np.asarray(expected[0]),np.asarray(Image.open(root/'prop-kits'/manifest['id']/'sprite.png'))))
                self.assertEqual(manifest['wall_connectors']['end'],[cut['length'],cut['length']//2])
                preview=root/'prop-kits'/manifest['id']/'repeat-preview.png'
                with Image.open(preview) as image:
                    self.assertEqual(image.size,(1024,640))
                self.assertIn('repeat-preview.png',manifest['files_sha256'])
                props.execute(root,job['id']);provider.assert_called_once()
                self.assertEqual(read(folder/'job.json')['kit_id'],done['kit_id'])

    def test_rejected_source_never_publishes_and_retry_never_calls_provider_again(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with patch('static_props.configured',return_value=True):
                job=props.prepare(root,dict(mode='ai',kind='custom',description='wall',title='墙',projection='isometric_2_1',wall_axis='b',wall_strip_build=True))
            folder=root/'.local/props/jobs'/job['id']
            with patch('static_props.generate_materials',side_effect=lambda f,s,p:provider_result(f,s,p,art('b',True))) as provider:
                props.execute(root,job['id'])
                self.assertEqual(read(folder/'job.json')['status'],'failed')
                self.assertFalse(list((root/'prop-kits').glob('*')))
                props.execute(root,job['id']);provider.assert_called_once()
                self.assertEqual(read(folder/'job.json')['status'],'failed')

    def test_worker_publishes_path_cut_when_straight_cut_fails(self):
        from wall_seam import cut
        from wall_assets import whole_cutout
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with patch('static_props.configured',return_value=True):
                job=props.prepare(root,dict(mode='ai',kind='custom',description='wall',title='墙',projection='isometric_2_1',wall_axis='b',wall_strip_build=True))
            folder=root/'.local/props/jobs'/job['id'];source=art('b')
            with patch('static_props.generate_materials',side_effect=lambda f,s,p:provider_result(f,s,p,source)),patch('wall_repeat.select',return_value=dict(passed=False)):
                props.execute(root,job['id'])
            done=read(folder/'job.json');self.assertEqual(done['status'],'complete',done)
            search=read(folder/'repeat-checks.json')
            self.assertEqual(search['recipe'],'studio.wall-path/1')
            expected,_,_=cut(whole_cutout(source),source_origin('b'),'b',search)
            with Image.open(root/'prop-kits'/done['kit_id']/'sprite.png') as actual:
                self.assertTrue(np.array_equal(np.asarray(expected[0]),np.asarray(actual)))
