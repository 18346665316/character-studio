from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from asset_repository import read
import static_props as props
from wall_corner import ORIGIN,partition
from test_wall_repeat import provider_result


def corner_art(drift=False):
    yy,xx=np.indices((1024,1024),dtype=float)
    t=np.abs(xx-ORIGIN[0]);k=yy-ORIGIN[1]-.5*t
    visible=(t<352)&(k>=-108)&(k<=8)
    rgba=np.zeros((1024,1024,4),dtype=np.uint8);rgba[:]=[255,0,255,255]
    roof=k<-84;phase=(t.astype(int)%16)<8
    for channel,(a,b) in enumerate(((80,220),(100,210),(90,180))):
        value=np.where(roof,a+phase*15,b+phase*3)
        if drift:value=40+t*.5
        rgba[:,:,channel][visible]=np.clip(value[visible],0,255).astype(np.uint8)
    return Image.fromarray(rgba)


class WallCornerTests(unittest.TestCase):
    def test_project_button_inherits_corner_recipe(self):
        import studio_projects as projects
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            p=projects.change(root,dict(action='create',title='院落',baseline=dict(style='painted')))
            p=projects.change(root,dict(action='add',project=p['id'],revision=p['revision'],kind='prop',title='内转角',description='corner'))
            entry=p['items'][0]['id']
            p=projects.change(root,dict(action='wall_template',project=p['id'],revision=p['revision'],item=entry,axis='corner'))
            with patch('terrain_images.configured',return_value=True):
                plan=projects.production_plan(root,p,p['items'][0])
            self.assertTrue(plan['ready'],plan)
            self.assertTrue(plan['data']['wall_corner_build'])
            self.assertNotIn('wall_axis',plan['data'])

    def test_shared_corner_and_arms_preserve_pixels_and_worker_reuses_publication(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with patch('static_props.configured',return_value=True):
                job=props.prepare(root,dict(mode='ai',kind='custom',description='painted corner',title='转角',projection='isometric_2_1',wall_corner_build=True))
            folder=root/'.local/props/jobs'/job['id']
            with patch('static_props.generate_materials',side_effect=lambda f,s,p:provider_result(f,s,p,corner_art())) as provider:
                props.execute(root,job['id'])
                done=read(folder/'job.json');self.assertEqual(done['status'],'complete',done)
                report=read(folder/'corner-checks.json')
                self.assertEqual(report['reconstruction_pixel_errors'],0)
                self.assertEqual(report['overlapping_source_pixels'],0)
                ids=read(folder/'corner-published.json');self.assertEqual(set(ids),{'a','b','corner'})
                corner=props.load_package(root,ids['corner'])
                for axis in ('a','b'):
                    wall=props.load_package(root,ids[axis])
                    cut=report['cuts'][axis]
                    self.assertEqual(corner['corner_ports'][axis],[(1 if axis=='a' else -1)*cut['start'],cut['start']//2])
                    self.assertEqual(wall['wall_connectors']['repeat_offset_px'],cut['repeat_offset_px'])
                props.execute(root,job['id']);provider.assert_called_once()
                self.assertEqual(read(folder/'corner-published.json'),ids)

    def test_incompatible_arms_are_rejected(self):
        from wall_assets import whole_cutout
        with self.assertRaisesRegex(ValueError,'未找到可重复接口'):
            partition(whole_cutout(corner_art(True)))
