"""Weapon integrity, calibration versioning, background preservation and staging."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from io import BytesIO
import base64
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from weapon_assets import load, calibrate, asset_dir, digest, prepare_white_background
from equipment import load as load_equipment, stage_model
from panel import Panel
from test_equipment import config
from PIL import Image, ImageDraw

class WeaponAssetTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve()
        target=asset_dir(self.root,'w1');target.mkdir(parents=True)
        (target/'model.glb').write_bytes(b'model fixture')
        self.asset={'schema':1,'id':'w1','name':'Sword','model_sha256':digest(target/'model.glb'),'confirmed':False,'length_meters':.85,'grip':[0,.15,0]}
        (target/'weapon.json').write_text(json.dumps(self.asset))
    def test_unconfirmed_asset_cannot_be_equipped(self):
        with self.assertRaisesRegex(ValueError,'先检查'):load(self.root,'w1',True)
        updated=calibrate(self.root,'w1',.8,[0,.2,0])
        self.assertTrue(load(self.root,updated['id'],True)['confirmed'])
        self.assertFalse(load(self.root,'w1')['confirmed'])
        self.assertEqual(updated['model_sha256'],self.asset['model_sha256'])
        self.assertEqual(updated['parent'],'w1')
    def test_invalid_calibration_rejected(self):
        for length,grip in [(True,[0,.2,0]),(float('nan'),[0,.2,0]),(.8,[0,2,0]),(.8,[0,float('inf'),0]),(.8,[])]:
            with self.assertRaises(ValueError):calibrate(self.root,'w1',length,grip)
    def test_tampered_model_and_links_rejected(self):
        (asset_dir(self.root,'w1')/'model.glb').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'变化'):load(self.root,'w1')
        with self.assertRaises(ValueError):asset_dir(self.root,'../secret')
        (self.root/'weapons/link').symlink_to(asset_dir(self.root,'w1'),target_is_directory=True)
        with self.assertRaises(ValueError):load(self.root,'link')
    def test_background_removal_preserves_gray_blade(self):
        source=self.root/'input.png'
        image=Image.new('RGB',(120,200),'white');draw=ImageDraw.Draw(image)
        draw.rectangle((52,15,68,140),fill=(210,212,218));draw.rectangle((55,140,65,180),fill=(80,45,30));image.save(source)
        target=self.root/'prepared.png';prepare_white_background(source,target)
        with Image.open(target) as result:
            colors=result.getcolors(result.width*result.height)
            self.assertTrue(any(color==(210,212,218) and count>1500 for count,color in colors))
            self.assertEqual(result.getpixel((0,0)),(128,128,128))
    def test_equipment_snapshot_survives_library_change_but_not_tampering(self):
        cfg=config();cfg.update(schema=2,weapon='asset',weapon_asset='w1',weapon_name='Sword',weapon_model_sha256=self.asset['model_sha256'],weapon_length=.85)
        target=self.root/'workspaces/hero/equipment/e1';target.mkdir(parents=True)
        (target/'weapon.glb').write_bytes(b'model fixture');(target/'equipment.json').write_text(json.dumps(cfg))
        batch=self.root/'workspaces/hero/animations/batch1';batch.mkdir(parents=True)
        (batch/'batch.json').write_text(json.dumps({'files':cfg['files'],'rig_sha256':'rig'}))
        (asset_dir(self.root,'w1')/'model.glb').write_bytes(b'library changed')
        other=self.root/'workspaces/hero/animations/new-actions'
        other.mkdir(parents=True)
        (other/'batch.json').write_text(json.dumps({'files':{'slash.fbx':'new'},'rig_sha256':'rig'}))
        loaded=load_equipment(self.root,'hero','new-actions','e1')
        project=self.root/'project';project.mkdir();stage_model(loaded,target/'weapon.glb',project)
        self.assertEqual(digest(project/'weapon.glb'),cfg['weapon_model_sha256'])
        (target/'weapon.glb').write_bytes(b'bad snapshot')
        with self.assertRaisesRegex(ValueError,'快照'):load_equipment(self.root,'hero','batch1','e1')
        with self.assertRaisesRegex(ValueError,'校验'):stage_model(loaded,target/'weapon.glb',project)
    def test_panel_weapon_boundary_and_task_validation(self):
        panel=Panel(self.root)
        self.assertEqual(panel.asset_path('weapons/w1/model.glb'),asset_dir(self.root,'w1')/'model.glb')
        for name in ['weapon.json','../w1/weapon.json','secret.txt']:
            with self.assertRaises(ValueError):panel.asset_path('weapons/w1/'+name)
        c={'has_model':True,'model_approved':True,'rig':{'ready':True},'batches':[{'id':'b','current_rig':True}]}
        with patch.object(panel,'character',return_value=c):
            with self.assertRaisesRegex(ValueError,'先检查'):panel.validate_task('hero','equipment',{'batch':'b','weapon_id':'w1'})
            updated=calibrate(self.root,'w1',.85,[0,.15,0])
            clean=panel.validate_task('hero','equipment',{'batch':'b','weapon_id':updated['id']})
            self.assertEqual(clean['weapon_id'],updated['id'])
    def test_weapon_upload_does_not_become_character_input(self):
        panel=Panel(self.root);data=BytesIO();Image.new('RGB',(64,64),'white').save(data,format='PNG')
        result=panel.upload_weapon({'name':'Sword','content':base64.b64encode(data.getvalue()).decode()})
        self.assertTrue(result['image'].startswith('.local/weapon-inputs/'))
        self.assertFalse((self.root/'workspaces').exists())
        with self.assertRaises(ValueError):panel.validate_task('hero','weapon',{'image':'../secret','name':'Sword'})
