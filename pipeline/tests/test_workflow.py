import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from workflow import guidance

class WorkflowTests(unittest.TestCase):
    def character(self):
        return {'id':'hero','prepared':{},'model_approved':False,'rig':{'status':'unbound','ready':False},'batches':[],'approvals':{}}
    def test_steps_follow_current_versions_not_old_deliveries(self):
        c=self.character();c['deliveries']=[{'id':'old'}]
        self.assertEqual(guidance(c,[])['stage'],0)
        c['prepared']={'id':'model'}
        self.assertIn('确认',guidance(c,[])['label'])
        c['model_approved']=True
        self.assertEqual(guidance(c,[])['stage'],1)
        c['rig'].update(status='ready',ready=True)
        self.assertEqual(guidance(c,[])['stage'],2)
        c['batches']=[{'id':'b','fingerprint':'v','current_rig':True}]
        self.assertEqual(guidance(c,[])['stage'],3)
        c['approvals']={'motions':{'b':{'fingerprint':'v'}}}
        self.assertEqual(guidance(c,[])['stage'],4)
    def test_mismatch_recovery_precedes_generic_retry(self):
        c=self.character();c['rig']['status']='needs_review'
        jobs=[{'character':'hero','action':'download','status':'failed','id':'job','error':'wrong mesh'}]
        self.assertEqual(guidance(c,jobs)['stage'],1)
        self.assertNotIn('retry',guidance(c,jobs))
    def test_running_task_and_other_character_are_distinguished(self):
        c=self.character()
        jobs=[{'character':'other','action':'bake','status':'running'}, {'character':'hero','action':'equipment','status':'running'}]
        self.assertEqual(guidance(c,jobs)['stage'],5)
        self.assertTrue(guidance(c,jobs)['running'])
    def test_failed_task_keeps_recovery_identity(self):
        c=self.character()
        g=guidance(c,[{'character':'hero','action':'review','status':'failed','id':'retry1','error':'capture failed'}])
        self.assertEqual((g['stage'],g['retry']),(3,'retry1'))
    def test_old_binding_batches_do_not_skip_download(self):
        c=self.character();c.update(prepared={'id':'x'},model_approved=True)
        c['rig'].update(status='ready',ready=True)
        c['batches']=[{'id':'old','current_rig':False}]
        self.assertEqual(guidance(c,[])['stage'],2)

    def test_retried_older_task_has_priority_over_newer_completed_task(self):
        jobs=[{'character':'hero','action':'bake','status':'succeeded'},
              {'character':'hero','action':'rig','status':'running'}]
        self.assertEqual(guidance(self.character(),jobs)['stage'],1)
        self.assertTrue(guidance(self.character(),jobs)['running'])
