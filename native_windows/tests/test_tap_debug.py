import struct
import unittest
from unittest.mock import patch
from ath6kl_win.tap_debug import translate, DEBUG_IP, RADAR_IP
from ath6kl_win.udp_bridge import UdpBridge
from ath6kl_win.network import HOST_IP

class TapTranslationTests(unittest.TestCase):
    def test_arp_request_and_response_translate_embedded_mac(self):
        tap = bytes.fromhex('00ff8cc242c2')
        ap = bytes.fromhex('00037f2044d2')
        peer = bytes.fromhex('60601fdf2fb1')
        request = b'\xff'*6 + tap + b'\x08\x06' + bytes.fromhex('0001080006040001') + tap + DEBUG_IP + bytes(6) + RADAR_IP
        wire = translate(request, tap, ap, True)
        self.assertEqual(wire[6:12], ap)
        self.assertEqual(wire[22:28], ap)
        response = ap + peer + b'\x08\x06' + bytes.fromhex('0001080006040002') + peer + RADAR_IP + ap + DEBUG_IP
        host = translate(response, ap, tap, False)
        self.assertEqual(host[:6], tap)
        self.assertEqual(host[32:38], tap)
        self.assertEqual(host[28:32], RADAR_IP)

    def test_only_diagnostic_ip_and_radar_allowed(self):
        ip = struct.pack('!BBHHHBBH4s4s', 0x45, 0, 20, 0, 0, 64, 6, 0, DEBUG_IP, RADAR_IP)
        packet = bytes(12) + b'\x08\0' + ip
        self.assertIsNotNone(translate(packet, bytes(6), bytes([1])*6, True))
        bad = bytearray(packet)
        bad[29] = 1  # Panel IP must stay on its existing UDP bridge.
        self.assertIsNone(translate(bytes(bad), bytes(6), bytes([1])*6, True))
        bad[29] = 3
        bad[33] = 99
        self.assertIsNone(translate(bytes(bad), bytes(6), bytes([1])*6, True))

    def test_udp_is_opt_in_and_payload_preserved(self):
        ip = struct.pack('!BBHHHBBH4s4s', 0x45, 0, 28, 0, 0, 64, 17, 0, HOST_IP, RADAR_IP)
        packet = bytes(12) + b'\x08\0' + ip + bytes(8)
        self.assertIsNone(translate(packet, bytes(6), b'a'*6, True, HOST_IP))
        output = translate(packet, bytes(6), b'a'*6, True, HOST_IP, True)
        self.assertEqual(output[14:], packet[14:])

    def test_direct_tap_does_not_bind_loopback_or_send_synthetic_arp(self):
        with patch('ath6kl_win.tap_debug.TapDebug') as tap, patch('ath6kl_win.udp_bridge.socket.socket') as sock:
            writes = []
            bridge = UdpBridge(lambda *args: writes.append(args), 2, bytes(6),
                               tap_guid='test', tap_ip=HOST_IP, tap_direct=True)
            self.assertEqual(bridge.sockets, {})
            sock.assert_not_called()
            bridge.poll()
            self.assertEqual(writes, [])
            tap.return_value.poll.assert_called_once()
            bridge.close()
            tap.return_value.close.assert_called_once()
