"""Projection contracts, raster coverage and immutable package integration."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np
from PIL import Image, ImageDraw
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from asset_projection import ISOMETRIC, diamond
from terrain import validate, prepare, execute
from terrain_integrity import inspect
from static_props import validate as prop_spec, package, load_package, remake, prompt


class ProjectionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def test_diamonds_cover_lattice_without_gaps_or_double_coverage(self):
        for width in (64,128,256):
            tile=diamond(Image.new('RGB',(64,64),'green'),width)
            self.assertEqual(tile.size,(width,width//2))
            self.assertEqual(tile.getpixel((0,0))[3],0)
            self.assertEqual(tile.getpixel((width//2,width//4))[3],255)
            # At the common vertex four half-open diamonds cover every pixel once.
            coverage=np.zeros((width,width*2),dtype=np.uint16)
            alpha=np.asarray(tile)[:,:,3]//255
            for x,y in [(width//2,0),(0,width//4),(width,width//4),(width//2,width//2)]:
                coverage[y:y+width//2,x:x+width]+=alpha
            self.assertTrue(np.all(coverage[width//4:width*3//4,width//2:width*3//2]==1))

    def test_iso_material_delivery_contains_hashed_transparent_exports(self):
        job=prepare(self.root,{'title':'test','description':'grass','mode':'demo','asset_type':'material','projection':ISOMETRIC})
        execute(self.root,job['id'])
        execute(self.root,job['id'])
        self.assertEqual(json.loads((self.root/'.local/terrain/jobs'/job['id']/'job.json').read_text())['status'],'complete')
        folder=self.root/'terrain-kits'/job['id']
        manifest=json.loads((folder/'manifest.json').read_text())
        self.assertTrue(inspect(self.root,'terrain-kits',job['id'])['passed'])
        projection=manifest['projection_spec']
        self.assertEqual(projection['cell_px'],[128,64])
        self.assertEqual(projection['basis_px'],[[64,32],[-64,32]])
        self.assertEqual(manifest['view'],ISOMETRIC)
        self.assertEqual(len(projection['variants']),4)
        with Image.open(folder/projection['variants'][0]['image']) as image:
            self.assertEqual(image.mode,'RGBA');self.assertEqual(image.size,(128,64))
        reused=prepare(self.root,{'title':'reuse','description':'grass','mode':'reuse','source_kit':job['id']})
        self.assertEqual(reused['spec']['projection'],ISOMETRIC)
        self.assertEqual(reused['spec']['view'],ISOMETRIC)
        execute(self.root,reused['id'])
        self.assertTrue(inspect(self.root,'terrain-kits',reused['id'])['passed'])
        (folder/projection['atlas']).write_bytes(b'bad')
        self.assertFalse(inspect(self.root,'terrain-kits',job['id'])['passed'])

    def test_unsupported_combinations_rejected_including_reuse(self):
        base={'title':'test','description':'test','projection':ISOMETRIC}
        for extra in ({},{'asset_type':'material','material_kind':'water'},{'asset_type':'material','projection':False}):
            with self.assertRaises(ValueError): validate({**base,**extra})
        source=prepare(self.root,{'title':'test','description':'grass','mode':'demo'})
        execute(self.root,source['id'])
        with self.assertRaisesRegex(ValueError,'仅支持独立地面'):
            prepare(self.root,{**base,'asset_type':'material','mode':'reuse','source_kit':source['id']})

    def test_object_geometry_preserved_projection_and_remake_retained(self):
        image=Image.new('RGBA',(128,128));ImageDraw.Draw(image).rectangle((24,24,104,104),fill=(100,70,30,255))
        legacy=package(self.root,image,prop_spec({'mode':'import','kind':'crate'}))
        spec=prop_spec({'mode':'import','kind':'crate','projection':ISOMETRIC})
        target=package(self.root,image,spec);manifest=load_package(self.root,target.name)
        self.assertEqual((target/'sprite.png').read_bytes(),(legacy/'sprite.png').read_bytes())
        self.assertEqual(manifest['view'],ISOMETRIC)
        self.assertEqual(manifest['projection']['artwork_transform'],'none')
        collision=manifest['suggested_collision'];self.assertFalse(collision['enabled_by_default'])
        self.assertEqual(len(collision['polygon']),4)
        self.assertEqual(collision['depth_px'],round(collision['width_px']/2,2))
        changed=remake(self.root,{'source_kit':target.name,'anchor_y':200})
        updated=load_package(self.root,changed.name)
        self.assertEqual(updated['view'],ISOMETRIC);self.assertEqual(updated['anchor_px'][1],200)
        self.assertEqual(updated['provenance']['parent_kit'],target.name)
        text=prompt('wooden crate','crate',ISOMETRIC)
        self.assertIn('26.565',text);self.assertIn('2:1 dimetric',text)
        self.assertNotIn('Orthographic three-quarter',text)
        self.assertIn('#FF00FF',text)
