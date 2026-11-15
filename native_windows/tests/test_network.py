import unittest
from ath6kl_win.network import unpack_data, pack_data, respond

class NetworkTests(unittest.TestCase):
    def test_captured_radar_arp(self):
        captured = bytes.fromhex('110006000000ffffffffffff60601fdf2fb10024aaaa030000000806000108000604000160601fdf2fb1c0a80802000000000000c0a80801')
        eth = unpack_data(captured)
        mac = bytes.fromhex('00037f2044d2')
        reply = respond(eth, mac)
        self.assertEqual(reply.hex(), '60601fdf2fb100037f2044d20806000108000604000200037f2044d2c0a8080160601fdf2fb1c0a80802')
        self.assertEqual(unpack_data(pack_data(reply)), reply)

    def test_unrelated_arp_not_answered(self):
        eth = bytes.fromhex('ffffffffffff60601fdf2fb10806000108000604000160601fdf2fb1c0a80802000000000000c0a80863')
        self.assertIsNone(respond(eth, bytes(6)))

    def test_truncated_frame(self):
        with self.assertRaises(ValueError):
            unpack_data(bytes(10))
