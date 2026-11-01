import io,json,sys,tempfile,unittest,zipfile
from pathlib import Path
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from game_package import build

class GamePackage(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.dir=self.root/'deliverables/hero/batch';self.dir.mkdir(parents=True)
        self.choices={r:{'delivery':'batch','clip':r} for r in ('idle','walk','run','jump')}
        self.manifest={'source':{'character':'hero'},'renderer':'godot'}
        for i,role in enumerate(self.choices):
            size=16+i*2
            Image.new('RGBA',(size*3,size),'red').save(self.dir/(role+'_spritesheet.png'))
            game=self.dir/'game';game.mkdir(exist_ok=True)
            Image.new('RGBA',(size*2,size),'red').save(game/(role+'_spritesheet.png'))
            info={'frame_width':size,'frame_height':size,'frame_count':3,'duration_seconds':.3,'body_height_px':96,'anchor_px':[size/2,size-2],'view':'front','projection':{'reference_sha256':'rig','pixels_per_source_unit':96},'quality':{'status':'passed'}}
            self.manifest[role+'_spritesheet.png']={**info,'game':{**info,'frame_count':2,'frame_durations_seconds':[.1,.2]}}
        self.save()
    def save(self):(self.dir/'manifest.json').write_text(json.dumps(self.manifest))
    def test_portable_selected_version_offsets_and_durations(self):
        z=zipfile.ZipFile(io.BytesIO(build(self.root,'hero',self.choices)))
        resource=z.read('character_assets/hero/animations.tres').decode()
        self.assertEqual(resource.count('[sub_resource'),8)
        self.assertIn('"duration": 0.200000000000',resource)
        self.assertIn('"name": &"jump", "speed": 1.0, "loop": false',resource)
        self.assertNotIn('res://deliverables',resource)
        script=z.read('character_assets/hero/character.gd').decode()
        self.assertIn('"jump": [0.0, -9.0]',script)
        self.assertIn('project.godot',z.namelist())
    def test_missing_role_incompatible_projection_and_bad_duration_rejected(self):
        with self.assertRaises(ValueError):build(self.root,'hero',{'walk':self.choices['walk']})
        self.manifest['jump_spritesheet.png']['game']['body_height_px']=128;self.save()
        with self.assertRaisesRegex(ValueError,'不一致'):build(self.root,'hero',self.choices)
        self.manifest['jump_spritesheet.png']['game']['body_height_px']=96
        self.manifest['jump_spritesheet.png']['game']['frame_durations_seconds']=[.1,.3];self.save()
        with self.assertRaisesRegex(ValueError,'时长'):build(self.root,'hero',self.choices)
    def test_paths_cannot_escape_and_original_version_supported(self):
        self.choices['idle']['delivery']='../other'
        with self.assertRaises(ValueError):build(self.root,'hero',self.choices)
        self.choices['idle']['delivery']='batch'
        z=zipfile.ZipFile(io.BytesIO(build(self.root,'hero',self.choices,'source')))
        m=json.loads(z.read('character_assets/hero/manifest.json'))
        self.assertEqual(m['actions']['idle']['frame_count'],3)
    def test_ai_contract_states_capabilities_and_no_unearned_certification(self):
        self.choices['idle']=self.choices['walk'].copy()
        z=zipfile.ZipFile(io.BytesIO(build(self.root,'hero',self.choices)))
        contract=json.loads(z.read('character_assets/hero/asset.json'))
        self.assertEqual(contract['schema'],'character_studio.asset/1.0')
        self.assertFalse(contract['motion']['physics_included'])
        self.assertFalse(contract['directions']['multi_direction_ready'])
        self.assertEqual(contract['validation']['engine_runtime'],'not_run_for_this_export')
        self.assertTrue(any('多个用途' in w for w in contract['validation']['warnings']))
        for record in contract['actions'].values():
            self.assertIn('character_assets/hero/'+record['texture'],z.namelist())
            self.assertEqual(record['semantic_validation'],'unverified')
        script=z.read('character_assets/hero/character.gd').decode()
        self.assertIn('signal action_finished',script)
        self.assertNotIn('func _process',script)
        self.assertIn('INTEGRATION.md',[Path(p).name for p in z.namelist()])
