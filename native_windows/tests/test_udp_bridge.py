import struct
import unittest
from unittest.mock import patch
from ath6kl_win.htc import decode
from ath6kl_win.network import checksum, HOST_IP, unpack_data
from ath6kl_win.udp_bridge import UdpBridge, RADAR_IP, build_udp, parse_udp

class UdpTests(unittest.TestCase):
    def incoming(self):
        packet = bytearray(build_udp(bytes(6), bytes([1])*6, 40204, b'example DUML'))
        packet[26:30], packet[30:34] = packet[30:34], packet[26:30]
        packet[24:26] = b'\0\0'
        packet[24:26] = struct.pack('!H', checksum(bytes(packet[14:34])))
        return bytes(packet)

    def test_parse_radar_datagram(self):
        self.assertEqual(parse_udp(self.incoming()), (40204, 40204, b'example DUML'))

    def test_corrupt_header_rejected(self):
        p = bytearray(self.incoming())
        p[22] ^= 1
        self.assertIsNone(parse_udp(bytes(p)))

    def test_wrong_direction_rejected(self):
        self.assertIsNone(parse_udp(build_udp(bytes(6), bytes(6), 50007, b'test')))

    def test_oversize_rejected(self):
        with self.assertRaises(ValueError):
            build_udp(bytes(6), bytes(6), 50007, bytes(1473))

    def test_arp_bootstraps_peer_without_prior_udp(self):
        mac = bytes.fromhex('00037f2044d2')
        peer = bytes.fromhex('60601fdf2fb1')
        sent = []
        with patch('ath6kl_win.udp_bridge.socket.socket'):
            bridge = UdpBridge(lambda *args: sent.append(args), 2, mac)
        bridge.sockets = {}
        bridge.poll()
        self.assertEqual(len(sent), 1)
        endpoint, payload = decode(sent[0][1])
        request = unpack_data(payload)
        self.assertEqual(endpoint, 2)
        self.assertEqual(request[:6], b'\xff' * 6)
        self.assertEqual(request[20:22], b'\0\1')
        self.assertEqual(request[28:32], HOST_IP)
        self.assertEqual(request[38:42], RADAR_IP)
        response = (mac + peer + b'\x08\x06'
                    + bytes.fromhex('0001080006040002')
                    + peer + RADAR_IP + mac + HOST_IP)
        bridge.receive(response)
        self.assertEqual(bridge.peer, peer)
        self.assertEqual(bridge.rx, 0)
        # Retrying must be bounded, including while the radar is absent.
        bridge.poll()
        self.assertEqual(len(sent), 1)

    def test_unrelated_arp_does_not_select_radar_peer(self):
        bridge = UdpBridge.__new__(UdpBridge)
        bridge.peer = None
        peer = bytes.fromhex('60601fdf2fb1')
        response = (bytes(6) + peer + b'\x08\x06'
                    + bytes.fromhex('0001080006040002')
                    + peer + bytes([192, 168, 8, 99]) + bytes(6) + HOST_IP)
        bridge.receive(response)
        self.assertIsNone(bridge.peer)

    def test_panel_closed_port_does_not_kill_bridge(self):
        with patch('ath6kl_win.udp_bridge.socket.socket'):
            bridge = UdpBridge(lambda *args: None, 2, bytes(6))
        bridge.sockets[40204].sendto.side_effect = [ConnectionResetError(10054, 'closed peer'), None]
        bridge.receive(self.incoming())
        bridge.receive(self.incoming())
        self.assertEqual(bridge.rx, 2)
        self.assertEqual(bridge.sockets[40204].sendto.call_count, 2)
