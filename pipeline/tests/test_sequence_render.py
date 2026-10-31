"""Arrangements share one source cohort and pin rig/animation/equipment versions."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from panel import Panel,atomic
from sequence_render import make_plan,render
import studio_core as studio


class SequenceRenderTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.panel=Panel(self.root)
        (self.root/'workspaces/hero').mkdir(parents=True)
        self.c={'rig':{'ready':True},'deliveries':[]}
        atomic(self.root/'.local/mixamo/hero/state.json',{'bound_sha256':'rig-one'})
        for i in range(2):
            directory=self.root/'workspaces/hero/animations'/f'b{i}';directory.mkdir(parents=True)
            source=directory/'attack.fbx';source.write_bytes(f'pose-{i}'.encode());sha=self.panel.digest(source)
            atomic(directory/'batch.json',{'character':'hero','batch':f'b{i}','rig_sha256':'rig-one','files':{'attack.fbx':sha}})
            atomic(self.root/f'deliverables/hero/d{i}/manifest.json',{'source':{'files':{'attack.fbx':sha}}})
            self.c['deliveries'].append({'id':f'd{i}','batch':f'b{i}','clips':[{'name':'attack'}]})
        self.recipe={'sources':['d1/attack','d0/attack','d1/attack'],'renderer':'godot','view':'front','frame_size':128,'supersample':4,'equipment_id':None}
        self.mock=patch.object(Panel,'character',return_value=self.c);self.mock.start();self.addCleanup(self.mock.stop)
        self.patch=patch.object(studio,'BASE_DIR',self.root);self.patch.start();self.addCleanup(self.patch.stop)

    def test_same_named_actions_are_pinned_without_collision(self):
        plan=make_plan(self.panel,'hero',self.recipe)
        self.assertEqual(plan['recipe']['sources'],['d0/attack','d1/attack'])
        self.assertEqual(len(set(s['target'] for s in plan['sources'])),2)
        (self.root/'workspaces/hero/animations/b0/attack.fbx').write_bytes(b'changed')
        with self.assertRaises(ValueError):make_plan(self.panel,'hero',self.recipe)

    def test_different_rigs_and_invalid_sources_rejected(self):
        path=self.root/'workspaces/hero/animations/b0/batch.json'
        data=json.loads(path.read_text());data['rig_sha256']='different';atomic(path,data)
        with self.assertRaises(ValueError):make_plan(self.panel,'hero',self.recipe)
        for extra in ({'sources':['missing/attack']},{'frame_size':True},{'renderer':'other'}):
            with self.assertRaises(ValueError):make_plan(self.panel,'hero',{**self.recipe,**extra})

    def test_render_collects_sources_in_one_bake_and_keeps_camera(self):
        plan=make_plan(self.panel,'hero',self.recipe)
        camera={'size':2.5,'center':[0,1,0],'view':'front'}
        def bake(character,batch,view,size,ss,equipment,renderer,pin):
            directory=self.root/'workspaces/hero/animations'/batch
            receipt=json.loads((directory/'batch.json').read_text())
            self.assertEqual(receipt['kind'],'sequence');self.assertEqual(len(receipt['files']),2)
            self.assertEqual({p.read_bytes() for p in directory.glob('*.fbx')},{b'pose-0',b'pose-1'})
            self.assertEqual((view,size,ss,renderer),('front',128,4,'godot'))
            output=self.root/'deliverables/hero/unified';output.mkdir(parents=True)
            atomic(output/'manifest.json',{Path(f).stem+'_spritesheet.png':{'camera':camera} for f in receipt['files']})
            return output
        with patch.object(studio,'bake',side_effect=bake),patch.object(studio,'progress_update'):
            record=render(self.root,'hero',plan)
        self.assertEqual(record['camera'],camera);self.assertEqual(len(record['clips']),2)
        self.assertTrue((self.root/'workspaces/hero/sequence_preview.json').is_file())

    def test_retry_rejects_changed_source_before_any_bake(self):
        plan=make_plan(self.panel,'hero',self.recipe)
        (self.root/'workspaces/hero/animations/b0/attack.fbx').write_bytes(b'new')
        with patch.object(studio,'bake') as bake,self.assertRaises(ValueError):render(self.root,'hero',plan)
        bake.assert_not_called()


if __name__=='__main__':unittest.main()
