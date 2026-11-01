"""Validate corner topology, cross-variant seams, and preserved pure materials."""
from pathlib import Path
import sys
import unittest
import numpy as np
from PIL import Image

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from terrain import material_variants
from terrain_transition import mask,validate_edges,example_vertices,render,shoreline_tile,pond_vertices


class TransitionTests(unittest.TestCase):
    def test_all_corner_combinations_are_binary_at_vertices(self):
        ground=Image.new('RGB',(64,64),'green')
        for bits in range(16):
            a=np.array(mask(64,bits,ground,3))
            for bit,pixel in [(1,a[0,0]),(2,a[0,-1]),(4,a[-1,-1]),(8,a[-1,0])]:
                self.assertEqual(int(pixel),255 if bits&bit else 0)
            if bits in (0,15):
                self.assertTrue(np.all(a==(255 if bits==15 else 0)))

    def test_arbitrary_images_and_every_legal_pair_across_variants(self):
        rng=np.random.default_rng(9)
        a=Image.fromarray(rng.integers(0,256,(173,211,3),dtype='uint8'))
        b=Image.fromarray(rng.integers(0,256,(201,177,3),dtype='uint8'))
        for size in (32,64,128):
            grass,sand=material_variants(a,size),material_variants(b,size)
            tiles=[[Image.composite(sand[v],grass[v],mask(size,bits,grass[v],v))
                    for bits in range(16)] for v in range(4)]
            report=validate_edges(tiles)
            self.assertTrue(report['passed'])
            self.assertEqual(report['matching_edge_pairs'],2048)
            self.assertEqual(report['max_channel_difference'],0)
            for v in range(4):
                self.assertTrue(np.array_equal(np.array(tiles[v][0]),np.array(grass[v])))
                self.assertTrue(np.array_equal(np.array(tiles[v][15]),np.array(sand[v])))
            preview=render(tiles,example_vertices(),size)
            self.assertEqual(preview.size,(16*size,10*size))

    def test_diagonal_ambiguity_has_consistent_sand_connection(self):
        grass=Image.new('RGB',(65,65),'green')
        for bits in (5,10):
            for variant in range(4):
                self.assertGreater(int(np.array(mask(65,bits,grass,variant))[32,32]),200)

    def test_water_banks_preserve_sources_and_every_cross_variant_edge(self):
        rng=np.random.default_rng(19)
        source=[Image.fromarray(rng.integers(0,256,(300,300,3),dtype='uint8')) for _ in range(2)]
        for size in (32,64,128):
            land,water=[material_variants(image,size) for image in source]
            tiles=[[shoreline_tile(land[v],water[v],mask(size,bits,land[v],v))
                    for bits in range(16)] for v in range(4)]
            self.assertEqual(validate_edges(tiles),{'passed':True,'matching_edge_pairs':2048,'max_channel_difference':0})
            for v in range(4):
                np.testing.assert_array_equal(np.array(tiles[v][0]),np.array(land[v]))
                np.testing.assert_array_equal(np.array(tiles[v][15]),np.array(water[v]))
            self.assertEqual(render(tiles,pond_vertices(),size).size,(16*size,10*size))

    def test_shoreline_changes_the_boundary_but_preserves_water_and_land_endpoints(self):
        base=Image.new('RGB',(64,64),(90,130,60))
        water=Image.new('RGB',(64,64),(40,100,120))
        coverage=mask(64,3,base,0)
        plain=np.array(Image.composite(water,base,coverage))
        shore=np.array(shoreline_tile(base,water,coverage))
        a=np.array(coverage)
        np.testing.assert_array_equal(shore[a==0],plain[a==0])
        np.testing.assert_array_equal(shore[a==255],plain[a==255])
        self.assertTrue(np.any(shore[(a>0)&(a<255)]!=plain[(a>0)&(a<255)]))


if __name__=='__main__': unittest.main()
