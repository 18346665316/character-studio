"""Template lifecycle and reusable shape/style separation; no paid generation."""
import base64
from io import BytesIO
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock

from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from asset_repository import read
import building_pipeline as bp
import building_templates as templates
from pipeline.tests.test_building_candidates import drawings,encoded


class BuildingTemplateTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.outline,self.raw=drawings()
        self.provider=Mock();self.provider.base='https://example.invalid/v1'
        self.provider.create.return_value={'data':[{'b64_json':encoded(self.outline)}]}

    def upload(self):
        return templates.save(self.root,dict(title='旅馆母版',view='isometric_2_1',line_drawing=encoded(self.outline),confirmed=True))

    def test_front_facing_template_generation_and_import(self):
        job=templates.prepare(self.root,dict(title='农舍',description='单层双坡屋顶',view='orthographic_three_quarter'))
        prompt=templates.prompt(job['spec'])
        self.assertIn('door facing screen bottom',prompt)
        self.assertNotIn('Show the roof and two sides',prompt)
        saved=templates.save(self.root,dict(title='斜俯视农舍',view='orthographic_three_quarter',line_drawing=encoded(self.outline),confirmed=True))
        self.assertEqual(saved['view'],'orthographic_three_quarter')

    def test_upload_needs_no_confirmation_and_preserves_immutable_versions(self):
        saved=templates.save(self.root,dict(title='模板',line_drawing=encoded(self.outline)))
        self.assertEqual(saved['review'],'saved_for_reuse_not_projection_measurement')
        first=self.upload();second=self.upload()
        self.assertNotEqual(first['id'],second['id']);self.assertEqual(len(templates.catalog(self.root)),3)
        folder,meta=templates.load(self.root,first['id']);self.assertEqual(meta['view'],'isometric_2_1')
        (folder/'outline.png').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'变化'):templates.load(self.root,first['id'])
        self.assertEqual(len(templates.catalog(self.root)),2)

    def test_same_template_supports_distinct_styles_with_identical_line_input(self):
        template=self.upload();jobs=[]
        for style in ['暖色木材手绘','冷灰石材水彩']:
            job=bp.prepare(self.root,dict(workflow='line_drawing',title='建筑',appearance=style,template_id=template['id']))
            folder=bp.folder_for(self.root,job['id']);self.assertEqual(bp.digest(folder/'outline.png'),template['outline_sha256'])
            self.assertEqual(read(folder/'template-source.json')['id'],template['id'])
            job=bp.new_attempt(self.root,job['id'],job['revision']);jobs.append(job)
            prompt=(bp.attempt_folder(folder,job['current_attempt'])/'prompt.txt').read_text()
            self.assertIn(style,prompt);self.assertNotIn('Ground axes have screen slopes',prompt)
        self.assertNotEqual(jobs[0]['id'],jobs[1]['id']);self.provider.create.assert_not_called()

    def test_generated_template_is_text_to_line_art_without_existing_outline_or_cutout(self):
        job=templates.prepare(self.root,dict(title='两层旅馆',description='两层矩形、双坡屋顶、单入口',view='isometric_2_1'))
        job=bp.new_attempt(self.root,job['id'],job['revision'])
        folder=bp.folder_for(self.root,job['id']);target=bp.attempt_folder(folder,job['current_attempt'])
        self.assertEqual(job['spec']['view'],'isometric_2_1');self.assertNotIn('appearance',job['spec'])
        job=bp.execute(self.root,job['id'],provider_factory=lambda _:self.provider)
        self.assertEqual(job['status'],'waiting_review')
        prompt,images=self.provider.create.call_args.args;self.assertEqual(images,[])
        self.assertIn('2:1 diamond tile',prompt);self.assertIn('Plain white background',prompt);self.assertNotIn('magenta',prompt)
        self.assertFalse((target/'sprite.png').exists())
        entry=bp.catalog(self.root)['jobs'][0]['candidates'][0];self.assertTrue(entry['ready'])
        meta=templates.save(self.root,dict(task=job['id'],revision=job['revision'],attempt=job['current_attempt'],
            title=job['spec']['title'],confirmed=True,evidence_key=entry['evidence_key']))
        self.assertEqual(meta['source']['kind'],'ai_line_drawing')
        self.assertEqual(meta['view'],'isometric_2_1');self.assertEqual(read(folder/'job.json')['template_id'],meta['id'])
        self.assertTrue((templates.folder_for(self.root,meta['id'])/'generation.json').exists())
        self.provider.create.assert_called_once()

    def test_generation_view_is_explicit_and_evidence_cannot_be_changed(self):
        job=templates.prepare(self.root,dict(title='塔楼',description='方形塔楼',view='isometric_true'))
        job=bp.new_attempt(self.root,job['id'],job['revision']);job=bp.execute(self.root,job['id'],provider_factory=lambda _:self.provider)
        self.assertIn('all three world axes equally foreshortened',self.provider.create.call_args.args[0])
        folder=bp.folder_for(self.root,job['id']);target=bp.attempt_folder(folder,job['current_attempt'])
        entry=bp.catalog(self.root)['jobs'][0]['candidates'][0]
        (target/'preview.png').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'变化'):templates.save(self.root,dict(task=job['id'],revision=job['revision'],attempt=job['current_attempt'],title='塔楼',confirmed=True,evidence_key=entry['evidence_key']))
        with self.assertRaises(ValueError):templates.prepare(self.root,dict(title='无视角',description='塔楼',view='custom'))

    def test_template_selection_rejects_missing_or_ambiguous_input(self):
        with self.assertRaises(ValueError):bp.prepare(self.root,dict(workflow='line_drawing',title='测试',appearance='手绘',template_id='missing'))
        template=self.upload()
        with self.assertRaisesRegex(ValueError,'同时'):bp.prepare(self.root,dict(workflow='line_drawing',title='测试',appearance='手绘',template_id=template['id'],line_drawing=encoded(self.outline)))

    def test_saved_building_includes_template_provenance_snapshot(self):
        import building_candidates as candidates
        template=self.upload()
        job=bp.prepare(self.root,dict(workflow='line_drawing',title='木旅馆',appearance='木材手绘',template_id=template['id']))
        self.provider.create.return_value={'data':[{'b64_json':encoded(self.raw)}]}
        job=bp.new_attempt(self.root,job['id'],job['revision']);job=bp.execute(self.root,job['id'],provider_factory=lambda _:self.provider)
        attempt=job['current_attempt'];folder=bp.folder_for(self.root,job['id']);target=bp.attempt_folder(folder,attempt)
        job=candidates.select(self.root,dict(task=job['id'],revision=job['revision'],attempt=attempt))
        kit=candidates.save(self.root,dict(task=job['id'],revision=job['revision'],attempt=attempt,evidence_key=bp.digest(target/'checks.json'),
            calibration=dict(anchor_px=[128,200],footprint_polygon_px=[[64,170],[128,145],[205,180],[128,220]],output_width_px=512)))
        saved=self.root/'building-kits'/kit['id']
        self.assertEqual(read(saved/'template-source.json')['id'],template['id'])
        self.assertEqual(bp.digest(saved/'inputs/outline.png'),template['outline_sha256'])
        # Production snapshots stay usable even if the library copy is lost.
        (templates.folder_for(self.root,template['id'])/'outline.png').unlink()
        self.assertEqual(bp.load_package(self.root,kit['id']),kit)


if __name__=='__main__':unittest.main()
