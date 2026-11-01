import sys,tempfile,unittest
from pathlib import Path
import numpy as np
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from color_clustering import make_palette,apply_palette
class ColorClustering(unittest.TestCase):
    def test_shared_palette_deterministic_and_alpha_unchanged(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);rgba=np.zeros((8,16,4),dtype=np.uint8)
            rgba[:,:,:3]=np.arange(128*3).reshape(8,16,3)%256
            rgba[:,:,3]=np.arange(128).reshape(8,16)*2
            source=root/'source.png';Image.fromarray(rgba).save(source)
            meta={source.name:{'frame_width':8,'frame_count':2}}
            palette=make_palette([source],meta,32)
            self.assertTrue(np.array_equal(palette,make_palette([source],meta,32)))
            for name in ('a.png','b.png'):apply_palette(source,root/name,palette)
            a=np.array(Image.open(root/'a.png'));b=np.array(Image.open(root/'b.png'))
            self.assertTrue(np.array_equal(a,b));self.assertTrue(np.array_equal(a[:,:,3],rgba[:,:,3]))
            visible=a[a[:,:,3]>0,:3]
            self.assertLessEqual(len(np.unique(visible,axis=0)),32)
            for rgb in visible:self.assertTrue(np.any(np.all(palette==rgb,axis=1)))
