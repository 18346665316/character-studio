"""Exercise the real job/compiler flow with a simulated image transport."""
import base64
from io import BytesIO
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from asset_repository import read
from component_jobs import prepare, execute
from fence_components import load_package
from terrain_images import Provider


class ComponentJobsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        output=BytesIO();Image.new('RGB',(64,64),(133,92,45)).save(output,format='PNG')
        self.raw=output.getvalue()

    def prepare(self):
        with patch('component_jobs.configured',return_value=True):
            job=prepare(self.root,{'description':'warm painted timber','reference':base64.b64encode(self.raw).decode()})
        return job,self.root/'.local/components/jobs'/job['id']

    def test_success_receipts_reference_and_reentry_are_idempotent(self):
        job,folder=self.prepare()
        with patch.object(Provider,'__init__',lambda obj,*args:setattr(obj,'base','mock://images')), \
             patch.object(Provider,'create',return_value={'data':[{'b64_json':base64.b64encode(self.raw).decode()}]}) as create:
            execute(self.root,job['id']);execute(self.root,job['id'])
        self.assertEqual(create.call_count,1)
        self.assertIn('vertical wood grain',create.call_args.args[0])
        self.assertEqual(len(create.call_args.args[1]),1)
        self.assertEqual(read(folder/'job.json')['status'],'complete')
        load_package(self.root,job['id'])
        package=self.root/'component-kits'/job['id']
        manifest=read(package/'manifest.json')
        self.assertEqual(manifest['art_source'],'ai_wood_texture_program_geometry')
        self.assertNotIn('ai_calls',manifest)
        self.assertTrue((package/'inputs/reference.png').exists())
        self.assertEqual(read(package/'generation.json')['ground']['sha256'],read(folder/'generation.json')['ground']['sha256'])

    def test_failed_remote_stops_then_explicit_continuation_resubmits(self):
        job,folder=self.prepare()
        with patch.object(Provider,'__init__',lambda obj,*args:setattr(obj,'base','mock://images')), \
             patch.object(Provider,'create',return_value={'id':'failed-image'}) as create, \
             patch.object(Provider,'request',return_value={'status':'failed'}) as request:
            execute(self.root,job['id'])
            self.assertEqual(request.call_count,1)
            self.assertEqual(read(folder/'job.json')['status'],'failed')
            execute(self.root,job['id'])
            self.assertEqual(create.call_count,2)
        self.assertEqual(len(read(folder/'generation.json')['ground']['failed_attempts']),1)

    def test_compile_failure_reuses_successful_texture(self):
        job,folder=self.prepare()
        with patch.object(Provider,'__init__',lambda obj,*args:setattr(obj,'base','mock://images')), \
             patch.object(Provider,'create',return_value={'data':[{'b64_json':base64.b64encode(self.raw).decode()}]}) as create:
            with patch('component_jobs.build',side_effect=ValueError('compile failed')):
                execute(self.root,job['id'])
            self.assertEqual(read(folder/'job.json')['status'],'failed')
            execute(self.root,job['id'])
            self.assertEqual(create.call_count,1)
        self.assertEqual(read(folder/'job.json')['status'],'complete')
