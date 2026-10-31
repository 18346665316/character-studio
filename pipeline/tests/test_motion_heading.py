"""Calibration follows source identity and rejects invalid manual values."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from motion_heading import records, save, stage


class HeadingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)

    def test_source_hash_reuses_calibration_across_batches_and_names(self):
        save(self.root,'hero','a'*64,{'degrees':-35,'status':'confirmed'})
        result=records(self.root,'hero',{'run.fbx':'a'*64,'clip_renamed.fbx':'a'*64,'changed.fbx':'b'*64})
        self.assertEqual(set(result),{'run.fbx','clip_renamed.fbx'})
        self.assertEqual(result['run.fbx']['degrees'],-35)
        self.assertEqual(records(self.root,'other',{'run.fbx':'a'*64}),{})

    def test_invalid_angles_rejected(self):
        for value in [True,'35',float('nan'),float('inf'),181,-181]:
            with self.assertRaises(ValueError):save(self.root,'hero','a'*64,{'degrees':value})

    def test_estimate_only_missing_and_keep_confirmation(self):
        import shutil
        shutil.copytree(Path(__file__).resolve().parents[1]/'heading',self.root/'pipeline/heading')
        project=self.root/'project';project.mkdir();job=self.root/'job';job.mkdir()
        save(self.root,'hero','a'*64,{'degrees':17,'status':'confirmed'})
        def estimate(*args,**kwargs):
            request=json.loads((project/'heading_request.json').read_text())
            self.assertEqual(request['files'],{'walk.fbx':'b'*64})
            (project/'heading_estimates.json').write_text(json.dumps({'walk.fbx':{'degrees':2,'status':'automatic'}}))
        with patch('motion_heading.subprocess.run',side_effect=estimate) as run:
            value=stage(self.root,'hero',project,{'run.fbx':'a'*64,'walk.fbx':'b'*64},'res://assets','godot',job)
            self.assertEqual(value['run.fbx']['degrees'],17)
            self.assertEqual(value['walk.fbx']['degrees'],0)
            self.assertEqual(value['walk.fbx']['estimated_degrees'],2)
            self.assertEqual(json.loads((project/'heading.json').read_text()),value)
            stage(self.root,'hero',project,{'run.fbx':'a'*64,'walk.fbx':'b'*64},'res://assets','godot',job)
            self.assertEqual(run.call_count,1)

    def test_legacy_automatic_record_does_not_apply(self):
        directory=self.root/'workspaces/hero/motion_heading'
        directory.mkdir(parents=True)
        (directory/('a'*64+'.json')).write_text(json.dumps({'source_sha256':'a'*64,'degrees':-35,'status':'automatic'}))
        value=records(self.root,'hero',{'run.fbx':'a'*64})['run.fbx']
        self.assertEqual(value['degrees'],0)
        self.assertEqual(value['estimated_degrees'],-35)
        self.assertEqual(value['status'],'suggested')

    def test_uncertain_estimate_is_advisory_and_confirmation_applies(self):
        value=save(self.root,'hero','b'*64,{'degrees':45,'status':'needs_review'})
        self.assertEqual(value['degrees'],0)
        self.assertEqual(value['estimated_degrees'],45)
        value=save(self.root,'hero','b'*64,{**value,'degrees':12,'status':'confirmed'})
        self.assertEqual(records(self.root,'hero',{'turn.fbx':'b'*64})['turn.fbx']['degrees'],12)
