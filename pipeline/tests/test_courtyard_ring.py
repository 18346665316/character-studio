from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
from PIL import Image,ImageDraw
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from asset_repository import read
from courtyard_ring import reference,partition,create_validation_scene
from wall_assets import whole_cutout
import static_props as props
import studio_projects as projects
from test_wall_repeat import provider_result


class CourtyardRingTests(unittest.TestCase):
    def test_eight_regions_reconstruct_all_source_pixels(self):
        source=whole_cutout(reference());parts,checks=partition(source)
        self.assertEqual(len(parts),8);self.assertTrue(checks['closed'])
        rebuilt=Image.new('RGBA',source.size)
        for part in parts:rebuilt.alpha_composite(part['sprite'],part['offset'])
        self.assertTrue(np.array_equal(np.asarray(rebuilt),np.asarray(source)))
        self.assertEqual(checks['reconstruction_pixel_errors'],0)

    def test_open_ring_and_filled_center_are_rejected(self):
        source=whole_cutout(reference());draw=ImageDraw.Draw(source)
        draw.rectangle((700,0,704,1023),fill=(0,0,0,0))
        with self.assertRaisesRegex(ValueError,'未闭合'):partition(source)
        source=whole_cutout(reference());source.putpixel((512,450),(100,100,100,255))
        with self.assertRaisesRegex(ValueError,'院心被填满'):partition(source)

    def test_project_generation_publishes_one_whole_with_eight_parts_and_reuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            p=projects.change(root,dict(action='create',title='四合院',baseline=dict(style='painted')))
            p=projects.change(root,dict(action='add',project=p['id'],revision=p['revision'],kind='prop',title='院墙',description='closed courtyard'))
            entry=p['items'][0]['id']
            p=projects.change(root,dict(action='wall_template',project=p['id'],revision=p['revision'],item=entry,axis='ring'))
            with patch('terrain_images.configured',return_value=True):plan=projects.production_plan(root,p,p['items'][0])
            self.assertTrue(plan['ready'],plan);self.assertTrue(plan['data']['courtyard_ring_build'])
            with patch('static_props.configured',return_value=True):job=props.prepare(root,plan['data'])
            folder=root/'.local/props/jobs'/job['id']
            with patch('static_props.generate_materials',side_effect=lambda f,s,p:provider_result(f,s,p,reference())) as provider:
                props.execute(root,job['id']);done=read(folder/'job.json')
                self.assertEqual(done['status'],'complete',done)
                manifest=props.load_package(root,done['kit_id'])
                self.assertEqual(len(manifest['assembly_parts']),8)
                for kit in manifest['assembly_parts']:props.load_package(root,kit)
                props.execute(root,job['id']);provider.assert_called_once()
                self.assertEqual(read(folder/'job.json')['kit_id'],done['kit_id'])
            import scene_modules as scenes
            scene=create_validation_scene(root,folder)
            self.assertEqual(len(scene['modules']),8);self.assertEqual(len(scene['instances']),8)
            self.assertEqual({m['source']['id'] for m in scene['modules']},set(manifest['assembly_parts']))
            # Returning to validation must not undo the user's scene edits.
            edited=scenes.change(root,dict(action='layout',scene=scene['id'],revision=scene['revision'],instances=scene['instances'][:-1],spawn=[0,192]))
            self.assertEqual(create_validation_scene(root,folder),edited)
