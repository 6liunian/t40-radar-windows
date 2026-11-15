import unittest,struct
from ath6kl_win.network import unpack_frames,pack_data

CAPTURE=bytes.fromhex('15002712000000037f2044d260601fdf2fb1004a00037f2044d260601fdf2fb1003caaaa03000000080045100034000040004006a960c0a80802c0a80801006bb5deb2acd9b5940e08c0801272108c230000020405b40101040201030306')

class AmsduTests(unittest.TestCase):
    def test_real_syn_ack(self):
        packets=unpack_frames(CAPTURE)
        self.assertEqual(len(packets),1)
        self.assertEqual(len(packets[0]),66)
        self.assertEqual(packets[0][23],6)
        self.assertEqual(struct.unpack_from('!H',packets[0],34)[0],107)
        self.assertEqual(packets[0][47],0x12)

    def test_two_frames_padding(self):
        sub=CAPTURE[20:]
        aggregate=CAPTURE[:6]+CAPTURE[6:18]+struct.pack('!H',len(sub)*2+2)+sub+b'\0\0'+sub
        self.assertEqual(unpack_frames(aggregate),unpack_frames(CAPTURE)*2)

    def test_truncation_is_atomic(self):
        sub=CAPTURE[20:]
        for data in (CAPTURE[:-1],CAPTURE[:20],CAPTURE+b'\0',CAPTURE+b'\0\0'+sub[:-1]):
            with self.assertRaises(ValueError):unpack_frames(data)

    def test_metadata_and_normal_frame(self):
        eth=unpack_frames(CAPTURE)[0];normal=pack_data(eth)
        self.assertEqual(unpack_frames(normal),[eth])
        for version,size in [(1,6),(2,3)]:
            frame=normal[:2]+struct.pack('<H',version<<13)+normal[4:6]+bytes(size)+normal[6:]
            self.assertEqual(unpack_frames(frame),[eth])
