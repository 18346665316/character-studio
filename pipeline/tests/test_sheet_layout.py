"""Grid padding, pixel processing, GIF timing and batch QA regression."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
import numpy as np
from PIL import Image,ImageDraw
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sheet_layout import layout,tiles,blank
from pixel_finish import finish_batch
from studio_core import validate_sheet,make_preview
from blender_backend import assemble


class SheetLayoutTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)

    def sheet(self,count=298,size=64):
        image,cols,rows=blank(size,count)
        for i in range(count):
            tile=Image.new('RGBA',(size,size));d=ImageDraw.Draw(tile)
            d.rectangle((15+i%8,8,40+i%8,size-8),fill=(180,45+i%100,55,255));image.paste(tile,((i%cols)*size,(i//cols)*size))
        path=self.root/'long.png';image.save(path);return path

    def test_298_frames_keep_order_and_padding_is_not_a_frame(self):
        path=self.sheet();image=Image.open(path)
        self.assertEqual(image.size,(1024,1216));self.assertEqual(layout(image,64,298)['rows'],19)
        self.assertEqual(len(list(tiles(image,64,298))),298)
        with self.assertRaises(ValueError):layout(image,64)
        meta=validate_sheet(path,64,298)
        self.assertEqual(meta['frame_count'],298);self.assertEqual(meta['quality']['status'],'passed')
        self.assertIsNone(image.crop((10*64,18*64,11*64,19*64)).getbbox())

    def test_pixel_finish_keeps_grid_and_gif_preserves_duration(self):
        path=self.sheet(33,64)
        finish_batch([path],frame_size=32,layouts={path.name:{'frame_width':64,'frame_count':33}})
        image=Image.open(path);self.assertEqual(image.size,(512,96))
        meta=validate_sheet(path,32,33);self.assertEqual(meta['frame_count'],33)
        self.assertIsNone(image.crop((32,64,64,96)).getbbox())
        gif=self.root/'long.gif';make_preview(path,gif,1.1,32,33)
        with Image.open(gif) as im:
            durations=[]
            for i in range(im.n_frames):im.seek(i);durations.append(im.info['duration'])
            self.assertEqual(im.n_frames,33);self.assertAlmostEqual(sum(durations),1100,delta=10)

    def test_bad_real_frame_fails_but_padding_is_allowed(self):
        path=self.sheet(17);im=Image.open(path);im.paste((0,0,0,0),(0,64,64,128));im.save(path)
        with self.assertRaisesRegex(ValueError,'第 17 帧'):validate_sheet(path,64,17)

    def test_small_character_flags_review_instead_of_silent_rescale(self):
        path=self.sheet(9)
        # Nine small, individually valid colored poses.
        im=Image.new('RGBA',(576,64));d=ImageDraw.Draw(im)
        for i in range(9):d.rectangle((i*64+20+i%3,28,i*64+30+i%3,38),fill='red')
        im.save(path)
        with self.assertRaisesRegex(ValueError,'过小'):validate_sheet(path,64,9)
        result=validate_sheet(path,64,9,allow_small=True)
        self.assertEqual(result['quality']['status'],'review');self.assertEqual(result['quality']['warnings'][0]['code'],'small_character')

    def test_loop_difference_is_separate_from_delivery_status(self):
        path=self.sheet(2);im=Image.open(path);tile=Image.new('RGBA',(64,64));ImageDraw.Draw(tile).rectangle((42,8,54,56),fill='red');im.paste(tile,(64,0));im.save(path)
        result=validate_sheet(path,64,2)
        self.assertEqual(result['quality']['loop']['status'],'review')
        self.assertNotEqual(result['quality']['status'],'failed')

    def test_blender_assembly_accepts_more_than_120_frames(self):
        count=121;clip={'name':'idle','frame_count':count,'duration_seconds':count/30}
        (self.root/'clips.json').write_text(json.dumps([clip]));(self.root/'idle_render.json').write_text(json.dumps({**clip,'renderer':'blender'}))
        for i in range(count):Image.new('RGBA',(8,8),(i,50,80,255)).save(self.root/f'idle_{i:03d}.png')
        assemble(self.root,self.root,self.root,8)
        image=Image.open(self.root/'idle_spritesheet.png');self.assertEqual(image.size,(128,64));self.assertEqual(list(tiles(image,8,count))[-1].getpixel((0,0)),(120,50,80,255))
        self.assertEqual(json.loads((self.root/'idle_render.json').read_text())['rows'],8)


if __name__=='__main__':unittest.main()
