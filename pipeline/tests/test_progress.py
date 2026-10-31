import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import progress


class Progress(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.patch=patch.object(progress,'BASE_DIR',Path(self.temp.name))
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def test_handoff_confirmation_is_not_completion(self):
        progress.update('hero','rig','等待关节点确认',status='waiting')
        progress.update('hero','rig','确认收到，开始文件验证')
        task=progress.read('hero')
        self.assertEqual(task['status'],'running')
        self.assertEqual([e['status'] for e in task['events']],['waiting','running'])
        progress.update('hero','download','正在下载 Running',action='Running')
        self.assertEqual(progress.read('hero')['action'],'Running')

    def test_direct_orchestrator_failure_records_actionable_job(self):
        @progress.track_failures
        def render(character):
            progress.update(character,'render','正在渲染',job='/tmp/test-job')
            raise RuntimeError('Renderer stopped')
        with self.assertRaises(RuntimeError):
            render('hero')
        task=progress.read('hero')
        self.assertEqual(task['status'],'failed')
        self.assertEqual(task['stage'],'render')
        self.assertEqual(task['job'],'/tmp/test-job')
        self.assertIn('Renderer stopped',task['message'])

    def test_role_progress_is_isolated(self):
        progress.update('hero','download','下载中')
        self.assertIsNone(progress.read('other'))
        with self.assertRaises(ValueError):
            progress.update('../other','download','bad')


if __name__=='__main__': unittest.main()
