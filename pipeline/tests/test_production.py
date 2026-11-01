"""Production orchestration with real palettes/compaction and simulated external services."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image, ImageDraw
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import production
from asset_repository import AssetRepository, atomic, read


class ProductionTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name).resolve()
        self.ws=self.root/'workspaces/hero';self.ws.mkdir(parents=True)
        self.info={'triangles':100,'skeleton_bones':20,'skinned_meshes':1,'textured_surfaces':1,'animations':[{'changing_tracks':10}]}
        atomic(self.root/'.local/mixamo/hero/state.json',{'bound_sha256':'rig','geometry':self.info})
        self.add_source('existing','Walking')
        root=self.root
        class Repository(AssetRepository):
            def character(self, character):
                batches=[]
                for receipt in sorted((root/'workspaces/hero/animations').glob('*/batch.json')):
                    data=read(receipt,{});request=read(receipt.parent/'request.json',{})
                    batches.append({'id':receipt.parent.name,'files':list(data['files']),'hashes':data['files'],'current_rig':True,'titles':{t.lower().replace(' ','_')+'.fbx':t for t in request.get('names',[])}})
                return {'rig':{'ready':True},'batches':batches}
        self.assets=Repository(root)
        for p in [patch('production.AssetRepository',Repository),patch('progress.BASE_DIR',root),patch('studio_core.BASE_DIR',root),patch('asset_inspector.inspect_download',return_value=self.info),patch('studio_core.bake',side_effect=self.bake)]:
            p.start();self.addCleanup(p.stop)
        self.render_calls=[];self.downloads=[];self.fail_titles=set();self.fail_render=set()
        self.params={'actions':[{'role':'walk','title':'Walking','loop':True},{'role':'attack','title':'Sword Attack','loop':False}],'colors':64,'body_height':96}
        self.saves=[]

    def add_source(self,batch,title):
        directory=self.ws/'animations'/batch;directory.mkdir(parents=True,exist_ok=True)
        filename=title.lower().replace(' ','_')+'.fbx';(directory/filename).write_text(title)
        atomic(directory/'batch.json',{'character':'hero','batch':batch,'rig_sha256':'rig','files':{filename:AssetRepository(self.root).digest(directory/filename)}})
        atomic(directory/'request.json',{'names':[title]})

    def download(self,title,checkpoint,persist):
        if title in self.fail_titles:raise ValueError('模拟下载失败')
        if not checkpoint.get('batch'):
            self.downloads.append(title);checkpoint['batch']='download-'+str(len(self.downloads));persist()
        self.add_source(checkpoint['batch'],title)

    def bake(self,character,batch,view,frame_size,supersample,equipment,renderer,usage,selected_files,body_height):
        self.render_calls.append(selected_files)
        if any(f in self.fail_render for f in selected_files):raise ValueError('模拟渲染失败')
        folder=self.root/'deliverables/hero'/('render-'+str(len(self.render_calls)));folder.mkdir(parents=True)
        receipt=read(self.ws/'animations'/batch/'batch.json',{})
        manifest={'source':{'character':'hero','batch':batch,'files':{f:receipt['files'][f] for f in selected_files}},'renderer':renderer,'pixel_style':{}}
        for filename in selected_files:
            clip=filename.removesuffix('.fbx');image=Image.new('RGBA',(64*4,64));d=ImageDraw.Draw(image)
            for i in range(4):
                d.rectangle((i*64+16+i,8,i*64+42+i,55),fill=(150,30+i*5,20,255))
                d.rectangle((i*64+20+i,8,i*64+36+i,20),fill=(220,160,100,255))
            image.save(folder/(clip+'_spritesheet.png'))
            Image.new('RGB',(64,64),'red').save(folder/(clip+'_preview.gif'))
            manifest[clip+'_spritesheet.png']={'frame_width':64,'frame_height':64,'frame_count':4,'duration_seconds':.4,'columns':4,'rows':1,'body_height_px':body_height,'anchor_px':[32,58],'view':view,'projection':{'reference_sha256':'rig','pixels_per_source_unit':96}}
        atomic(folder/'manifest.json',manifest);return folder

    def job(self,params=None):
        return {'id':'production-'+str(len(self.saves)),'character':'hero','params':production.plan(self.assets,'hero',params or self.params),'outputs':{}}

    def persist(self): self.saves.append(True)

    def test_one_request_downloads_only_missing_renders_together_and_publishes(self):
        job=self.job();production.run(self.root,job,self.persist,self.download)
        self.assertEqual(self.downloads,['Sword Attack'])
        self.assertEqual(len(self.render_calls),1)
        self.assertEqual(set(self.render_calls[0]),{'walking.fbx','sword_attack.fbx'})
        recipe=read(self.ws/'action_set.json');self.assertEqual(set(recipe['actions']),{'walk','attack'})
        self.assertTrue(recipe['actions']['walk']['loop']);self.assertFalse(recipe['actions']['attack']['loop'])
        self.assertFalse(recipe['actions']['walk']['reviewed'])
        self.assertEqual(len({a['delivery'] for a in recipe['actions'].values()}),1)
        folder=self.root/'deliverables/hero'/recipe['actions']['walk']['delivery']
        self.assertTrue((folder/'palette.json').is_file());self.assertTrue((folder/'game/walking.tres').is_file())
        self.assertTrue(read(folder/'manifest.json')['walking_spritesheet.png']['game']['frame_count']>0)

    def test_partial_failure_preserves_previous_set_and_retry_reuses_render(self):
        previous={'revision':4,'title':'Previous','actions':{}}
        atomic(self.ws/'action_set.json',previous)
        self.fail_titles={'Sword Attack'};job=self.job()
        with self.assertRaisesRegex(ValueError,'部分动作失败'):production.run(self.root,job,self.persist,self.download)
        self.assertEqual(read(self.ws/'action_set.json'),previous)
        first_calls=len(self.render_calls);self.assertEqual(first_calls,1)
        self.fail_titles.clear();production.run(self.root,job,self.persist,self.download)
        self.assertEqual(len(self.render_calls),first_calls+1)
        self.assertEqual(self.render_calls[-1],['sword_attack.fbx'])
        self.assertEqual(read(self.ws/'action_set.json')['revision'],5)

    def test_new_color_job_uses_cached_renders_and_source_change_rejects(self):
        job=self.job();production.run(self.root,job,self.persist,self.download)
        count=len(self.render_calls)
        job2=self.job({**self.params,'colors':32,'profile':'compact'})
        production.run(self.root,job2,self.persist,self.download)
        self.assertEqual(len(self.render_calls),count)
        previous_delivery=job2['outputs']['action_set']['actions']['walk']['delivery']
        job3=self.job({**self.params,'colors':32,'profile':'compact'})
        production.run(self.root,job3,self.persist,self.download)
        self.assertEqual(job3['outputs']['action_set']['actions']['walk']['delivery'],previous_delivery)
        source=job2['params']['sources']['walk']
        (self.ws/'animations'/source['batch']/source['file']).write_text('changed')
        with self.assertRaisesRegex(ValueError,'来源已变化'):production.run(self.root,job2,self.persist,self.download)

    def test_render_failure_isolated_and_no_incomplete_publication(self):
        self.fail_render={'sword_attack.fbx'};job=self.job()
        with self.assertRaisesRegex(ValueError,'部分动作失败'):production.run(self.root,job,self.persist,self.download)
        self.assertEqual(job['outputs']['production']['roles']['walk']['status'],'ready')
        self.assertEqual(job['outputs']['production']['roles']['attack']['status'],'failed')
        self.assertFalse((self.ws/'action_set.json').exists())
        self.fail_render.clear();production.run(self.root,job,self.persist,self.download)
        self.assertEqual(self.render_calls[-1],['sword_attack.fbx'])
        self.assertTrue((self.ws/'action_set.json').is_file())

    def test_revision_conflict_does_not_overwrite_current_set(self):
        job=self.job();atomic(self.ws/'action_set.json',{'revision':1,'title':'Other editor','actions':{}})
        with self.assertRaisesRegex(ValueError,'生产期间动作集已被修改'):production.run(self.root,job,self.persist,self.download)
        self.assertEqual(read(self.ws/'action_set.json')['title'],'Other editor')

    def test_request_validation_and_pin_checks(self):
        for change in ({'colors':15},{'body_height':100},{'actions':[]},{'rig_sha256':'other'}):
            with self.assertRaises(ValueError):self.job({**self.params,**change})
