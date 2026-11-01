import sys
from pathlib import Path
import unittest
from unittest.mock import MagicMock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import mixamo_controller as c

class MixamoAuthTests(unittest.TestCase):
    def test_login_loop_clears_stale_auth_once(self):
        context=MagicMock();page=MagicMock();page.is_closed.return_value=False
        page.url='https://www.mixamo.com/ims/logout?token=secret'
        page.get_by_role.return_value.is_visible.side_effect=[False,False,False,False,True]
        c.wait_for_login(context,page)
        context.clear_cookies.assert_called_once();page.goto.assert_called_once()
        page.add_init_script.assert_called_once()
    def test_closed_page_has_actionable_error(self):
        page=MagicMock();page.is_closed.return_value=True
        with self.assertRaisesRegex(ValueError,'重新打开'):c.wait_for_login(MagicMock(),page)
    def test_errors_never_include_url_credentials(self):
        text=c.safe_error(Exception('navigation https://www.mixamo.com/ims/logout?token=secret and https://adobe.com/?access_token=secret'))
        self.assertNotIn('secret',text);self.assertNotIn('access_token',text)
        self.assertIn('重新打开',c.safe_error(Exception('Target page, context or browser has been closed')))

class SharedSSOTests(unittest.TestCase):
    def test_shared_login_excludes_character_storage_and_other_domains(self):
        import tempfile,json
        with tempfile.TemporaryDirectory() as folder, patch.object(c,'SESSION_FILE',Path(folder)/'session.json'):
            context=MagicMock()
            context.storage_state.return_value={'origins':[{'origin':'https://www.mixamo.com','localStorage':[{'name':'access_token','value':'test-token'},{'name':'SettingsStore','value':'character-data'}]}]}
            context.cookies.return_value=[{'domain':'.adobelogin.com','name':'sso','value':'test','expires':-1},
                {'domain':'.mixamo.com','name':'character','value':'hero','expires':-1},
                {'domain':'eviladobe.com','name':'fake','value':'no','expires':-1}]
            c.save_shared_login(context)
            saved=json.loads(c.SESSION_FILE.read_text())
            self.assertEqual([v['name'] for v in saved['cookies']],['sso'])
            self.assertEqual([v['name'] for v in saved['origins'][0]['localStorage']],['access_token'])
            page=MagicMock();page.url='https://www.mixamo.com/'
            self.assertTrue(c.restore_shared_login(context,page))
            page.evaluate.assert_called_once()
            self.assertTrue(c.restore_shared_login(context))
            self.assertEqual(context.add_cookies.call_args.args[0],saved['cookies'])

    def test_expired_sso_is_not_restored(self):
        import tempfile,json
        with tempfile.TemporaryDirectory() as folder, patch.object(c,'SESSION_FILE',Path(folder)/'session.json'):
            c.SESSION_FILE.write_text(json.dumps({'cookies':[{'domain':'.adobe.com','expires':1}]}))
            context=MagicMock()
            self.assertFalse(c.restore_shared_login(context))
            context.add_cookies.assert_not_called()
