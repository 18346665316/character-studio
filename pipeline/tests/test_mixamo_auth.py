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
