"""Line-art production contracts; fake image service, no paid requests."""
import base64
from io import BytesIO
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock

from PIL import Image, ImageDraw
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from asset_repository import read, atomic
import building_pipeline as bp
import building_candidates as candidates


def encoded(image):
    stream=BytesIO();image.save(stream,format='PNG');return base64.b64encode(stream.getvalue()).decode()


def drawings():
    outline=Image.new('RGB',(256,256),'white');pen=ImageDraw.Draw(outline)
    pen.polygon([(60,180),(60,100),(125,40),(200,100),(200,180),(125,215)],outline='black',width=3)
    raw=Image.new('RGB',(256,256),'#ff00ff');pen=ImageDraw.Draw(raw)
    pen.polygon([(60,180),(60,100),(125,40),(200,100),(200,180),(125,215)],fill='#92744b')
    return outline,raw


class BuildingCandidatesTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.outline,self.raw=drawings()
        self.job=bp.prepare(self.root,dict(workflow='line_drawing',title='旅馆',appearance='暖棕木材，低对比手绘',line_drawing=encoded(self.outline)))
        self.task=self.job['id'];self.folder=bp.folder_for(self.root,self.task)
        self.provider=Mock();self.provider.base='https://example.invalid/v1'
        self.provider.create.return_value={'data':[{'b64_json':encoded(self.raw)}]}
        self.factory=Mock(return_value=self.provider)
        self.marking=dict(anchor_px=[128,200],footprint_polygon_px=[[64,170],[128,145],[205,180],[128,220]],output_width_px=512,cell_px=128)

    def generate(self):
        self.job=bp.new_attempt(self.root,self.task,self.job['revision'])
        self.job=bp.execute(self.root,self.task,provider_factory=self.factory)
        return bp.attempt_folder(self.folder,self.job['current_attempt'])

    def select(self,attempt):
        self.job=candidates.select(self.root,dict(task=self.task,revision=self.job['revision'],attempt=attempt))

    def save(self,attempt,**values):
        target=bp.attempt_folder(self.folder,attempt)
        result=candidates.save(self.root,dict(task=self.task,revision=self.job['revision'],attempt=attempt,
            evidence_key=bp.digest(target/'checks.json'),calibration=values.get('calibration',self.marking)))
        self.job=read(self.folder/'job.json');return result

    def test_visual_adoption_needs_no_prior_selection_or_calibration(self):
        target=self.generate();attempt=self.job['current_attempt']
        self.assertIsNone(self.job.get('selected_attempt'))
        result=candidates.save(self.root,dict(task=self.task,revision=self.job['revision'],attempt=attempt,
            evidence_key=bp.digest(target/'checks.json'),visual_only=True))
        bp.load_package(self.root,result['id'])
        folder=self.root/'building-kits'/result['id']
        integration=read(folder/'integration.json')
        self.assertEqual(integration['footprint_polygon'],[])
        self.assertEqual(integration['collision']['proposal'],'not_provided')
        self.assertFalse(result['production_ready'])
        self.assertEqual(read(folder/'calibration.json')['source'],'visual_only_bottom_center_not_calibrated')

    def test_input_is_original_line_drawing_and_style_no_structure_defaults(self):
        self.assertFalse((self.folder/'structure').exists());self.assertEqual(self.job['attempts'],[])
        first=self.generate();self.assertEqual(self.job['status'],'waiting_review')
        prompt,images=self.provider.create.call_args.args
        self.assertEqual(images,[self.folder/'outline.png']);self.assertIn('暖棕木材',prompt)
        self.assertNotIn('gable',prompt);self.assertNotIn('Footprint',prompt)
        self.assertNotIn('wall height',prompt)
        original_prompt=bp.digest(first/'prompt.txt');original_raw=bp.digest(first/'raw.png')
        second=self.generate()
        self.assertNotEqual(first,second);self.assertEqual(bp.digest(second/'prompt.txt'),original_prompt)
        self.assertEqual(bp.digest(first/'raw.png'),original_raw)
        self.assertEqual(self.provider.create.call_count,2)
        self.assertEqual(self.provider.create.call_args.args[1],[self.folder/'outline.png'])

    def test_drawing_and_style_are_required_before_preparation(self):
        for data in [dict(title='测试',appearance='手绘'),dict(title='测试',line_drawing=encoded(self.outline))]:
            with self.assertRaises(ValueError):bp.prepare(self.root,dict(workflow='line_drawing',**data))
        self.provider.create.assert_not_called()

    def test_muted_pink_background_is_sampled_without_erasing_interior(self):
        raw=Image.new('RGB',(256,256),'#cd5692')
        pen=ImageDraw.Draw(raw)
        pen.rectangle((60,60,195,195),fill='#92744b')
        pen.rectangle((100,100,140,140),fill='#cd5692')
        self.provider.create.return_value={'data':[{'b64_json':encoded(raw)}]}
        target=self.generate()
        self.assertEqual(self.job['status'],'waiting_review')
        with Image.open(target/'sprite.png') as sprite:
            self.assertEqual(sprite.getpixel((20,20))[3],0)
            self.assertEqual(sprite.getpixel((120,120)),(205,86,146,255))
        self.assertEqual(read(target/'checks.json')['background']['key_rgb'],[205,86,146])

    def test_nonuniform_pink_scene_is_not_accepted_as_chroma_key(self):
        raw=Image.new('RGB',(256,256),'#cd5692')
        ImageDraw.Draw(raw).rectangle((0,0,127,255),fill='#703060')
        self.provider.create.return_value={'data':[{'b64_json':encoded(raw)}]}
        target=self.generate()
        self.assertEqual(self.job['status'],'failed')
        self.assertTrue((target/'raw.png').exists())

    def test_thin_dark_pink_canvas_rim_is_removed_without_resizing(self):
        raw=Image.new('RGB',(256,256),'#cd5692')
        pen=ImageDraw.Draw(raw)
        pen.rectangle((0,0,255,255),outline='#723854')
        pen.rectangle((60,60,195,195),fill='#92744b')
        self.provider.create.return_value={'data':[{'b64_json':encoded(raw)}]}
        target=self.generate()
        self.assertEqual(self.job['status'],'waiting_review')
        with Image.open(target/'sprite.png') as sprite:
            self.assertEqual(sprite.size,raw.size)
            self.assertEqual(sprite.getpixel((0,120))[3],0)

    def test_old_candidate_can_be_selected_after_new_cutout_failure(self):
        first=self.generate();self.provider.create.return_value={'data':[{'b64_json':encoded(Image.new('RGB',(256,256),'blue'))}]}
        second=self.generate();self.assertEqual(self.job['status'],'failed')
        entries=bp.catalog(self.root)['jobs'][0]['candidates']
        self.assertTrue(entries[0]['ready']);self.assertFalse(entries[1]['ready']);self.assertTrue(entries[1]['error'])
        self.select(first.name);kit=self.save(first.name)
        self.assertEqual(kit['attempt_id'],first.name)
        self.assertTrue((second/'raw.png').exists());self.assertEqual(self.provider.create.call_count,2)

    def test_save_maps_calibration_uniformly_and_preserves_sources(self):
        target=self.generate()
        with self.assertRaisesRegex(ValueError,'先选定'):self.save(target.name)
        self.select(target.name);kit=self.save(target.name);folder=self.root/'building-kits'/kit['id']
        integration=read(folder/'integration.json')
        self.assertEqual(integration['anchor_px'],[256,400])
        self.assertEqual(integration['sprite_offset_px'],[-256,-400])
        self.assertEqual(integration['footprint_polygon'][0],[-128,-60])
        self.assertFalse(integration['collision']['enabled_by_default'])
        self.assertEqual(integration['game_integration'],'not_tested')
        self.assertEqual(kit['human_review'],'candidate_selected');self.assertFalse(kit['production_ready'])
        with Image.open(folder/'sprite.png') as image:self.assertEqual(image.size,(512,512))
        self.assertIn('inputs/outline.png',kit['files_sha256']);self.assertNotIn('structure.json',kit['files_sha256'])
        report=read(folder/'checks.json')
        for name,sha in report['evidence_sha256'].items():self.assertEqual(bp.digest(folder/'inputs'/name),sha)
        self.assertEqual(bp.load_package(self.root,kit['id']),kit)
        before=bp.digest(folder/'kit.zip');self.select(target.name);second=self.save(target.name,calibration={**self.marking,'output_width_px':256})
        self.assertNotEqual(kit['id'],second['id']);self.assertEqual(before,bp.digest(folder/'kit.zip'))
        self.provider.create.assert_called_once()

    def test_stale_selection_or_changed_image_blocks_save(self):
        target=self.generate();revision=self.job['revision'];self.select(target.name)
        with self.assertRaisesRegex(ValueError,'更新'):candidates.select(self.root,dict(task=self.task,revision=revision,attempt=target.name))
        (target/'sprite.png').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'变化'):self.save(target.name)
        self.assertFalse(list((self.root/'building-kits').glob('*')))

    def test_bad_calibration_or_evidence_key_does_not_publish(self):
        target=self.generate();self.select(target.name)
        for values in [dict(anchor_px=None),dict(footprint_polygon_px=[[1,1],[2,2],[3,3]]),
                       dict(footprint_polygon_px=[[10,10],[100,100],[10,100],[100,10]]),dict(output_width_px=0)]:
            with self.assertRaises(ValueError):self.save(target.name,calibration={**self.marking,**values})
        with self.assertRaisesRegex(ValueError,'更新'):
            candidates.save(self.root,dict(task=self.task,revision=self.job['revision'],attempt=target.name,evidence_key='old',calibration=self.marking))
        self.assertFalse(list((self.root/'building-kits').glob('*')))

    def test_new_style_scheme_inherits_line_drawing_without_overwriting(self):
        before=bp.digest(self.folder/'outline.png')
        child=bp.prepare(self.root,dict(workflow='line_drawing',title='另一种画风',appearance='冷色石材',source_task=self.task,source_revision=self.job['revision']))
        self.assertEqual(child['parent_task'],self.task)
        self.assertEqual(bp.digest(bp.folder_for(self.root,child['id'])/'outline.png'),before)
        self.assertEqual(bp.digest(self.folder/'outline.png'),before)
        self.assertEqual(child['spec']['appearance'],'冷色石材');self.provider.create.assert_not_called()

    def test_candidate_flow_rejects_edit_and_formal_structure_review(self):
        target=self.generate()
        with self.assertRaisesRegex(ValueError,'重新生成'):bp.new_attempt(self.root,self.task,self.job['revision'],'修门',mode='edit')
        with self.assertRaisesRegex(ValueError,'无需结构复核'):bp.review(self.root,self.task,self.job['revision'],dict.fromkeys(bp.CHECKS,True))
        with self.assertRaises(ValueError):bp.adjust(self.root,dict(task=self.task,revision=self.job['revision'],action='repair'))
        with self.assertRaisesRegex(ValueError,'标定保存'):bp.publish(self.root,self.task,self.job['revision'])

    def test_resume_keeps_remote_task_and_original_outline(self):
        self.provider.create.return_value={'id':'existing'}
        stream=BytesIO();self.raw.save(stream,format='PNG')
        self.provider.request.side_effect=[{'status':'running'},{'status':'completed'},stream.getvalue()]
        self.job=bp.new_attempt(self.root,self.task,self.job['revision'])
        self.job=bp.execute(self.root,self.task,deadline_seconds=0,provider_factory=self.factory)
        self.assertEqual(self.job['status'],'failed')
        self.job=bp.execute(self.root,self.task,provider_factory=self.factory)
        self.assertEqual(self.job['status'],'waiting_review');self.provider.create.assert_called_once()


if __name__=='__main__':unittest.main()
