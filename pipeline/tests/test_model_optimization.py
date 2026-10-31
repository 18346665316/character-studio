"""Optimization remains an isolated candidate until explicit adoption."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from model_optimization import activate,compare,digest
from panel import Panel,atomic


class ModelOptimizationTests(unittest.TestCase):
    def test_pixel_comparison_detects_shape_and_color_changes(self):
        a=Image.new('RGBA',(32,32));a.paste((180,50,50,255),(8,4,24,28))
        self.assertEqual(compare(a,a,64),{'silhouette_iou':1,'rgb_mae':0})
        b=a.copy();b.paste((20,180,20,255),(8,4,24,28))
        self.assertGreater(compare(a,b,64)['rgb_mae'],0)
        b=Image.new('RGBA',(32,32));b.paste((180,50,50,255),(12,4,28,28))
        self.assertLess(compare(a,b,64)['silhouette_iou'],1)

    def test_adoption_preserves_original_and_rejects_changed_candidate(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);ws=root/'workspaces/hero';models=ws/'models';models.mkdir(parents=True)
            (models/'hero.obj').write_text('original')
            parent=models/'prepared/base';parent.mkdir(parents=True)
            atomic(parent/'prepare.json',{'source_sha256':digest(models/'hero.obj')})
            folder=models/'optimizations/experiment';candidate=folder/'30000';candidate.mkdir(parents=True)
            for name in ('preview.glb','mixamo.zip','model.obj','albedo.png'): (candidate/name).write_bytes(b'candidate')
            atomic(candidate/'prepare.json',{'source_sha256':digest(models/'hero.obj'),'triangles_after':30000})
            report={'source_sha256':digest(models/'hero.obj'),'source_prepared':'base','source_fingerprint':digest(parent/'prepare.json'),'variants':[{'id':'30000','triangles':30000,'artifacts':{n:digest(candidate/n) for n in ('preview.glb','mixamo.zip','model.obj','albedo.png','prepare.json')}}]}
            atomic(folder/'report.json',report)
            panel=Panel(root)
            self.assertEqual(panel.character('hero')['prepared']['id'],'base')
            clean=panel.validate_task('hero','adopt_model',{'experiment':'experiment','variant':'30000'})
            self.assertEqual(clean['variant'],'30000')
            result=activate(root,'hero','experiment','30000')
            self.assertNotEqual(result,parent)
            self.assertEqual((models/'hero.obj').read_text(),'original')
            self.assertEqual(panel.character('hero')['prepared']['id'],result.name)
            self.assertFalse(panel.character('hero')['rig']['ready'])
            self.assertFalse(panel.character('hero')['model_approved'])
            (candidate/'preview.glb').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'候选文件已变化'):activate(root,'hero','experiment','30000')
            with self.assertRaises(ValueError):panel.validate_task('hero','adopt_model',{'experiment':'experiment','variant':'../30000'})
            (models/'hero.obj').write_text('new model')
            with self.assertRaisesRegex(ValueError,'人物模型已变化'):activate(root,'hero','experiment','30000')
