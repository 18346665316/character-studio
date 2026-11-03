"""Current-action updates replace output, preserve raw input and keep consumers valid."""
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from asset_repository import atomic, read
from task_lock import task_lock
from panel import Panel
from panel_worker import execute
from current_delivery import publish
from action_set import save, inspect, export


class CurrentDeliveryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        (self.root/'workspaces/hero').mkdir(parents=True)
        self.source = self.root/'deliverables/hero/raw'
        self.source.mkdir(parents=True)
        image = Image.new('RGBA', (64*12, 64))
        draw = ImageDraw.Draw(image)
        for i in range(12):
            draw.rectangle((i*64+12+i, 8, i*64+30+i, 55), fill=(120+i, 70, 30, 255))
        image.save(self.source/'walk_spritesheet.png')
        atomic(self.source/'manifest.json', {
            'source': {'character': 'hero', 'batch': 'original'}, 'renderer': 'godot',
            'walk_spritesheet.png': {'frame_width': 64, 'frame_height': 64, 'frame_count': 12,
                'duration_seconds': .4, 'columns': 12, 'rows': 1, 'body_height_px': 48,
                'view': 'three_quarter', 'anchor_px': [32, 58],
                'projection': {'reference_sha256': 'rig', 'pixels_per_source_unit': 48}}})
        self.raw_bytes = {p.name: p.read_bytes() for p in self.source.iterdir()}
        for target in ('studio_core.BASE_DIR', 'progress.BASE_DIR'):
            patcher = patch(target, self.root)
            patcher.start()
            self.addCleanup(patcher.stop)

    def edit(self, action, **params):
        pinned = Panel(self.root).validate_task('hero', action, params)
        job = {'character': 'hero', 'action': action, 'params': pinned, 'outputs': {}}
        with task_lock(self.root):
            execute(job, lambda: None)
        return Path(job['outputs']['delivery'])

    def test_repeated_color_and_frame_changes_keep_only_raw_and_current(self):
        first = self.edit('palette', delivery='raw', clips=['walk'], colors=32, profile='compact')
        current = self.edit('compact', delivery=first.name, clips=['walk'], profile='smooth')
        self.assertEqual(first, current)
        self.assertTrue((current/'palette.json').is_file())
        self.assertTrue((current/'comparison/walk_spritesheet.png').is_file())
        info=read(current/'manifest.json')['walk_spritesheet.png']
        for field in ('frame_count','source_frame_indices','frame_durations_seconds'):
            self.assertEqual(info['game'][field],info['color_comparison'][field])
        for colors in (64, 128, 0, 32):
            result = self.edit('palette', delivery='raw', timing_delivery=current.name,
                clips=['walk'], colors=colors, preserve_timing=True)
            self.assertEqual(result, current)
        self.assertEqual({p.name for p in self.source.parent.iterdir()}, {'raw', current.name})
        self.assertEqual(self.raw_bytes, {p.name: p.read_bytes() for p in self.source.iterdir()})
        self.assertEqual(read(current/'manifest.json')['operation'], {'source_delivery': 'raw'})
        self.assertFalse(list((self.root/'.local/jobs').glob('*')))
        self.assertFalse(list((self.root/'palettes').glob('*/palette.json')))
        with zipfile.ZipFile(io.BytesIO(Panel(self.root).export('hero',current.name,'walk','game'))) as package:
            self.assertIn('walk_spritesheet.png', package.namelist())

    def test_adopted_current_action_follows_edits_and_exports(self):
        current = self.edit('compact', delivery='raw', clips=['walk'], profile='compact')
        recipe = save(self.root, 'hero', {'actions': {'walk': {
            'delivery': current.name, 'clip': 'walk', 'variant': 'game', 'loop': True}}})['recipe']
        before = recipe['actions']['walk']['fingerprint']
        self.edit('palette', delivery='raw', timing_delivery=current.name,
            clips=['walk'], colors=32, preserve_timing=True)
        self.assertTrue(inspect(self.root, 'hero')['complete'])
        updated = read(self.root/'workspaces/hero/action_set.json')
        self.assertNotEqual(before, updated['actions']['walk']['fingerprint'])
        self.assertEqual(updated['actions']['walk']['delivery'], current.name)
        self.assertTrue(export(self.root, 'hero'))

    def test_legacy_adopted_action_updates_without_reselecting(self):
        save(self.root, 'hero', {'actions': {'walk': {
            'delivery': 'raw', 'clip': 'walk', 'variant': 'source', 'loop': True}}})
        current = self.edit('compact', delivery='raw', clips=['walk'], profile='compact')
        self.assertEqual(read(self.root/'workspaces/hero/action_set.json')['actions']['walk']['delivery'], current.name)
        self.assertTrue(inspect(self.root, 'hero')['complete'])

    def test_failed_replace_restores_current_and_recipe(self):
        current = self.edit('compact', delivery='raw', clips=['walk'], profile='compact')
        save(self.root, 'hero', {'actions': {'walk': {
            'delivery': current.name, 'clip': 'walk', 'variant': 'game', 'loop': True}}})
        before = {str(p.relative_to(current)): p.read_bytes() for p in current.rglob('*') if p.is_file()}
        recipe_before = (self.root/'workspaces/hero/action_set.json').read_bytes()
        with patch('action_set.save', side_effect=OSError('write failed')):
            with self.assertRaisesRegex(OSError, 'write failed'):
                self.edit('compact', delivery=current.name, clips=['walk'], profile='smooth')
        self.assertEqual(before, {str(p.relative_to(current)): p.read_bytes() for p in current.rglob('*') if p.is_file()})
        self.assertEqual(recipe_before, (self.root/'workspaces/hero/action_set.json').read_bytes())
        self.assertTrue(inspect(self.root, 'hero')['complete'])

    def test_legacy_dependency_is_kept_but_unused_edits_are_removed(self):
        import shutil
        legacy = self.source.parent/'old-edit';shutil.copytree(self.source, legacy)
        data = read(legacy/'manifest.json');data['operation']={'source_delivery':'raw'};atomic(legacy/'manifest.json',data)
        other = self.source.parent/'other-action';shutil.copytree(legacy, other)
        data['operation']={'source_delivery':'old-edit'}
        data['idle_spritesheet.png']=data.pop('walk_spritesheet.png');atomic(other/'manifest.json',data)
        self.edit('compact', delivery='raw', clips=['walk'], profile='compact')
        self.assertTrue(legacy.is_dir())
        shutil.rmtree(other)
        self.edit('compact', delivery='raw', clips=['walk'], profile='smooth')
        self.assertFalse(legacy.exists())

    def test_saved_sequence_keeps_its_source_edit(self):
        import shutil
        legacy=self.source.parent/'sequence-input';shutil.copytree(self.source,legacy)
        data=read(legacy/'manifest.json');data['operation']={'source_delivery':'raw'};atomic(legacy/'manifest.json',data)
        atomic(self.root/'workspaces/hero/sequence.json',{'segments':[{'delivery':'sequence-input','clip':'walk'}]})
        self.edit('compact',delivery='raw',clips=['walk'],profile='compact')
        self.assertTrue(legacy.is_dir())
