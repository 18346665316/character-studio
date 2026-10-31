import json
import sys
import tempfile
from pathlib import Path
import unittest
from PIL import Image,ImageDraw
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from compact_frames import compact,error,POLICY,write_spriteframes
from sheet_layout import blank,tiles
from studio_core import make_preview


class CompactFrames(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)

    def build(self,positions,colors=None):
        sheet,cols,_=blank(64,len(positions))
        for i,x in enumerate(positions):
            tile=Image.new('RGBA',(64,64));d=ImageDraw.Draw(tile)
            d.rectangle((x,8,x+16,56),fill=(colors[i] if colors else (120,50,40,255)))
            sheet.paste(tile,(i%cols*64,i//cols*64))
        path=self.root/'source.png';sheet.save(path)
        return path,{'frame_width':64,'frame_height':64,'frame_count':len(positions),'duration_seconds':len(positions)/30,'fps':30}

    def test_hold_reduces_frames_keeps_exact_duration_and_endpoints(self):
        path,t=self.build([20]*120)
        r=compact(path,self.root/'game.png',t)
        self.assertLess(r['frame_count'],30)
        self.assertEqual(r['source_frame_indices'][0],0);self.assertEqual(r['source_frame_indices'][-1],119)
        self.assertAlmostEqual(sum(r['frame_durations_seconds']),4)
        self.assertLessEqual(max(r['frame_durations_seconds']),POLICY['max_hold_seconds']+1e-8)

    def test_motion_peak_and_protected_equipment_boundary_are_not_lost(self):
        path,t=self.build([20]*20+[40]+[20]*39)
        r=compact(path,self.root/'game.png',t,protected=[10,11])
        self.assertTrue({10,11,20,21}.issubset(r['source_frame_indices']))

    def test_compare_to_held_frame_and_check_every_discarded_frame(self):
        path,t=self.build([20+i//6 for i in range(60)])
        r=compact(path,self.root/'game.png',t)
        with Image.open(path) as im:frames=list(tiles(im,64,60))
        limits=(POLICY['silhouette_error'],POLICY['color_error'],POLICY['local_error'])
        starts=r['source_frame_indices'];ends=starts[1:]+[60]
        for a,b in zip(starts,ends):
            for i in range(a,b):self.assertTrue(all(e<=limit+1e-8 for e,limit in zip(error(frames[a],frames[i]),limits)))

    def test_local_detail_and_texture_change_are_preserved(self):
        path,t=self.build([20]*30,[(120,50,40,255)]*15+[(40,50,160,255)]*15)
        im=Image.open(path);ImageDraw.Draw(im).rectangle((3*64+50,20,3*64+53,23),fill='white');im.save(path)
        r=compact(path,self.root/'game.png',t)
        self.assertTrue({3,4,15}.issubset(r['source_frame_indices']))

    def test_variable_gif_and_godot_resource_carry_frame_durations(self):
        path,t=self.build([20]*15+[30]*15+[20]*30)
        r=compact(path,self.root/'game.png',t)
        make_preview(self.root/'game.png',self.root/'game.gif',2,64,r['frame_count'],r['frame_durations_seconds'])
        with Image.open(self.root/'game.gif') as gif:
            total=0
            for i in range(gif.n_frames):gif.seek(i);total+=gif.info['duration']
        self.assertAlmostEqual(total,2000,delta=10)
        write_spriteframes(self.root/'game.tres','game.png',r)
        resource=(self.root/'game.tres').read_text()
        self.assertIn('"speed": 1.0',resource);self.assertIn('"loop": false',resource)
        self.assertEqual(resource.count('"duration":'),r['frame_count'])
        with self.assertRaisesRegex(ValueError,'时长'):make_preview(self.root/'game.png',self.root/'bad.gif',2,64,r['frame_count'],[1]*r['frame_count'])

if __name__=='__main__':unittest.main()
