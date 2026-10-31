"""Saved arrangements pin rendered assets and remain isolated per character."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from panel import Panel, atomic


class SequenceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.panel=Panel(self.root)
        (self.root/'workspaces/hero').mkdir(parents=True)
        (self.root/'workspaces/other').mkdir(parents=True)
        for n in range(14):
            d=self.root/'deliverables/hero'/f'render{n}'
            d.mkdir(parents=True)
            Image.new('RGBA',(32,16)).save(d/'idle_spritesheet.png')
            Image.new('RGB',(16,16)).save(d/'idle_preview.gif')
            atomic(d/'manifest.json',{'source':{'character':'hero','batch':'b1'},'idle_spritesheet.png':{'frame_count':2,'frame_width':16,'frame_height':16,'fps':12}})
        self.data={'character':'hero','title':'拔剑与攻击','loop':False,'segments':[{'delivery':'render0','clip':'idle','repeat':2,'speed':.5}]}

    def test_save_reload_preserves_exact_version_and_old_exports(self):
        self.panel.save_sequence(self.data)
        c=Panel(self.root).character('hero')
        self.assertEqual(c['sequence'],{k:v for k,v in self.data.items() if k!='character'})
        self.assertEqual(len(c['deliveries']),14)
        self.assertIsNone(self.panel.character('other')['sequence'])

    def test_foreign_missing_and_invalid_segments_cannot_replace_saved(self):
        self.panel.save_sequence(self.data)
        before=(self.root/'workspaces/hero/sequence.json').read_bytes()
        for edit in ({'delivery':'../render0'},{'clip':'missing'},{'repeat':0},{'repeat':True},{'repeat':21},{'speed':float('nan')},{'speed':5}):
            with self.subTest(edit=edit),self.assertRaises(ValueError):
                self.panel.save_sequence({**self.data,'segments':[{**self.data['segments'][0],**edit}]})
        with self.assertRaises(ValueError):self.panel.save_sequence({**self.data,'character':'other'})
        self.assertEqual((self.root/'workspaces/hero/sequence.json').read_bytes(),before)

    def test_limits_and_empty_arrangement(self):
        for patch in ({'segments':self.data['segments']*65},{'loop':'yes'},{'title':' '}):
            with self.assertRaises(ValueError):self.panel.save_sequence({**self.data,**patch})
        self.panel.save_sequence({**self.data,'segments':[]})
        self.assertEqual(self.panel.character('hero')['sequence']['segments'],[])

    def test_symlink_storage_is_rejected(self):
        (self.root/'workspaces/hero/sequence.json').symlink_to(self.root/'outside.json')
        with self.assertRaises(ValueError):self.panel.save_sequence(self.data)
        self.assertFalse((self.root/'outside.json').exists())


if __name__=='__main__':unittest.main()
