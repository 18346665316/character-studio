"""Independent compression must work without model/FBX and preserve provenance."""
import sys,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image,ImageDraw
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from panel import Panel,atomic
from compact_delivery import plan,run


class CompactDelivery(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.source=self.root/'deliverables/hero/old';self.source.mkdir(parents=True)
        (self.root/'workspaces/hero').mkdir(parents=True)
        self.data={'source':{'character':'hero','batch':'b1','files':{'idle.fbx':'hash'}},'renderer':'godot','pixel_style':{'frame_size':64}}
        for name in ['idle','walk']:
            im=Image.new('RGBA',(640,64));d=ImageDraw.Draw(im)
            for i in range(10):d.rectangle((i*64+20+i//5,8,i*64+40+i//5,55),fill='red')
            im.save(self.source/(name+'_spritesheet.png'))
            self.data[name+'_spritesheet.png']={'frame_width':64,'frame_height':64,'frame_count':10,'fps':30,'duration_seconds':10/30,'columns':10,'rows':1}
        atomic(self.source/'manifest.json',self.data)

    def test_select_one_without_model_rig_or_renderer_and_keep_original(self):
        pinned=plan(self.root,'hero','old',['idle']);before={p.name:p.read_bytes() for p in self.source.iterdir()}
        with patch('progress.BASE_DIR',self.root),patch('studio_core.subprocess.run',side_effect=AssertionError('No renderer needed')):
            destination=run(self.root,'hero',pinned)
        self.assertNotEqual(destination,self.source)
        self.assertEqual(before,{p.name:p.read_bytes() for p in self.source.iterdir()})
        data=json.loads((destination/'manifest.json').read_text())
        self.assertEqual(data['operation']['source_delivery'],'old')
        self.assertIn('idle_spritesheet.png',data);self.assertNotIn('walk_spritesheet.png',data)
        self.assertTrue((destination/'game/idle.tres').is_file())
        self.assertAlmostEqual(sum(data['idle_spritesheet.png']['game']['frame_durations_seconds']),10/30)

    def test_batch_and_identity_and_changed_inputs(self):
        pinned=Panel(self.root).validate_task('hero','compact',{'delivery':'old','clips':['idle','walk']})
        with patch('progress.BASE_DIR',self.root):destination=run(self.root,'hero',pinned)
        self.assertEqual(len(list((destination/'game').glob('*.tres'))),2)
        with self.assertRaises((ValueError,OSError)):plan(self.root,'other','old',['idle'])
        with self.assertRaises(ValueError):plan(self.root,'hero','old',['../idle'])
        with self.assertRaises(ValueError):plan(self.root,'hero','old',['idle','idle'])
        (self.source/'idle_spritesheet.png').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'变化'):run(self.root,'hero',pinned)

if __name__=='__main__':unittest.main()
