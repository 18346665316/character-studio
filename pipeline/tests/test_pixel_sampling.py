import sys
import tempfile
import unittest
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw
from scipy.ndimage import binary_dilation
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pixel_finish import finish_batch

class SamplingTests(unittest.TestCase):
    def test_outline_is_created_after_coverage_downsampling(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'sheet.png'
            source = Image.new('RGBA', (512,256))
            draw = ImageDraw.Draw(source)
            draw.rectangle((81,45,169,221),fill=(60,140,80,255))
            draw.rectangle((337,45,425,221),fill=(60,140,80,255))
            source.save(path)
            meta = finish_batch([path],frame_size=64)
            result = np.array(Image.open(path))
            self.assertEqual(result.shape,(64,128,4))
            mask = np.array(source.crop((0,0,256,256)).resize((64,64),Image.Resampling.BOX))[:,:,3]>=128
            outline = np.all(result[:,:64]==(25,29,32,255),axis=2)
            np.testing.assert_array_equal(outline,binary_dilation(mask)&~mask)
            np.testing.assert_array_equal(result[:,:64],result[:,64:])
            self.assertEqual(meta['outline_stage'],'after_resize')
