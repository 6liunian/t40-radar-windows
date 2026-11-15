import math
import struct
import unittest

from server import decode_sector_xyz
from sector_cloud import SIZE, STRIDE


def record(distance=10.0, elevation=0.2, strength=123, encoder=134):
    raw = bytearray(SIZE)
    raw[0] = 1
    raw[1] = 1
    struct.pack_into("<H", raw, 5, encoder)
    struct.pack_into("<f", raw, 15, distance)
    elevation_bits = struct.unpack("<I", struct.pack("<f", elevation))[0] ^ 0x80000000
    struct.pack_into("<I", raw, 19, elevation_bits)
    struct.pack_into("<H", raw, 31, strength)
    return raw


class HeightDecodeTests(unittest.TestCase):
    def test_valid_elevation_projects_real_height(self):
        points, stats = decode_sector_xyz(record())
        self.assertEqual(len(points), 1)
        self.assertAlmostEqual(points[0][2], math.sin(0.2) * 10, places=3)
        self.assertEqual(points[0][3:], [123, 0, 1])
        self.assertEqual(stats["elevation_valid"], 1)
        self.assertEqual(stats["invalid_elevation"], 0)

    def test_invalid_elevation_stays_visible_but_is_not_calibration_valid(self):
        points, stats = decode_sector_xyz(record(elevation=float("nan")))
        self.assertEqual(points[0][2], 0)
        self.assertEqual(points[0][5], 0)
        self.assertEqual(stats["invalid_elevation"], 1)

    def test_empty_snapshot_has_no_fake_points(self):
        points, stats = decode_sector_xyz(bytes(SIZE))
        self.assertEqual(points, [])
        self.assertEqual(stats["points"], 0)


if __name__ == "__main__":
    unittest.main()
