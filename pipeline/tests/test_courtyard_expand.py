from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from courtyard_ring import reference
from courtyard_expand import analyze,assemble,placements
from wall_assets import whole_cutout
from asset_repository import read
import static_props as props
from test_wall_repeat import provider_result


class CourtyardExpansionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source=whole_cutout(reference())
        cls.parts,cls.checks=analyze(cls.source)

    def test_same_four_corners_and_same_wall_images_expand_both_axes(self):
        lengths=self.checks['lengths'];before=[np.asarray(p['sprite']).copy() for p in self.parts]
        base,_=assemble(self.parts,lengths,(1,1))
        self.assertTrue(np.array_equal(np.asarray(base),np.asarray(self.source)))
        areas=[]
        for case in self.checks['cases']:
            layout=placements(self.parts,lengths,case['copies'])
            corners=[v for v in layout if self.parts[v['part']]['a']!=1 and self.parts[v['part']]['b']!=1]
            self.assertEqual(len(corners),4)
            self.assertEqual({v['part'] for v in corners},{0,1,2,3})
            n,m=case['copies'];self.assertEqual(len(layout),4+2*n+2*m)
            self.assertTrue(case['closed']);self.assertEqual(case['overlapping_pixels'],0)
            areas.append(case['interior_pixels'])
        self.assertGreater(areas[1],areas[0]);self.assertGreater(areas[2],areas[0]);self.assertGreater(areas[3],max(areas[1:3]));self.assertGreater(areas[4],areas[3])
        for p,pixels in zip(self.parts,before):self.assertTrue(np.array_equal(np.asarray(p['sprite']),pixels))

    def test_corner_offsets_close_and_opposite_walls_grow_together(self):
        la,lb=self.checks['lengths']
        layout=placements(self.parts,[la,lb],(5,3))
        corners={(self.parts[v['part']]['a'],self.parts[v['part']]['b']):v['shift'] for v in layout if self.parts[v['part']]['a']!=1 and self.parts[v['part']]['b']!=1}
        self.assertEqual(corners[(0,0)],[0,0])
        self.assertEqual(corners[(2,0)],[4*la,2*la])
        self.assertEqual(corners[(0,2)],[-2*lb,lb])
        self.assertEqual(corners[(2,2)],[4*la-2*lb,2*la+lb])
        for b in (0,2):self.assertEqual(sum(self.parts[v['part']]['a']==1 and self.parts[v['part']]['b']==b for v in layout),5)

    def test_invalid_counts_are_rejected(self):
        for copies in ((0,1),(1.5,2),(1,21)):
            with self.assertRaises(ValueError):placements(self.parts,self.checks['lengths'],copies)

    def test_nonrepeating_color_on_one_opposite_wall_is_rejected(self):
        pixels=np.asarray(self.source).copy();yy,xx=np.indices(pixels.shape[:2],dtype=float)
        u=(xx-512)/2+yy-300;v=-(xx-512)/2+yy-300
        # Only one wall drifts; the matching opposite wall must not hide failure.
        visible=(pixels[:,:,3]>0)&(v<60)
        value=np.clip(u*1.2,0,255).astype(np.uint8)
        for channel in range(3):pixels[:,:,channel][visible]=value[visible]
        with self.assertRaisesRegex(ValueError,'没有共同重复接口'):
            analyze(Image.fromarray(pixels))

    def test_verified_source_can_be_reprocessed_without_calling_provider(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);data=dict(mode='ai',kind='custom',description='closed wall',title='院墙',projection='isometric_2_1',courtyard_ring_build=True)
            with patch('static_props.configured',return_value=True):first=props.prepare(root,data)
            folder=root/'.local/props/jobs'/first['id']
            provider_result(folder,first['spec'],None,reference())
            with patch('static_props.configured',return_value=True):second=props.prepare(root,dict(data,courtyard_source_job=first['id']))
            with patch('static_props.generate_materials') as provider:
                props.execute(root,second['id']);provider.assert_not_called()
            done=read(root/'.local/props/jobs'/second['id']/'job.json')
            self.assertEqual(done['status'],'complete',done)
            manifest=props.load_package(root,done['kit_id'])
            self.assertEqual(manifest['processing']['recipe'],'studio.courtyard-expand/1')
