"""Adoption is persistent, versioned and verified independently of candidate generation."""
import io
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from PIL import Image
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from action_set import save, load, inspect, export


class ActionSetTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        (self.root/'workspaces/hero').mkdir(parents=True)
        self.folder = self.root/'deliverables/hero/first'; self.folder.mkdir(parents=True)
        self.manifest = {'source':{'character':'hero'}, 'renderer':'godot'}
        for role, size in [('walk',32), ('attack',40)]:
            Image.new('RGBA',(size*2,size),'red').save(self.folder/(role+'_spritesheet.png'))
            self.manifest[role+'_spritesheet.png'] = {'frame_width':size,'frame_height':size,'frame_count':2,'duration_seconds':.3,'frame_durations_seconds':[.1,.2], 'body_height_px':96, 'view':'front','anchor_px':[size/2,size-2], 'projection':{'reference_sha256':'rig','pixels_per_source_unit':96}, 'quality':{'status':'passed','loop':{'status':'passed'}}}
        self.write()
        self.draft = {'title':'Combat', 'actions':{'walk':{'delivery':'first','clip':'walk','variant':'source','loop':True},'attack':{'delivery':'first','clip':'attack','variant':'source','loop':False}}}

    def write(self): (self.folder/'manifest.json').write_text(json.dumps(self.manifest))

    def test_save_reload_partial_and_revision_conflicts(self):
        self.draft['actions']['idle'] = {'loop':True}
        result = save(self.root,'hero',self.draft)
        self.assertFalse(result['validation']['complete'])
        self.assertEqual(load(self.root,'hero')['actions']['walk']['clip'],'walk')
        with self.assertRaisesRegex(ValueError,'其他页面'): save(self.root,'hero',self.draft)
        with self.assertRaisesRegex(ValueError,'尚不能交付'): export(self.root,'hero')

    def test_generic_actions_mixed_canvas_and_exact_loop_timing_export(self):
        result = save(self.root,'hero',self.draft)
        self.assertTrue(result['validation']['complete'])
        archive = zipfile.ZipFile(io.BytesIO(export(self.root,'hero')))
        base = 'character_assets/hero/'
        report = json.loads(archive.read(base+'manifest.json'))
        self.assertEqual(set(report['actions']), {'walk','attack'})
        self.assertTrue(report['actions']['walk']['loop']); self.assertFalse(report['actions']['attack']['loop'])
        self.assertEqual(report['actions']['attack']['frame_durations_seconds'], [.1,.2])
        self.assertIn('action_set.json', [Path(p).name for p in archive.namelist()])
        self.assertIn('play_action("walk")', archive.read(base+'character.gd').decode())
        self.assertIn('["walk", "attack"]', archive.read(base+'preview.gd').decode())
        self.assertNotIn('animation = &"idle"', archive.read(base+'character.tscn').decode())

    def test_new_candidate_does_not_replace_adopted_and_mutation_blocks_export(self):
        saved = save(self.root,'hero',self.draft)['recipe']
        (self.root/'deliverables/hero/new').mkdir()
        self.assertEqual(load(self.root,'hero'), saved)
        Image.new('RGBA',(64,32),'blue').save(self.folder/'walk_spritesheet.png')
        self.assertFalse(inspect(self.root,'hero')['complete'])
        with self.assertRaisesRegex(ValueError,'来源已变化'): export(self.root,'hero')

    def test_incompatible_body_density_and_palette_block_whole_set(self):
        self.manifest['attack_spritesheet.png']['body_height_px'] = 128; self.write()
        result = save(self.root,'hero',self.draft)
        self.assertFalse(result['validation']['complete'])
        self.assertTrue(any('不一致' in e for e in result['validation']['errors']))
        self.manifest['attack_spritesheet.png']['body_height_px'] = 96; self.write()
        other = self.root/'deliverables/hero/colored'; other.mkdir()
        import shutil
        shutil.copy(self.folder/'attack_spritesheet.png',other/'attack_spritesheet.png')
        (other/'manifest.json').write_text(json.dumps({**self.manifest,'color_processing':{'colors':32}}))
        (other/'palette.json').write_text(json.dumps({'rgb':[[255,0,0]]}))
        self.draft['revision'] = result['recipe']['revision']
        self.draft['actions']['attack']['delivery'] = 'colored'
        self.assertTrue(any('配色不一致' in e for e in save(self.root,'hero',self.draft)['validation']['errors']))

    def test_changed_loop_invalidates_review_and_paths_are_scoped(self):
        self.draft['actions']['walk']['reviewed'] = True
        recipe = save(self.root,'hero',self.draft)['recipe']
        recipe['actions']['walk']['loop'] = False
        result = save(self.root,'hero',recipe)
        self.assertFalse(result['recipe']['actions']['walk']['reviewed'])
        recipe['actions']['walk']['delivery'] = '../outside'
        recipe['revision'] = result['recipe']['revision']
        with self.assertRaises(ValueError): save(self.root,'hero',recipe)
