import sys,unittest,json,tempfile
from pathlib import Path
from unittest.mock import patch
from PIL import Image,ImageDraw
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from palette_delivery import plan,run,catalog
class PaletteDelivery(unittest.TestCase):
 def test_any_character_size_and_palette_reuse_original_immutable(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp)
   for hero in ('hero','other'):
    folder=root/'deliverables'/hero/'raw';folder.mkdir(parents=True)
    im=Image.new('RGBA',(64*4,64));draw=ImageDraw.Draw(im)
    for i in range(4):draw.rectangle((i*64+20+i*2,8,i*64+40+i*2,55),fill=(120,70,30,255))
    im.save(folder/'walk_spritesheet.png')
    (folder/'manifest.json').write_text(json.dumps({'source':{'character':hero},'walk_spritesheet.png':{'frame_width':64,'frame_height':64,'frame_count':4,'duration_seconds':.4,'columns':4,'rows':1}}))
   source=root/'deliverables/hero/raw/walk_spritesheet.png';before=source.read_bytes()
   with patch('progress.BASE_DIR',root):
    output=run(root,'hero',plan(root,'hero',{'delivery':'raw','clips':['walk'],'colors':64,'label':'warm','profile':'compact'}))
    palette=catalog(root)[0]
    reused=run(root,'other',plan(root,'other',{'delivery':'raw','clips':['walk'],'palette_id':palette['id']}))
   self.assertEqual(source.read_bytes(),before)
   self.assertEqual(json.loads((output/'palette.json').read_text()),json.loads((reused/'palette.json').read_text()))
   self.assertTrue((output/'game/walk.tres').is_file())
   info=json.loads((output/'manifest.json').read_text())['walk_spritesheet.png']
   self.assertEqual(info['game']['compression']['profile'],'compact')
   self.assertTrue(np.array_equal(np.array(Image.open(source))[:,:,3],np.array(Image.open(output/'walk_spritesheet.png'))[:,:,3]))
   with self.assertRaises(ValueError):plan(root,'hero',{'delivery':output.name,'clips':['walk']})
   with self.assertRaises(ValueError):plan(root,'hero',{'delivery':'raw','clips':['walk'],'colors':256})
 def test_color_only_keeps_explicit_frame_selection_and_comparison(self):
  from compact_delivery import plan as cp,run as cr
  # Reuse a realistic moving sheet, then deliberately choose a reduced timing source.
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);folder=root/'deliverables/hero/raw';folder.mkdir(parents=True)
   im=Image.new('RGBA',(64*12,64));draw=ImageDraw.Draw(im)
   for i in range(12):draw.rectangle((i*64+12+i,8,i*64+30+i,55),fill=(120+i,70,30,255))
   im.save(folder/'walk_spritesheet.png')
   original={'frame_width':64,'frame_height':64,'frame_count':12,'duration_seconds':.4,'columns':12,'rows':1}
   (folder/'manifest.json').write_text(json.dumps({'source':{'character':'hero'},'walk_spritesheet.png':original}))
   with patch('progress.BASE_DIR',root):
    reduced=cr(root,'hero',cp(root,'hero','raw',['walk'],'compact'))
    before=json.loads((reduced/'manifest.json').read_text())['walk_spritesheet.png']['game']
    params={'delivery':'raw','clips':['walk'],'colors':32,'timing_delivery':reduced.name,'preserve_timing':True,'profile':'compact'}
    with patch('studio_core.make_game_version',side_effect=AssertionError('Must not compact')):
     output=run(root,'hero',plan(root,'hero',params))
    result=json.loads((output/'manifest.json').read_text())['walk_spritesheet.png']
    for key in ('source_frame_indices','frame_durations_seconds','frame_count'):
     self.assertEqual(before[key],result['game'][key]);self.assertEqual(before[key],result['color_comparison'][key])
    self.assertEqual(original['frame_count'],result['frame_count'])
    restored=run(root,'hero',plan(root,'hero',{**params,'colors':0,'timing_delivery':output.name}))
    m=json.loads((restored/'manifest.json').read_text())
    self.assertIsNone(m['color_processing'])
    self.assertEqual(m['walk_spritesheet.png']['game']['source_frame_indices'],before['source_frame_indices'])
