import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from ath6kl_win.htc import frame
from ath6kl_win.monitor import serve


class RxResyncTests(unittest.TestCase):
    def bridge(self):
        return Mock(rx=0, tx=0, dropped=0, replies_sent=0, tap=None)

    def test_captured_partial_usb_tail_dropped_then_valid_event_received(self):
        # Exact first 32 bytes and size of the 2026-11-12 hardware failure.
        tail = bytes.fromhex('6b09c7407d2cdc7ff2802db811e24ef32bb6ffdafbebbc613cc3335fe3e120df') + bytes(478)
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            packets = iter([tail, b'', frame(1, b'\x10\x10\0\0\0\0')])
            def bulk(*args):
                try:
                    return next(packets)
                except StopIteration:
                    (directory / 'stop').touch()
                    return b''
            with patch('ath6kl_win.monitor.UdpBridge', return_value=self.bridge()):
                serve(bulk, {0x100:1, 0x101:2}, b'abcdef', directory)
            state = json.loads((directory/'status.json').read_text())
            self.assertEqual(state['htc_dropped'], 1)
            self.assertEqual(state['events'], 1)
            self.assertEqual(state['state'], 'stopped')

    def test_corrupt_burst_still_aborts_for_launcher_recovery(self):
        with tempfile.TemporaryDirectory() as tmp, patch('ath6kl_win.monitor.UdpBridge', return_value=self.bridge()):
            directory = Path(tmp)
            with self.assertRaisesRegex(RuntimeError, 'Repeated invalid HTC'):
                serve(lambda *args: b'bad', {0x100:1, 0x101:2}, b'abcdef', directory)
            state = json.loads((directory/'status.json').read_text())
            self.assertEqual(state['htc_dropped'], 9)
            self.assertEqual(state['state'], 'error')
