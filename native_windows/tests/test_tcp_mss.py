import struct
import unittest
from ath6kl_win.network import limit_radar_tcp_mss, checksum, pack_data


class MssTests(unittest.TestCase):
    def packet(self,mss=1460,flags=2,dest=b'\xc0\xa8\x08\x02',options=None):
        if options is None:options=struct.pack('!BBH',2,4,mss)
        tcp=bytearray(struct.pack('!HHIIBBHHH',50000,107,123,0,6<<4,flags,8192,0,0)+options)
        ip=bytearray(struct.pack('!BBHHHBBH4s4s',0x45,0,20+len(tcp),1,0x4000,64,6,0,b'\xc0\xa8\x08\x01',dest))
        struct.pack_into('!H',tcp,16,checksum(ip[12:20]+struct.pack('!BBH',0,6,len(tcp))+tcp))
        struct.pack_into('!H',ip,10,checksum(ip))
        return bytes(12)+b'\x08\x00'+ip+tcp

    def test_only_mss_and_tcp_checksum_change(self):
        before=self.packet();after=limit_radar_tcp_mss(before)
        self.assertEqual(struct.unpack_from('!H',after,56)[0],384)
        self.assertEqual(before[:50],after[:50])
        self.assertEqual(checksum(after[14:34]),0)
        self.assertEqual(checksum(after[26:34]+struct.pack('!BBH',0,6,len(after)-34)+after[34:]),0)

    def test_smaller_mss_ack_and_other_host_unchanged(self):
        for packet in (self.packet(256),self.packet(flags=16),self.packet(dest=b'\xc0\xa8\x08\x03')):
            self.assertEqual(limit_radar_tcp_mss(packet),packet)

    def test_invalid_options_not_partially_mutated(self):
        packet=self.packet(options=b'\x02\x05\x05\xb4')
        self.assertEqual(limit_radar_tcp_mss(packet),packet)

    def test_actual_wmi_send_path_limits_syn(self):
        encoded=pack_data(self.packet())
        self.assertIn(b'\x02\x04\x01\x80',encoded)
