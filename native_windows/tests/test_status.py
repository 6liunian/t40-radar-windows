import unittest
from unittest.mock import MagicMock
from ath6kl_win.monitor import publish_status

class StatusTests(unittest.TestCase):
    def test_windows_read_lock_is_nonfatal(self):
        directory = MagicMock()
        directory.__truediv__.return_value.replace.side_effect = PermissionError(13, 'access denied')
        self.assertFalse(publish_status(directory, {'state': 'running'}))

    def test_disk_write_error_is_nonfatal(self):
        directory = MagicMock()
        directory.__truediv__.return_value.write_text.side_effect = OSError('disk full')
        self.assertFalse(publish_status(directory, {}))

    def test_publish_succeeds(self):
        self.assertTrue(publish_status(MagicMock(), {'state': 'running'}))
