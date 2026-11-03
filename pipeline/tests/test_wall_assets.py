"""Synthetic art checks fixed canvas, malformed geometry and producer integration."""
import json
import tempfile
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import wall_assets as walls
import static_props as props
from asset_repository import read,atomic
import studio_projects as projects


def fixture(axis):
    image=Image.new('RGBA',(512,512),(255,0,255,255))
    color=Image.new('RGBA',(512,512),(164,154,130,255))
    image.paste(color,(0,0),walls.mask(axis));return image


class WallAssets(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name)

    def test_both_axes_preserve_full_canvas_and_accept_matching_silhouette(self):
        for axis in ('a','b'):
            sprite,report=walls.process(fixture(axis),axis)
            self.assertTrue(report['geometry_passed'],report)
            self.assertEqual(sprite.size,(512,512))
            self.assertEqual(sprite.getchannel('A').getbbox(),walls.mask(axis).getbbox())

    def test_shifted_and_wrong_axis_outputs_are_rejected(self):
        image=fixture('a');shift=Image.new('RGBA',image.size,(255,0,255,255));shift.paste(image,(15,0))
        self.assertFalse(walls.process(shift,'a')[1]['geometry_passed'])
        self.assertFalse(walls.process(fixture('b'),'a')[1]['geometry_passed'])
        with self.assertRaises(ValueError):walls.process(Image.new('RGB',(512,400)),'a')

    def prepare(self):
        with patch('static_props.configured',return_value=True):
            job=props.prepare(self.root,dict(mode='ai',kind='custom',title='院墙',description='plain wall',projection='isometric_2_1',wall_axis='a'))
        return job,self.root/'.local/props/jobs'/job['id']

    def test_job_publishes_connectors_without_bbox_normalization(self):
        job,folder=self.prepare();fixture('a').save(folder/'inputs/ground.png')
        import hashlib
        atomic(folder/'generation.json',dict(ground=dict(sha256=hashlib.sha256((folder/'inputs/ground.png').read_bytes()).hexdigest())))
        props.execute(self.root,job['id']);done=read(folder/'job.json')
        self.assertEqual(done['status'],'complete',done)
        m=props.load_package(self.root,done['kit_id'])
        self.assertEqual(m['canvas_px'],[512,512]);self.assertEqual(m['anchor_px'],[256,280])
        self.assertEqual(m['wall_connectors']['end'],[128,64])
        self.assertEqual(m['processing']['geometry']['iou'],1)
        props.execute(self.root,job['id'])
        self.assertEqual(read(folder/'job.json')['kit_id'],done['kit_id'])
        self.assertEqual(len(list((self.root/'prop-kits').glob('*/manifest.json'))),1)

    def test_anchor_edit_keeps_connectors_at_same_image_points(self):
        job,folder=self.prepare();fixture('a').save(folder/'inputs/original.png')
        m=walls.publish(self.root,folder,job['spec'])
        config=props.module_settings(m)
        config['anchor']=[250,270]
        changed=props.annotate(self.root,dict(source_kit=m['id'],**config))
        self.assertEqual(changed['wall_connectors']['start'],[6,10])
        self.assertEqual(changed['wall_connectors']['end'],[134,74])
        self.assertEqual(changed['wall_connectors']['repeat_offset_px'],[128,64])

    def test_wall_connectors_reach_scene_and_keep_fixed_collision(self):
        import scene_modules as scenes
        job,folder=self.prepare();fixture('a').save(folder/'inputs/original.png')
        manifest=walls.publish(self.root,folder,job['spec'])
        scene=scenes.change(self.root,dict(action='create',title='wall check'))
        scene=scenes.change(self.root,dict(action='adopt',scene=scene['id'],revision=scene['revision'],kit=manifest['id']))
        module=scenes.load(self.root,scene['id'])['modules'][0]
        self.assertEqual(module['wall_connectors']['end'],[128,64])
        self.assertEqual(module['anchor'],[256,280]);self.assertEqual(module['behavior'],'blocking')
        self.assertEqual(len(module['polygons']),1)

    def test_bad_reference_or_geometry_never_publishes(self):
        job,folder=self.prepare();fixture('b').save(folder/'inputs/original.png')
        with self.assertRaisesRegex(ValueError,'偏离'):walls.publish(self.root,folder,job['spec'])
        self.assertFalse(list((self.root/'prop-kits').glob('*')))
        (folder/'inputs/reference.png').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'线框'):walls.verify_reference(folder,job['spec'])

    def test_surface_projection_uses_shared_material_and_exact_geometry(self):
        import numpy as np
        textures=walls.material_textures(fixture('a'))
        for axis in ('a','b'):
            sprite=walls.compile_surfaces(textures,axis)
            self.assertTrue(np.array_equal(np.asarray(sprite.getchannel('A'))>0,np.asarray(walls.mask(axis))>0))
            self.assertEqual(sprite.size,(512,512))
        for texture in textures.values():
            pixels=np.asarray(texture)
            self.assertTrue(np.array_equal(pixels[:,0],pixels[:,-1]))
            self.assertTrue(np.array_equal(pixels[0],pixels[-1]))

    def test_project_template_binding_is_explicit_and_used_by_production(self):
        p=projects.change(self.root,dict(action='create',title='院墙',baseline=dict(style='hand painted')))
        p=projects.change(self.root,dict(action='add',project=p['id'],revision=p['revision'],kind='prop',title='A墙',description='plain wall'))
        entry=p['items'][0]
        p=projects.change(self.root,dict(action='wall_template',project=p['id'],revision=p['revision'],item=entry['id'],axis='a'))
        with patch('terrain_images.configured',return_value=True):
            plan=projects.production_plan(self.root,p,p['items'][0])
        self.assertTrue(plan['ready'],plan);self.assertEqual(plan['data']['wall_axis'],'a')
        prior=self.root/'.local/props/jobs/shared/job.json'
        atomic(prior,dict(status='complete',spec=dict(wall_axis='a',wall_surface_projection=True)))
        projects.record_task(self.root,plan['context'],'/api/props/generate',dict(id='shared'))
        p=projects.load(self.root,p['id'])
        with patch('terrain_images.configured',return_value=True):
            shared=projects.production_plan(self.root,p,p['items'][0])
        self.assertEqual(shared['data']['wall_material_job'],'shared')
        direct=dict(mode='import',description='wall',wall_material_job='unrelated')
        projects.inherit(self.root,shared['context'],'/api/props/generate',direct)
        self.assertEqual(direct['wall_material_job'],'shared')
        self.assertEqual(direct['mode'],'ai')
        self.assertEqual(direct['wall_axis'],'a')
        p['baseline_revision']+=1
        atomic(projects.folder(self.root,p['id'])/'project.json',p)
        with patch('terrain_images.configured',return_value=True):
            fresh=projects.production_plan(self.root,p,p['items'][0])
        self.assertNotIn('wall_material_job',fresh['data'])
