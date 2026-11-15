import struct
import unittest
from ath6kl_win.htc import decode, frame, connect_services, HtcUsbTransport

class HtcTests(unittest.TestCase):
    def test_tx_matches_driver_flags_and_endpoint_sequence_wrap(self):
        sent = []
        transport = HtcUsbTransport(lambda ep, packet: sent.append((ep, packet)))
        for _ in range(257):
            transport(2, frame(2, b'data'))
        transport(1, frame(1, b'control'))
        self.assertEqual([sent[i][1][5] for i in (0, 1, 255, 256, 257)], [0, 1, 255, 0, 0])
        self.assertTrue(all(packet[1] == 4 for _, packet in sent))
        self.assertEqual(decode(sent[0][1]), (2, b'data'))
        transport(0x82, 4096)
        self.assertEqual(sent[-1], (0x82, 4096))

    def test_captured_ready(self):
        ep, payload = decode(bytes.fromhex('00000a00000001001600800616000100'))
        self.assertEqual(ep, 0)
        self.assertEqual(struct.unpack_from('<HHH', payload), (1, 22, 1664))

    def test_bad_length(self):
        with self.assertRaises(ValueError):
            decode(bytes.fromhex('00000a0000000100'))

    def test_service_handshake(self):
        replies = []
        requests = []
        def bulk(endpoint, data):
            if endpoint == 0x82:
                return replies.pop(0)
            ep, payload = decode(data)
            self.assertEqual(ep, 0)
            msg = struct.unpack_from('<H', payload)[0]
            if msg == 2:
                _, service, flags, _, _ = struct.unpack('<HHHBB', payload)
                requests.append((service, flags))
                replies.append(frame(0, struct.pack('<HHBBHBB', 3, service, 0, len(requests), 1536, 0, 0)))
            elif msg == 5:
                replies.append(frame(1, struct.pack('<HHHII6sB', 0x1001, 0, 0, 1, 1, b'abcdef', 6)))
            else:
                self.fail('Unexpected message')
        endpoints, mac = connect_services(bulk, bytes.fromhex('00000a00000001001600800616000100'))
        self.assertEqual(mac, b'abcdef')
        self.assertEqual(endpoints[0x100], 1)
        self.assertEqual([flags >> 8 for _, flags in requests], [1, 11, 1, 5, 4])

if __name__ == '__main__':
    unittest.main()
