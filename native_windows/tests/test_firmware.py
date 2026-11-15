import struct
import unittest
from ath6kl_win.firmware import MAGIC, parse_container

class FirmwareTests(unittest.TestCase):
    def test_extract_image_without_container_header(self):
        image = b'SGMTpayload'
        container = MAGIC + struct.pack('<II', 3, len(image)) + image
        self.assertEqual(parse_container(container)[3], image)

    def test_reject_truncated_image(self):
        with self.assertRaises(ValueError):
            parse_container(MAGIC + struct.pack('<II', 3, 100) + b'SGMT')

    def test_reject_duplicate_image(self):
        entry = struct.pack('<II', 3, 1) + b'x'
        with self.assertRaises(ValueError):
            parse_container(MAGIC + entry + entry)

    def test_reject_raw_image(self):
        with self.assertRaises(ValueError):
            parse_container(b'SGMTpayload')

if __name__ == '__main__':
    unittest.main()
