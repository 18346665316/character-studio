"""Production regressions with fake provider: zero network and zero paid calls."""
import base64
from io import BytesIO
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock
import zipfile

from PIL import Image

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from asset_repository import read, atomic
from building_pipeline import (prepare,new_attempt,execute,review,publish,load_package,
                               folder_for,attempt_folder,CHECKS,digest,adjust,recovery,process,catalog)
from terrain_images import SubmissionRejected


class BuildingPipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.provider=Mock();self.provider.base='https://example.invalid/v1'
        self.factory=Mock(return_value=self.provider)
        self.job=prepare(self.root,{'title':'测试建筑','structure':{},'appearance':'浅灰泥墙，红瓦'})
        self.task=self.job['id'];self.folder=folder_for(self.root,self.task)
        # Exact fake image edit: solid magenta background, same square transform.
        transform=read(self.folder/'input-transform.json')
        with Image.open(self.folder/'structure/structure.png') as sprite:
            side=transform['square_side'];image=Image.new('RGBA',(side,side),'#ff00ff')
            image.alpha_composite(sprite,tuple(transform['offset_px']))
        image=image.convert('RGB').resize((1024,1024),Image.Resampling.LANCZOS)
        stream=BytesIO();image.save(stream,format='PNG');self.raw=stream.getvalue()
        self.provider.create.return_value={'data':[{'b64_json':base64.b64encode(self.raw).decode()}]}

    def start(self):
        self.job=new_attempt(self.root,self.task,self.job['revision'])
        self.job=execute(self.root,self.task,provider_factory=self.factory)
        return attempt_folder(self.folder,self.job['current_attempt'])

    def approve(self):
        self.job=review(self.root,self.task,self.job['revision'],dict.fromkeys(CHECKS,True))

    def test_full_path_preserves_cell_scale_and_requires_review(self):
        target=self.start();self.assertEqual(self.job['status'],'waiting_review')
        with self.assertRaisesRegex(ValueError,'复核'):publish(self.root,self.task,self.job['revision'])
        with Image.open(target/'sprite.png') as image:
            self.assertEqual(list(image.size),read(self.folder/'structure/structure.json')['canvas_px'])
        self.approve();kit=publish(self.root,self.task,self.job['revision'])
        self.assertFalse(kit['production_ready']);self.assertEqual(kit['game_integration'],'not_tested')
        self.assertEqual(load_package(self.root,kit['id']),kit)
        self.provider.create.assert_called_once()
        with zipfile.ZipFile(self.root/'building-kits'/kit['id']/'kit.zip') as archive:
            self.assertIn('inputs/raw.png',archive.namelist());self.assertIn('review.json',archive.namelist())

    def test_interruption_resumes_remote_id_without_resubmission(self):
        self.provider.create.return_value={'id':'remote-id'}
        self.provider.request.side_effect=[{'status':'running'},{'status':'completed'},self.raw]
        self.job=new_attempt(self.root,self.task,self.job['revision'])
        self.job=execute(self.root,self.task,deadline_seconds=0,provider_factory=self.factory)
        self.assertEqual(self.job['status'],'failed')
        self.job=execute(self.root,self.task,provider_factory=self.factory)
        self.assertEqual(self.job['status'],'waiting_review');self.provider.create.assert_called_once()

    def test_uncertain_submission_never_retries_or_creates_new_attempt(self):
        self.provider.create.side_effect=TimeoutError('network')
        self.start();self.assertEqual(self.job['status'],'failed')
        self.job=execute(self.root,self.task,provider_factory=self.factory)
        self.provider.create.assert_called_once()
        with self.assertRaisesRegex(ValueError,'结果不明'):new_attempt(self.root,self.task,self.job['revision'])

    def test_explicit_remote_failure_requires_new_attempt(self):
        self.provider.create.return_value={'id':'failed-id'}
        self.provider.request.return_value={'status':'failed'}
        self.start();old=self.job['current_attempt']
        self.job=execute(self.root,self.task,provider_factory=self.factory)
        self.provider.create.assert_called_once()
        self.job=new_attempt(self.root,self.task,self.job['revision'],'屋顶保持双坡')
        self.assertNotEqual(old,self.job['current_attempt'])
        self.assertTrue((attempt_folder(self.folder,old)/'generation.json').exists())

    def test_postprocess_failure_preserves_raw_and_resume_does_not_pay(self):
        image=Image.new('RGB',(1024,1024),'#f3f1ec');stream=BytesIO();image.save(stream,format='PNG')
        self.provider.create.return_value={'data':[{'b64_json':base64.b64encode(stream.getvalue()).decode()}]}
        target=self.start();self.assertEqual(self.job['status'],'failed');self.assertTrue((target/'raw.png').exists())
        self.job=execute(self.root,self.task,provider_factory=self.factory)
        self.provider.create.assert_called_once()

    def test_rejected_candidate_can_create_child_without_overwrite(self):
        target=self.start();original=digest(target/'raw.png')
        checks=dict.fromkeys(CHECKS,True);checks['roof_topology']=False
        self.job=review(self.root,self.task,self.job['revision'],checks,'山墙被画成瓦面')
        self.assertEqual(self.job['status'],'rejected')
        with self.assertRaises(ValueError):publish(self.root,self.task,self.job['revision'])
        previous=self.job['current_attempt'];self.job=new_attempt(self.root,self.task,self.job['revision'],'保留山墙')
        meta=read(attempt_folder(self.folder,self.job['current_attempt'])/'attempt.json')
        self.assertEqual(meta['parent_attempt'],previous);self.assertEqual(digest(target/'raw.png'),original)

    def test_tampering_or_stale_review_is_rejected(self):
        target=self.start()
        with self.assertRaisesRegex(ValueError,'更新'):review(self.root,self.task,1,dict.fromkeys(CHECKS,True))
        self.approve()
        (target/'sprite.png').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'变化'):publish(self.root,self.task,self.job['revision'])

    def test_changed_structure_blocks_paid_call(self):
        self.job=new_attempt(self.root,self.task,self.job['revision'])
        (self.folder/'structure/ai-reference.png').write_bytes(b'changed')
        self.job=execute(self.root,self.task,provider_factory=self.factory)
        self.assertEqual(self.job['status'],'failed');self.provider.create.assert_not_called()

    def test_archive_corruption_blocks_loading(self):
        self.start();self.approve();kit=publish(self.root,self.task,self.job['revision'])
        (self.root/'building-kits'/kit['id']/'kit.zip').write_bytes(b'bad')
        with self.assertRaises((ValueError,zipfile.BadZipFile)):load_package(self.root,kit['id'])

    def change(self, action, **data):
        self.job = adjust(self.root, dict(task=self.task, revision=self.job['revision'], action=action, **data))
        return self.job

    def test_structure_only_preview_and_copy_retain_context(self):
        style=base64.b64encode(self.raw).decode()
        original=prepare(self.root, {'title':'大厅', 'structure':{'footprint_cells':[4,3]}, 'style_reference':style})
        source=folder_for(self.root,original['id'])
        spec=read(source/'structure/structure.json')['spec'];spec['openings'][0]['center']=1.8
        copied=prepare(self.root, {'title':original['spec']['title'], 'structure':spec,
                                 'source_task':original['id'], 'source_revision':original['revision']})
        target=folder_for(self.root,copied['id'])
        self.assertEqual(copied['parent_task'],original['id'])
        self.assertEqual(digest(source/'style.png'),digest(target/'style.png'))
        self.assertEqual(read(target/'structure/structure.json')['spec']['footprint_cells'],[4,3])
        with self.assertRaisesRegex(ValueError,'外观描述'):new_attempt(self.root,copied['id'],copied['revision'])
        copied=adjust(self.root,dict(task=copied['id'],revision=copied['revision'],action='appearance',appearance='木墙'))
        self.assertEqual(new_attempt(self.root,copied['id'],copied['revision'])['status'],'queued')
        self.provider.create.assert_not_called()

    def test_failed_unsubmitted_execute_requires_explicit_paid_launch(self):
        self.job=new_attempt(self.root,self.task,self.job['revision'])
        self.job['status']='failed';atomic(self.folder/'job.json',self.job)
        self.job=execute(self.root,self.task,provider_factory=self.factory)
        self.assertEqual(self.job['status'],'failed');self.provider.create.assert_not_called()
        target=attempt_folder(self.folder,self.job['current_attempt'])
        self.assertEqual(recovery(self.folder,target),'unsubmitted')
        self.assertIn('尚未提交',self.job['error'])

    def test_raw_without_receipt_hash_redownloads_same_remote(self):
        self.job=new_attempt(self.root,self.task,self.job['revision'])
        target=attempt_folder(self.folder,self.job['current_attempt'])
        (target/'raw.png').write_bytes(b'untrusted partial file')
        atomic(target/'generation.json',dict(remote_id='same-id',base_url=self.provider.base))
        self.provider.request.side_effect=[{'status':'completed'},self.raw]
        self.job=execute(self.root,self.task,provider_factory=self.factory)
        self.assertEqual(self.job['status'],'waiting_review');self.provider.create.assert_not_called()
        self.assertEqual(self.provider.request.call_args_list[1].args[0],'/images/same-id/content')

    def test_pending_image_with_committed_hash_recovers_without_network(self):
        self.job=new_attempt(self.root,self.task,self.job['revision'])
        target=attempt_folder(self.folder,self.job['current_attempt'])
        (target/'raw.pending.png').write_bytes(self.raw)
        atomic(target/'generation.json',dict(status='completed',sha256=digest(target/'raw.pending.png')))
        self.job=execute(self.root,self.task,provider_factory=self.factory)
        self.assertEqual(self.job['status'],'waiting_review');self.factory.assert_not_called()
        self.assertFalse((target/'raw.pending.png').exists())

    def test_rejected_review_can_pass_and_approval_can_be_withdrawn(self):
        target=self.start();checks=dict.fromkeys(CHECKS,False)
        self.job=review(self.root,self.task,self.job['revision'],checks,'暂未检查')
        self.approve();self.assertEqual(self.job['status'],'approved')
        self.job=review(self.root,self.task,self.job['revision'],dict.fromkeys(CHECKS,True),'再检查',action='reopen')
        self.assertEqual(self.job['status'],'waiting_review')
        with self.assertRaises(ValueError):publish(self.root,self.task,self.job['revision'])
        self.job=review(self.root,self.task,self.job['revision'],dict.fromkeys(CHECKS,True),action='draft')
        self.assertFalse(read(target/'review.json')['accepted'])
        self.assertEqual(len(list((target/'review-history').glob('*.json'))),3)
        self.provider.create.assert_called_once()

    def test_all_displayed_evidence_is_bound_before_review_and_publish(self):
        target=self.start();self.approve()
        Image.new('RGB',(10,10),'black').save(target/'preview.png')
        with self.assertRaisesRegex(ValueError,'检查图'):publish(self.root,self.task,self.job['revision'])
        with self.assertRaisesRegex(ValueError,'检查图'):review(self.root,self.task,self.job['revision'],dict.fromkeys(CHECKS,True))
        self.change('recheck');self.assertEqual(self.job['status'],'waiting_review')
        self.assertFalse((target/'review.json').exists());self.approve()
        publish(self.root,self.task,self.job['revision']);self.provider.create.assert_called_once()

    def test_legacy_checks_require_explicit_free_rebuild(self):
        target=self.start();report=read(target/'checks.json');report.pop('algorithm');report.pop('evidence_sha256')
        atomic(target/'checks.json',report)
        with self.assertRaisesRegex(ValueError,'版本'):self.approve()
        self.assertFalse(catalog(self.root)['jobs'][0]['evidence_valid'])
        self.change('recheck');self.approve();self.provider.create.assert_called_once()

    def test_edit_passes_selected_image_and_cumulative_requirements(self):
        first=self.start();original=digest(first/'raw.png')
        self.job=new_attempt(self.root,self.task,self.job['revision'],'保留墙色',mode='edit',source_attempt=first.name)
        second=attempt_folder(self.folder,self.job['current_attempt'])
        self.job=execute(self.root,self.task,provider_factory=self.factory)
        references=self.provider.create.call_args.args[1]
        self.assertEqual(references[-1],second/'edit-source.png')
        self.assertEqual(digest(references[-1]),original)
        self.job=new_attempt(self.root,self.task,self.job['revision'],'只修门',mode='edit')
        meta=read(attempt_folder(self.folder,self.job['current_attempt'])/'attempt.json')
        self.assertEqual(meta['corrections'],['保留墙色','只修门'])
        self.assertEqual(meta['image_roles'][-1]['role'],'edit_target')

    def test_manual_alpha_repair_invalidates_approval_and_preserves_raw(self):
        target=self.start();original=digest(target/'raw.png');self.approve()
        transform=read(self.folder/'input-transform.json')
        with Image.open(self.folder/'structure/structure.png') as sprite:
            image=Image.new('RGBA',(transform['square_side'],)*2)
            image.alpha_composite(sprite,tuple(transform['offset_px']))
            image=image.resize((1024,1024),Image.Resampling.LANCZOS)
        stream=BytesIO();image.save(stream,format='PNG')
        self.change('repair',image=base64.b64encode(stream.getvalue()).decode())
        self.assertEqual(self.job['status'],'waiting_review');self.assertEqual(digest(target/'raw.png'),original)
        self.assertEqual(read(target/'checks.json')['background'],'manual_alpha')
        self.assertFalse((target/'review.json').exists());self.provider.create.assert_called_once()
        self.approve();kit=publish(self.root,self.task,self.job['revision'])
        self.assertIn('processing.json',kit['files_sha256'])
        self.assertTrue(any(p.startswith('repairs/') for p in kit['files_sha256']))

    def test_invalid_repair_does_not_remove_approval(self):
        target=self.start();self.approve();approval=digest(target/'review.json')
        with self.assertRaises(ValueError):self.change('repair',image=base64.b64encode(self.raw).decode())
        self.assertEqual(digest(target/'review.json'),approval)

    def test_select_old_published_candidate_preserves_package(self):
        target=self.start();self.approve();kit=publish(self.root,self.task,self.job['revision'])
        self.job=read(self.folder/'job.json');before=digest(self.root/'building-kits'/kit['id']/'kit.zip')
        self.change('adopt',attempt=target.name)
        self.assertNotEqual(self.job['current_attempt'],target.name)
        self.assertEqual(self.job['status'],'waiting_review')
        self.assertEqual(load_package(self.root,kit['id']),kit)
        self.assertEqual(digest(self.root/'building-kits'/kit['id']/'kit.zip'),before)
        self.provider.create.assert_called_once()

    def test_reconcile_uncertain_submission_only_resumes_supplied_remote(self):
        self.provider.create.side_effect=TimeoutError('lost response')
        target=self.start();self.assertEqual(self.job['status'],'failed')
        self.change('reconcile',remote_id='verified-id')
        self.provider.request.side_effect=[{'status':'completed'},self.raw]
        self.job=execute(self.root,self.task,provider_factory=self.factory)
        self.assertEqual(self.job['status'],'waiting_review')
        self.provider.create.assert_called_once()
        self.assertEqual(self.provider.request.call_args_list[0].args[0],'/images/verified-id')
        self.assertTrue(list((target/'generation-history').glob('*.json')))


if __name__=='__main__':unittest.main()
