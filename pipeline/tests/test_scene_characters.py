"""Character scenes retain reviewed action provenance and immutable atlas bytes."""
from io import BytesIO
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import scene_characters as sc
import scene_modules as sm

class SceneCharacters(unittest.TestCase):
    def fixture(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);root=Path(temp.name)
        (root/'workspaces/elder').mkdir(parents=True)
        (root/'workspaces/elder/character.json').write_text(json.dumps(dict(display_name='Elder')))
        image=BytesIO();Image.new('RGBA',(128,64),(50,80,70,255)).save(image,format='PNG')
        package=BytesIO()
        contract=dict(directions=dict(available_views=['three_quarter']),
            actions=dict(idle=dict(texture='assets/textures/idle.png',frame_size=64,anchor_px=[32,56])),
            coordinates=dict(body_height_px=48))
        files={'asset.json':json.dumps(contract).encode(),'assets/textures/idle.png':image.getvalue(),
               'character.tscn':b'character fixture'}
        with zipfile.ZipFile(package,'w') as z:
            for name,raw in files.items():z.writestr('character_assets/elder/'+name,raw)
        for target,value in [('action_set.export',package.getvalue()),('action_set.inspect',dict(status='ready',complete=True))]:
            patcher=patch(target,return_value=value);patcher.start();self.addCleanup(patcher.stop)
        return root,files,package.getvalue()

    def test_adopt_replace_export_and_pin(self):
        root,files,original=self.fixture()
        scene=sm.change(root,dict(action='create',title='test'))
        scene=sm.change(root,dict(action='adopt',scene=scene['id'],revision=scene['revision'],family='character',kit='elder'))
        module=scene['modules'][0]
        self.assertEqual(module['source']['family'],'character')
        self.assertEqual(module['anchor'],[32,56])
        self.assertEqual(module['world_scale'],.65)
        self.assertIn('character_assets/elder/character.tscn',module['character_scene'])
        with zipfile.ZipFile(BytesIO(sm.export(root,scene['id']))) as z:
            self.assertEqual(z.read(module['character_scene'].replace('character.tscn','assets/textures/idle.png')),files['assets/textures/idle.png'])
            self.assertEqual(z.read('assets/'+module['source']['id']+'-actions.zip'),original)
        before=module['source']
        # A fresh export with the same file contents reuses the same scene version.
        m=sc.snapshot(root,'elder');self.assertEqual(m['id'],before['id'])
        self.assertEqual(sm.load(root,scene['id'])['modules'][0]['source'],before)
        with self.assertRaises(ValueError):
            sm.change(root,dict(action='module',scene=scene['id'],revision=scene['revision'],module=module['id'],
                title='edit',anchor=[0,0],world_scale=1,behavior='passable',polygons=[]))
        folder=sc.directory(root)/m['id'];(folder/'sprite.png').write_bytes(b'corrupt')
        with self.assertRaises(ValueError):sm.load(root,scene['id'])

    def test_unreviewed_deliverable_set_can_be_validated_without_claiming_review(self):
        root,_,_=self.fixture()
        report=dict(status='review',complete=True,warnings=['idle：尚未人工验收动作与循环效果'])
        with patch('action_set.inspect',return_value=report):
            manifest=sc.snapshot(root,'elder')
            self.assertEqual(manifest['validation'],report)
            self.assertTrue(any(a['id']=='elder' for a in sm.library(root)))
            scene=sm.change(root,dict(action='create',title='未检查人物验证'))
            scene=sm.change(root,dict(action='adopt',scene=scene['id'],revision=scene['revision'],family='character',kit='elder'))
            with zipfile.ZipFile(BytesIO(sm.export(root,scene['id']))) as archive:
                self.assertIn('assets/'+manifest['id']+'-actions.zip',archive.namelist())

    def test_incomplete_action_set_still_blocks_validation(self):
        root,_,_=self.fixture()
        with patch('action_set.inspect',return_value=dict(status='blocked',complete=False,errors=['来源已变化'])):
            with self.assertRaisesRegex(ValueError,'结构错误'):sc.snapshot(root,'elder')
            self.assertFalse(any(a.get('family')=='character' for a in sm.library(root)))

if __name__=='__main__':unittest.main()
