import sys
from pathlib import Path
import unittest
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from prepare_model import rasterize_colors
from mixamo_state import check_mesh_identity


class TextureBake(unittest.TestCase):
    def test_uv_color_interpolation_and_vertical_orientation(self):
        uv = np.array([[0, 0], [1, 0], [0, 1]], dtype=float)
        rgb = np.array([[255, 0, 0, 255], [0, 255, 0, 255], [0, 0, 255, 255]])
        image, coverage = rasterize_colors(uv, np.array([[0, 1, 2]]), rgb, 32)
        pixels = np.array(image)
        np.testing.assert_array_equal(pixels[-1, 0], [255, 0, 0])
        np.testing.assert_array_equal(pixels[-1, -1], [0, 255, 0])
        np.testing.assert_array_equal(pixels[0, 0], [0, 0, 255])
        self.assertGreater(coverage, 0.45)
        self.assertLess(coverage, 0.6)
        self.assertGreater(pixels[21, 10].min(), 50)

    def test_missing_texture_rejected_after_cloud_roundtrip(self):
        reference = {'triangles': 100, 'textured_surfaces': 1}
        downloaded = {'triangles': 100, 'skeleton_bones': 33, 'skinned_meshes': 1, 'textured_surfaces': 0}
        with self.assertRaisesRegex(ValueError, '贴图'):
            check_mesh_identity(downloaded, reference)
        check_mesh_identity({**downloaded, 'textured_surfaces': 1}, reference)


if __name__ == '__main__':
    unittest.main()
