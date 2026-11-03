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

    def test_whole_wall_preserves_painted_image_without_false_connectors(self):
        import numpy as np
        job,folder=self.prepare()
        walls.whole_sprite(folder,job['spec'],self.root)
        fixture('b').save(folder/'inputs/original.png')
        expected,report=walls.process(fixture('b'),'a')
        self.assertFalse(report['geometry_passed'])
        with patch('wall_assets.material_textures',side_effect=AssertionError('must not sample textures')):
            manifest=walls.publish(self.root,folder,job['spec'])
        image=Image.open(self.root/'prop-kits'/manifest['id']/'sprite.png')
        self.assertTrue(np.array_equal(np.asarray(image),np.asarray(expected)))
        self.assertFalse(manifest['processing']['geometry']['geometry_passed'])
        self.assertIsNone(manifest['wall_connectors'])
        self.assertEqual(props.module_settings(manifest)['polygons'],[])
        self.assertEqual(manifest['provenance']['art_source'],'ai_whole_wall')

    def test_continuous_wall_keeps_the_generated_pixels_and_open_reference(self):
        import numpy as np
        from build_courtyard_wall_templates import render_continuous
        with patch('static_props.configured',return_value=True):
            job=props.prepare(self.root,dict(mode='ai',kind='custom',title='连续墙',description='painted wall',projection='isometric_2_1',wall_axis='a',wall_whole_sprite=True,wall_continuous=True))
        folder=self.root/'.local/props/jobs'/job['id']
        self.assertTrue(np.array_equal(np.asarray(Image.open(folder/'inputs/reference.png')),np.asarray(render_continuous('a'))))
        self.assertIn('invisible cut planes',job['spec']['material_prompt'])
        source=Image.new('RGBA',(512,512),(255,0,255,255))
        source.paste(Image.new('RGBA',(512,512),(170,160,140,255)),(0,0),walls.mask('a',True))
        source.save(folder/'inputs/original.png')
        expected,_=walls.process(walls.whole_cutout(source),'a',True)
        with patch('wall_assets.compile_surfaces',side_effect=AssertionError('no geometry processing')):
            manifest=walls.publish(self.root,folder,job['spec'])
        self.assertTrue(np.array_equal(np.asarray(Image.open(self.root/'prop-kits'/manifest['id']/'sprite.png')),np.asarray(expected)))

    def test_continuous_wall_rejects_wrong_geometry_instead_of_publishing_a_preview(self):
        job,folder=self.prepare();job['spec']['wall_continuous']=True
        walls.configure(folder,job['spec'],'a');walls.whole_sprite(folder,job['spec'],self.root)
        fixture('b').save(folder/'inputs/original.png')
        with self.assertRaisesRegex(ValueError,'偏离线框'):walls.publish(self.root,folder,job['spec'])
        self.assertFalse(list((self.root/'prop-kits').glob('*')))

    def test_style_reference_has_receipt_and_is_not_reused_as_output(self):
        import hashlib
        job,folder=self.prepare()
        walls.whole_sprite(folder,job['spec'],self.root)
        job['status']='complete';atomic(folder/'job.json',job)
        fixture('a').save(folder/'inputs/ground.png')
        digest=hashlib.sha256((folder/'inputs/ground.png').read_bytes()).hexdigest()
        atomic(folder/'generation.json',dict(ground=dict(sha256=digest)))
        _,target=self.prepare();spec=dict(description='wall',title='B wall')
        walls.configure(target,spec,'b');walls.whole_sprite(target,spec,self.root,job['id'])
        self.assertEqual(spec['wall_style_sha256'],digest)
        self.assertFalse((target/'inputs/ground.png').exists())
        walls.verify_reference(target,spec)
        (target/'inputs/wall-style.png').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'风格参考'):walls.verify_reference(target,spec)

    def test_whole_cutout_removes_pink_gradient_and_white_rim_preserving_paint(self):
        import numpy as np
        pixels=np.zeros((512,512,3),dtype=np.uint8)
        pixels[:,:,0]=225;pixels[:,:,1]=140
        pixels[:,:,2]=np.linspace(175,200,512).astype(np.uint8)[None,:]
        image=Image.fromarray(pixels)
        image.paste((255,255,255),(508,0,512,512))
        image.paste((246,222,233),(507,0,508,512))
        image.paste((238,227,198),(180,180,320,340))
        result=walls.whole_cutout(image)
        self.assertEqual(result.getchannel('A').getbbox(),(180,180,320,340))
        self.assertEqual(result.getpixel((250,250)),(238,227,198,255))
        with self.assertRaises(ValueError):walls.whole_cutout(Image.new('RGB',(512,512),'green'))
        with self.assertRaisesRegex(ValueError,'品红背景'):walls.whole_cutout(Image.new('RGB',(512,512),'white'))

    def test_surface_projection_uses_shared_material_and_exact_geometry(self):
        import numpy as np
        textures=walls.material_textures(fixture('a'))
        for axis in ('a','b'):
            sprite=walls.compile_surfaces(textures,axis)
            self.assertTrue(np.array_equal(np.asarray(sprite.getchannel('A'))>0,np.asarray(walls.mask(axis))>0))
            self.assertEqual(sprite.size,(512,512))
        for role,texture in textures.items():
            pixels=np.asarray(texture)
            self.assertTrue(np.array_equal(pixels[:,0],pixels[:,-1]))
            if role=='plaster':self.assertTrue(np.array_equal(pixels[0],pixels[-1]))

    def test_roof_sampling_straightens_tiles_instead_of_sampling_a_diagonal_crop(self):
        import numpy as np
        from PIL import ImageDraw
        from build_courtyard_wall_templates import point,project,ANCHOR
        image=fixture('a');draw=ImageDraw.Draw(image)
        draw.bitmap((0,0),walls.mask('a'),fill=(230,220,200))
        for t in range(0,128,16):
            vertices=[point('a',t,8,100),point('a',t+16,8,100),point('a',t+16,0,108),point('a',t,0,108)]
            color=80 if t%32==0 else 145
            draw.polygon([(project(p)[0]+ANCHOR[0],project(p)[1]+ANCHOR[1]) for p in vertices],fill=(color,color,color))
        texture=np.asarray(walls.material_textures(image)['cap']).astype(float)
        self.assertLess(np.abs(texture[20]-texture[-20]).mean(),15)
        self.assertGreater(texture[128,:,0].std(),15)

    def test_project_template_binding_is_explicit_and_used_by_production(self):
        p=projects.change(self.root,dict(action='create',title='院墙',baseline=dict(style='hand painted')))
        p=projects.change(self.root,dict(action='add',project=p['id'],revision=p['revision'],kind='prop',title='A墙',description='plain wall'))
        entry=p['items'][0]
        p=projects.change(self.root,dict(action='wall_template',project=p['id'],revision=p['revision'],item=entry['id'],axis='a'))
        with patch('terrain_images.configured',return_value=True):
            plan=projects.production_plan(self.root,p,p['items'][0])
        self.assertTrue(plan['ready'],plan);self.assertEqual(plan['data']['wall_axis'],'a')
        prior=self.root/'.local/props/jobs/shared/job.json'
        atomic(prior,dict(status='complete',spec=dict(wall_axis='b',wall_whole_sprite=True)))
        projects.record_task(self.root,plan['context'],'/api/props/generate',dict(id='shared'))
        p=projects.load(self.root,p['id'])
        with patch('terrain_images.configured',return_value=True):
            shared=projects.production_plan(self.root,p,p['items'][0])
        self.assertTrue(shared['data']['wall_strip_build'])
        self.assertNotIn('wall_style_job',shared['data'])
        direct=dict(mode='import',description='wall',wall_material_job='unrelated',wall_whole_sprite=True)
        projects.inherit(self.root,shared['context'],'/api/props/generate',direct)
        self.assertTrue(direct['wall_strip_build'])
        self.assertNotIn('wall_material_job',direct)
        self.assertNotIn('wall_whole_sprite',direct)
        self.assertEqual(direct['mode'],'ai')
        self.assertEqual(direct['wall_axis'],'a')
        p['baseline_revision']+=1
        atomic(projects.folder(self.root,p['id'])/'project.json',p)
        with patch('terrain_images.configured',return_value=True):
            fresh=projects.production_plan(self.root,p,p['items'][0])
        self.assertNotIn('wall_style_job',fresh['data'])
