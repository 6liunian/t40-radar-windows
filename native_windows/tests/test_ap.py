import struct
import unittest
from ath6kl_win.ap import profile, start_ap
from ath6kl_win.htc import frame

class ApTests(unittest.TestCase):
    def test_profile_layout(self):
        data = profile()
        self.assertEqual(len(data), 53)
        self.assertEqual(data[:8], bytes([16, 1, 1, 1, 0, 1, 0, 10]))
        self.assertEqual(data[8:18], b'radar_wifi')
        self.assertEqual(struct.unpack_from('<H', data, 40)[0], 5240)

    def test_ap_started_event(self):
        mac = bytes.fromhex('00037f2044d2')
        sent = []
        event = bytes.fromhex('021000000000781400037f2044d25a00000000000000810000')
        event += bytes(2)
        def bulk(ep, data):
            if ep == 1:
                sent.append(data)
                return b''
            return frame(1, event)
        start_ap(bulk, {0x100: 1}, mac)
        self.assertEqual(len(sent), 5)

    def test_reject_invalid_profile(self):
        with self.assertRaises(ValueError):
            profile(b'x' * 33)

if __name__ == '__main__':
    unittest.main()
